"""Models and storage paths for on-demand lap telemetry."""

from dataclasses import dataclass
from pathlib import Path

from app.pipeline.models import SessionKey

MAX_REASONABLE_LAP = 200


@dataclass(frozen=True, slots=True)
class TelemetryRequest:
    """Identify one driver's telemetry for one race lap."""

    session_key: SessionKey
    driver: str
    lap_number: int

    def __post_init__(self) -> None:
        """Validate and normalize the telemetry request."""
        if not isinstance(self.session_key, SessionKey):
            raise TypeError("session_key must be a SessionKey")

        if not isinstance(self.driver, str):
            raise TypeError("driver must be a string")

        normalized_driver = self.driver.strip().upper()

        if (
            len(normalized_driver) != 3
            or not normalized_driver.isascii()
            or not normalized_driver.isalpha()
        ):
            raise ValueError(
                "driver must be a three-letter ASCII abbreviation"
            )

        if (
            isinstance(self.lap_number, bool)
            or not isinstance(self.lap_number, int)
        ):
            raise TypeError("lap_number must be an integer")

        if not 1 <= self.lap_number <= MAX_REASONABLE_LAP:
            raise ValueError(
                "lap_number must be between "
                f"1 and {MAX_REASONABLE_LAP}"
            )

        object.__setattr__(
            self,
            "driver",
            normalized_driver,
        )

    @property
    def identifier(self) -> str:
        """Return a stable identifier for the telemetry request."""
        return (
            f"{self.session_key.identifier}-"
            f"{self.driver}-"
            f"L{self.lap_number:03d}"
        )

    @property
    def partition_parts(self) -> tuple[str, ...]:
        """Return the request's partition directory names."""
        return (
            *self.session_key.partition_parts,
            f"driver={self.driver}",
            f"lap={self.lap_number:03d}",
        )


@dataclass(frozen=True, slots=True)
class TelemetryDataPaths:
    """Construct storage paths for on-demand telemetry."""

    raw_root: Path

    def __post_init__(self) -> None:
        """Validate the raw-data root."""
        if not isinstance(self.raw_root, Path):
            raise TypeError("raw_root must be a pathlib.Path")

    @property
    def telemetry_root(self) -> Path:
        """Return the root directory for detailed telemetry."""
        return self.raw_root / "telemetry"

    @property
    def temporary_root(self) -> Path:
        """Return the root for temporary telemetry writes."""
        return self.raw_root / ".tmp" / "telemetry"

    def directory_for(
        self,
        request: TelemetryRequest,
    ) -> Path:
        """Return the final directory for a telemetry request."""
        return self.telemetry_root.joinpath(
            *request.partition_parts,
        )

    def telemetry_file_for(
        self,
        request: TelemetryRequest,
    ) -> Path:
        """Return the telemetry Parquet path."""
        return self.directory_for(request) / "telemetry.parquet"

    def metadata_file_for(
        self,
        request: TelemetryRequest,
    ) -> Path:
        """Return the telemetry metadata path."""
        return self.directory_for(request) / "metadata.json"

    def manifest_file_for(
        self,
        request: TelemetryRequest,
    ) -> Path:
        """Return the telemetry manifest path."""
        return self.directory_for(request) / "manifest.json"