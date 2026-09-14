"""Command-line interface for Phase 4 dataset construction."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import cast

from app.cleaning.paths import ProcessedDataPaths
from app.datasets.batch import DatasetBatchRunner
from app.datasets.contracts import (
    DATASET_CONTRACT_VERSION,
    DEVELOPMENT_SEASONS,
    EXPECTED_DEVELOPMENT_TOTALS,
    EXPECTED_SEASON_TOTALS,
    PROTECTED_EVALUATION_SEASON,
)
from app.datasets.integrity import (
    DatasetIntegrityReport,
    verify_complete_dataset,
)
from app.datasets.paths import DatasetPaths
from app.datasets.runner import DatasetPipelineRunner
from app.pipeline.models import SessionKey
from app.pipeline.serialization import read_parquet_table

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROCESSED_ROOT = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "fastf1"
)
DEFAULT_DATASETS_ROOT = (
    PROJECT_ROOT
    / "data"
    / "datasets"
)

CommandHandler = Callable[
    [argparse.Namespace],
    int,
]


class DatasetCliError(RuntimeError):
    """Raised when a dataset CLI request cannot continue safely."""


def build_parser() -> argparse.ArgumentParser:
    """Build the Phase 4 dataset command-line parser."""
    parser = argparse.ArgumentParser(
        prog="python -m app.datasets.cli",
        description=(
            "Build and verify the leakage-controlled "
            "Formula 1 development dataset."
        ),
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    plan_parser = subparsers.add_parser(
        "plan",
        help=(
            "show the frozen development-dataset schedule"
        ),
    )
    _add_processed_root_argument(plan_parser)
    _add_datasets_root_argument(plan_parser)
    plan_parser.set_defaults(handler=_run_plan)

    build_command = subparsers.add_parser(
        "build",
        help=(
            "build all development sessions and global artifacts"
        ),
    )
    _add_processed_root_argument(build_command)
    _add_datasets_root_argument(build_command)
    build_command.add_argument(
        "--force",
        action="store_true",
        help=(
            "rebuild every dataset partition instead of resuming"
        ),
    )
    build_command.set_defaults(handler=_run_build)

    verify_parser = subparsers.add_parser(
        "verify",
        help=(
            "verify the complete stored development dataset"
        ),
    )
    _add_processed_root_argument(verify_parser)
    _add_datasets_root_argument(verify_parser)
    verify_parser.set_defaults(handler=_run_verify)

    return parser


def main(
    argv: list[str] | None = None,
) -> int:
    """Run one Phase 4 dataset command."""
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
    """Print the exact development-dataset schedule."""
    processed_paths = ProcessedDataPaths(
        Path(arguments.processed_root)
    )
    dataset_paths = DatasetPaths(
        Path(arguments.datasets_root)
    )
    session_keys = _load_development_session_keys(
        processed_paths
    )
    season_counts = Counter(
        session_key.season
        for session_key in session_keys
    )

    print("DEVELOPMENT DATASET PLAN")
    print("========================")
    print(
        "Dataset contract: "
        f"{DATASET_CONTRACT_VERSION}"
    )
    print(
        "Processed catalog: "
        f"{processed_paths.catalog}"
    )
    print(
        "Dataset directory: "
        f"{dataset_paths.version_root}"
    )
    print()
    print("SESSIONS BY SEASON")

    for season in sorted(season_counts):
        print(
            f"  {season}: "
            f"{season_counts[season]} races"
        )

    print()
    print(
        "Total: "
        f"{len(session_keys)} race sessions"
    )
    print(
        "Protected evaluation season: "
        f"{PROTECTED_EVALUATION_SEASON} excluded"
    )

    return 0


def _run_build(
    arguments: argparse.Namespace,
) -> int:
    """Build the complete dataset and verify the result."""
    processed_paths = ProcessedDataPaths(
        Path(arguments.processed_root)
    )
    dataset_paths = DatasetPaths(
        Path(arguments.datasets_root)
    )
    session_keys = _load_development_session_keys(
        processed_paths
    )
    session_runner = DatasetPipelineRunner(
        processed_paths=processed_paths,
        dataset_paths=dataset_paths,
    )
    batch_runner = DatasetBatchRunner(
        dataset_paths=dataset_paths,
        session_runner=session_runner,
    )
    result = batch_runner.run(
        session_keys,
        force=arguments.force,
    )

    print("DEVELOPMENT DATASET BUILD")
    print("=========================")
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

    print()
    print(
        "Summary: "
        f"{result.written_count} written, "
        f"{result.skipped_count} skipped, "
        f"{result.failed_count} failed"
    )
    print(
        "Global artifacts: "
        f"{result.global_artifact_status}"
    )
    print(f"Run record: {result.record_path}")

    if result.catalog_path is not None:
        print(f"Catalog: {result.catalog_path}")

    if result.splits_path is not None:
        print(f"Splits: {result.splits_path}")

    if result.global_error_message is not None:
        print(
            "Global error: "
            f"{result.global_error_type}: "
            f"{result.global_error_message}"
        )

    if not result.succeeded:
        print("Post-build integrity: not run")
        return 1

    integrity_report = verify_complete_dataset(
        dataset_paths,
        session_keys,
    )
    _print_integrity_report(integrity_report)

    return 0 if integrity_report.is_valid else 1


def _run_verify(
    arguments: argparse.Namespace,
) -> int:
    """Run read-only verification of the complete dataset."""
    processed_paths = ProcessedDataPaths(
        Path(arguments.processed_root)
    )
    dataset_paths = DatasetPaths(
        Path(arguments.datasets_root)
    )
    session_keys = _load_development_session_keys(
        processed_paths
    )
    report = verify_complete_dataset(
        dataset_paths,
        session_keys,
    )

    print("DEVELOPMENT DATASET INTEGRITY")
    print("=============================")
    _print_integrity_report(report)

    return 0 if report.is_valid else 1


def _print_integrity_report(
    report: DatasetIntegrityReport,
) -> None:
    """Print one deterministic complete-dataset report."""
    status = "valid" if report.is_valid else "invalid"

    print(f"Integrity status: {status}")
    print(
        "Requested sessions: "
        f"{report.requested_sessions}"
    )
    print(
        "Valid sessions: "
        f"{report.valid_sessions}"
    )
    print(f"Catalog rows: {report.catalog_rows}")
    print(f"Split rows: {report.split_rows}")
    print(f"Issues: {report.issue_count}")

    for issue in report.issues:
        identity = (
            f" session={issue.session_id}"
            if issue.session_id is not None
            else ""
        )
        print(
            f"[{issue.code.value}]"
            f"{identity} "
            f"path={issue.path} "
            f"{issue.message}"
        )


def _load_development_session_keys(
    processed_paths: ProcessedDataPaths,
) -> tuple[SessionKey, ...]:
    """Load and validate the frozen processed-data schedule."""
    if not isinstance(
        processed_paths,
        ProcessedDataPaths,
    ):
        raise TypeError(
            "processed_paths must be ProcessedDataPaths"
        )

    protected_directory = (
        processed_paths.version_root
        / f"season={PROTECTED_EVALUATION_SEASON}"
    )

    if protected_directory.exists():
        raise DatasetCliError(
            "protected evaluation-season processed directory "
            f"exists: {protected_directory}"
        )

    if not processed_paths.catalog.is_file():
        raise DatasetCliError(
            "processed data catalog does not exist: "
            f"{processed_paths.catalog}"
        )

    try:
        catalog = read_parquet_table(
            processed_paths.catalog
        )
    except Exception as error:
        raise DatasetCliError(
            "processed data catalog could not be read: "
            f"{type(error).__name__}: {error}"
        ) from error

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
        raise DatasetCliError(
            "processed catalog is missing columns: "
            f"{', '.join(missing_columns)}"
        )

    try:
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
                    for row in catalog.itertuples(
                        index=False
                    )
                ),
                key=lambda session_key: (
                    session_key.season,
                    session_key.round_number,
                    session_key.session_type,
                ),
            )
        )
    except (TypeError, ValueError) as error:
        raise DatasetCliError(
            "processed catalog contains an invalid "
            f"session identity: {error}"
        ) from error

    if not session_keys:
        raise DatasetCliError(
            "processed catalog contains no sessions"
        )

    if len(set(session_keys)) != len(session_keys):
        raise DatasetCliError(
            "processed catalog contains duplicate sessions"
        )

    invalid_seasons = sorted(
        {
            session_key.season
            for session_key in session_keys
        }.difference(DEVELOPMENT_SEASONS)
    )

    if invalid_seasons:
        raise DatasetCliError(
            "processed catalog contains non-development "
            "seasons: "
            + ", ".join(
                str(season)
                for season in invalid_seasons
            )
        )

    if (
        len(session_keys)
        != EXPECTED_DEVELOPMENT_TOTALS.sessions
    ):
        raise DatasetCliError(
            "complete dataset construction requires exactly "
            f"{EXPECTED_DEVELOPMENT_TOTALS.sessions} "
            "processed sessions; found "
            f"{len(session_keys)}"
        )

    actual_season_counts = Counter(
        session_key.season
        for session_key in session_keys
    )
    expected_season_counts = {
        total.season: total.sessions
        for total in EXPECTED_SEASON_TOTALS
    }

    if dict(actual_season_counts) != expected_season_counts:
        raise DatasetCliError(
            "processed catalog season counts differ from "
            f"the contract: expected {expected_season_counts}, "
            f"got {dict(actual_season_counts)}"
        )

    return session_keys


def _add_processed_root_argument(
    parser: argparse.ArgumentParser,
) -> None:
    """Add the shared processed-data root option."""
    parser.add_argument(
        "--processed-root",
        type=Path,
        default=DEFAULT_PROCESSED_ROOT,
        help="processed FastF1 dataset root",
    )


def _add_datasets_root_argument(
    parser: argparse.ArgumentParser,
) -> None:
    """Add the shared modelling-datasets root option."""
    parser.add_argument(
        "--datasets-root",
        type=Path,
        default=DEFAULT_DATASETS_ROOT,
        help="parent directory for modelling datasets",
    )


if __name__ == "__main__":
    raise SystemExit(main())