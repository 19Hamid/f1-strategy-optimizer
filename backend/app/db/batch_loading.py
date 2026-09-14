"""Orchestrate complete, auditable development-database builds."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from app.datasets import (
    DATASET_CONTRACT_VERSION,
    DEVELOPMENT_SEASONS,
    EXPECTED_DEVELOPMENT_TOTALS,
    EXPECTED_SEASON_TOTALS,
    SOURCE_CLEANING_RULE_VERSION,
    SOURCE_PROCESSED_CONTRACT_VERSION,
    TEMPORAL_FOLDS,
    DatasetPaths,
)
from app.datasets.contracts import PROTECTED_EVALUATION_SEASON, SPLITS_CONTRACT
from app.db.base import DATABASE_SCHEMA_VERSION
from app.db.loading import SessionDatabaseLoader, SessionLoadResult
from app.db.provenance import DatasetBuild, DatasetVersion
from app.db.reconciliation import (
    DatabaseReconciliationReport,
    reconcile_development_database,
)
from app.db.repositories import ImmutableRepository
from app.db.runtime import database_transaction
from app.db.temporal_splits import SessionSplitAssignment, TemporalFold
from app.pipeline import SessionKey
from app.pipeline.storage import RAW_CONTRACT_VERSION
from app.pipeline.serialization import read_parquet_table, sha256_file


class DatabaseBatchLoadError(RuntimeError):
    """Raised when a complete development database build cannot finish safely."""


@dataclass(frozen=True, slots=True)
class DatabaseBatchLoadResult:
    """Summarize one terminal complete-database build."""

    run_id: str
    status: str
    requested_sessions: int
    written_sessions: int
    verified_sessions: int
    reconciliation: DatabaseReconciliationReport


@dataclass(frozen=True, slots=True)
class DevelopmentDatabaseLoader:
    """Load all authoritative Phase 4 artifacts into PostgreSQL."""

    session_factory: sessionmaker[Session]
    session_loader: SessionDatabaseLoader
    dataset_paths: DatasetPaths

    def __post_init__(self) -> None:
        """Require explicit, mutually compatible dependencies."""
        if not isinstance(self.session_factory, sessionmaker):
            raise TypeError("session_factory must be a sessionmaker")
        if not isinstance(self.session_loader, SessionDatabaseLoader):
            raise TypeError("session_loader must be a SessionDatabaseLoader")
        if not isinstance(self.dataset_paths, DatasetPaths):
            raise TypeError("dataset_paths must be DatasetPaths")
        if self.session_loader.session_factory is not self.session_factory:
            raise DatabaseBatchLoadError(
                "batch and session loaders must share one session factory"
            )
        if self.session_loader.dataset_paths != self.dataset_paths:
            raise DatabaseBatchLoadError(
                "batch and session loaders must share dataset paths"
            )

    def load(
        self,
        session_keys: Iterable[SessionKey],
        *,
        run_id: str,
        started_at_utc: datetime | None = None,
    ) -> DatabaseBatchLoadResult:
        """Load, finalize and reconcile one complete development run."""
        keys = _validate_session_keys(session_keys)
        normalized_run_id = _validate_run_id(run_id)
        started = _normalize_started_at(started_at_utc)
        catalog_hash, splits_hash = _global_artifact_hashes(self.dataset_paths)
        split_rows = _read_split_rows(self.dataset_paths, keys)

        self._open_build(
            run_id=normalized_run_id,
            started_at_utc=started,
            requested_sessions=len(keys),
        )
        results: list[SessionLoadResult] = []
        try:
            for key in keys:
                results.append(
                    self.session_loader.load(key, run_id=normalized_run_id)
                )

            with database_transaction(self.session_factory) as session:
                _persist_temporal_splits(session, split_rows)
                reconciliation = reconcile_development_database(session)
                written = sum(result.status == "written" for result in results)
                verified = len(results) - written
                _finish_build(
                    session,
                    run_id=normalized_run_id,
                    status="SUCCEEDED",
                    completed_at_utc=datetime.now(UTC),
                    written_sessions=written,
                    skipped_sessions=verified,
                    failed_sessions=0,
                    catalog_sha256=catalog_hash,
                    splits_sha256=splits_hash,
                )
        except Exception:
            self._fail_build(
                run_id=normalized_run_id,
                completed_sessions=len(results),
                written_sessions=sum(
                    result.status == "written" for result in results
                ),
            )
            raise

        return DatabaseBatchLoadResult(
            run_id=normalized_run_id,
            status="SUCCEEDED",
            requested_sessions=len(keys),
            written_sessions=written,
            verified_sessions=verified,
            reconciliation=reconciliation,
        )

    def _open_build(
        self,
        *,
        run_id: str,
        started_at_utc: datetime,
        requested_sessions: int,
    ) -> None:
        """Initialize immutable version metadata and one RUNNING build."""
        with database_transaction(self.session_factory) as session:
            ImmutableRepository(
                DatasetVersion.__table__,
                ("dataset_contract_version",),
            ).insert_or_verify(
                session,
                {
                    "dataset_contract_version": DATASET_CONTRACT_VERSION,
                    "database_schema_version": DATABASE_SCHEMA_VERSION,
                    "source_contract_version": RAW_CONTRACT_VERSION,
                    "processed_contract_version": (
                        SOURCE_PROCESSED_CONTRACT_VERSION
                    ),
                    "cleaning_rule_version": SOURCE_CLEANING_RULE_VERSION,
                    "created_at_utc": started_at_utc,
                },
            )
            ImmutableRepository(
                DatasetBuild.__table__,
                ("run_id",),
            ).insert_or_verify(
                session,
                {
                    "run_id": run_id,
                    "dataset_contract_version": DATASET_CONTRACT_VERSION,
                    "started_at_utc": started_at_utc,
                    "completed_at_utc": None,
                    "status": "RUNNING",
                    "requested_sessions": requested_sessions,
                    "written_sessions": 0,
                    "skipped_sessions": 0,
                    "failed_sessions": 0,
                    "catalog_sha256": None,
                    "splits_sha256": None,
                    "run_record_path": str(
                        self.dataset_paths.run_record(run_id)
                    ),
                },
            )

    def _fail_build(
        self,
        *,
        run_id: str,
        completed_sessions: int,
        written_sessions: int,
    ) -> None:
        """Record a terminal failure without masking the original error."""
        with database_transaction(self.session_factory) as session:
            skipped = completed_sessions - written_sessions
            failed = (
                EXPECTED_DEVELOPMENT_TOTALS.sessions - completed_sessions
            )
            _finish_build(
                session,
                run_id=run_id,
                status="FAILED",
                completed_at_utc=datetime.now(UTC),
                written_sessions=written_sessions,
                skipped_sessions=skipped,
                failed_sessions=failed,
                catalog_sha256=None,
                splits_sha256=None,
            )


def _validate_run_id(run_id: str) -> str:
    """Return one canonical build identifier."""
    if not isinstance(run_id, str):
        raise TypeError("run_id must be a string")
    if not run_id or run_id != run_id.strip():
        raise DatabaseBatchLoadError("run_id must be non-blank canonical text")
    return run_id


def _normalize_started_at(value: datetime | None) -> datetime:
    """Return a timezone-aware UTC build start."""
    started = datetime.now(UTC) if value is None else value
    if not isinstance(started, datetime):
        raise TypeError("started_at_utc must be a datetime")
    if started.tzinfo is None or started.utcoffset() is None:
        raise DatabaseBatchLoadError("started_at_utc must be timezone-aware")
    return started.astimezone(UTC)


def _validate_session_keys(
    session_keys: Iterable[SessionKey],
) -> tuple[SessionKey, ...]:
    """Require the exact canonical 68-race development schedule."""
    if isinstance(session_keys, (str, bytes)):
        raise TypeError("session_keys must be an iterable of SessionKey values")
    try:
        keys = tuple(session_keys)
    except TypeError as error:
        raise TypeError(
            "session_keys must be an iterable of SessionKey values"
        ) from error
    if any(not isinstance(key, SessionKey) for key in keys):
        raise TypeError("session_keys must contain only SessionKey values")
    if any(key.season == PROTECTED_EVALUATION_SEASON for key in keys):
        raise DatabaseBatchLoadError(
            "protected evaluation sessions must be rejected before SQL"
        )
    if any(
        key.season not in DEVELOPMENT_SEASONS or key.session_type != "R"
        for key in keys
    ):
        raise DatabaseBatchLoadError(
            "database loading accepts development race sessions only"
        )
    identifiers = [key.identifier for key in keys]
    if len(identifiers) != len(set(identifiers)):
        raise DatabaseBatchLoadError("database session identities must be unique")
    expected_counts = {
        total.season: total.sessions for total in EXPECTED_SEASON_TOTALS
    }
    actual_counts = Counter(key.season for key in keys)
    if len(keys) != EXPECTED_DEVELOPMENT_TOTALS.sessions:
        raise DatabaseBatchLoadError(
            "complete database loading requires exactly "
            f"{EXPECTED_DEVELOPMENT_TOTALS.sessions} sessions"
        )
    if dict(actual_counts) != expected_counts:
        raise DatabaseBatchLoadError(
            "database session season counts differ from the frozen contract"
        )
    return tuple(
        sorted(
            keys,
            key=lambda key: (
                key.season,
                key.round_number,
                key.session_type,
            ),
        )
    )


def _global_artifact_hashes(dataset_paths: DatasetPaths) -> tuple[str, str]:
    """Hash required global artifacts before opening a transaction."""
    missing = [
        path
        for path in (dataset_paths.catalog, dataset_paths.splits)
        if not path.is_file()
    ]
    if missing:
        raise DatabaseBatchLoadError(
            "required global dataset artifacts are missing: "
            + ", ".join(str(path) for path in missing)
        )
    return sha256_file(dataset_paths.catalog), sha256_file(dataset_paths.splits)


def _read_split_rows(
    dataset_paths: DatasetPaths,
    session_keys: tuple[SessionKey, ...],
) -> tuple[dict[str, object], ...]:
    """Read and strictly validate frozen split identities."""
    splits = read_parquet_table(dataset_paths.splits)
    SPLITS_CONTRACT.validate_column_order(splits.columns)
    if splits.isna().any(axis=None):
        raise DatabaseBatchLoadError("temporal splits contain missing values")
    expected_ids = {key.identifier for key in session_keys}
    if set(splits["session_id"].astype(str)) != expected_ids:
        raise DatabaseBatchLoadError(
            "temporal split sessions differ from the load schedule"
        )
    if len(splits) != EXPECTED_DEVELOPMENT_TOTALS.split_rows:
        raise DatabaseBatchLoadError(
            "temporal split row count differs from the frozen contract"
        )
    records: list[dict[str, object]] = []
    for record in splits.to_dict(orient="records"):
        records.append(
            {
                "dataset_contract_version": DATASET_CONTRACT_VERSION,
                **{
                    key: _python_scalar(value)
                    for key, value in record.items()
                },
            }
        )
    return tuple(records)


def _python_scalar(value: object) -> object:
    """Convert pandas scalar wrappers to SQL-friendly Python values."""
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return value.item() if hasattr(value, "item") else value


def _persist_temporal_splits(
    session: Session,
    rows: tuple[dict[str, object], ...],
) -> None:
    """Insert or verify immutable fold definitions and assignments."""
    for fold in TEMPORAL_FOLDS:
        ImmutableRepository(
            TemporalFold.__table__,
            ("dataset_contract_version", "fold_id"),
        ).insert_or_verify(
            session,
            {
                "dataset_contract_version": DATASET_CONTRACT_VERSION,
                "fold_id": fold.fold_id,
                "train_seasons": list(fold.train_seasons),
                "validation_seasons": list(fold.validation_seasons),
                "excluded_seasons": list(fold.excluded_seasons),
            },
        )
    repository = ImmutableRepository(
        SessionSplitAssignment.__table__,
        ("dataset_contract_version", "fold_id", "session_id"),
    )
    for row in rows:
        repository.insert_or_verify(session, row)


def _finish_build(
    session: Session,
    *,
    run_id: str,
    status: str,
    completed_at_utc: datetime,
    written_sessions: int,
    skipped_sessions: int,
    failed_sessions: int,
    catalog_sha256: str | None,
    splits_sha256: str | None,
) -> None:
    """Transition one RUNNING build to its terminal state exactly once."""
    result = session.execute(
        update(DatasetBuild)
        .where(
            DatasetBuild.run_id == run_id,
            DatasetBuild.status == "RUNNING",
        )
        .values(
            completed_at_utc=completed_at_utc,
            status=status,
            written_sessions=written_sessions,
            skipped_sessions=skipped_sessions,
            failed_sessions=failed_sessions,
            catalog_sha256=catalog_sha256,
            splits_sha256=splits_sha256,
        )
    )
    if result.rowcount != 1:
        raise DatabaseBatchLoadError(
            f"database build {run_id!r} is absent or not RUNNING"
        )
