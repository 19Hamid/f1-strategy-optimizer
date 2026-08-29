"""Tests for raw Formula 1 session validation."""

from dataclasses import replace

import pandas as pd
import pytest

from app.pipeline.models import SessionKey
from app.pipeline.source import RawSessionData
from app.pipeline.validation import (
    RawDataValidationError,
    validate_raw_session,
)


def make_valid_raw_session() -> RawSessionData:
    """Create a minimal valid raw session for testing."""
    provenance = {
        "Season": [2024],
        "RoundNumber": [1],
        "SessionType": ["R"],
        "EventName": ["Bahrain Grand Prix"],
    }

    laps = pd.DataFrame(
        provenance
        | {
            "Driver": ["VER"],
            "Team": ["Red Bull Racing"],
            "LapNumber": [1.0],
            "LapTime": [pd.Timedelta(95, unit="s")],
            "Stint": [1.0],
            "Compound": ["SOFT"],
            "TyreLife": [1.0],
            "PitInTime": [pd.NaT],
            "PitOutTime": [pd.NaT],
            "TrackStatus": ["1"],
            "LapStartTime": [pd.Timedelta(0, unit="s")],
        }
    )

    weather = pd.DataFrame(
        provenance
        | {
            "Time": [pd.Timedelta(0, unit="s")],
            "AirTemp": [18.5],
            "TrackTemp": [22.0],
            "Humidity": [45.0],
            "Pressure": [1015.0],
            "Rainfall": [False],
            "WindDirection": [180],
            "WindSpeed": [2.5],
        }
    )

    results = pd.DataFrame(
        provenance
        | {
            "Abbreviation": ["VER"],
            "TeamName": ["Red Bull Racing"],
            "Position": [1.0],
            "ClassifiedPosition": ["1"],
            "GridPosition": [1.0],
            "Status": ["Finished"],
            "Points": [25.0],
        }
    )

    return RawSessionData(
        session_key=SessionKey(
            season=2024,
            round_number=1,
        ),
        laps=laps,
        weather=weather,
        results=results,
        metadata={
            "season": 2024,
            "round_number": 1,
            "session_type": "R",
            "event_name": "Bahrain Grand Prix",
        },
    )


def test_accepts_valid_raw_session() -> None:
    report = validate_raw_session(make_valid_raw_session())

    assert report.is_valid is True
    assert report.issues == ()


def test_reports_missing_columns() -> None:
    raw_session = make_valid_raw_session()
    invalid_laps = raw_session.laps.drop(
        columns=["LapTime", "Compound"]
    )

    report = validate_raw_session(
        replace(
            raw_session,
            laps=invalid_laps,
        )
    )

    assert report.is_valid is False
    assert report.issues[0].table_name == "laps"
    assert report.issues[0].code == "missing_columns"
    assert "Compound" in report.issues[0].message
    assert "LapTime" in report.issues[0].message


def test_reports_empty_table() -> None:
    raw_session = make_valid_raw_session()

    report = validate_raw_session(
        replace(
            raw_session,
            weather=raw_session.weather.iloc[0:0].copy(),
        )
    )

    assert report.is_valid is False
    assert report.issues[0].table_name == "weather"
    assert report.issues[0].code == "empty_table"


def test_reports_inconsistent_provenance() -> None:
    raw_session = make_valid_raw_session()
    invalid_laps = raw_session.laps.copy()
    invalid_laps.loc[0, "EventName"] = "Wrong Grand Prix"

    report = validate_raw_session(
        replace(
            raw_session,
            laps=invalid_laps,
        )
    )

    assert report.is_valid is False
    assert report.issues[0].table_name == "laps"
    assert report.issues[0].code == "invalid_provenance"


def test_reports_metadata_identity_mismatch() -> None:
    raw_session = make_valid_raw_session()
    invalid_metadata = dict(raw_session.metadata)
    invalid_metadata["season"] = 2023

    report = validate_raw_session(
        replace(
            raw_session,
            metadata=invalid_metadata,
        )
    )

    assert report.is_valid is False
    assert report.issues[0].table_name == "metadata"
    assert report.issues[0].code == "identity_mismatch"


def test_raises_combined_validation_error() -> None:
    raw_session = make_valid_raw_session()
    invalid_laps = raw_session.laps.drop(
        columns=["LapTime"]
    )

    report = validate_raw_session(
        replace(
            raw_session,
            laps=invalid_laps,
        )
    )

    with pytest.raises(
        RawDataValidationError,
        match="missing required columns",
    ):
        report.raise_for_errors()