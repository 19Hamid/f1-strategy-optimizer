"""Tests for the FastF1 raw-data source."""

from pathlib import Path

import fastf1
import pandas as pd
import pytest

from app.pipeline.models import SessionKey
from app.pipeline.source import (
    PROVENANCE_COLUMNS,
    FastF1Source,
)


class FakeSession:
    """Small network-free replacement for a FastF1 session."""

    def __init__(self) -> None:
        self.event: dict[str, object] = {
            "EventName": "Bahrain Grand Prix",
            "OfficialEventName": "Formula 1 Bahrain Grand Prix",
            "Country": "Bahrain",
            "Location": "Sakhir",
            "EventFormat": "conventional",
            "EventDate": pd.Timestamp("2024-03-02"),
        }
        self.laps = pd.DataFrame(
            {
                "Driver": ["VER", "PER"],
                "LapNumber": [1.0, 1.0],
            }
        )
        self.weather_data = pd.DataFrame(
            {
                "AirTemp": [18.5],
                "TrackTemp": [22.0],
            }
        )
        self.results = pd.DataFrame(
            {
                "Abbreviation": ["VER", "PER"],
                "Position": [1.0, 2.0],
            }
        )
        self.load_arguments: dict[str, bool] | None = None

    def load(
        self,
        *,
        laps: bool,
        telemetry: bool,
        weather: bool,
        messages: bool,
    ) -> None:
        self.load_arguments = {
            "laps": laps,
            "telemetry": telemetry,
            "weather": weather,
            "messages": messages,
        }


def test_extracts_core_session_tables(
    tmp_path: Path,
) -> None:
    fake_session = FakeSession()
    factory_calls: list[tuple[int, int, str]] = []
    cache_calls: list[str] = []

    def fake_factory(
        year: int,
        round_number: int,
        session_type: str,
    ) -> FakeSession:
        factory_calls.append(
            (year, round_number, session_type)
        )
        return fake_session

    def fake_cache_enabler(cache_directory: str) -> None:
        cache_calls.append(cache_directory)

    cache_directory = tmp_path / "cache"

    source = FastF1Source(
        cache_directory=cache_directory,
        session_factory=fake_factory,
        cache_enabler=fake_cache_enabler,
    )

    extracted = source.extract(
        SessionKey(
            season=2024,
            round_number=1,
        )
    )

    assert cache_directory.is_dir()
    assert cache_calls == [str(cache_directory)]
    assert factory_calls == [(2024, 1, "R")]
    assert fake_session.load_arguments == {
        "laps": True,
        "telemetry": False,
        "weather": True,
        "messages": False,
    }

    assert tuple(extracted.laps.columns[:4]) == PROVENANCE_COLUMNS
    assert tuple(extracted.weather.columns[:4]) == PROVENANCE_COLUMNS
    assert tuple(extracted.results.columns[:4]) == PROVENANCE_COLUMNS

    assert extracted.laps is not fake_session.laps
    assert extracted.weather is not fake_session.weather_data
    assert extracted.results is not fake_session.results


def test_builds_json_compatible_metadata(
    tmp_path: Path,
) -> None:
    fake_session = FakeSession()

    def fake_factory(
        year: int,
        round_number: int,
        session_type: str,
    ) -> FakeSession:
        del year, round_number, session_type
        return fake_session

    source = FastF1Source(
        cache_directory=tmp_path / "cache",
        session_factory=fake_factory,
        cache_enabler=lambda cache_directory: None,
    )

    extracted = source.extract(
        SessionKey(
            season=2024,
            round_number=1,
        )
    )

    assert extracted.metadata == {
        "season": 2024,
        "round_number": 1,
        "session_type": "R",
        "event_name": "Bahrain Grand Prix",
        "official_event_name": "Formula 1 Bahrain Grand Prix",
        "country": "Bahrain",
        "location": "Sakhir",
        "event_format": "conventional",
        "event_date": "2024-03-02T00:00:00",
        "telemetry_loaded": False,
        "fastf1_version": fastf1.__version__,
    }


def test_rejects_missing_event_name(
    tmp_path: Path,
) -> None:
    fake_session = FakeSession()
    fake_session.event["EventName"] = None

    def fake_factory(
        year: int,
        round_number: int,
        session_type: str,
    ) -> FakeSession:
        del year, round_number, session_type
        return fake_session

    source = FastF1Source(
        cache_directory=tmp_path / "cache",
        session_factory=fake_factory,
        cache_enabler=lambda cache_directory: None,
    )

    with pytest.raises(
        ValueError,
        match="missing its event name",
    ):
        source.extract(
            SessionKey(
                season=2024,
                round_number=1,
            )
        )