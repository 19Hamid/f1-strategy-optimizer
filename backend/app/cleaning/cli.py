"""Command-line interface for Phase 3 data processing."""

import argparse
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import cast

from app.cleaning.batch import (
    ProcessedBatchRunner,
)
from app.cleaning.catalog import (
    ProcessedCatalogBuilder,
)
from app.cleaning.integrity import (
    verify_processed_partition,
)
from app.cleaning.paths import ProcessedDataPaths
from app.cleaning.profile import (
    DEVELOPMENT_SEASONS,
)
from app.cleaning.runner import (
    ProcessedPipelineRunner,
)
from app.pipeline.models import SessionKey
from app.pipeline.paths import RawDataPaths
from app.pipeline.serialization import (
    read_parquet_table,
)

PROJECT_ROOT = (
    Path(__file__).resolve().parents[3]
)
DEFAULT_RAW_ROOT = (
    PROJECT_ROOT / "data" / "raw" / "fastf1"
)
DEFAULT_PROCESSED_ROOT = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "fastf1"
)

CommandHandler = Callable[
    [argparse.Namespace],
    int,
]


class CleaningCliError(RuntimeError):
    """Raised when a CLI request cannot be completed."""


def build_parser() -> argparse.ArgumentParser:
    """Build the Phase 3 command-line parser."""
    parser = argparse.ArgumentParser(
        prog="python -m app.cleaning.cli",
        description=(
            "Build and verify processed Formula 1 "
            "development data."
        ),
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    plan_parser = subparsers.add_parser(
        "plan",
        help=(
            "show development sessions selected "
            "from the raw catalog"
        ),
    )
    _add_raw_root_argument(plan_parser)
    _add_selection_arguments(plan_parser)
    plan_parser.set_defaults(
        handler=_run_plan
    )

    process_parser = subparsers.add_parser(
        "process",
        help=(
            "process selected development sessions"
        ),
    )
    _add_raw_root_argument(process_parser)
    _add_processed_root_argument(
        process_parser
    )
    _add_selection_arguments(
        process_parser
    )
    process_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "rebuild selected processed partitions"
        ),
    )
    process_parser.set_defaults(
        handler=_run_process
    )

    verify_parser = subparsers.add_parser(
        "verify",
        help=(
            "verify one processed development session"
        ),
    )
    _add_processed_root_argument(
        verify_parser
    )
    verify_parser.add_argument(
        "--season",
        type=int,
        required=True,
        choices=DEVELOPMENT_SEASONS,
    )
    verify_parser.add_argument(
        "--round",
        type=int,
        required=True,
        choices=range(1, 31),
        dest="round_number",
    )
    verify_parser.set_defaults(
        handler=_run_verify
    )

    catalog_parser = subparsers.add_parser(
        "catalog",
        help=(
            "catalog all valid processed "
            "development sessions"
        ),
    )
    _add_raw_root_argument(
        catalog_parser
    )
    _add_processed_root_argument(
        catalog_parser
    )
    catalog_parser.set_defaults(
        handler=_run_catalog
    )

    return parser


def main(
    argv: list[str] | None = None,
) -> int:
    """Run one Phase 3 CLI command."""
    parser = build_parser()
    arguments = parser.parse_args(argv)

    handler = cast(
        CommandHandler,
        arguments.handler,
    )

    return handler(arguments)


def _run_plan(
    arguments: argparse.Namespace,
) -> int:
    """Print the selected development-session plan."""
    raw_paths = RawDataPaths(
        Path(arguments.raw_root)
    )
    session_keys = _select_session_keys(
        all_session_keys=(
            _load_development_session_keys(
                raw_paths
            )
        ),
        seasons=arguments.season,
        round_numbers=(
            arguments.round_number
        ),
    )

    counts = Counter(
        session_key.season
        for session_key in session_keys
    )

    print("DEVELOPMENT PROCESSING PLAN")
    print("===========================")

    for season in sorted(counts):
        print(
            f"{season}: "
            f"{counts[season]} race sessions"
        )

    print(
        f"Total: {len(session_keys)} race sessions"
    )

    return 0


def _run_process(
    arguments: argparse.Namespace,
) -> int:
    """Process selected development sessions."""
    raw_paths = RawDataPaths(
        Path(arguments.raw_root)
    )
    processed_paths = ProcessedDataPaths(
        Path(arguments.processed_root)
    )

    all_session_keys = (
        _load_development_session_keys(
            raw_paths
        )
    )
    selected_session_keys = (
        _select_session_keys(
            all_session_keys=all_session_keys,
            seasons=arguments.season,
            round_numbers=(
                arguments.round_number
            ),
        )
    )

    session_runner = ProcessedPipelineRunner(
        raw_paths=raw_paths,
        processed_paths=processed_paths,
    )
    batch_runner = ProcessedBatchRunner(
        processed_paths=processed_paths,
        session_runner=session_runner,
    )

    result = batch_runner.run(
        selected_session_keys,
        force=arguments.force,
    )

    print(f"Run ID: {result.run_id}")

    for record in result.records:
        print(
            f"{record.session_key.identifier}: "
            f"{record.status} "
            f"({record.duration_seconds:.3f}s)"
        )

        if record.error_message is not None:
            print(
                f"  {record.error_type}: "
                f"{record.error_message}"
            )

    print(
        "Summary: "
        f"{result.written_count} written, "
        f"{result.skipped_count} skipped, "
        f"{result.failed_count} failed"
    )
    print(
        f"Run record: {result.record_path}"
    )

    available_session_keys = (
        _find_valid_processed_sessions(
            processed_paths=processed_paths,
            session_keys=all_session_keys,
        )
    )

    if available_session_keys:
        catalog_result = (
            ProcessedCatalogBuilder(
                processed_paths
            ).build(
                available_session_keys
            )
        )

        print(
            "Catalog: "
            f"{len(catalog_result.catalog)} "
            f"sessions at "
            f"{catalog_result.path}"
        )
    else:
        print(
            "Catalog: no valid processed "
            "sessions available"
        )

    return (
        0
        if result.succeeded
        else 1
    )


def _run_verify(
    arguments: argparse.Namespace,
) -> int:
    """Verify one processed development partition."""
    processed_paths = ProcessedDataPaths(
        Path(arguments.processed_root)
    )
    session_key = SessionKey(
        season=arguments.season,
        round_number=(
            arguments.round_number
        ),
    )

    report = verify_processed_partition(
        processed_paths,
        session_key,
    )

    if report.is_valid:
        print(
            f"{session_key.identifier}: valid"
        )
        return 0

    print(
        f"{session_key.identifier}: invalid"
    )

    for issue in report.issues:
        print(
            f"[{issue.code}] "
            f"{issue.message}"
        )

    return 1


def _run_catalog(
    arguments: argparse.Namespace,
) -> int:
    """Rebuild the catalog from valid processed sessions."""
    raw_paths = RawDataPaths(
        Path(arguments.raw_root)
    )
    processed_paths = ProcessedDataPaths(
        Path(arguments.processed_root)
    )

    all_session_keys = (
        _load_development_session_keys(
            raw_paths
        )
    )
    available_session_keys = (
        _find_valid_processed_sessions(
            processed_paths=processed_paths,
            session_keys=all_session_keys,
        )
    )

    if not available_session_keys:
        raise CleaningCliError(
            "no valid processed development "
            "sessions are available"
        )

    result = ProcessedCatalogBuilder(
        processed_paths
    ).build(
        available_session_keys
    )

    print(
        f"Catalog built: "
        f"{len(result.catalog)} sessions"
    )
    print(f"Path: {result.path}")
    print(f"SHA-256: {result.sha256}")

    return 0


def _load_development_session_keys(
    raw_paths: RawDataPaths,
) -> tuple[SessionKey, ...]:
    """Load development identities from the raw catalog."""
    if not raw_paths.catalog.is_file():
        raise CleaningCliError(
            "raw data catalog does not exist: "
            f"{raw_paths.catalog}"
        )

    catalog = read_parquet_table(
        raw_paths.catalog
    )
    required_columns = {
        "season",
        "round_number",
        "session_type",
    }
    missing_columns = sorted(
        required_columns.difference(
            catalog.columns
        )
    )

    if missing_columns:
        raise CleaningCliError(
            "raw catalog is missing columns: "
            f"{', '.join(missing_columns)}"
        )

    development_catalog = catalog[
        catalog["season"].isin(
            DEVELOPMENT_SEASONS
        )
    ]

    session_keys = tuple(
        sorted(
            (
                SessionKey(
                    season=int(row.season),
                    round_number=int(
                        row.round_number
                    ),
                    session_type=str(
                        row.session_type
                    ),
                )
                for row in (
                    development_catalog
                    .itertuples(index=False)
                )
            ),
            key=lambda session_key: (
                session_key.season,
                session_key.round_number,
                session_key.session_type,
            ),
        )
    )

    if not session_keys:
        raise CleaningCliError(
            "raw catalog contains no development sessions"
        )

    if (
        len(set(session_keys))
        != len(session_keys)
    ):
        raise CleaningCliError(
            "raw catalog contains duplicate "
            "development sessions"
        )

    return session_keys


def _select_session_keys(
    *,
    all_session_keys: tuple[
        SessionKey,
        ...,
    ],
    seasons: list[int] | None,
    round_numbers: list[int] | None,
) -> tuple[SessionKey, ...]:
    """Filter the raw development plan."""
    selected_seasons = (
        set(seasons)
        if seasons
        else set(DEVELOPMENT_SEASONS)
    )
    selected_rounds = (
        set(round_numbers)
        if round_numbers
        else None
    )

    selected = tuple(
        session_key
        for session_key in all_session_keys
        if (
            session_key.season
            in selected_seasons
            and (
                selected_rounds is None
                or session_key.round_number
                in selected_rounds
            )
        )
    )

    if not selected:
        raise CleaningCliError(
            "the requested selection contains "
            "no development sessions"
        )

    return selected


def _find_valid_processed_sessions(
    *,
    processed_paths: ProcessedDataPaths,
    session_keys: tuple[
        SessionKey,
        ...,
    ],
) -> tuple[SessionKey, ...]:
    """Find valid outputs while refusing hidden corruption."""
    valid_session_keys: list[
        SessionKey
    ] = []

    for session_key in session_keys:
        report = verify_processed_partition(
            processed_paths,
            session_key,
        )

        if report.is_valid:
            valid_session_keys.append(
                session_key
            )
            continue

        issue_codes = {
            issue.code
            for issue in report.issues
        }

        if issue_codes == {
            "MISSING_DIRECTORY"
        }:
            continue

        details = "; ".join(
            (
                f"{issue.code}: "
                f"{issue.message}"
            )
            for issue in report.issues
        )

        raise CleaningCliError(
            "existing processed partition failed "
            f"integrity for "
            f"{session_key.identifier}: "
            f"{details}"
        )

    return tuple(valid_session_keys)


def _add_raw_root_argument(
    parser: argparse.ArgumentParser,
) -> None:
    """Add the shared raw-root option."""
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=DEFAULT_RAW_ROOT,
        help=(
            "raw FastF1 dataset root"
        ),
    )


def _add_processed_root_argument(
    parser: argparse.ArgumentParser,
) -> None:
    """Add the shared processed-root option."""
    parser.add_argument(
        "--processed-root",
        type=Path,
        default=DEFAULT_PROCESSED_ROOT,
        help=(
            "processed FastF1 dataset root"
        ),
    )


def _add_selection_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    """Add repeatable development selection options."""
    parser.add_argument(
        "--season",
        type=int,
        action="append",
        choices=DEVELOPMENT_SEASONS,
        help=(
            "development season; may be repeated"
        ),
    )
    parser.add_argument(
        "--round",
        type=int,
        action="append",
        choices=range(1, 31),
        dest="round_number",
        help=(
            "race round; may be repeated"
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())