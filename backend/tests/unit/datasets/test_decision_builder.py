"""Tests for leakage-controlled decision-table construction."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.datasets import (
    DATASET_CONTRACT_VERSION,
    DECISION_LABELS_CONTRACT,
    DECISION_ROWS_CONTRACT,
)
from app.datasets.decisions import (
    DecisionConstructionError,
    DecisionSessionData,
    build_session_decisions,
)
from app.datasets.normalization import (
    NormalizedProcessedSession,
)
from app.pipeline import SessionKey


def make_session() -> NormalizedProcessedSession:
    """Create one normalized seven-lap race session."""
    pit_in_times = pd.to_timedelta(
        [
            None,
            None,
            None,
            None,
            390,
            None,
            None,
        ],
        unit="s",
    )

    pit_out_times = pd.to_timedelta(
        [
            None,
            None,
            None,
            None,
            None,
            470,
            None,
        ],
        unit="s",
    )

    laps = pd.DataFrame(
        {
            "SourceRowNumber": pd.Series(
                range(7),
                dtype="int64",
            ),
            "Season": pd.Series(
                [2024] * 7,
                dtype="int64",
            ),
            "RoundNumber": pd.Series(
                [1] * 7,
                dtype="int64",
            ),
            "SessionType": pd.Series(
                ["R"] * 7,
                dtype="string",
            ),
            "EventName": pd.Series(
                [
                    "Bahrain Grand Prix"
                ]
                * 7,
                dtype="string",
            ),
            "Driver": pd.Series(
                ["VER"] * 7,
                dtype="string",
            ),
            "DriverNumber": pd.Series(
                ["1"] * 7,
                dtype="string",
            ),
            "Team": pd.Series(
                [
                    "Red Bull Racing"
                ]
                * 7,
                dtype="string",
            ),
            "LapNumber": pd.Series(
                range(1, 8),
                dtype="Int64",
            ),
            "Stint": pd.Series(
                [
                    1,
                    1,
                    1,
                    1,
                    1,
                    2,
                    2,
                ],
                dtype="Int64",
            ),
            "Compound": pd.Series(
                [
                    "MEDIUM",
                    "MEDIUM",
                    "MEDIUM",
                    "MEDIUM",
                    "MEDIUM",
                    "HARD",
                    "HARD",
                ],
                dtype="string",
            ),
            "TyreLife": pd.Series(
                [
                    1,
                    2,
                    3,
                    4,
                    5,
                    1,
                    2,
                ],
                dtype="Int64",
            ),
            "LapStartTime": (
                pd.to_timedelta(
                    [
                        0,
                        90,
                        180,
                        270,
                        360,
                        450,
                        540,
                    ],
                    unit="s",
                )
            ),
            "TrackStatus": pd.Series(
                ["1"] * 7,
                dtype="string",
            ),
            "Position": pd.Series(
                [
                    1,
                    1,
                    1,
                    1,
                    1,
                    1,
                    1,
                ],
                dtype="Int64",
            ),
            "WeatherObservationTime": (
                pd.to_timedelta(
                    [
                        0,
                        60,
                        150,
                        240,
                        330,
                        420,
                        510,
                    ],
                    unit="s",
                )
            ),
            "AirTemp": pd.Series(
                [
                    25.0,
                    25.1,
                    25.2,
                    25.3,
                    25.4,
                    25.5,
                    25.6,
                ],
                dtype="float64",
            ),
            "Humidity": pd.Series(
                [
                    45.0,
                    45.1,
                    45.2,
                    45.3,
                    45.4,
                    45.5,
                    45.6,
                ],
                dtype="float64",
            ),
            "Pressure": pd.Series(
                [1012.0] * 7,
                dtype="float64",
            ),
            "Rainfall": pd.Series(
                [False] * 7,
                dtype="boolean",
            ),
            "TrackTemp": pd.Series(
                [
                    34.0,
                    34.1,
                    34.2,
                    34.3,
                    34.4,
                    34.5,
                    34.6,
                ],
                dtype="float64",
            ),
            "WindDirection": pd.Series(
                [
                    180,
                    181,
                    182,
                    183,
                    184,
                    185,
                    186,
                ],
                dtype="int64",
            ),
            "WindSpeed": pd.Series(
                [
                    2.0,
                    2.1,
                    2.2,
                    2.3,
                    2.4,
                    2.5,
                    2.6,
                ],
                dtype="float64",
            ),
            "WeatherMatched": pd.Series(
                [True] * 7,
                dtype="bool",
            ),
            "WeatherAgeSeconds": (
                pd.Series(
                    [
                        0.0,
                        30.0,
                        30.0,
                        30.0,
                        30.0,
                        30.0,
                        30.0,
                    ],
                    dtype="float64",
                )
            ),
            "LapTimeSeconds": pd.Series(
                [
                    100.0,
                    101.0,
                    102.0,
                    103.0,
                    104.0,
                    105.0,
                    106.0,
                ],
                dtype="float64",
            ),
            "Sector1TimeSeconds": (
                pd.Series(
                    [
                        33.0,
                        33.1,
                        33.2,
                        33.3,
                        33.4,
                        33.5,
                        33.6,
                    ],
                    dtype="float64",
                )
            ),
            "Sector2TimeSeconds": (
                pd.Series(
                    [
                        33.0,
                        33.1,
                        33.2,
                        33.3,
                        33.4,
                        33.5,
                        33.6,
                    ],
                    dtype="float64",
                )
            ),
            "Sector3TimeSeconds": (
                pd.Series(
                    [
                        34.0,
                        34.8,
                        35.6,
                        36.4,
                        37.2,
                        38.0,
                        38.8,
                    ],
                    dtype="float64",
                )
            ),
            "PitInTime": pit_in_times,
            "PitOutTime": pit_out_times,
            "IsEligible": pd.Series(
                [
                    True,
                    True,
                    True,
                    True,
                    False,
                    False,
                    True,
                ],
                dtype="bool",
            ),
            "ExclusionReasonCount": (
                pd.Series(
                    [
                        0,
                        0,
                        0,
                        0,
                        1,
                        1,
                        0,
                    ],
                    dtype="int64",
                )
            ),
            "ExclusionReasons": pd.Series(
                [
                    "",
                    "",
                    "",
                    "",
                    "PIT_IN_LAP",
                    "PIT_OUT_LAP",
                    "",
                ],
                dtype="string",
            ),
        }
    )

    pit_events = pd.DataFrame(
        {
            "pit_event_id": pd.Series(
                [
                    "2024-01-R-VER-001"
                ],
                dtype="string",
            ),
            "driver": pd.Series(
                ["VER"],
                dtype="string",
            ),
            "pit_in_lap": pd.Series(
                [5],
                dtype="Int64",
            ),
        }
    )

    return NormalizedProcessedSession(
        session_key=SessionKey(
            2024,
            1,
        ),
        event_name=(
            "Bahrain Grand Prix"
        ),
        laps=laps,
        stints=pd.DataFrame(),
        pit_events=pit_events,
    )


def decision_row(
    result: DecisionSessionData,
    lap_number: int,
) -> pd.Series:
    """Return one decision row by decision lap."""
    rows = result.decision_rows.loc[
        result.decision_rows[
            "decision_lap"
        ].eq(lap_number)
    ]

    assert len(rows) == 1

    return rows.iloc[0]


def label_row(
    result: DecisionSessionData,
    lap_number: int,
) -> pd.Series:
    """Return one label row by decision lap."""
    rows = result.decision_labels.loc[
        result.decision_labels[
            "decision_lap"
        ].eq(lap_number)
    ]

    assert len(rows) == 1

    return rows.iloc[0]


def test_builder_creates_one_candidate_after_first_lap() -> None:
    """The first recorded driver lap is omitted."""
    result = build_session_decisions(
        make_session()
    )

    assert (
        len(result.decision_rows)
        == 6
    )
    assert (
        len(result.decision_labels)
        == 6
    )

    assert result.decision_rows[
        "decision_lap"
    ].tolist() == [
        2,
        3,
        4,
        5,
        6,
        7,
    ]

    assert result.decision_rows[
        "decision_id"
    ].tolist() == [
        "2024-01-R-VER-002",
        "2024-01-R-VER-003",
        "2024-01-R-VER-004",
        "2024-01-R-VER-005",
        "2024-01-R-VER-006",
        "2024-01-R-VER-007",
    ]


def test_output_tables_match_contract_order_and_dtypes() -> None:
    """Both outputs implement their contracts exactly."""
    result = build_session_decisions(
        make_session()
    )

    for table, contract in (
        (
            result.decision_rows,
            DECISION_ROWS_CONTRACT,
        ),
        (
            result.decision_labels,
            DECISION_LABELS_CONTRACT,
        ),
    ):
        assert (
            table.columns.tolist()
            == [
                column.name
                for column in (
                    contract.columns
                )
            ]
        )

        assert [
            str(dtype)
            for dtype in (
                table.dtypes
            )
        ] == [
            column.pandas_dtype
            for column in (
                contract.columns
            )
        ]


def test_past_only_state_and_three_lap_history() -> None:
    """Lap four uses completed laps one to three."""
    result = build_session_decisions(
        make_session()
    )
    row = decision_row(
        result,
        4,
    )

    assert (
        row["current_compound"]
        == "MEDIUM"
    )
    assert row["tyre_age_laps"] == 3
    assert (
        row["current_stint_number"]
        == 1
    )
    assert (
        row[
            "current_stint_laps_completed"
        ]
        == 3
    )
    assert (
        row["completed_pit_stops"]
        == 0
    )
    assert (
        row["previous_position"]
        == 1
    )
    assert row[
        "previous_lap_was_target_eligible"
    ]
    assert (
        row[
            "previous_lap_time_seconds"
        ]
        == 102.0
    )
    assert (
        row["eligible_laps_completed"]
        == 3
    )
    assert (
        row[
            "rolling_lap_time_median_3"
        ]
        == 101.0
    )
    assert (
        row[
            "rolling_lap_time_median_5"
        ]
        == 101.0
    )
    assert row[
        "rolling_lap_time_std_5"
    ] == pytest.approx(
        np.std(
            [
                100.0,
                101.0,
                102.0,
            ],
            ddof=0,
        )
    )
    assert row[
        "rolling_lap_time_trend_5"
    ] == pytest.approx(1.0)


def test_rolling_window_excludes_current_lap() -> None:
    """A target cannot enter its historical features."""
    session = make_session()
    session.laps.loc[
        3,
        "LapTimeSeconds",
    ] = 999.0

    result = build_session_decisions(
        session
    )
    row = decision_row(
        result,
        4,
    )
    label = label_row(
        result,
        4,
    )

    assert (
        row[
            "rolling_lap_time_median_3"
        ]
        == 101.0
    )
    assert (
        row[
            "previous_lap_time_seconds"
        ]
        == 102.0
    )
    assert (
        label[
            "lap_time_target_seconds"
        ]
        == 999.0
    )


def test_rolling_five_statistics_use_latest_eligible_laps() -> None:
    """Up to five eligible laps drive the window."""
    result = build_session_decisions(
        make_session()
    )
    row = decision_row(
        result,
        7,
    )

    assert (
        row["eligible_laps_completed"]
        == 4
    )
    assert (
        row[
            "rolling_lap_time_median_3"
        ]
        == 102.0
    )
    assert (
        row[
            "rolling_lap_time_median_5"
        ]
        == 101.5
    )
    assert row[
        "rolling_lap_time_std_5"
    ] == pytest.approx(
        np.std(
            [
                100.0,
                101.0,
                102.0,
                103.0,
            ],
            ddof=0,
        )
    )
    assert row[
        "rolling_lap_time_trend_5"
    ] == pytest.approx(1.0)


def test_immediate_features_are_null_after_ineligible_lap() -> None:
    """An excluded prior lap supplies no performance."""
    result = build_session_decisions(
        make_session()
    )
    row = decision_row(
        result,
        7,
    )

    assert not row[
        "previous_lap_was_target_eligible"
    ]
    assert pd.isna(
        row[
            "previous_lap_time_seconds"
        ]
    )
    assert pd.isna(
        row[
            "previous_sector1_time_seconds"
        ]
    )
    assert pd.isna(
        row[
            "previous_sector2_time_seconds"
        ]
    )
    assert pd.isna(
        row[
            "previous_sector3_time_seconds"
        ]
    )


def test_pit_now_label_is_separated_from_features() -> None:
    """The current pit marker appears only in labels."""
    result = build_session_decisions(
        make_session()
    )
    label = label_row(
        result,
        5,
    )

    assert (
        label["historical_action"]
        == "PIT_NOW"
    )
    assert label["did_pit"]
    assert (
        label["pit_event_id"]
        == "2024-01-R-VER-001"
    )
    assert not label[
        "is_lap_time_target_eligible"
    ]
    assert pd.isna(
        label[
            "lap_time_target_seconds"
        ]
    )
    assert (
        label[
            "lap_target_exclusion_count"
        ]
        == 1
    )
    assert (
        label[
            "lap_target_exclusion_reasons"
        ]
        == "PIT_IN_LAP"
    )


def test_stay_out_label_uses_current_lap_only_as_label() -> None:
    """No pit-in marker receives STAY_OUT."""
    result = build_session_decisions(
        make_session()
    )
    label = label_row(
        result,
        4,
    )

    assert (
        label["historical_action"]
        == "STAY_OUT"
    )
    assert not label["did_pit"]
    assert pd.isna(
        label["pit_event_id"]
    )
    assert label[
        "is_lap_time_target_eligible"
    ]
    assert (
        label[
            "lap_time_target_seconds"
        ]
        == 103.0
    )


def test_target_eligibility_does_not_change_decision_eligibility() -> None:
    """Current target quality is not a decision rule."""
    session = make_session()

    session.laps.loc[
        3,
        "IsEligible",
    ] = False
    session.laps.loc[
        3,
        "ExclusionReasonCount",
    ] = 1
    session.laps.loc[
        3,
        "ExclusionReasons",
    ] = "INACCURATE_LAP"

    result = build_session_decisions(
        session
    )
    row = decision_row(
        result,
        4,
    )
    label = label_row(
        result,
        4,
    )

    assert row[
        "is_decision_eligible"
    ]
    assert (
        row[
            "decision_exclusion_count"
        ]
        == 0
    )
    assert not label[
        "is_lap_time_target_eligible"
    ]
    assert pd.isna(
        label[
            "lap_time_target_seconds"
        ]
    )


def test_previous_pit_commitment_excludes_next_decision() -> None:
    """An in-lap closes the next decision."""
    result = build_session_decisions(
        make_session()
    )
    row = decision_row(
        result,
        6,
    )

    assert not row[
        "previous_lap_not_pit_commitment"
    ]
    assert row[
        "state_reconstruction_consistent"
    ]
    assert not row[
        "is_decision_eligible"
    ]
    assert (
        row[
            "decision_exclusion_count"
        ]
        == 1
    )
    assert (
        row[
            "decision_exclusion_reasons"
        ]
        == "PREVIOUS_LAP_PIT_COMMITMENT"
    )


def test_completed_pit_stop_and_new_stint_are_past_only() -> None:
    """A pit exit counts only for later decisions."""
    result = build_session_decisions(
        make_session()
    )
    row = decision_row(
        result,
        7,
    )

    assert (
        row["completed_pit_stops"]
        == 1
    )
    assert (
        row["current_compound"]
        == "HARD"
    )
    assert row["tyre_age_laps"] == 1
    assert (
        row["current_stint_number"]
        == 2
    )
    assert (
        row[
            "current_stint_laps_completed"
        ]
        == 1
    )
    assert row[
        "is_decision_eligible"
    ]


def test_state_reconstruction_conflict_is_explicit() -> None:
    """Current state is only a consistency check."""
    session = make_session()
    session.laps.loc[
        3,
        "Compound",
    ] = "HARD"

    result = build_session_decisions(
        session
    )
    row = decision_row(
        result,
        4,
    )

    assert (
        row["current_compound"]
        == "MEDIUM"
    )
    assert not row[
        "state_reconstruction_consistent"
    ]
    assert (
        "STATE_RECONSTRUCTION_CONFLICT"
        in row[
            "decision_exclusion_reasons"
        ]
    )


def test_exclusion_reasons_have_frozen_order() -> None:
    """Multiple failures retain contract order."""
    session = make_session()

    session.laps.loc[
        0:1,
        "Compound",
    ] = "INTERMEDIATE"
    session.laps.loc[
        0:1,
        "Stint",
    ] = pd.NA
    session.laps.loc[
        0,
        "TyreLife",
    ] = pd.NA
    session.laps.loc[
        0,
        "TrackStatus",
    ] = "4"
    session.laps.loc[
        0,
        "Position",
    ] = pd.NA
    session.laps.loc[
        1,
        "WeatherMatched",
    ] = False
    session.laps.loc[
        1,
        "Rainfall",
    ] = True

    result = build_session_decisions(
        session
    )
    row = decision_row(
        result,
        2,
    )

    expected = (
        "WEATHER_NOT_AVAILABLE_BY_DECISION|"
        "UNSUPPORTED_CURRENT_COMPOUND|"
        "INVALID_CURRENT_TYRE_AGE|"
        "MISSING_CURRENT_STINT|"
        "WET_AT_DECISION|"
        "PREVIOUS_LAP_NOT_GREEN|"
        "INSUFFICIENT_ELIGIBLE_HISTORY|"
        "MISSING_PREVIOUS_POSITION"
    )

    assert (
        row[
            "decision_exclusion_reasons"
        ]
        == expected
    )
    assert (
        row[
            "decision_exclusion_count"
        ]
        == 8
    )
    assert not row[
        "is_decision_eligible"
    ]


def test_future_weather_is_rejected_without_substitution() -> None:
    """Future weather makes a decision ineligible."""
    session = make_session()

    session.laps.loc[
        3,
        "WeatherObservationTime",
    ] = np.timedelta64(
        280,
        "s",
    )

    result = build_session_decisions(
        session
    )
    row = decision_row(
        result,
        4,
    )

    assert not row[
        "weather_available_by_decision"
    ]
    assert (
        "WEATHER_NOT_AVAILABLE_BY_DECISION"
        in row[
            "decision_exclusion_reasons"
        ]
    )


def test_builder_does_not_mutate_normalized_sources() -> None:
    """Construction leaves Phase 3 tables untouched."""
    session = make_session()

    original_laps = (
        session.laps.copy(
            deep=True
        )
    )
    original_stints = (
        session.stints.copy(
            deep=True
        )
    )
    original_pits = (
        session.pit_events.copy(
            deep=True
        )
    )

    build_session_decisions(
        session
    )

    pd.testing.assert_frame_equal(
        session.laps,
        original_laps,
    )
    pd.testing.assert_frame_equal(
        session.stints,
        original_stints,
    )
    pd.testing.assert_frame_equal(
        session.pit_events,
        original_pits,
    )


def test_duplicate_driver_lap_identity_is_rejected() -> None:
    """Decision IDs cannot be ambiguous."""
    session = make_session()
    session.laps.loc[
        6,
        "LapNumber",
    ] = 6

    with pytest.raises(
        DecisionConstructionError,
        match=(
            "duplicate driver-lap "
            "identities"
        ),
    ):
        build_session_decisions(
            session
        )


def test_pit_marker_without_event_is_rejected() -> None:
    """Every pit action must retain event lineage."""
    source = make_session()

    session = NormalizedProcessedSession(
        session_key=source.session_key,
        event_name=source.event_name,
        laps=source.laps,
        stints=source.stints,
        pit_events=(
            source.pit_events
            .iloc[0:0]
            .copy()
        ),
    )

    with pytest.raises(
        DecisionConstructionError,
        match=(
            "pit-in marker without"
        ),
    ):
        build_session_decisions(
            session
        )


def test_pit_event_without_marker_is_rejected() -> None:
    """Events cannot invent historical actions."""
    session = make_session()
    session.laps.loc[
        4,
        "PitInTime",
    ] = pd.NaT

    with pytest.raises(
        DecisionConstructionError,
        match=(
            "pit event without a "
            "pit-in marker"
        ),
    ):
        build_session_decisions(
            session
        )


def test_protected_evaluation_season_is_rejected() -> None:
    """The builder rejects 2025 immediately."""
    source = make_session()

    session = NormalizedProcessedSession(
        session_key=SessionKey(
            2025,
            1,
        ),
        event_name=source.event_name,
        laps=source.laps,
        stints=source.stints,
        pit_events=source.pit_events,
    )

    with pytest.raises(
        DecisionConstructionError,
        match=(
            "protected evaluation season"
        ),
    ):
        build_session_decisions(
            session
        )


def test_unsupported_development_season_is_rejected() -> None:
    """Only frozen development seasons work."""
    source = make_session()

    session = NormalizedProcessedSession(
        session_key=SessionKey(
            2021,
            1,
        ),
        event_name=source.event_name,
        laps=source.laps,
        stints=source.stints,
        pit_events=source.pit_events,
    )

    with pytest.raises(
        DecisionConstructionError,
        match=(
            "outside the development "
            "seasons"
        ),
    ):
        build_session_decisions(
            session
        )


def test_missing_required_source_column_is_rejected() -> None:
    """Source schema loss must fail closed."""
    session = make_session()

    session.laps.drop(
        columns=["Position"],
        inplace=True,
    )

    with pytest.raises(
        DecisionConstructionError,
        match=(
            "missing required columns"
        ),
    ):
        build_session_decisions(
            session
        )


def test_builder_requires_normalized_session() -> None:
    """Raw tables cannot bypass normalization."""
    with pytest.raises(
        TypeError,
        match=(
            "NormalizedProcessedSession"
        ),
    ):
        build_session_decisions(
            None  # type: ignore[arg-type]
        )


def test_decision_and_label_ids_form_one_to_one_join() -> None:
    """Every decision has one separated label."""
    result = build_session_decisions(
        make_session()
    )

    assert result.decision_rows[
        "decision_id"
    ].is_unique
    assert result.decision_labels[
        "decision_id"
    ].is_unique

    assert result.decision_rows[
        "decision_id"
    ].equals(
        result.decision_labels[
            "decision_id"
        ]
    )

    assert set(
        result.decision_rows[
            "dataset_contract_version"
        ]
    ) == {
        DATASET_CONTRACT_VERSION
    }

    assert set(
        result.decision_labels[
            "dataset_contract_version"
        ]
    ) == {
        DATASET_CONTRACT_VERSION
    }


def test_fixture_has_expected_eligibility_population() -> None:
    """The fixture has three eligible decisions."""
    result = build_session_decisions(
        make_session()
    )

    eligible = (
        result.decision_rows[
            "is_decision_eligible"
        ]
    )

    assert int(
        eligible.sum()
    ) == 3

    assert result.decision_rows.loc[
        eligible,
        "decision_lap",
    ].tolist() == [
        4,
        5,
        7,
    ]