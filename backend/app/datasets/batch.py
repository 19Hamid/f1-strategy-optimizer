"""Execute modelling-dataset construction across development races."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Literal
from uuid import uuid4

import pandas as pd

from app.datasets.catalog import DatasetCatalogBuilder
from app.datasets.contracts import (
    DATASET_CONTRACT_VERSION,
    DEVELOPMENT_SEASONS,
    EXPECTED_DEVELOPMENT_TOTALS,
    EXPECTED_SEASON_TOTALS,
    SPLITS_CONTRACT,
)
from app.datasets.paths import DatasetPaths
from app.datasets.runner import DatasetPipelineRunner
from app.datasets.splits import (
    build_temporal_splits,
    validate_temporal_splits,
)
from app.pipeline.models import SessionKey
from app.pipeline.serialization import (
    read_parquet_table,
    sha256_file,
    write_json_document,
    write_parquet_table,
)

DatasetBatchSessionStatus = Literal[
    "written",
    "skipped",
    "failed",
]

DatasetGlobalArtifactStatus = Literal[
    "published",
    "not_published",
    "failed",
]


class DatasetBatchError(RuntimeError):
    """Raised when dataset batch setup or publication fails."""


@dataclass(frozen=True, slots=True)
class DatasetBatchSessionRecord:
    """Describe one session attempted by a dataset batch."""

    session_key: SessionKey
    status: DatasetBatchSessionStatus
    duration_seconds: float
    directory: Path
    error_type: str | None = None
    error_message: str | None = None

    def to_document(self) -> dict[str, object]:
        """Convert the session record into JSON-safe data."""
        return {
            "session_id": self.session_key.identifier,
            "season": self.session_key.season,
            "round_number": (
                self.session_key.round_number
            ),
            "session_type": (
                self.session_key.session_type
            ),
            "status": self.status,
            "duration_seconds": (
                self.duration_seconds
            ),
            "directory": str(self.directory),
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


@dataclass(frozen=True, slots=True)
class DatasetBatchRunResult:
    """Describe a completed development-dataset batch."""

    run_id: str
    records: tuple[
        DatasetBatchSessionRecord,
        ...,
    ]
    record_path: Path
    global_artifact_status: (
        DatasetGlobalArtifactStatus
    )
    catalog_path: Path | None = None
    catalog_sha256: str | None = None
    splits_path: Path | None = None
    splits_sha256: str | None = None
    global_error_type: str | None = None
    global_error_message: str | None = None

    @property
    def session_count(self) -> int:
        """Return the number of attempted sessions."""
        return len(self.records)

    @property
    def written_count(self) -> int:
        """Return the number of newly written sessions."""
        return sum(
            record.status == "written"
            for record in self.records
        )

    @property
    def skipped_count(self) -> int:
        """Return the number of verified skips."""
        return sum(
            record.status == "skipped"
            for record in self.records
        )

    @property
    def failed_count(self) -> int:
        """Return the number of failed sessions."""
        return sum(
            record.status == "failed"
            for record in self.records
        )

    @property
    def succeeded(self) -> bool:
        """Return whether sessions and global publication passed."""
        return (
            self.failed_count == 0
            and self.global_artifact_status
            == "published"
        )


@dataclass(frozen=True, slots=True)
class DatasetBatchRunner:
    """Build the complete versioned development dataset."""

    dataset_paths: DatasetPaths
    session_runner: DatasetPipelineRunner

    def __post_init__(self) -> None:
        """Validate batch dependencies."""
        if not isinstance(
            self.dataset_paths,
            DatasetPaths,
        ):
            raise TypeError(
                "dataset_paths must be DatasetPaths"
            )

        if not isinstance(
            self.session_runner,
            DatasetPipelineRunner,
        ):
            raise TypeError(
                "session_runner must be a DatasetPipelineRunner"
            )

        if (
            self.session_runner.dataset_paths
            != self.dataset_paths
        ):
            raise ValueError(
                "session runner and batch runner must use "
                "the same dataset paths"
            )

    def run(
        self,
        session_keys: Iterable[SessionKey],
        *,
        force: bool = False,
    ) -> DatasetBatchRunResult:
        """Build every development session and global artifact."""
        if not isinstance(force, bool):
            raise TypeError(
                "force must be a boolean"
            )

        requested_sessions = _validate_session_keys(
            session_keys
        )
        run_id = _new_run_id()
        started_at_utc = _utc_timestamp()
        batch_started = perf_counter()
        records: list[
            DatasetBatchSessionRecord
        ] = []

        for session_key in requested_sessions:
            session_started = perf_counter()
            intended_directory = (
                self.dataset_paths
                .for_session(session_key)
                .directory
            )

            try:
                result = (
                    self.session_runner.run_session(
                        session_key,
                        force=force,
                    )
                )
            except Exception as error:  # noqa: BLE001
                records.append(
                    DatasetBatchSessionRecord(
                        session_key=session_key,
                        status="failed",
                        duration_seconds=(
                            perf_counter()
                            - session_started
                        ),
                        directory=(
                            intended_directory
                        ),
                        error_type=(
                            type(error).__name__
                        ),
                        error_message=str(error),
                    )
                )
                continue

            records.append(
                DatasetBatchSessionRecord(
                    session_key=session_key,
                    status=result.status,
                    duration_seconds=(
                        perf_counter()
                        - session_started
                    ),
                    directory=result.directory,
                )
            )

        (
            artifact_status,
            catalog_path,
            catalog_sha256,
            splits_path,
            splits_sha256,
            global_error_type,
            global_error_message,
        ) = _publish_global_artifacts(
            dataset_paths=self.dataset_paths,
            session_keys=requested_sessions,
            records=tuple(records),
        )

        completed_at_utc = _utc_timestamp()
        total_duration_seconds = (
            perf_counter() - batch_started
        )
        record_path = self.dataset_paths.run_record(
            run_id
        )
        result = DatasetBatchRunResult(
            run_id=run_id,
            records=tuple(records),
            record_path=record_path,
            global_artifact_status=(
                artifact_status
            ),
            catalog_path=catalog_path,
            catalog_sha256=catalog_sha256,
            splits_path=splits_path,
            splits_sha256=splits_sha256,
            global_error_type=global_error_type,
            global_error_message=(
                global_error_message
            ),
        )

        write_json_document(
            _build_run_document(
                result=result,
                started_at_utc=started_at_utc,
                completed_at_utc=(
                    completed_at_utc
                ),
                duration_seconds=(
                    total_duration_seconds
                ),
                force=force,
            ),
            record_path,
        )

        return result


def _publish_global_artifacts(
    *,
    dataset_paths: DatasetPaths,
    session_keys: tuple[SessionKey, ...],
    records: tuple[
        DatasetBatchSessionRecord,
        ...,
    ],
) -> tuple[
    DatasetGlobalArtifactStatus,
    Path | None,
    str | None,
    Path | None,
    str | None,
    str | None,
    str | None,
]:
    """Publish splits and catalog only after all sessions pass."""
    if any(
        record.status == "failed"
        for record in records
    ):
        return (
            "not_published",
            None,
            None,
            None,
            None,
            None,
            None,
        )

    try:
        split_result = build_temporal_splits(
            session_keys
        )
        splits_sha256 = _publish_splits(
            dataset_paths=dataset_paths,
            session_keys=session_keys,
            splits=split_result.splits,
        )
        catalog_result = DatasetCatalogBuilder(
            dataset_paths
        ).build(
            session_keys
        )
    except Exception as error:  # noqa: BLE001
        return (
            "failed",
            None,
            None,
            (
                dataset_paths.splits
                if dataset_paths.splits.is_file()
                else None
            ),
            (
                sha256_file(
                    dataset_paths.splits
                )
                if dataset_paths.splits.is_file()
                else None
            ),
            type(error).__name__,
            str(error),
        )

    return (
        "published",
        catalog_result.path,
        catalog_result.sha256,
        dataset_paths.splits,
        splits_sha256,
        None,
        None,
    )


def _publish_splits(
    *,
    dataset_paths: DatasetPaths,
    session_keys: tuple[SessionKey, ...],
    splits: pd.DataFrame,
) -> str:
    """Read back and atomically publish frozen temporal splits."""
    report = validate_temporal_splits(
        splits,
        session_keys,
    )
    report.raise_for_errors()

    temporary_path = (
        dataset_paths.version_root
        / ".tmp"
        / SPLITS_CONTRACT.file_name
    )

    if temporary_path.exists():
        temporary_path.unlink()

    try:
        write_parquet_table(
            splits,
            temporary_path,
        )
        restored = read_parquet_table(
            temporary_path
        )

        try:
            pd.testing.assert_frame_equal(
                restored,
                splits,
            )
        except AssertionError as error:
            raise DatasetBatchError(
                "temporal split Parquet readback differs "
                "from its source"
            ) from error

        restored_report = validate_temporal_splits(
            restored,
            session_keys,
        )
        restored_report.raise_for_errors()

        dataset_paths.splits.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        temporary_path.replace(
            dataset_paths.splits
        )
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    return sha256_file(
        dataset_paths.splits
    )


def _validate_session_keys(
    session_keys: Iterable[SessionKey],
) -> tuple[SessionKey, ...]:
    """Validate and freeze the complete development schedule."""
    if isinstance(
        session_keys,
        (str, bytes),
    ):
        raise TypeError(
            "session_keys must be an iterable of SessionKey objects"
        )

    try:
        requested = tuple(session_keys)
    except TypeError as error:
        raise TypeError(
            "session_keys must be iterable"
        ) from error

    if not requested:
        raise DatasetBatchError(
            "at least one session key is required"
        )

    for session_key in requested:
        if not isinstance(
            session_key,
            SessionKey,
        ):
            raise TypeError(
                "every requested session must be a SessionKey"
            )

        if session_key.season not in DEVELOPMENT_SEASONS:
            supported = ", ".join(
                str(season)
                for season in DEVELOPMENT_SEASONS
            )

            raise DatasetBatchError(
                "dataset development batches support only "
                f"seasons: {supported}"
            )

    identifiers = [
        session_key.identifier
        for session_key in requested
    ]

    if len(identifiers) != len(set(identifiers)):
        raise DatasetBatchError(
            "duplicate session keys are not allowed"
        )

    if (
        len(requested)
        != EXPECTED_DEVELOPMENT_TOTALS.sessions
    ):
        raise DatasetBatchError(
            "a complete development batch requires exactly "
            f"{EXPECTED_DEVELOPMENT_TOTALS.sessions} sessions"
        )

    actual_season_counts = Counter(
        session_key.season
        for session_key in requested
    )
    expected_season_counts = {
        total.season: total.sessions
        for total in EXPECTED_SEASON_TOTALS
    }

    if dict(actual_season_counts) != expected_season_counts:
        raise DatasetBatchError(
            "development batch season counts differ from "
            f"the contract: expected {expected_season_counts}, "
            f"got {dict(actual_season_counts)}"
        )

    return tuple(
        sorted(
            requested,
            key=lambda session_key: (
                session_key.season,
                session_key.round_number,
                session_key.session_type,
            ),
        )
    )


def _build_run_document(
    *,
    result: DatasetBatchRunResult,
    started_at_utc: str,
    completed_at_utc: str,
    duration_seconds: float,
    force: bool,
) -> dict[str, object]:
    """Build the auditable JSON batch record."""
    return {
        "run_id": result.run_id,
        "dataset_contract_version": (
            DATASET_CONTRACT_VERSION
        ),
        "development_seasons": list(
            DEVELOPMENT_SEASONS
        ),
        "started_at_utc": started_at_utc,
        "completed_at_utc": completed_at_utc,
        "duration_seconds": duration_seconds,
        "force": force,
        "requested_sessions": (
            result.session_count
        ),
        "summary": {
            "written": result.written_count,
            "skipped": result.skipped_count,
            "failed": result.failed_count,
            "succeeded": result.succeeded,
        },
        "global_artifacts": {
            "status": (
                result.global_artifact_status
            ),
            "catalog_path": (
                str(result.catalog_path)
                if result.catalog_path is not None
                else None
            ),
            "catalog_sha256": (
                result.catalog_sha256
            ),
            "splits_path": (
                str(result.splits_path)
                if result.splits_path is not None
                else None
            ),
            "splits_sha256": (
                result.splits_sha256
            ),
            "error_type": (
                result.global_error_type
            ),
            "error_message": (
                result.global_error_message
            ),
        },
        "sessions": [
            record.to_document()
            for record in result.records
        ],
    }


def _new_run_id() -> str:
    """Create a sortable unique batch identifier."""
    timestamp = (
        datetime.now(UTC)
        .strftime("%Y%m%dT%H%M%S%fZ")
    )

    return (
        f"{timestamp}-"
        f"{uuid4().hex[:8]}"
    )


def _utc_timestamp() -> str:
    """Return the current time as ISO 8601 UTC text."""
    return (
        datetime.now(UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )