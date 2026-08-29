"""Run raw-data extraction across multiple race sessions."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Literal, Protocol
from uuid import uuid4

from app.pipeline.models import SessionKey
from app.pipeline.paths import RawDataPaths
from app.pipeline.runner import SessionRunResult
from app.pipeline.serialization import write_json_document

BatchSessionStatus = Literal["written", "skipped", "failed"]


class SessionRunner(Protocol):
    """Describe a single-session pipeline runner."""

    def run_session(
        self,
        session_key: SessionKey,
        *,
        force: bool = False,
    ) -> SessionRunResult:
        """Run one session."""


@dataclass(frozen=True, slots=True)
class BatchSessionRecord:
    """Record the outcome of one session in a batch."""

    session_key: SessionKey
    status: BatchSessionStatus
    duration_seconds: float
    directory: str | None = None
    error_type: str | None = None
    error_message: str | None = None

    def to_document(self) -> dict[str, object]:
        """Convert the record into JSON-compatible data."""
        return {
            "session_id": self.session_key.identifier,
            "season": self.session_key.season,
            "round_number": self.session_key.round_number,
            "session_type": self.session_key.session_type,
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "directory": self.directory,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


@dataclass(frozen=True, slots=True)
class BatchRunResult:
    """Describe the result of one complete pipeline batch."""

    run_id: str
    started_at_utc: str
    finished_at_utc: str
    force: bool
    records: tuple[BatchSessionRecord, ...]
    record_path: Path

    @property
    def written_count(self) -> int:
        """Return the number of newly written sessions."""
        return sum(
            record.status == "written"
            for record in self.records
        )

    @property
    def skipped_count(self) -> int:
        """Return the number of skipped sessions."""
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
        """Return whether every session avoided failure."""
        return self.failed_count == 0

    def to_document(self) -> dict[str, object]:
        """Convert the complete run result into JSON-compatible data."""
        return {
            "run_id": self.run_id,
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": self.finished_at_utc,
            "force": self.force,
            "summary": {
                "total": len(self.records),
                "written": self.written_count,
                "skipped": self.skipped_count,
                "failed": self.failed_count,
            },
            "sessions": [
                record.to_document()
                for record in self.records
            ],
        }


@dataclass(frozen=True, slots=True)
class RawBatchRunner:
    """Run and record multiple independent race sessions."""

    raw_paths: RawDataPaths
    session_runner: SessionRunner
    run_id_factory: Callable[[], str] = lambda: _new_run_id()

    def run(
        self,
        session_keys: Sequence[SessionKey],
        *,
        force: bool = False,
    ) -> BatchRunResult:
        """Run all selected sessions without stopping after one failure."""
        if not isinstance(force, bool):
            raise TypeError("force must be a boolean")

        if not session_keys:
            raise ValueError("at least one session must be selected")

        if any(
            not isinstance(session_key, SessionKey)
            for session_key in session_keys
        ):
            raise TypeError(
                "every selected session must be a SessionKey"
            )

        if len(set(session_keys)) != len(session_keys):
            raise ValueError(
                "selected sessions must not contain duplicates"
            )

        run_id = self.run_id_factory()
        started_at_utc = _utc_timestamp()
        records: list[BatchSessionRecord] = []

        for session_key in session_keys:
            records.append(
                self._run_one(
                    session_key,
                    force=force,
                )
            )

        finished_at_utc = _utc_timestamp()
        record_path = (
            self.raw_paths.runs_directory
            / f"{run_id}.json"
        )

        result = BatchRunResult(
            run_id=run_id,
            started_at_utc=started_at_utc,
            finished_at_utc=finished_at_utc,
            force=force,
            records=tuple(records),
            record_path=record_path,
        )

        write_json_document(
            result.to_document(),
            record_path,
        )

        return result

    def _run_one(
        self,
        session_key: SessionKey,
        *,
        force: bool,
    ) -> BatchSessionRecord:
        """Run one session while isolating its failures."""
        started = perf_counter()

        try:
            result = self.session_runner.run_session(
                session_key,
                force=force,
            )
        # A batch boundary must isolate every per-session failure.
        except Exception as error:  # noqa: BLE001
            return BatchSessionRecord(
                session_key=session_key,
                status="failed",
                duration_seconds=_elapsed_seconds(started),
                error_type=type(error).__name__,
                error_message=str(error),
            )

        return BatchSessionRecord(
            session_key=session_key,
            status=result.status,
            duration_seconds=_elapsed_seconds(started),
            directory=str(result.directory),
        )


def _new_run_id() -> str:
    """Create a sortable, collision-resistant run identifier."""
    timestamp = datetime.now(UTC).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )
    return f"{timestamp}-{uuid4().hex[:8]}"


def _utc_timestamp() -> str:
    """Return the current time as ISO 8601 UTC text."""
    return (
        datetime.now(UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _elapsed_seconds(started: float) -> float:
    """Return a stable session-duration measurement."""
    return round(
        perf_counter() - started,
        6,
    )