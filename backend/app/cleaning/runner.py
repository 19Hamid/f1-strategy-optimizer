"""Run processed-data construction for one race session."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.cleaning.integrity import (
    ProcessedIntegrityReport,
    verify_processed_partition,
)
from app.cleaning.paths import ProcessedDataPaths
from app.cleaning.processing import (
    process_session_tables,
)
from app.cleaning.storage import (
    ProcessedSessionWriter,
)
from app.pipeline.integrity import (
    verify_session_partition,
)
from app.pipeline.models import SessionKey
from app.pipeline.paths import RawDataPaths
from app.pipeline.serialization import (
    read_parquet_table,
)


class ProcessedPipelineError(RuntimeError):
    """Raised when processed execution cannot continue safely."""


@dataclass(frozen=True, slots=True)
class ProcessedSessionRunResult:
    """Describe one processed-session execution."""

    status: Literal["written", "skipped"]
    session_key: SessionKey
    directory: Path
    manifest: dict[str, object]


@dataclass(frozen=True, slots=True)
class ProcessedPipelineRunner:
    """Build verified processed data from immutable raw data."""

    raw_paths: RawDataPaths
    processed_paths: ProcessedDataPaths

    def __post_init__(self) -> None:
        """Validate runner dependencies."""
        if not isinstance(
            self.raw_paths,
            RawDataPaths,
        ):
            raise TypeError(
                "raw_paths must be RawDataPaths"
            )

        if not isinstance(
            self.processed_paths,
            ProcessedDataPaths,
        ):
            raise TypeError(
                "processed_paths must be ProcessedDataPaths"
            )

    def run_session(
        self,
        session_key: SessionKey,
        *,
        force: bool = False,
    ) -> ProcessedSessionRunResult:
        """Process and store one race session."""
        if not isinstance(session_key, SessionKey):
            raise TypeError(
                "session_key must be a SessionKey"
            )

        if not isinstance(force, bool):
            raise TypeError(
                "force must be a boolean"
            )

        if not force:
            existing_report = (
                verify_processed_partition(
                    self.processed_paths,
                    session_key,
                )
            )

            if existing_report.is_valid:
                manifest = existing_report.manifest

                if manifest is None:
                    raise ProcessedPipelineError(
                        "valid processed partition has "
                        "no manifest"
                    )

                return ProcessedSessionRunResult(
                    status="skipped",
                    session_key=session_key,
                    directory=(
                        existing_report.directory
                    ),
                    manifest=manifest,
                )

            if not _partition_is_absent(
                existing_report
            ):
                raise ProcessedPipelineError(
                    _format_existing_partition_error(
                        existing_report
                    )
                )

        raw_integrity = verify_session_partition(
            self.raw_paths,
            session_key,
        )
        raw_integrity.raise_for_errors()

        raw_session_paths = (
            self.raw_paths.for_session(
                session_key
            )
        )

        raw_laps = read_parquet_table(
            raw_session_paths.laps
        )
        raw_weather = read_parquet_table(
            raw_session_paths.weather
        )

        processed_data = process_session_tables(
            session_key,
            raw_laps,
            raw_weather,
        )

        write_result = ProcessedSessionWriter(
            self.processed_paths
        ).write(
            processed_data,
            force=force,
        )

        final_integrity = (
            verify_processed_partition(
                self.processed_paths,
                session_key,
            )
        )
        final_integrity.raise_for_errors()

        manifest = final_integrity.manifest

        if manifest is None:
            raise ProcessedPipelineError(
                "stored processed partition has "
                "no manifest"
            )

        return ProcessedSessionRunResult(
            status=write_result.status,
            session_key=session_key,
            directory=write_result.directory,
            manifest=manifest,
        )


def _partition_is_absent(
    report: ProcessedIntegrityReport,
) -> bool:
    """Return whether no processed partition exists yet."""
    return (
        len(report.issues) == 1
        and report.issues[0].code
        == "MISSING_DIRECTORY"
    )


def _format_existing_partition_error(
    report: ProcessedIntegrityReport,
) -> str:
    """Explain why an existing partition blocks a rerun."""
    details = "; ".join(
        (
            f"{issue.code}: "
            f"{issue.message}"
        )
        for issue in report.issues
    )

    return (
        "existing processed partition failed integrity "
        f"for {report.session_key.identifier}: "
        f"{details}. Use force=True to rebuild it."
    )