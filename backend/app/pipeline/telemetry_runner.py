"""Run incremental on-demand telemetry extraction."""

from dataclasses import dataclass
from typing import Protocol

from app.pipeline.telemetry import TelemetryRequest
from app.pipeline.telemetry_source import TelemetryLapData
from app.pipeline.telemetry_storage import (
    TelemetryWriter,
    TelemetryWriteResult,
)


class TelemetrySource(Protocol):
    """Describe an on-demand telemetry source."""

    def extract(
        self,
        request: TelemetryRequest,
    ) -> TelemetryLapData:
        """Extract telemetry for one request."""


@dataclass(frozen=True, slots=True)
class TelemetryPipelineRunner:
    """Skip verified telemetry before loading FastF1."""

    source: TelemetrySource
    writer: TelemetryWriter

    def __post_init__(self) -> None:
        """Validate the runner dependencies."""
        if not isinstance(self.writer, TelemetryWriter):
            raise TypeError(
                "writer must be a TelemetryWriter"
            )

    def run(
        self,
        request: TelemetryRequest,
        *,
        force: bool = False,
    ) -> TelemetryWriteResult:
        """Extract and store one telemetry request."""
        if not isinstance(request, TelemetryRequest):
            raise TypeError(
                "request must be a TelemetryRequest"
            )

        if not isinstance(force, bool):
            raise TypeError("force must be a boolean")

        if not force:
            existing_result = (
                self.writer.inspect_existing(request)
            )

            if existing_result is not None:
                return existing_result

        data = self.source.extract(request)

        return self.writer.write(
            data,
            force=force,
        )