"""Tests for canonical Phase 3 source normalization."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.datasets import (
    PIT_EVENT_NULLABLE_BOOLEAN_COLUMNS,
    PIT_EVENT_NULLABLE_INTEGER_COLUMNS,
    NormalizedProcessedSession,
    SourceNormalizationError,
    normalize_processed_laps,
    normalize_processed_pit_events,
    normalize_processed_session_tables,
    normalize_processed_stints,
)
from app.pipeline import SessionKey


def make_laps() -> pd.DataFrame:
    """Create representative processed lap source rows."""
    return pd.DataFrame(
        {
            "SourceRowNumber": [
                0.0,
                1.0,
            ],
            "Season": [
                "2024",
                "2024",
            ],
            "RoundNumber": [
                1.0,
                1.0,
            ],
            "SessionType": [
                " r ",
                " r ",
            ],
            "EventName": [
                "Bahrain Grand Prix",
                "Bahrain Grand Prix",
            ],
            "Driver": [
                " ver ",
                " ver ",
            ],
            "DriverNumber": [
                1,
                1,
            ],
            "Team": [
                "Red Bull Racing",
                "Red Bull Racing",
            ],
            "LapNumber": [
                1.0,
                2.0,
            ],
            "Stint": [
                1.0,
                1.0,
            ],
            "Compound": [
                " medium ",
                " medium ",
            ],
            "TyreLife": [
                1.0,
                2.0,
            ],
            "FreshTyre": [
                np.bool_(True),
                np.bool_(True),
            ],
            "LapStartTime": pd.to_timedelta(
                [
                    0,
                    90,
                ],
                unit="s",
            ),
            "TrackStatus": [
                "1",
                "1",
            ],
            "Position": [
                1.0,
                1.0,
            ],
            "WeatherObservationTime": (
                pd.to_timedelta(
                    [
                        0,
                        60,
                    ],
                    unit="s",
                )
            ),
            "AirTemp": [
                25.0,
                25.1,
            ],
            "Humidity": [
                45.0,
                45.5,
            ],
            "Pressure": [
                1012.0,
                1012.1,
            ],
            "Rainfall": [
                False,
                False,
            ],
            "TrackTemp": [
                34.0,
                34.2,
            ],
            "WindDirection": [
                180.0,
                181.0,
            ],
            "WindSpeed": [
                2.0,
                2.1,
            ],
            "WeatherMatched": [
                True,
                True,
            ],
            "WeatherAgeSeconds": [
                0.0,
                30.0,
            ],
            "LapTimeSeconds": [
                90.0,
                89.5,
            ],
            "Sector1TimeSeconds": [
                30.0,
                29.8,
            ],
            "Sector2TimeSeconds": [
                30.0,
                29.9,
            ],
            "Sector3TimeSeconds": [
                30.0,
                29.8,
            ],
            "PitInTime": pd.to_timedelta(
                [
                    None,
                    None,
                ],
                unit="s",
            ),
            "PitOutTime": pd.to_timedelta(
                [
                    None,
                    None,
                ],
                unit="s",
            ),
            "IsAccurate": [
                True,
                True,
            ],
            "IsEligible": [
                False,
                True,
            ],
            "QualityFlags": [
                "FIRST_LAP",
                "",
            ],
            "ExclusionReasons": [
                "FIRST_LAP",
                "",
            ],
        }
    )


def make_stints() -> pd.DataFrame:
    """Create one representative processed stint."""
    return pd.DataFrame(
        {
            "season": ["2024"],
            "round_number": [1.0],
            "session_type": [" r "],
            "event_name": [
                "Bahrain Grand Prix"
            ],
            "driver": [" ver "],
            "team": ["Red Bull Racing"],
            "stint_number": [1.0],
            "compound": [" medium "],
            "start_lap": [1.0],
            "end_lap": [2.0],
            "recorded_laps": [2.0],
            "start_tyre_life": [1.0],
            "end_tyre_life": [2.0],
            "is_first_stint": [True],
            "is_last_stint": [True],
            "boundary_before_verified": [
                True
            ],
            "boundary_after_verified": [
                True
            ],
            "is_complete": [True],
            "warning_count": [0.0],
            "warnings": [""],
        }
    )


def make_pit_events() -> pd.DataFrame:
    """Create matched, entry-only and exit-only events."""
    return pd.DataFrame(
        {
            "pit_event_id": [
                "2024-01-R-VER-001",
                "2024-01-R-PER-001",
                "2024-01-R-ALO-001",
            ],
            "season": [
                "2024",
                "2024",
                "2024",
            ],
            "round_number": [
                1.0,
                1.0,
                1.0,
            ],
            "session_type": [
                " r ",
                " r ",
                " r ",
            ],
            "event_name": [
                "Bahrain Grand Prix",
                "Bahrain Grand Prix",
                "Bahrain Grand Prix",
            ],
            "driver": [
                " ver ",
                " per ",
                " alo ",
            ],
            "team": [
                "Red Bull Racing",
                "Red Bull Racing",
                "Aston Martin",
            ],
            "event_type": [
                " matched ",
                " entry_only ",
                " exit_only ",
            ],
            "pit_in_lap": [
                20.0,
                25.0,
                None,
            ],
            "pit_out_lap": [
                21.0,
                None,
                15.0,
            ],
            "stint_before": [
                1.0,
                1.0,
                None,
            ],
            "stint_after": [
                2.0,
                None,
                2.0,
            ],
            "compound_before": [
                " medium ",
                " hard ",
                None,
            ],
            "compound_after": [
                " hard ",
                None,
                " medium ",
            ],
            "tyre_life_before": [
                20.0,
                25.0,
                None,
            ],
            "tyre_life_after": [
                1.0,
                None,
                1.0,
            ],
            "pit_in_time_seconds": [
                1800.0,
                2250.0,
                None,
            ],
            "pit_out_time_seconds": [
                1823.0,
                None,
                1373.0,
            ],
            "observed_pit_lane_duration_seconds": [
                23.0,
                None,
                None,
            ],
            "entry_track_status": [
                "1",
                "1",
                None,
            ],
            "exit_track_status": [
                "1",
                None,
                "1",
            ],
            "is_stint_change": [
                True,
                None,
                None,
            ],
            "is_compound_change": [
                True,
                None,
                None,
            ],
            "is_green_flag_pair": [
                True,
                False,
                False,
            ],
            "is_dry_compound_pair": [
                True,
                False,
                False,
            ],
            "is_interrupted_duration": [
                False,
                False,
                False,
            ],
            "is_complete": [
                True,
                False,
                False,
            ],
            "is_duration_analysis_candidate": [
                True,
                False,
                False,
            ],
            "warning_count": [
                0.0,
                1.0,
                1.0,
            ],
            "warnings": [
                "",
                "ENTRY_ONLY",
                "EXIT_ONLY",
            ],
            "entry_rainfall": [
                False,
                False,
                None,
            ],
            "exit_rainfall": [
                False,
                None,
                False,
            ],
            "is_dry_weather_pair": [
                True,
                False,
                False,
            ],
        }
    )


def test_lap_normalization_produces_canonical_dtypes() -> None:
    """Integer, string and boolean sources become canonical."""
    result = normalize_processed_laps(
        make_laps(),
        SessionKey(2024, 1),
    )

    assert str(
        result["LapNumber"].dtype
    ) == "Int64"
    assert str(
        result["Stint"].dtype
    ) == "Int64"
    assert str(
        result["TyreLife"].dtype
    ) == "Int64"
    assert str(
        result["Position"].dtype
    ) == "Int64"
    assert str(
        result["Driver"].dtype
    ) == "string"
    assert str(
        result["Rainfall"].dtype
    ) == "boolean"
    assert str(
        result["IsEligible"].dtype
    ) == "bool"

    assert result["SessionType"].tolist() == [
        "R",
        "R",
    ]
    assert result["Driver"].tolist() == [
        "VER",
        "VER",
    ]
    assert result["Compound"].tolist() == [
        "MEDIUM",
        "MEDIUM",
    ]
    assert result["DriverNumber"].tolist() == [
        "1",
        "1",
    ]


def test_lap_normalization_does_not_mutate_source() -> None:
    """Normalization must return a defensive copy."""
    source = make_laps()
    original = source.copy(deep=True)

    result = normalize_processed_laps(
        source,
        SessionKey(2024, 1),
    )

    pd.testing.assert_frame_equal(
        source,
        original,
    )
    assert result is not source


def test_missing_required_lap_column_is_rejected() -> None:
    """The normalizer must fail closed on schema loss."""
    source = make_laps().drop(
        columns=["LapStartTime"]
    )

    with pytest.raises(
        SourceNormalizationError,
        match="missing required columns",
    ):
        normalize_processed_laps(
            source,
            SessionKey(2024, 1),
        )


def test_protected_season_is_rejected() -> None:
    """Development normalization must never inspect 2025."""
    with pytest.raises(
        SourceNormalizationError,
        match="protected evaluation season",
    ):
        normalize_processed_laps(
            make_laps(),
            SessionKey(2025, 1),
        )


def test_unsupported_development_season_is_rejected() -> None:
    """Only the frozen 2022–2024 period is supported."""
    with pytest.raises(
        SourceNormalizationError,
        match="outside the development seasons",
    ):
        normalize_processed_laps(
            make_laps(),
            SessionKey(2021, 1),
        )


def test_session_key_rejects_non_race_session() -> None:
    """The shared identity boundary accepts races only."""
    with pytest.raises(
        ValueError,
        match="unsupported session_type",
    ):
        SessionKey(
            2024,
            1,
            session_type="Q",
        )


def test_lap_identity_mismatch_is_rejected() -> None:
    """Partition metadata must match its session key."""
    source = make_laps()
    source["RoundNumber"] = 2

    with pytest.raises(
        SourceNormalizationError,
        match="round does not match",
    ):
        normalize_processed_laps(
            source,
            SessionKey(2024, 1),
        )


def test_fractional_lap_number_is_rejected() -> None:
    """Whole-number semantic fields cannot be rounded."""
    source = make_laps()
    source.loc[1, "LapNumber"] = 2.5

    with pytest.raises(
        SourceNormalizationError,
        match="fractional values",
    ):
        normalize_processed_laps(
            source,
            SessionKey(2024, 1),
        )


def test_non_boolean_source_value_is_rejected() -> None:
    """Integer truth values must not impersonate booleans."""
    source = make_laps()
    source["IsEligible"] = source[
        "IsEligible"
    ].astype("object")
    source.loc[1, "IsEligible"] = 1

    with pytest.raises(
        SourceNormalizationError,
        match="non-boolean values",
    ):
        normalize_processed_laps(
            source,
            SessionKey(2024, 1),
        )


def test_invalid_timedelta_is_rejected() -> None:
    """Malformed decision timestamps must fail closed."""
    source = make_laps()
    source["LapStartTime"] = [
        "00:00:00",
        "not-a-time",
    ]

    with pytest.raises(
        SourceNormalizationError,
        match="invalid timedeltas",
    ):
        normalize_processed_laps(
            source,
            SessionKey(2024, 1),
        )


def test_nullable_lap_state_is_preserved() -> None:
    """Missing tyre life and position remain explicit."""
    source = make_laps()
    source.loc[1, "TyreLife"] = None
    source.loc[1, "Position"] = None

    result = normalize_processed_laps(
        source,
        SessionKey(2024, 1),
    )

    assert pd.isna(
        result.loc[1, "TyreLife"]
    )
    assert pd.isna(
        result.loc[1, "Position"]
    )


def test_stint_normalization_produces_canonical_values() -> None:
    """Processed stint identities and integers are stable."""
    result = normalize_processed_stints(
        make_stints(),
        SessionKey(2024, 1),
    )

    assert str(
        result["stint_number"].dtype
    ) == "int64"
    assert str(
        result["compound"].dtype
    ) == "string"
    assert str(
        result["is_complete"].dtype
    ) == "bool"

    assert result.loc[
        0,
        "session_type",
    ] == "R"
    assert result.loc[0, "driver"] == "VER"
    assert (
        result.loc[0, "compound"]
        == "MEDIUM"
    )


def test_pit_normalization_produces_nullable_types() -> None:
    """Incomplete pit events receive canonical dtypes."""
    result = normalize_processed_pit_events(
        make_pit_events(),
        SessionKey(2024, 1),
    )

    for column in (
        PIT_EVENT_NULLABLE_INTEGER_COLUMNS
    ):
        assert str(
            result[column].dtype
        ) == "Int64"

    for column in (
        PIT_EVENT_NULLABLE_BOOLEAN_COLUMNS
    ):
        assert str(
            result[column].dtype
        ) == "boolean"

    assert result[
        "event_type"
    ].tolist() == [
        "MATCHED",
        "ENTRY_ONLY",
        "EXIT_ONLY",
    ]
    assert result[
        "compound_before"
    ].tolist()[:2] == [
        "MEDIUM",
        "HARD",
    ]


def test_pit_schema_variants_normalize_identically() -> None:
    """Missingness must not create multiple schemas."""
    mixed_source = make_pit_events()

    complete_source = (
        mixed_source.iloc[[0]]
        .copy(deep=True)
    )

    for column in (
        PIT_EVENT_NULLABLE_INTEGER_COLUMNS
    ):
        complete_source[column] = (
            complete_source[column]
            .astype("int64")
        )

    for column in (
        PIT_EVENT_NULLABLE_BOOLEAN_COLUMNS
    ):
        complete_source[column] = (
            complete_source[column]
            .astype("bool")
        )

    mixed = normalize_processed_pit_events(
        mixed_source,
        SessionKey(2024, 1),
    )
    complete = normalize_processed_pit_events(
        complete_source,
        SessionKey(2024, 1),
    )

    mixed_signature = {
        column: str(dtype)
        for column, dtype in zip(
            mixed.columns,
            mixed.dtypes,
            strict=True,
        )
    }
    complete_signature = {
        column: str(dtype)
        for column, dtype in zip(
            complete.columns,
            complete.dtypes,
            strict=True,
        )
    }

    assert (
        mixed_signature
        == complete_signature
    )


def test_unsupported_pit_event_type_is_rejected() -> None:
    """The source cannot invent a fourth event type."""
    source = make_pit_events()
    source.loc[
        0,
        "event_type",
    ] = "TELEPORT"

    with pytest.raises(
        SourceNormalizationError,
        match="unsupported values",
    ):
        normalize_processed_pit_events(
            source,
            SessionKey(2024, 1),
        )


def test_fractional_pit_identity_is_rejected() -> None:
    """Nullable pit identifiers remain whole numbers."""
    source = make_pit_events()
    source.loc[0, "pit_in_lap"] = 20.5

    with pytest.raises(
        SourceNormalizationError,
        match="fractional values",
    ):
        normalize_processed_pit_events(
            source,
            SessionKey(2024, 1),
        )


def test_processed_session_normalizes_all_tables() -> None:
    """The aggregate normalizer returns one coherent session."""
    result = normalize_processed_session_tables(
        laps=make_laps(),
        stints=make_stints(),
        pit_events=make_pit_events(),
        session_key=SessionKey(2024, 1),
    )

    assert isinstance(
        result,
        NormalizedProcessedSession,
    )
    assert (
        result.session_key
        == SessionKey(2024, 1)
    )
    assert (
        result.event_name
        == "Bahrain Grand Prix"
    )
    assert len(result.laps) == 2
    assert len(result.stints) == 1
    assert len(result.pit_events) == 3


def test_cross_table_event_mismatch_is_rejected() -> None:
    """All processed tables must identify the same race."""
    stints = make_stints()
    stints["event_name"] = (
        "Different Grand Prix"
    )

    with pytest.raises(
        SourceNormalizationError,
        match="disagree on event name",
    ):
        normalize_processed_session_tables(
            laps=make_laps(),
            stints=stints,
            pit_events=make_pit_events(),
            session_key=SessionKey(2024, 1),
        )


def test_empty_pit_table_is_supported() -> None:
    """A race with no pit events may still normalize."""
    empty_pits = (
        make_pit_events()
        .iloc[0:0]
        .copy(deep=True)
    )

    result = normalize_processed_session_tables(
        laps=make_laps(),
        stints=make_stints(),
        pit_events=empty_pits,
        session_key=SessionKey(2024, 1),
    )

    assert result.pit_events.empty

    for column in (
        PIT_EVENT_NULLABLE_INTEGER_COLUMNS
    ):
        assert str(
            result.pit_events[column].dtype
        ) == "Int64"


def test_normalizer_requires_dataframe() -> None:
    """Non-tabular input must fail with a clear type error."""
    with pytest.raises(
        TypeError,
        match="must be a pandas DataFrame",
    ):
        normalize_processed_laps(
            None,  # type: ignore[arg-type]
            SessionKey(2024, 1),
        )