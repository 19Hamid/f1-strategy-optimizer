"""Command-line interface for the historical-data pipeline."""

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import fastf1

from app.pipeline.batch import RawBatchRunner
from app.pipeline.catalog import (
    CatalogBuildError,
    RawCatalogBuilder,
)
from app.pipeline.config import (
    CORE_STUDY_SEASONS,
    ExtractionPlan,
)
from app.pipeline.integrity import (
    SessionIntegrityError,
    verify_session_partition,
)
from app.pipeline.models import SessionKey
from app.pipeline.paths import RawDataPaths
from app.pipeline.runner import RawPipelineRunner
from app.pipeline.schedule import discover_session_keys
from app.pipeline.source import FastF1Source
from app.pipeline.telemetry import (
    TelemetryDataPaths,
    TelemetryRequest,
)
from app.pipeline.telemetry_source import (
    FastF1TelemetrySource,
    TelemetryExtractionError,
)
from app.pipeline.telemetry_storage import (
    TelemetryStorageError,
    TelemetryWriter,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RAW_ROOT = PROJECT_ROOT / "data" / "raw" / "fastf1"
DEFAULT_CACHE_ROOT = (
    PROJECT_ROOT
    / "data"
    / "cache"
    / "fastf1"
)


def build_parser() -> argparse.ArgumentParser:
    """Build the pipeline command-line parser."""
    parser = argparse.ArgumentParser(
        prog="f1-pipeline",
        description=(
            "Extract, verify and catalog historical "
            "Formula 1 race data."
        ),
    )

    parser.add_argument(
        "--raw-root",
        type=Path,
        default=DEFAULT_RAW_ROOT,
        help="Directory used for raw Parquet datasets.",
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=DEFAULT_CACHE_ROOT,
        help="Directory used for the FastF1 download cache.",
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    schedule_parser = commands.add_parser(
        "schedule",
        help="Discover selected championship races.",
    )
    _add_season_arguments(schedule_parser)

    extract_parser = commands.add_parser(
        "extract",
        help="Extract selected race sessions.",
    )
    _add_season_arguments(extract_parser)
    extract_parser.add_argument(
        "--round",
        dest="rounds",
        type=int,
        action="append",
        help=(
            "Extract a selected round. May be repeated, "
            "but requires exactly one --season."
        ),
    )
    extract_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace already completed selected sessions.",
    )

    telemetry_parser = commands.add_parser(
        "telemetry",
        help="Extract one driver's telemetry for one race lap.",
    )
    telemetry_parser.add_argument(
        "--season",
        type=int,
        choices=CORE_STUDY_SEASONS,
        required=True,
        help="Select a season from 2022 to 2025.",
    )
    telemetry_parser.add_argument(
        "--round",
        dest="round_number",
        type=int,
        required=True,
        help="Select the championship round number.",
    )
    telemetry_parser.add_argument(
        "--driver",
        required=True,
        help=(
            "Select the driver's three-letter abbreviation, "
            "such as VER."
        ),
    )
    telemetry_parser.add_argument(
        "--lap",
        dest="lap_number",
        type=int,
        required=True,
        help="Select the race lap number.",
    )
    telemetry_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace already stored telemetry for this lap.",
    )

    verify_parser = commands.add_parser(
        "verify",
        help="Verify one stored race session.",
    )
    verify_parser.add_argument(
        "--season",
        type=int,
        choices=CORE_STUDY_SEASONS,
        required=True,
    )
    verify_parser.add_argument(
        "--round",
        dest="round_number",
        type=int,
        required=True,
    )

    commands.add_parser(
        "catalog",
        help="Rebuild catalog.parquet from verified sessions.",
    )

    return parser


def selected_seasons(
    seasons: Sequence[int] | None,
) -> tuple[int, ...]:
    """Return normalized selected seasons or the V1 defaults."""
    if seasons is None:
        return CORE_STUDY_SEASONS

    return tuple(sorted(set(seasons)))


def select_sessions(
    discovered: Sequence[SessionKey],
    *,
    seasons: Sequence[int] | None,
    rounds: Sequence[int] | None,
) -> tuple[SessionKey, ...]:
    """Filter discovered sessions using CLI selections."""
    normalized_seasons = selected_seasons(seasons)

    if rounds is None:
        return tuple(discovered)

    if len(normalized_seasons) != 1:
        raise ValueError(
            "--round requires exactly one selected --season"
        )

    selected_rounds = set(rounds)

    if any(round_number < 1 for round_number in selected_rounds):
        raise ValueError("round numbers must be positive")

    selected = tuple(
        session_key
        for session_key in discovered
        if session_key.round_number in selected_rounds
    )

    discovered_rounds = {
        session_key.round_number
        for session_key in discovered
    }
    missing_rounds = sorted(
        selected_rounds.difference(discovered_rounds)
    )

    if missing_rounds:
        missing_text = ", ".join(
            str(round_number)
            for round_number in missing_rounds
        )
        raise ValueError(
            f"selected rounds do not exist: {missing_text}"
        )

    return selected


def main(
    arguments: Sequence[str] | None = None,
) -> int:
    """Run the selected pipeline command."""
    parser = build_parser()
    namespace = parser.parse_args(arguments)
    raw_paths = RawDataPaths(namespace.raw_root)

    try:
        if namespace.command in {
            "schedule",
            "extract",
            "telemetry",
        }:
            _configure_fastf1_cache(
                namespace.cache_root
            )

        if namespace.command == "schedule":
            return _run_schedule(namespace)

        if namespace.command == "extract":
            return _run_extract(
                namespace,
                raw_paths,
            )

        if namespace.command == "telemetry":
            return _run_telemetry(namespace)

        if namespace.command == "verify":
            return _run_verify(
                namespace,
                raw_paths,
            )

        if namespace.command == "catalog":
            return _run_catalog(raw_paths)
    except (
        CatalogBuildError,
        OSError,
        SessionIntegrityError,
        TelemetryExtractionError,
        TelemetryStorageError,
        TypeError,
        ValueError,
    ) as error:
        _write_error(
            f"Pipeline error: {error}"
        )
        return 1

    parser.error(
        f"unsupported command: {namespace.command}"
    )
    return 2


def _add_season_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    """Add repeatable V1 season selection."""
    parser.add_argument(
        "--season",
        dest="seasons",
        type=int,
        choices=CORE_STUDY_SEASONS,
        action="append",
        help=(
            "Select a season from 2022 to 2025. "
            "May be repeated. Defaults to all V1 seasons."
        ),
    )


def _configure_fastf1_cache(
    cache_root: Path,
) -> None:
    """Enable the project-controlled FastF1 cache."""
    cache_root = Path(cache_root)
    cache_root.mkdir(
        parents=True,
        exist_ok=True,
    )
    fastf1.Cache.enable_cache(
        str(cache_root)
    )


def _run_schedule(
    namespace: argparse.Namespace,
) -> int:
    """Discover and display selected races."""
    seasons = selected_seasons(namespace.seasons)
    sessions = discover_session_keys(
        ExtractionPlan(seasons=seasons)
    )
    counts = Counter(
        session.season
        for session in sessions
    )

    for season in sorted(counts):
        _write_line(
            f"{season}: {counts[season]} races"
        )

    _write_line(
        f"Total: {len(sessions)} race sessions"
    )
    return 0


def _run_extract(
    namespace: argparse.Namespace,
    raw_paths: RawDataPaths,
) -> int:
    """Extract selected sessions and rebuild the catalog."""
    seasons = selected_seasons(namespace.seasons)
    discovered = discover_session_keys(
        ExtractionPlan(seasons=seasons)
    )
    sessions = select_sessions(
        discovered,
        seasons=namespace.seasons,
        rounds=namespace.rounds,
    )

    source = FastF1Source(
        cache_directory=namespace.cache_root
    )
    session_runner = RawPipelineRunner(
        raw_paths=raw_paths,
        source=source,
    )
    batch_runner = RawBatchRunner(
        raw_paths=raw_paths,
        session_runner=session_runner,
    )

    result = batch_runner.run(
        sessions,
        force=namespace.force,
    )

    _write_line(f"Run ID: {result.run_id}")

    for record in result.records:
        _write_line(
            f"{record.session_key.identifier}: "
            f"{record.status} "
            f"({record.duration_seconds:.3f}s)"
        )

        if record.error_message is not None:
            _write_line(
                f"  {record.error_type}: "
                f"{record.error_message}"
            )

    _write_line(
        "Summary: "
        f"{result.written_count} written, "
        f"{result.skipped_count} skipped, "
        f"{result.failed_count} failed"
    )
    _write_line(
        f"Run record: {result.record_path}"
    )

    if result.written_count + result.skipped_count > 0:
        catalog_result = RawCatalogBuilder(
            raw_paths
        ).build()
        _write_line(
            "Catalog: "
            f"{catalog_result.session_count} sessions at "
            f"{catalog_result.path}"
        )

    return 0 if result.succeeded else 1


def _run_telemetry(
    namespace: argparse.Namespace,
) -> int:
    """Extract and store one requested telemetry lap."""
    request = TelemetryRequest(
        session_key=SessionKey(
            season=namespace.season,
            round_number=namespace.round_number,
        ),
        driver=namespace.driver,
        lap_number=namespace.lap_number,
    )

    source = FastF1TelemetrySource(
        cache_directory=namespace.cache_root
    )
    data = source.extract(request)

    writer = TelemetryWriter(
        TelemetryDataPaths(
            raw_root=namespace.raw_root,
        )
    )
    result = writer.write(
        data,
        force=namespace.force,
    )

    _write_line(
        f"{request.identifier}: {result.status}"
    )
    _write_line(
        f"Samples: {len(data.telemetry)}"
    )
    _write_line(
        f"Path: {result.directory}"
    )

    return 0


def _run_verify(
    namespace: argparse.Namespace,
    raw_paths: RawDataPaths,
) -> int:
    """Verify one stored session."""
    session_key = SessionKey(
        season=namespace.season,
        round_number=namespace.round_number,
    )
    report = verify_session_partition(
        raw_paths,
        session_key,
    )

    if report.is_valid:
        _write_line(
            f"{session_key.identifier}: valid"
        )
        return 0

    for issue in report.issues:
        _write_error(
            f"{session_key.identifier}: "
            f"{issue.code}: {issue.message}"
        )

    return 1


def _run_catalog(
    raw_paths: RawDataPaths,
) -> int:
    """Rebuild and display the raw-data catalog."""
    result = RawCatalogBuilder(
        raw_paths
    ).build()

    _write_line(
        f"Catalog built: {result.session_count} sessions"
    )
    _write_line(f"Path: {result.path}")
    _write_line(f"SHA-256: {result.sha256}")
    return 0


def _write_line(message: str) -> None:
    """Write one line to standard output."""
    sys.stdout.write(f"{message}\n")


def _write_error(message: str) -> None:
    """Write one line to standard error."""
    sys.stderr.write(f"{message}\n")


if __name__ == "__main__":
    raise SystemExit(main())