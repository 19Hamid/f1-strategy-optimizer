"""Coordinate extraction, verification and storage of race data."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from app.pipeline.integrity import (
    IntegrityReport,
    verify_session_partition,
)
from app.pipeline.models import SessionKey
from app.pipeline.paths import RawDataPaths
from app.pipeline.serialization import read_json_document
from app.pipeline.source import RawSessionData
from app.pipeline.storage import (
    RawSessionWriter,
    SessionWriteResult,
)


class SessionSource(Protocol):
    """Describe a source capable of extracting one race session."""

    def extract(
        self,
        session_key: SessionKey,
    ) -> RawSessionData:
        """Extract one session."""


class SessionWriter(Protocol):
    """Describe a component capable of storing one race session."""

    def write(
        self,
        raw_session: RawSessionData,
        *,
        force: bool = False,
    ) -> SessionWriteResult:
        """Store one session."""


class IntegrityChecker(Protocol):
    """Describe a stored-session integrity checker."""

    def __call__(
        self,
        raw_paths: RawDataPaths,
        session_key: SessionKey,
    ) -> IntegrityReport:
        """Verify one stored session."""


@dataclass(frozen=True, slots=True)
class SessionRunResult:
    """Describe one pipeline session outcome."""

    session_key: SessionKey
    status: Literal["written", "skipped"]
    directory: Path
    manifest: dict[str, object]


@dataclass(slots=True)
class RawPipelineRunner:
    """Run the raw-data pipeline for individual race sessions."""

    raw_paths: RawDataPaths
    source: SessionSource
    writer: SessionWriter | None = None
    integrity_checker: IntegrityChecker = verify_session_partition

    def __post_init__(self) -> None:
        """Create the default atomic writer when none is supplied."""
        if self.writer is None:
            self.writer = RawSessionWriter(self.raw_paths)

    def run_session(
        self,
        session_key: SessionKey,
        *,
        force: bool = False,
    ) -> SessionRunResult:
        """Extract or safely skip one race session."""
        if not isinstance(force, bool):
            raise TypeError("force must be a boolean")

        session_paths = self.raw_paths.for_session(
            session_key
        )

        if session_paths.directory.exists() and not force:
            integrity_report = self.integrity_checker(
                self.raw_paths,
                session_key,
            )
            integrity_report.raise_for_errors()

            return SessionRunResult(
                session_key=session_key,
                status="skipped",
                directory=session_paths.directory,
                manifest=read_json_document(
                    session_paths.manifest
                ),
            )

        raw_session = self.source.extract(session_key)

        writer = self.writer

        if writer is None:
            raise RuntimeError("pipeline writer is unavailable")

        write_result = writer.write(
            raw_session,
            force=force,
        )

        return SessionRunResult(
            session_key=session_key,
            status=write_result.status,
            directory=write_result.directory,
            manifest=write_result.manifest,
        )