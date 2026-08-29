"""Extract detailed telemetry for one requested race lap."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Self

import fastf1
import pandas as pd

from app.pipeline.telemetry import TelemetryRequest

TELEMETRY_REQUIRED_COLUMNS = (
    "Time",
    "Distance",
    "RPM",
    "Speed",
    "nGear",
    "Throttle",
    "Brake",
    "DRS",
    "X",
    "Y",
    "Z",
)

TELEMETRY_PROVENANCE_COLUMNS = (
    "Season",
    "RoundNumber",
    "SessionType",
    "EventName",
    "Driver",
    "LapNumber",
)


class TelemetryExtractionError(RuntimeError):
    """Raised when requested telemetry cannot be extracted."""


class _TelemetryLap(Protocol):
    """Describe the FastF1 lap behaviour used by the source."""

    def get_telemetry(self) -> pd.DataFrame:
        """Return merged car and position telemetry."""


class _LapIndexer(Protocol):
    """Describe positional access to a selected lap."""

    def __getitem__(self, index: int) -> _TelemetryLap:
        """Return one selected lap."""


class _LapCollection(Protocol):
    """Describe the FastF1 lap-selection behaviour used here."""

    iloc: _LapIndexer

    def pick_drivers(self, drivers: str) -> Self:
        """Select laps belonging to a driver."""

    def pick_laps(self, laps: int) -> Self:
        """Select a lap number."""

    def __len__(self) -> int:
        """Return the number of selected laps."""


class _RaceSession(Protocol):
    """Describe the FastF1 session behaviour used by the source."""

    event: Mapping[str, object]
    laps: _LapCollection

    def load(
        self,
        *,
        laps: bool,
        telemetry: bool,
        weather: bool,
        messages: bool,
    ) -> None:
        """Load the requested session data."""


type SessionLoader = Callable[
    [int, int, str],
    _RaceSession,
]


@dataclass(frozen=True, slots=True)
class TelemetryLapData:
    """Hold extracted telemetry and its provenance metadata."""

    request: TelemetryRequest
    telemetry: pd.DataFrame
    metadata: dict[str, object]


@dataclass(slots=True)
class FastF1TelemetrySource:
    """Retrieve telemetry only for explicitly requested laps."""

    cache_directory: Path
    session_loader: SessionLoader = field(
        default=fastf1.get_session,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Configure the dedicated FastF1 cache."""
        if not isinstance(self.cache_directory, Path):
            raise TypeError(
                "cache_directory must be a pathlib.Path"
            )

        self.cache_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        fastf1.Cache.enable_cache(
            str(self.cache_directory),
        )

    def extract(
        self,
        request: TelemetryRequest,
    ) -> TelemetryLapData:
        """Extract detailed telemetry for one requested lap."""
        if not isinstance(request, TelemetryRequest):
            raise TypeError(
                "request must be a TelemetryRequest"
            )

        session = self.session_loader(
            request.session_key.season,
            request.session_key.round_number,
            request.session_key.session_type,
        )

        session.load(
            laps=True,
            telemetry=True,
            weather=False,
            messages=False,
        )

        driver_laps = session.laps.pick_drivers(
            request.driver,
        )
        selected_laps = driver_laps.pick_laps(
            request.lap_number,
        )

        selected_count = len(selected_laps)

        if selected_count == 0:
            raise TelemetryExtractionError(
                "no telemetry lap was found for "
                f"{request.identifier}"
            )

        if selected_count != 1:
            raise TelemetryExtractionError(
                "expected exactly one telemetry lap for "
                f"{request.identifier}, but found "
                f"{selected_count}"
            )

        selected_lap = selected_laps.iloc[0]
        telemetry = selected_lap.get_telemetry()

        if not isinstance(telemetry, pd.DataFrame):
            raise TelemetryExtractionError(
                "FastF1 did not return a telemetry DataFrame"
            )

        telemetry = telemetry.copy(deep=True)

        if telemetry.empty:
            raise TelemetryExtractionError(
                "FastF1 returned empty telemetry for "
                f"{request.identifier}"
            )

        missing_columns = [
            column
            for column in TELEMETRY_REQUIRED_COLUMNS
            if column not in telemetry.columns
        ]

        if missing_columns:
            missing = ", ".join(missing_columns)

            raise TelemetryExtractionError(
                "telemetry is missing required columns: "
                f"{missing}"
            )

        event_name_value = session.event.get(
            "EventName",
            "Unknown Event",
        )
        event_name = str(event_name_value)

        provenance: dict[str, object] = {
            "Season": request.session_key.season,
            "RoundNumber": request.session_key.round_number,
            "SessionType": (
                request.session_key.session_type
            ),
            "EventName": event_name,
            "Driver": request.driver,
            "LapNumber": request.lap_number,
        }

        original_columns = [
            column
            for column in telemetry.columns
            if column not in provenance
        ]

        for column, value in provenance.items():
            telemetry[column] = value

        telemetry = telemetry[
            [
                *TELEMETRY_PROVENANCE_COLUMNS,
                *original_columns,
            ]
        ]

        metadata: dict[str, object] = {
            "season": request.session_key.season,
            "round_number": (
                request.session_key.round_number
            ),
            "session_type": (
                request.session_key.session_type
            ),
            "session_id": (
                request.session_key.identifier
            ),
            "telemetry_id": request.identifier,
            "event_name": event_name,
            "driver": request.driver,
            "lap_number": request.lap_number,
            "sample_count": len(telemetry),
            "available_columns": list(
                telemetry.columns
            ),
            "telemetry_loaded": True,
            "fastf1_version": fastf1.__version__,
        }

        return TelemetryLapData(
            request=request,
            telemetry=telemetry,
            metadata=metadata,
        )