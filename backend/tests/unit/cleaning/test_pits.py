"""Tests for pit-event reconstruction."""

import pandas as pd
import pytest

from app.cleaning.pits import (
    PitEventReconstructionError,
    PitEventType,
    PitEventWarning,
    reconstruct_pit_events,
)


def make_laps() -> pd.DataFrame:
    """Create one valid matched pit event."""
    return pd.DataFrame(
        {
            "Season": [2024, 2024],
            "RoundNumber": [1, 1],
            "SessionType": ["R", "R"],
            "EventName": [
                "Bahrain Grand Prix",
                "Bahrain Grand Prix",
            ],
            "Driver": ["VER", "VER"],
            "Team": [
                "Red Bull Racing",
                "Red Bull Racing",
            ],
            "LapNumber": [1.0, 2.0],
            "Stint": [1.0, 2.0],
            "Compound": [
                "MEDIUM",
                "HARD",
            ],
            "TyreLife": [1.0, 1.0],
            "PitInTime": pd.to_timedelta(
                [
                    100,
                    None,
                ],
                unit="s",
            ),
            "PitOutTime": pd.to_timedelta(
                [
                    None,
                    120,
                ],
                unit="s",
            ),
            "TrackStatus": ["1", "1"],
        }
    )


def warning_values(
    warning_text: str,
) -> set[str]:
    """Split a pipe-delimited warning value."""
    if not warning_text:
        return set()

    return set(warning_text.split("|"))


def test_reconstructs_complete_duration_candidate() -> None:
    """A normal paired dry stop should be analysis-ready."""
    result = reconstruct_pit_events(
        make_laps()
    )

    assert result.input_lap_count == 2
    assert result.driver_count == 1
    assert result.pit_event_count == 1
    assert result.matched_event_count == 1
    assert result.entry_only_event_count == 0
    assert result.exit_only_event_count == 0
    assert result.complete_event_count == 1
    assert result.incomplete_event_count == 0
    assert result.duration_analysis_candidate_count == 1

    event = result.pit_events.iloc[0]

    assert (
        event["pit_event_id"]
        == "2024-01-R-VER-IN001-OUT002"
    )
    assert (
        event["event_type"]
        == PitEventType.MATCHED.value
    )
    assert event["season"] == 2024
    assert event["round_number"] == 1
    assert event["driver"] == "VER"
    assert event["pit_in_lap"] == 1
    assert event["pit_out_lap"] == 2
    assert event["stint_before"] == 1
    assert event["stint_after"] == 2
    assert event["compound_before"] == "MEDIUM"
    assert event["compound_after"] == "HARD"
    assert event["tyre_life_before"] == pytest.approx(1.0)
    assert event["tyre_life_after"] == pytest.approx(1.0)
    assert (
        event["pit_in_time_seconds"]
        == pytest.approx(100.0)
    )
    assert (
        event["pit_out_time_seconds"]
        == pytest.approx(120.0)
    )
    assert (
        event[
            "observed_pit_lane_duration_seconds"
        ]
        == pytest.approx(20.0)
    )
    assert bool(event["is_stint_change"])
    assert bool(event["is_compound_change"])
    assert bool(event["is_green_flag_pair"])
    assert bool(event["is_dry_compound_pair"])
    assert not bool(event["is_interrupted_duration"])
    assert bool(event["is_complete"])
    assert bool(
        event["is_duration_analysis_candidate"]
    )
    assert event["warning_count"] == 0
    assert event["warnings"] == ""


def test_flags_same_stint_pit_event() -> None:
    """A matched pit passage may not create a new stint."""
    laps = make_laps()
    laps.loc[1, "Stint"] = 1.0
    laps.loc[1, "Compound"] = "MEDIUM"
    laps.loc[1, "TyreLife"] = 2.0

    result = reconstruct_pit_events(laps)
    event = result.pit_events.iloc[0]
    warnings = warning_values(event["warnings"])

    assert bool(event["is_complete"])
    assert not bool(event["is_stint_change"])
    assert not bool(event["is_compound_change"])
    assert not bool(
        event["is_duration_analysis_candidate"]
    )
    assert PitEventWarning.NO_STINT_CHANGE.value in warnings


def test_flags_non_green_pair() -> None:
    """Non-green pit events must not enter duration analysis."""
    laps = make_laps()
    laps.loc[0, "TrackStatus"] = "12"

    result = reconstruct_pit_events(laps)
    event = result.pit_events.iloc[0]
    warnings = warning_values(event["warnings"])

    assert bool(event["is_complete"])
    assert not bool(event["is_green_flag_pair"])
    assert not bool(
        event["is_duration_analysis_candidate"]
    )
    assert PitEventWarning.NON_GREEN_ENTRY.value in warnings


def test_flags_interrupted_duration() -> None:
    """Restart-sized durations remain stored but ineligible."""
    laps = make_laps()
    laps["PitOutTime"] = pd.to_timedelta(
        [
            None,
            250,
        ],
        unit="s",
    )

    result = reconstruct_pit_events(laps)
    event = result.pit_events.iloc[0]
    warnings = warning_values(event["warnings"])

    assert (
        event[
            "observed_pit_lane_duration_seconds"
        ]
        == pytest.approx(150.0)
    )
    assert bool(event["is_complete"])
    assert bool(event["is_interrupted_duration"])
    assert not bool(
        event["is_duration_analysis_candidate"]
    )
    assert (
        PitEventWarning.INTERRUPTED_DURATION.value
        in warnings
    )


def test_preserves_entry_only_event() -> None:
    """A terminal pit entry must remain auditable."""
    laps = make_laps()
    laps["PitOutTime"] = pd.to_timedelta(
        [
            None,
            None,
        ],
        unit="s",
    )

    result = reconstruct_pit_events(laps)
    event = result.pit_events.iloc[0]
    warnings = warning_values(event["warnings"])

    assert result.pit_event_count == 1
    assert result.matched_event_count == 0
    assert result.entry_only_event_count == 1
    assert result.exit_only_event_count == 0
    assert result.complete_event_count == 0
    assert result.incomplete_event_count == 1
    assert (
        event["event_type"]
        == PitEventType.ENTRY_ONLY.value
    )
    assert event["pit_in_lap"] == 1
    assert pd.isna(event["pit_out_lap"])
    assert not bool(event["is_complete"])
    assert (
        PitEventWarning.ENTRY_ONLY.value
        in warnings
    )


def test_preserves_exit_only_event() -> None:
    """A pit-lane start or unpaired exit must remain visible."""
    laps = make_laps()
    laps["PitInTime"] = pd.to_timedelta(
        [
            None,
            None,
        ],
        unit="s",
    )

    result = reconstruct_pit_events(laps)
    event = result.pit_events.iloc[0]
    warnings = warning_values(event["warnings"])

    assert result.pit_event_count == 1
    assert result.matched_event_count == 0
    assert result.entry_only_event_count == 0
    assert result.exit_only_event_count == 1
    assert result.complete_event_count == 0
    assert result.incomplete_event_count == 1
    assert (
        event["event_type"]
        == PitEventType.EXIT_ONLY.value
    )
    assert pd.isna(event["pit_in_lap"])
    assert event["pit_out_lap"] == 2
    assert not bool(event["is_complete"])
    assert (
        PitEventWarning.EXIT_ONLY.value
        in warnings
    )


def test_handles_row_with_both_markers() -> None:
    """One lap may exit a stop and enter another stop."""
    laps = pd.DataFrame(
        {
            "Season": [2024, 2024, 2024],
            "RoundNumber": [1, 1, 1],
            "SessionType": ["R", "R", "R"],
            "EventName": [
                "Bahrain Grand Prix",
                "Bahrain Grand Prix",
                "Bahrain Grand Prix",
            ],
            "Driver": ["VER", "VER", "VER"],
            "Team": [
                "Red Bull Racing",
                "Red Bull Racing",
                "Red Bull Racing",
            ],
            "LapNumber": [1.0, 2.0, 3.0],
            "Stint": [1.0, 2.0, 3.0],
            "Compound": [
                "MEDIUM",
                "HARD",
                "SOFT",
            ],
            "TyreLife": [1.0, 1.0, 1.0],
            "PitInTime": pd.to_timedelta(
                [
                    100,
                    180,
                    None,
                ],
                unit="s",
            ),
            "PitOutTime": pd.to_timedelta(
                [
                    None,
                    120,
                    200,
                ],
                unit="s",
            ),
            "TrackStatus": ["1", "1", "1"],
        }
    )

    result = reconstruct_pit_events(laps)

    assert result.pit_event_count == 2
    assert result.matched_event_count == 2
    assert result.complete_event_count == 2
    assert result.duration_analysis_candidate_count == 2

    assert result.pit_events[
        "pit_event_id"
    ].tolist() == [
        "2024-01-R-VER-IN001-OUT002",
        "2024-01-R-VER-IN002-OUT003",
    ]


def test_flags_unsupported_compound() -> None:
    """A placeholder compound must block duration analysis."""
    laps = make_laps()
    laps.loc[1, "Compound"] = "NONE"

    result = reconstruct_pit_events(laps)
    event = result.pit_events.iloc[0]
    warnings = warning_values(event["warnings"])

    assert bool(event["is_complete"])
    assert not bool(event["is_dry_compound_pair"])
    assert not bool(
        event["is_duration_analysis_candidate"]
    )
    assert (
        PitEventWarning.UNSUPPORTED_COMPOUND_AFTER.value
        in warnings
    )


def test_flags_missing_compound() -> None:
    """A missing compound must remain distinguishable."""
    laps = make_laps()
    laps.loc[1, "Compound"] = None

    result = reconstruct_pit_events(laps)
    event = result.pit_events.iloc[0]
    warnings = warning_values(event["warnings"])

    assert event["compound_after"] is None
    assert not bool(event["is_dry_compound_pair"])
    assert (
        PitEventWarning.MISSING_COMPOUND_AFTER.value
        in warnings
    )


def test_rejects_non_positive_duration() -> None:
    """A reversed marker duration cannot be complete."""
    laps = make_laps()
    laps["PitOutTime"] = pd.to_timedelta(
        [
            None,
            90,
        ],
        unit="s",
    )

    result = reconstruct_pit_events(laps)
    event = result.pit_events.iloc[0]
    warnings = warning_values(event["warnings"])

    assert (
        event[
            "observed_pit_lane_duration_seconds"
        ]
        == pytest.approx(-10.0)
    )
    assert not bool(event["is_complete"])
    assert result.complete_event_count == 0
    assert result.incomplete_event_count == 1
    assert (
        PitEventWarning.NON_POSITIVE_DURATION.value
        in warnings
    )


def test_flags_non_adjacent_laps() -> None:
    """A marker pair with a lap gap cannot be complete."""
    laps = make_laps()
    laps.loc[1, "LapNumber"] = 3.0

    result = reconstruct_pit_events(laps)
    event = result.pit_events.iloc[0]
    warnings = warning_values(event["warnings"])

    assert event["pit_in_lap"] == 1
    assert event["pit_out_lap"] == 3
    assert not bool(event["is_complete"])
    assert (
        PitEventWarning.NON_ADJACENT_LAPS.value
        in warnings
    )


def test_rejects_duplicate_lap_identity() -> None:
    """Duplicate driver-lap identities are ambiguous."""
    laps = make_laps()
    laps.loc[1, "LapNumber"] = 1.0

    with pytest.raises(
        PitEventReconstructionError,
        match="duplicate",
    ):
        reconstruct_pit_events(laps)


def test_accepts_empty_typed_table() -> None:
    """A typed empty table should produce an empty result."""
    laps = make_laps().iloc[0:0].copy()

    result = reconstruct_pit_events(laps)

    assert result.input_lap_count == 0
    assert result.driver_count == 0
    assert result.pit_event_count == 0
    assert result.matched_event_count == 0
    assert result.entry_only_event_count == 0
    assert result.exit_only_event_count == 0
    assert result.complete_event_count == 0
    assert result.incomplete_event_count == 0
    assert result.duration_analysis_candidate_count == 0
    assert result.pit_events.empty
    assert all(
        count == 0
        for count in result.warning_counts.values()
    )


def test_is_deterministic_and_preserves_input() -> None:
    """Reconstruction must not modify raw lap records."""
    laps = make_laps()
    original = laps.copy(deep=True)

    first = reconstruct_pit_events(laps)
    second = reconstruct_pit_events(laps)

    pd.testing.assert_frame_equal(
        first.pit_events,
        second.pit_events,
    )
    pd.testing.assert_frame_equal(
        laps,
        original,
    )

    assert first.input_lap_count == second.input_lap_count
    assert first.driver_count == second.driver_count
    assert first.pit_event_count == second.pit_event_count
    assert first.warning_counts == second.warning_counts