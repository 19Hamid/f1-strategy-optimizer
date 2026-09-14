"""Command-line interface for Phase 4 PostgreSQL loading and audit."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from app.cleaning import ProcessedDataPaths
from app.datasets import DatasetPaths
from app.datasets.cli import _load_development_session_keys
from app.db.batch_loading import DevelopmentDatabaseLoader
from app.db.loading import SessionDatabaseLoader
from app.db.reconciliation import reconcile_development_database
from app.db.runtime import (
    DatabaseSettings,
    create_database_engine,
    create_database_session_factory,
    database_transaction,
)
from app.pipeline import RawDataPaths

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RAW_ROOT = PROJECT_ROOT / "data" / "raw" / "fastf1"
DEFAULT_PROCESSED_ROOT = PROJECT_ROOT / "data" / "processed" / "fastf1"
DEFAULT_DATASETS_ROOT = PROJECT_ROOT / "data" / "datasets"


def build_parser() -> argparse.ArgumentParser:
    """Build the database command parser."""
    parser = argparse.ArgumentParser(
        prog="python -m app.db.cli",
        description=(
            "Load and reconcile the verified Phase 4 development database."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    load_parser = commands.add_parser(
        "load",
        help="load all 68 development races and reconcile PostgreSQL",
    )
    _add_path_arguments(load_parser)
    load_parser.add_argument(
        "--run-id",
        help="canonical build identifier; defaults to a UTC timestamp",
    )
    load_parser.set_defaults(handler=_run_load)

    audit_parser = commands.add_parser(
        "audit",
        help="read-only reconciliation of the populated database",
    )
    audit_parser.set_defaults(handler=_run_audit)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute one database command."""
    arguments = build_parser().parse_args(argv)
    handler = cast(object, arguments.handler)
    return handler(arguments)  # type: ignore[operator]


def _run_load(arguments: argparse.Namespace) -> int:
    """Load the complete authoritative development dataset."""
    raw_paths = RawDataPaths(Path(arguments.raw_root))
    processed_paths = ProcessedDataPaths(Path(arguments.processed_root))
    dataset_paths = DatasetPaths(Path(arguments.datasets_root))
    session_keys = _load_development_session_keys(processed_paths)
    run_id = arguments.run_id or _default_run_id()
    settings = DatabaseSettings.from_environment()
    engine = create_database_engine(settings)
    try:
        session_factory = create_database_session_factory(engine)
        session_loader = SessionDatabaseLoader(
            session_factory=session_factory,
            raw_paths=raw_paths,
            processed_paths=processed_paths,
            dataset_paths=dataset_paths,
        )
        result = DevelopmentDatabaseLoader(
            session_factory=session_factory,
            session_loader=session_loader,
            dataset_paths=dataset_paths,
        ).load(session_keys, run_id=run_id)
    finally:
        engine.dispose()

    print("DEVELOPMENT DATABASE LOAD")
    print("=========================")
    print(f"Run ID: {result.run_id}")
    print(f"Status: {result.status}")
    print(f"Requested sessions: {result.requested_sessions}")
    print(f"Written sessions: {result.written_sessions}")
    print(f"Verified sessions: {result.verified_sessions}")
    _print_reconciliation(result.reconciliation.actual)
    return 0


def _run_audit(arguments: argparse.Namespace) -> int:
    """Reconcile an already populated database without writing."""
    del arguments
    settings = DatabaseSettings.from_environment()
    engine = create_database_engine(settings)
    try:
        session_factory = create_database_session_factory(engine)
        with database_transaction(session_factory) as session:
            report = reconcile_development_database(session)
    finally:
        engine.dispose()

    print("DEVELOPMENT DATABASE AUDIT")
    print("==========================")
    print("Status: valid")
    _print_reconciliation(report.actual)
    return 0


def _print_reconciliation(actual: dict[str, int]) -> None:
    """Print deterministic sorted database totals."""
    print()
    print("RECONCILIATION TOTALS")
    for field, value in sorted(actual.items()):
        print(f"  {field}: {value}")


def _default_run_id(now: datetime | None = None) -> str:
    """Generate a filesystem-safe UTC run identity."""
    timestamp = datetime.now(UTC) if now is None else now
    if not isinstance(timestamp, datetime):
        raise TypeError("now must be a datetime")
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return timestamp.astimezone(UTC).strftime(
        "database-%Y%m%dT%H%M%SZ"
    )


def _add_path_arguments(parser: argparse.ArgumentParser) -> None:
    """Add authoritative artifact roots used by the loader."""
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=DEFAULT_RAW_ROOT,
        help="raw FastF1 dataset root",
    )
    parser.add_argument(
        "--processed-root",
        type=Path,
        default=DEFAULT_PROCESSED_ROOT,
        help="processed FastF1 dataset root",
    )
    parser.add_argument(
        "--datasets-root",
        type=Path,
        default=DEFAULT_DATASETS_ROOT,
        help="parent directory for modelling datasets",
    )


if __name__ == "__main__":
    raise SystemExit(main())
