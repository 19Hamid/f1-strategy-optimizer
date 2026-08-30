"""Tests for complete session-level lap cleaning."""

import pandas as pd
import pytest

from app.cleaning import (
    LapQualityReason,
    SessionCleaningError,
    clean_session_laps,
)


def make_laps(
    *,
    compound: str = "MEDIUM",
    is_accurate: bool = True,
    lap_start_seconds: int = 100,
) -> pd.DataFrame:
    """Create one valid representative raw lap."""
    return pd.DataFrame(
        {
            "Season": [2024],
            "RoundNumber": [1],
            "SessionType": ["R"],
            "EventName": ["Bahrain Grand Prix"],
            "Driver": ["VER"],
            "Team": ["Red Bull Racing"],
            "LapNumber": [2.0],
            "LapTime": pd.to_timedelta(
                [95],
                unit="s",
            ),
            "Stint": [1.0],
            "Compound": [compound],
            "TyreLife": [2.0],
            "PitInTime": pd.Series(
                [pd.NaT],
                dtype="timedelta64[ns]",
            ),
            "PitOutTime": pd.Series(
                [pd.NaT],
                dtype="timedelta64[ns]",
            ),
            "Sector1Time": pd.to_timedelta(
                [31],
                unit="s",
            ),
            "Sector2Time": pd.to_timedelta(
                [33],
                unit="s",
            ),
            "Sector3Time": pd.to_timedelta(
                [31],
                unit="s",
            ),
            "TrackStatus": ["1"],
            "LapStartTime": pd.to_timedelta(
                [lap_start_seconds],
                unit="s",
            ),
            "IsPersonalBest": [False],
            "IsAccurate": [is_accurate],
        }
    )


def make_weather(
    *,
    rainfall: bool = False,
    observation_seconds: int = 90,
) -> pd.DataFrame:
    """Create one representative weather observation."""
    return pd.DataFrame(
        {
            "Season": [2024],
            "RoundNumber": [1],
            "SessionType": ["R"],
            "EventName": ["Bahrain Grand Prix"],
            "Time": pd.to_timedelta(
                [observation_seconds],
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


def test_keeps_valid_dry_lap_eligible() -> None:
    """A valid dry lap should remain eligible."""
    result = clean_session_laps(
        make_laps(),
        make_weather(),
    )

    assert result.input_lap_count == 1
    assert result.eligible_lap_count == 1
    assert result.flagged_lap_count == 0
    assert result.excluded_lap_count == 0
    assert result.weather_observation_count == 1
    assert result.rainy_lap_count == 0
    assert result.rain_added_reason_count == 0
    assert result.rain_newly_excluded_count == 0
    assert result.maximum_weather_age_seconds == pytest.approx(10.0)
    assert not result.weather_was_reordered
    assert (
        result.quality_counts[
            LapQualityReason.WET_CONDITION.value
        ]
        == 0
    )


def test_rainfall_excludes_otherwise_valid_lap() -> None:
    """Observed rainfall should add the wet-condition reason."""
    result = clean_session_laps(
        make_laps(),
        make_weather(rainfall=True),
    )

    assert result.input_lap_count == 1
    assert result.eligible_lap_count == 0
    assert result.flagged_lap_count == 1
    assert result.excluded_lap_count == 1
    assert result.rainy_lap_count == 1
    assert result.rain_added_reason_count == 1
    assert result.rain_newly_excluded_count == 1
    assert (
        result.quality_counts[
            LapQualityReason.WET_CONDITION.value
        ]
        == 1
    )


def test_rain_does_not_duplicate_existing_wet_reason() -> None:
    """A wet compound and rainfall should produce one wet reason."""
    result = clean_session_laps(
        make_laps(compound="INTERMEDIATE"),
        make_weather(rainfall=True),
    )

    assert result.eligible_lap_count == 0
    assert result.flagged_lap_count == 1
    assert result.excluded_lap_count == 1
    assert result.rainy_lap_count == 1
    assert result.rain_added_reason_count == 0
    assert result.rain_newly_excluded_count == 0
    assert (
        result.quality_counts[
            LapQualityReason.WET_CONDITION.value
        ]
        == 1
    )


def test_rain_does_not_recount_already_excluded_lap() -> None:
    """Rain may add a reason without newly excluding the lap."""
    result = clean_session_laps(
        make_laps(is_accurate=False),
        make_weather(rainfall=True),
    )

    assert result.eligible_lap_count == 0
    assert result.flagged_lap_count == 1
    assert result.excluded_lap_count == 1
    assert result.rainy_lap_count == 1
    assert result.rain_added_reason_count == 1
    assert result.rain_newly_excluded_count == 0
    assert (
        result.quality_counts[
            LapQualityReason.INACCURATE_LAP.value
        ]
        == 1
    )
    assert (
        result.quality_counts[
            LapQualityReason.WET_CONDITION.value
        ]
        == 1
    )


def test_rejects_lap_without_earlier_weather() -> None:
    """Cleaning must not borrow weather from the future."""
    laps = make_laps(
        lap_start_seconds=100,
    )
    weather = make_weather(
        observation_seconds=110,
    )

    with pytest.raises(
        SessionCleaningError,
        match="weather",
    ):
        clean_session_laps(
            laps,
            weather,
        )


def test_is_deterministic_and_preserves_inputs() -> None:
    """Repeated cleaning must agree and leave raw inputs unchanged."""
    laps = make_laps()
    weather = make_weather(rainfall=True)

    original_laps = laps.copy(deep=True)
    original_weather = weather.copy(deep=True)

    first = clean_session_laps(
        laps,
        weather,
    )
    second = clean_session_laps(
        laps,
        weather,
    )

    pd.testing.assert_frame_equal(
        first.laps,
        second.laps,
    )
    pd.testing.assert_frame_equal(
        laps,
        original_laps,
    )
    pd.testing.assert_frame_equal(
        weather,
        original_weather,
    )

    assert first.quality_counts == second.quality_counts
    assert (
        first.eligible_lap_count
        == second.eligible_lap_count
    )
    assert (
        first.rain_newly_excluded_count
        == second.rain_newly_excluded_count
    )