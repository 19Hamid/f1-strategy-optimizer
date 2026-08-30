import pandas as pd
import pytest

from app.cleaning import (
    WeatherAlignmentError,
    align_weather_to_laps,
)


def _lap_table(
    start_times: tuple[float, ...] = (
        10.0,
        70.0,
        130.0,
    ),
) -> pd.DataFrame:
    row_count = len(start_times)

    return pd.DataFrame(
        {
            "Season": [2024] * row_count,
            "RoundNumber": [1] * row_count,
            "SessionType": ["R"] * row_count,
            "EventName": [
                "Bahrain Grand Prix"
            ] * row_count,
            "LapStartTime": pd.to_timedelta(
                start_times,
                unit="s",
            ),
        }
    )


def _weather_table(
    times: tuple[float, ...] = (
        0.0,
        60.0,
        120.0,
    ),
    rainfall: tuple[bool, ...] = (
        False,
        True,
        False,
    ),
) -> pd.DataFrame:
    if len(times) != len(rainfall):
        raise ValueError(
            "weather times and rainfall must have equal length"
        )

    row_count = len(times)

    return pd.DataFrame(
        {
            "Season": [2024] * row_count,
            "RoundNumber": [1] * row_count,
            "SessionType": ["R"] * row_count,
            "EventName": [
                "Bahrain Grand Prix"
            ] * row_count,
            "Time": pd.to_timedelta(
                times,
                unit="s",
            ),
            "AirTemp": [
                20.0 + index
                for index in range(row_count)
            ],
            "Humidity": [
                50.0 + index
                for index in range(row_count)
            ],
            "Pressure": [
                1000.0 + index
                for index in range(row_count)
            ],
            "Rainfall": list(rainfall),
            "TrackTemp": [
                30.0 + index
                for index in range(row_count)
            ],
            "WindDirection": [
                100 + index
                for index in range(row_count)
            ],
            "WindSpeed": [
                2.0 + index
                for index in range(row_count)
            ],
        }
    )


def test_aligns_latest_previous_weather_without_mutation() -> None:
    laps = _lap_table()
    weather = _weather_table()
    original_laps = laps.copy(deep=True)
    original_weather = weather.copy(deep=True)

    result = align_weather_to_laps(
        laps,
        weather,
    )

    pd.testing.assert_frame_equal(
        laps,
        original_laps,
    )
    pd.testing.assert_frame_equal(
        weather,
        original_weather,
    )

    assert result.laps[
        "WeatherObservationTime"
    ].tolist() == pd.to_timedelta(
        [0.0, 60.0, 120.0],
        unit="s",
    ).tolist()
    assert result.laps[
        "WeatherAgeSeconds"
    ].tolist() == pytest.approx(
        [10.0, 10.0, 10.0]
    )
    assert result.laps["WeatherMatched"].tolist() == [
        True,
        True,
        True,
    ]
    assert result.laps["Rainfall"].tolist() == [
        False,
        True,
        False,
    ]
    assert result.laps["WeatherAgeSeconds"].ge(0).all()

    assert result.input_lap_count == 3
    assert result.weather_observation_count == 3
    assert result.matched_lap_count == 3
    assert result.unmatched_lap_count == 0
    assert result.rainy_lap_count == 1
    assert result.maximum_weather_age_seconds == pytest.approx(
        10.0
    )
    assert not result.weather_was_reordered


def test_restores_original_lap_order_and_sorts_weather() -> None:
    laps = _lap_table(
        (
            130.0,
            10.0,
            70.0,
        )
    )
    weather = (
        _weather_table()
        .iloc[[2, 0, 1]]
        .reset_index(drop=True)
    )

    result = align_weather_to_laps(
        laps,
        weather,
    )

    assert result.laps[
        "LapStartTime"
    ].tolist() == pd.to_timedelta(
        [130.0, 10.0, 70.0],
        unit="s",
    ).tolist()
    assert result.laps[
        "WeatherObservationTime"
    ].tolist() == pd.to_timedelta(
        [120.0, 0.0, 60.0],
        unit="s",
    ).tolist()
    assert result.laps[
        "WeatherAgeSeconds"
    ].tolist() == pytest.approx(
        [10.0, 10.0, 10.0]
    )
    assert result.weather_was_reordered


def test_allows_exact_timestamp_match() -> None:
    laps = _lap_table((60.0,))
    weather = _weather_table(
        times=(0.0, 60.0),
        rainfall=(False, True),
    )

    result = align_weather_to_laps(
        laps,
        weather,
    )
    aligned = result.laps.iloc[0]

    assert aligned["WeatherObservationTime"] == (
        pd.to_timedelta(60.0, unit="s")
    )
    assert aligned["WeatherAgeSeconds"] == pytest.approx(0.0)
    assert bool(aligned["WeatherMatched"])
    assert bool(aligned["Rainfall"])


def test_reports_lap_without_previous_weather() -> None:
    laps = _lap_table((0.0,))
    weather = _weather_table(
        times=(10.0,),
        rainfall=(False,),
    )

    result = align_weather_to_laps(
        laps,
        weather,
    )
    aligned = result.laps.iloc[0]

    assert not bool(aligned["WeatherMatched"])
    assert pd.isna(aligned["WeatherObservationTime"])
    assert pd.isna(aligned["WeatherAgeSeconds"])
    assert pd.isna(aligned["Rainfall"])
    assert result.matched_lap_count == 0
    assert result.unmatched_lap_count == 1
    assert result.rainy_lap_count == 0
    assert result.maximum_weather_age_seconds is None


def test_rejects_duplicate_weather_timestamps() -> None:
    laps = _lap_table((10.0,))
    weather = (
        _weather_table()
        .iloc[[0, 0]]
        .reset_index(drop=True)
    )

    with pytest.raises(
        WeatherAlignmentError,
        match="weather Time must not contain duplicates",
    ):
        align_weather_to_laps(
            laps,
            weather,
        )


def test_rejects_mismatched_session_identity() -> None:
    laps = _lap_table()
    weather = _weather_table()
    weather["Season"] = 2023

    with pytest.raises(
        WeatherAlignmentError,
        match=(
            "lap and weather session identities "
            "do not match"
        ),
    ):
        align_weather_to_laps(
            laps,
            weather,
        )


def test_reports_missing_required_weather_column() -> None:
    laps = _lap_table()
    weather = _weather_table().drop(
        columns="AirTemp"
    )

    with pytest.raises(
        WeatherAlignmentError,
        match=(
            "weather table is missing required columns: "
            "AirTemp"
        ),
    ):
        align_weather_to_laps(
            laps,
            weather,
        )


def test_rejects_non_timedelta_weather_time() -> None:
    laps = _lap_table((10.0,))
    weather = _weather_table(
        times=(0.0,),
        rainfall=(False,),
    )
    weather["Time"] = [0.0]

    with pytest.raises(
        WeatherAlignmentError,
        match="Time must use a timedelta dtype",
    ):
        align_weather_to_laps(
            laps,
            weather,
        )


def test_rejects_repeated_weather_alignment() -> None:
    laps = _lap_table()
    weather = _weather_table()
    aligned_laps = align_weather_to_laps(
        laps,
        weather,
    ).laps

    with pytest.raises(
        WeatherAlignmentError,
        match=(
            "lap table already contains weather "
            "output columns"
        ),
    ):
        align_weather_to_laps(
            aligned_laps,
            weather,
        )