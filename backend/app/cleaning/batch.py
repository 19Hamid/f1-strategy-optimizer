"""Execute processed-data construction across development races."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Literal
from uuid import uuid4

from app.cleaning.paths import ProcessedDataPaths
from app.cleaning.profile import (
    DEVELOPMENT_SEASONS,
)
from app.cleaning.runner import (
    ProcessedPipelineRunner,
)
from app.pipeline.models import SessionKey
from app.pipeline.serialization import (
    write_json_document,
)

BatchSessionStatus = Literal[
    "written",
    "skipped",
    "failed",
]


@dataclass(frozen=True, slots=True)
class ProcessedBatchSessionRecord:
    """Describe one session attempted by a batch."""

    session_key: SessionKey
    status: BatchSessionStatus
    duration_seconds: float
    directory: Path
    error_type: str | None = None
    error_message: str | None = None

    def to_document(self) -> dict[str, object]:
        """Convert the record into JSON-safe data."""
        return {
            "session_id": (
                self.session_key.identifier
            ),
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
class ProcessedBatchRunResult:
    """Describe a completed processed-data batch."""

    run_id: str
    records: tuple[
        ProcessedBatchSessionRecord,
        ...,
    ]
    record_path: Path

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
        """Return whether every requested session succeeded."""
        return self.failed_count == 0


@dataclass(frozen=True, slots=True)
class ProcessedBatchRunner:
    """Run processed construction across development sessions."""

    processed_paths: ProcessedDataPaths
    session_runner: ProcessedPipelineRunner

    def __post_init__(self) -> None:
        """Validate batch dependencies."""
        if not isinstance(
            self.processed_paths,
            ProcessedDataPaths,
        ):
            raise TypeError(
                "processed_paths must be ProcessedDataPaths"
            )

        if not isinstance(
            self.session_runner,
            ProcessedPipelineRunner,
        ):
            raise TypeError(
                "session_runner must be ProcessedPipelineRunner"
            )

        if (
            self.session_runner.processed_paths
            != self.processed_paths
        ):
            raise ValueError(
                "session_runner and batch runner must "
                "use the same processed paths"
            )

    def run(
        self,
        session_keys: Iterable[SessionKey],
        *,
        force: bool = False,
    ) -> ProcessedBatchRunResult:
        """Run every requested development session."""
        if not isinstance(force, bool):
            raise TypeError(
                "force must be a boolean"
            )

        requested_sessions = (
            _validate_session_keys(
                session_keys
            )
        )

        run_id = _new_run_id()
        started_at_utc = _utc_timestamp()
        batch_started = perf_counter()

        records: list[
            ProcessedBatchSessionRecord
        ] = []

        for session_key in requested_sessions:
            session_started = perf_counter()
            intended_directory = (
                self.processed_paths
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
                    ProcessedBatchSessionRecord(
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
                ProcessedBatchSessionRecord(
                    session_key=session_key,
                    status=result.status,
                    duration_seconds=(
                        perf_counter()
                        - session_started
                    ),
                    directory=result.directory,
                )
            )

        completed_at_utc = _utc_timestamp()
        total_duration_seconds = (
            perf_counter() - batch_started
        )
        record_path = (
            self.processed_paths.runs_directory
            / f"{run_id}.json"
        )

        result = ProcessedBatchRunResult(
            run_id=run_id,
            records=tuple(records),
            record_path=record_path,
        )

        write_json_document(
            {
                "run_id": run_id,
                "cleaning_rule_version": (
                    self.processed_paths
                    .cleaning_rule_version
                ),
                "development_seasons": list(
                    DEVELOPMENT_SEASONS
                ),
                "started_at_utc": (
                    started_at_utc
                ),
                "completed_at_utc": (
                    completed_at_utc
                ),
                "duration_seconds": (
                    total_duration_seconds
                ),
                "force": force,
                "requested_sessions": len(
                    requested_sessions
                ),
                "summary": {
                    "written": (
                        result.written_count
                    ),
                    "skipped": (
                        result.skipped_count
                    ),
                    "failed": (
                        result.failed_count
                    ),
                    "succeeded": (
                        result.succeeded
                    ),
                },
                "sessions": [
                    record.to_document()
                    for record in result.records
                ],
            },
            record_path,
        )

        return result


def _validate_session_keys(
    session_keys: Iterable[SessionKey],
) -> tuple[SessionKey, ...]:
    """Validate and freeze requested development sessions."""
    if isinstance(
        session_keys,
        (
            str,
            bytes,
        ),
    ):
        raise TypeError(
            "session_keys must be an iterable "
            "of SessionKey objects"
        )

    try:
        requested_sessions = tuple(
            session_keys
        )
    except TypeError as error:
        raise TypeError(
            "session_keys must be iterable"
        ) from error

    if not requested_sessions:
        raise ValueError(
            "at least one session key is required"
        )

    for session_key in requested_sessions:
        if not isinstance(
            session_key,
            SessionKey,
        ):
            raise TypeError(
                "every requested session must be "
                "a SessionKey"
            )

        if (
            session_key.season
            not in DEVELOPMENT_SEASONS
        ):
            supported = ", ".join(
                str(season)
                for season in DEVELOPMENT_SEASONS
            )

            raise ValueError(
                "processed development batches support "
                f"only seasons: {supported}"
            )

    if (
        len(set(requested_sessions))
        != len(requested_sessions)
    ):
        raise ValueError(
            "duplicate session keys are not allowed"
        )

    return requested_sessions


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