"""Load raw Formula 1 session data from FastF1."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

import fastf1
import pandas as pd

from app.pipeline.models import SessionKey

MetadataValue = str | int | bool | None

PROVENANCE_COLUMNS = (
    "Season",
    "RoundNumber",
    "SessionType",
    "EventName",
)


class SessionLike(Protocol):
    """Describe the FastF1 session attributes used by the pipeline."""

    event: Mapping[str, object]
    laps: pd.DataFrame
    weather_data: pd.DataFrame
    results: pd.DataFrame

    def load(
        self,
        *,
        laps: bool,
        telemetry: bool,
        weather: bool,
        messages: bool,
    ) -> None:
        """Load the required FastF1 session data."""


class SessionFactory(Protocol):
    """Describe a callable that creates a FastF1 session."""

    def __call__(
        self,
        year: int,
        round_number: int,
        session_type: str,
    ) -> SessionLike:
        """Create one session."""


class CacheEnabler(Protocol):
    """Describe a callable that enables the FastF1 cache."""

    def __call__(self, cache_directory: str) -> None:
        """Enable caching in the selected directory."""


@dataclass(frozen=True, slots=True)
class RawSessionData:
    """Hold the raw tables and metadata extracted for one race."""

    session_key: SessionKey
    laps: pd.DataFrame
    weather: pd.DataFrame
    results: pd.DataFrame
    metadata: dict[str, MetadataValue]


@dataclass(slots=True)
class FastF1Source:
    """Extract core race data from FastF1."""

    cache_directory: Path
    session_factory: SessionFactory = fastf1.get_session
    cache_enabler: CacheEnabler = fastf1.Cache.enable_cache

    def __post_init__(self) -> None:
        """Prepare and enable the project-controlled FastF1 cache."""
        self.cache_directory = Path(self.cache_directory)
        self.cache_directory.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.cache_enabler(str(self.cache_directory))

    def extract(
        self,
        session_key: SessionKey,
    ) -> RawSessionData:
        """Load the core raw tables for one race session."""
        session = self.session_factory(
            session_key.season,
            session_key.round_number,
            session_key.session_type,
        )

        session.load(
            laps=True,
            telemetry=False,
            weather=True,
            messages=False,
        )

        event_name = _required_event_name(session.event)

        return RawSessionData(
            session_key=session_key,
            laps=_copy_with_provenance(
                session.laps,
                session_key,
                event_name,
            ),
            weather=_copy_with_provenance(
                session.weather_data,
                session_key,
                event_name,
            ),
            results=_copy_with_provenance(
                session.results,
                session_key,
                event_name,
            ),
            metadata=_build_metadata(
                session.event,
                session_key,
                event_name,
            ),
        )


def _required_event_name(
    event: Mapping[str, object],
) -> str:
    """Return the event name or fail if it is unavailable."""
    event_name = _optional_text(event.get("EventName"))

    if event_name is None:
        raise ValueError("FastF1 session is missing its event name")

    return event_name


def _copy_with_provenance(
    table: pd.DataFrame,
    session_key: SessionKey,
    event_name: str,
) -> pd.DataFrame:
    """Copy a raw table and add stable session-identification fields."""
    copied_table = pd.DataFrame(table).copy(deep=True)

    provenance = {
        "Season": session_key.season,
        "RoundNumber": session_key.round_number,
        "SessionType": session_key.session_type,
        "EventName": event_name,
    }

    conflicting_columns = set(provenance).intersection(
        copied_table.columns
    )

    if conflicting_columns:
        conflicts = ", ".join(sorted(conflicting_columns))
        raise ValueError(
            f"source table already contains provenance columns: {conflicts}"
        )

    for position, (column, value) in enumerate(
        provenance.items()
    ):
        copied_table.insert(
            position,
            column,
            value,
        )

    return copied_table


def _build_metadata(
    event: Mapping[str, object],
    session_key: SessionKey,
    event_name: str,
) -> dict[str, MetadataValue]:
    """Build JSON-compatible metadata for one race session."""
    return {
        "season": session_key.season,
        "round_number": session_key.round_number,
        "session_type": session_key.session_type,
        "event_name": event_name,
        "official_event_name": _optional_text(
            event.get("OfficialEventName")
        ),
        "country": _optional_text(event.get("Country")),
        "location": _optional_text(event.get("Location")),
        "event_format": _optional_text(
            event.get("EventFormat")
        ),
        "event_date": _iso_date(event.get("EventDate")),
        "telemetry_loaded": False,
        "fastf1_version": fastf1.__version__,
    }


def _optional_text(value: object) -> str | None:
    """Convert an optional scalar value into text."""
    if value is None or bool(pd.isna(value)):
        return None

    text = str(value).strip()
    return text or None


def _iso_date(value: object) -> str | None:
    """Convert an optional date value into ISO 8601 text."""
    if value is None or bool(pd.isna(value)):
        return None

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    return str(value)