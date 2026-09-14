"""Run modelling-dataset construction for one race session."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.cleaning.integrity import verify_processed_partition
from app.cleaning.paths import ProcessedDataPaths
from app.datasets.contracts import DEVELOPMENT_SEASONS
from app.datasets.decisions import build_session_decisions
from app.datasets.normalization import normalize_processed_session_tables
from app.datasets.paths import (
    DatasetPaths,
    DatasetSessionPaths,
)
from app.datasets.pit_durations import (
    build_pit_duration_observations,
    validate_pit_duration_session,
)
from app.datasets.storage import (
    DatasetSessionData,
    DatasetSessionWriter,
    DatasetStorageError,
    ProcessedSourceReference,
    _validate_completed_partition,
)
from app.datasets.validation import validate_decision_session
from app.pipeline.models import SessionKey
from app.pipeline.serialization import (
    read_parquet_table,
    sha256_file,
)


class DatasetPipelineError(RuntimeError):
    """Raised when dataset execution cannot continue safely."""


@dataclass(frozen=True, slots=True)
class DatasetSessionRunResult:
    """Describe one modelling-dataset session execution."""

    status: Literal["written", "skipped"]
    session_key: SessionKey
    directory: Path
    manifest: dict[str, object]
    quality_report: dict[str, object]


@dataclass(frozen=True, slots=True)
class DatasetPipelineRunner:
    """Build verified modelling data from processed data."""

    processed_paths: ProcessedDataPaths
    dataset_paths: DatasetPaths
    writer: DatasetSessionWriter | None = None

    def __post_init__(self) -> None:
        """Validate and complete runner dependencies."""
        if not isinstance(
            self.processed_paths,
            ProcessedDataPaths,
        ):
            raise TypeError(
                "processed_paths must be ProcessedDataPaths"
            )

        if not isinstance(
            self.dataset_paths,
            DatasetPaths,
        ):
            raise TypeError(
                "dataset_paths must be DatasetPaths"
            )

        writer = self.writer

        if writer is None:
            writer = DatasetSessionWriter(
                self.dataset_paths
            )
            object.__setattr__(
                self,
                "writer",
                writer,
            )
        elif not isinstance(
            writer,
            DatasetSessionWriter,
        ):
            raise TypeError(
                "writer must be a DatasetSessionWriter"
            )

        if writer.dataset_paths != self.dataset_paths:
            raise ValueError(
                "writer and runner must use the same dataset paths"
            )

    def run_session(
        self,
        session_key: SessionKey,
        *,
        force: bool = False,
    ) -> DatasetSessionRunResult:
        """Construct and atomically store one dataset session."""
        _validate_session_key(session_key)

        if not isinstance(force, bool):
            raise TypeError(
                "force must be a boolean"
            )

        session_paths = self.dataset_paths.for_session(
            session_key
        )

        if not force and session_paths.directory.exists():
            return _validated_existing_result(
                session_key=session_key,
                session_paths=session_paths,
            )

        processed_integrity = verify_processed_partition(
            self.processed_paths,
            session_key,
        )
        processed_integrity.raise_for_errors()

        processed_manifest = processed_integrity.manifest

        if processed_manifest is None:
            raise DatasetPipelineError(
                "valid processed partition has no manifest"
            )

        processed_session_paths = (
            self.processed_paths.for_session(
                session_key
            )
        )

        normalized = normalize_processed_session_tables(
            laps=read_parquet_table(
                processed_session_paths.laps
            ),
            stints=read_parquet_table(
                processed_session_paths.stints
            ),
            pit_events=read_parquet_table(
                processed_session_paths.pit_events
            ),
            session_key=session_key,
        )

        decisions = build_session_decisions(
            normalized
        )
        decision_report = validate_decision_session(
            decisions
        )
        decision_report.raise_for_errors()

        pit_durations = (
            build_pit_duration_observations(
                normalized
            )
        )
        pit_report = validate_pit_duration_session(
            pit_durations
        )
        pit_report.raise_for_errors()

        source = _build_source_reference(
            manifest=processed_manifest,
            directory=processed_session_paths.directory,
            manifest_path=processed_session_paths.manifest,
            laps_path=processed_session_paths.laps,
            stints_path=processed_session_paths.stints,
            pit_events_path=(
                processed_session_paths.pit_events
            ),
        )

        data = DatasetSessionData(
            source_lap_count=len(
                normalized.laps
            ),
            decisions=decisions,
            pit_durations=pit_durations,
            source=source,
        )

        writer = self.writer

        if writer is None:
            raise DatasetPipelineError(
                "dataset writer is unavailable"
            )

        write_result = writer.write(
            data,
            force=force,
        )

        final_manifest, final_quality_report = (
            _validate_completed_partition(
                session_paths
            )
        )

        return DatasetSessionRunResult(
            status=write_result.status,
            session_key=session_key,
            directory=write_result.directory,
            manifest=final_manifest,
            quality_report=final_quality_report,
        )


def _validate_session_key(
    session_key: SessionKey,
) -> None:
    """Require one supported development race identity."""
    if not isinstance(session_key, SessionKey):
        raise TypeError(
            "session_key must be a SessionKey"
        )

    if session_key.season not in DEVELOPMENT_SEASONS:
        supported = ", ".join(
            str(season)
            for season in DEVELOPMENT_SEASONS
        )

        raise DatasetPipelineError(
            "dataset construction supports only development "
            f"seasons: {supported}"
        )


def _validated_existing_result(
    *,
    session_key: SessionKey,
    session_paths: DatasetSessionPaths,
) -> DatasetSessionRunResult:
    """Verify and return one safe existing partition."""
    if not session_paths.manifest.is_file():
        raise DatasetPipelineError(
            "dataset session directory exists without a "
            "completed manifest: "
            f"{session_paths.directory}. Use force=True "
            "to rebuild it."
        )

    try:
        manifest, quality_report = (
            _validate_completed_partition(
                session_paths
            )
        )
    except DatasetStorageError as error:
        raise DatasetPipelineError(
            "existing dataset partition failed integrity for "
            f"{session_key.identifier}: {error}. Use force=True "
            "to rebuild it."
        ) from error

    return DatasetSessionRunResult(
        status="skipped",
        session_key=session_key,
        directory=session_paths.directory,
        manifest=manifest,
        quality_report=quality_report,
    )


def _build_source_reference(
    *,
    manifest: dict[str, object],
    directory: Path,
    manifest_path: Path,
    laps_path: Path,
    stints_path: Path,
    pit_events_path: Path,
) -> ProcessedSourceReference:
    """Capture immutable processed-source provenance."""
    return ProcessedSourceReference(
        cleaning_rule_version=_require_manifest_text(
            manifest,
            "cleaning_rule_version",
        ),
        processed_contract_version=(
            _require_manifest_text(
                manifest,
                "processed_contract_version",
            )
        ),
        session_directory=str(directory),
        manifest_sha256=sha256_file(
            manifest_path
        ),
        laps_sha256=sha256_file(laps_path),
        stints_sha256=sha256_file(stints_path),
        pit_events_sha256=sha256_file(
            pit_events_path
        ),
    )


def _require_manifest_text(
    manifest: dict[str, object],
    field: str,
) -> str:
    """Return one required non-empty manifest text field."""
    value = manifest.get(field)

    if not isinstance(value, str) or not value.strip():
        raise DatasetPipelineError(
            f"processed manifest {field} must be non-empty text"
        )

    return value