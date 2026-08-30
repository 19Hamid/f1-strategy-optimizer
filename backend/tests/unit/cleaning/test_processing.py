"""Tests for complete session-table processing."""

import json

import pandas as pd
import pytest

from app.cleaning.processing import (
    CLEANING_RULE_VERSION,
    PROCESSED_CONTRACT_VERSION,
    SessionProcessingError,
    process_session_tables,
)
from app.pipeline.models import SessionKey
from app.pipeline.storage import RAW_CONTRACT_VERSION


def make_laps() -> pd.DataFrame:
    """Create two valid stints and one matched pit event."""
    return pd.DataFrame(
        {
            "Season": [2024, 2024, 2024, 2024],
            "RoundNumber": [1, 1, 1, 1],
            "SessionType": ["R", "R", "R", "R"],
            "EventName": [
                "Bahrain Grand Prix",
                "Bahrain Grand Prix",
                "Bahrain Grand Prix",
                "Bahrain Grand Prix",
            ],
            "Driver": ["VER", "VER", "VER", "VER"],
            "Team": [
                "Red Bull Racing",
                "Red Bull Racing",
                "Red Bull Racing",
                "Red Bull Racing",
            ],
            "LapNumber": [1.0, 2.0, 3.0, 4.0],
            "LapTime": pd.to_timedelta(
                [
                    90,
                    90,
                    90,
                    90,
                ],
                unit="s",
            ),
            "Stint": [1.0, 1.0, 2.0, 2.0],
            "Compound": [
                "MEDIUM",
                "MEDIUM",
                "HARD",
                "HARD",
            ],
            "TyreLife": [1.0, 2.0, 1.0, 2.0],
            "PitInTime": pd.to_timedelta(
                [
                    None,
                    190,
                    None,
                    None,
                ],
                unit="s",
            ),
            "PitOutTime": pd.to_timedelta(
                [
                    None,
                    None,
                    210,
                    None,
                ],
                unit="s",
            ),
            "Sector1Time": pd.to_timedelta(
                [
                    30,
                    30,
                    30,
                    30,
                ],
                unit="s",
            ),
            "Sector2Time": pd.to_timedelta(
                [
                    30,
                    30,
                    30,
                    30,
                ],
                unit="s",
            ),
            "Sector3Time": pd.to_timedelta(
                [
                    30,
                    30,
                    30,
                    30,
                ],
                unit="s",
            ),
            "TrackStatus": ["1", "1", "1", "1"],
            "LapStartTime": pd.to_timedelta(
                [
                    10,
                    100,
                    200,
                    300,
                ],
                unit="s",
            ),
            "IsPersonalBest": [
                False,
                False,
                False,
                False,
            ],
            "IsAccurate": [
                True,
                True,
                True,
                True,
            ],
        }
    )


def make_weather(
    *,
    rainfall: bool = False,
) -> pd.DataFrame:
    """Create one weather observation before every lap."""
    return pd.DataFrame(
        {
            "Season": [2024],
            "RoundNumber": [1],
            "SessionType": ["R"],
            "EventName": ["Bahrain Grand Prix"],
            "Time": pd.to_timedelta(
                [0],
                unit="s",
            ),
            "AirTemp": [25.0],
            "Humidity": [40.0],
            "Pressure": [1015.0],
            "Rainfall": [rainfall],
            "TrackTemp": [35.0],
            "WindDirection": [180],
            "WindSpeed": [2.5],
        }
    )


def test_processes_complete_session_tables() -> None:
    """One call should build every authoritative output."""
    result = process_session_tables(
        SessionKey(2024, 1),
        make_laps(),
        make_weather(),
    )

    assert result.session_key.identifier == "2024-01-R"
    assert len(result.laps) == 4
    assert len(result.stints) == 2
    assert len(result.pit_events) == 1

    assert int(
        result.laps["IsEligible"].sum()
    ) == 1

    assert result.stints["is_complete"].all()

    pit_event = result.pit_events.iloc[0]

    assert not bool(
        pit_event["entry_rainfall"]
    )
    assert not bool(
        pit_event["exit_rainfall"]
    )
    assert bool(
        pit_event["is_dry_weather_pair"]
    )
    assert bool(
        pit_event[
            "is_duration_analysis_candidate"
        ]
    )

    report = result.quality_report

    assert (
        report["processed_contract_version"]
        == PROCESSED_CONTRACT_VERSION
    )
    assert (
        report["cleaning_rule_version"]
        == CLEANING_RULE_VERSION
    )
    assert (
        report["source_contract_version"]
        == RAW_CONTRACT_VERSION
    )

    session = report["session"]
    tables = report["tables"]
    lap_quality = report["lap_quality"]
    stint_quality = report["stint_quality"]
    pit_quality = report["pit_event_quality"]
    validation = report["validation"]

    assert isinstance(session, dict)
    assert isinstance(tables, dict)
    assert isinstance(lap_quality, dict)
    assert isinstance(stint_quality, dict)
    assert isinstance(pit_quality, dict)
    assert isinstance(validation, dict)

    assert session["identifier"] == "2024-01-R"
    assert session["event_name"] == "Bahrain Grand Prix"

    assert tables == {
        "laps_rows": 4,
        "stints_rows": 2,
        "pit_events_rows": 1,
    }

    assert lap_quality["input_laps"] == 4
    assert lap_quality["eligible_laps"] == 1
    assert lap_quality["flagged_laps"] == 3
    assert lap_quality["excluded_laps"] == 3
    assert lap_quality["weather_observations"] == 1
    assert lap_quality["rain_aligned_laps"] == 0

    assert stint_quality["stints"] == 2
    assert stint_quality["complete_stints"] == 2
    assert stint_quality["incomplete_stints"] == 0

    assert pit_quality["pit_events"] == 1
    assert pit_quality["matched_events"] == 1
    assert pit_quality["complete_events"] == 1
    assert pit_quality["dry_weather_pairs"] == 1
    assert (
        pit_quality["duration_analysis_candidates"]
        == 1
    )

    assert validation["status"] == "passed"
    assert validation["raw_laps_preserved"]
    assert validation["future_weather_matches"] == 0
    assert validation["pit_weather_context_complete"]

    serialized = json.dumps(
        report,
        allow_nan=False,
        sort_keys=True,
    )

    assert serialized


def test_rainfall_disables_pit_duration_candidate() -> None:
    """Aligned rainfall must override dry-compound appearance."""
    result = process_session_tables(
        SessionKey(2024, 1),
        make_laps(),
        make_weather(rainfall=True),
    )

    assert int(
        result.laps["IsEligible"].sum()
    ) == 0

    pit_event = result.pit_events.iloc[0]

    assert bool(
        pit_event["entry_rainfall"]
    )
    assert bool(
        pit_event["exit_rainfall"]
    )
    assert not bool(
        pit_event["is_dry_weather_pair"]
    )
    assert not bool(
        pit_event[
            "is_duration_analysis_candidate"
        ]
    )

    lap_quality = result.quality_report[
        "lap_quality"
    ]
    pit_quality = result.quality_report[
        "pit_event_quality"
    ]

    assert isinstance(lap_quality, dict)
    assert isinstance(pit_quality, dict)

    assert lap_quality["rain_aligned_laps"] == 4
    assert (
        lap_quality["rainfall_newly_excluded_laps"]
        == 1
    )
    assert (
        pit_quality["duration_analysis_candidates"]
        == 0
    )


def test_rejects_session_key_mismatch() -> None:
    """Requested identity must match the source tables."""
    with pytest.raises(
        SessionProcessingError,
        match="round",
    ):
        process_session_tables(
            SessionKey(2024, 2),
            make_laps(),
            make_weather(),
        )


def test_rejects_event_name_mismatch() -> None:
    """Lap and weather tables must describe one event."""
    weather = make_weather()
    weather["EventName"] = "Different Grand Prix"

    with pytest.raises(
        SessionProcessingError,
        match="event names differ",
    ):
        process_session_tables(
            SessionKey(2024, 1),
            make_laps(),
            weather,
        )


def test_rejects_missing_provenance_column() -> None:
    """Source identity must never be inferred silently."""
    weather = make_weather().drop(
        columns="EventName"
    )

    with pytest.raises(
        SessionProcessingError,
        match="EventName",
    ):
        process_session_tables(
            SessionKey(2024, 1),
            make_laps(),
            weather,
        )


def test_rejects_empty_lap_table() -> None:
    """A session with no laps cannot be processed."""
    laps = make_laps().iloc[0:0].copy()

    with pytest.raises(
        SessionProcessingError,
        match="must not be empty",
    ):
        process_session_tables(
            SessionKey(2024, 1),
            laps,
            make_weather(),
        )


def test_is_deterministic_and_preserves_sources() -> None:
    """Processing must preserve raw tables and repeat exactly."""
    laps = make_laps()
    weather = make_weather()

    original_laps = laps.copy(deep=True)
    original_weather = weather.copy(deep=True)

    first = process_session_tables(
        SessionKey(2024, 1),
        laps,
        weather,
    )
    second = process_session_tables(
        SessionKey(2024, 1),
        laps,
        weather,
    )

    pd.testing.assert_frame_equal(
        first.laps,
        second.laps,
    )
    pd.testing.assert_frame_equal(
        first.stints,
        second.stints,
    )
    pd.testing.assert_frame_equal(
        first.pit_events,
        second.pit_events,
    )
    pd.testing.assert_frame_equal(
        laps,
        original_laps,
    )
    pd.testing.assert_frame_equal(
        weather,
        original_weather,
    )

    assert (
        first.quality_report
        == second.quality_report
    )