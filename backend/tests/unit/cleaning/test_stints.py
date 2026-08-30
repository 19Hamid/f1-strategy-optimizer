"""Tests for tyre-stint reconstruction."""

import pandas as pd
import pytest

from app.cleaning.stints import (
    StintReconstructionError,
    StintWarning,
    reconstruct_stints,
)


def make_laps() -> pd.DataFrame:
    """Create two valid consecutive tyre stints."""
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
                    200,
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
        }
    )


def warning_values(
    warning_text: str,
) -> set[str]:
    """Split a pipe-delimited warning value."""
    if not warning_text:
        return set()

    return set(warning_text.split("|"))


def test_reconstructs_complete_ordered_stints() -> None:
    """Valid lap records should produce complete stints."""
    result = reconstruct_stints(
        make_laps()
    )

    assert result.input_lap_count == 4
    assert result.driver_count == 1
    assert result.stint_count == 2
    assert result.complete_stint_count == 2
    assert result.incomplete_stint_count == 0
    assert len(result.stints) == 2

    first = result.stints.iloc[0]
    second = result.stints.iloc[1]

    assert first["season"] == 2024
    assert first["round_number"] == 1
    assert first["session_type"] == "R"
    assert first["driver"] == "VER"
    assert first["stint_number"] == 1
    assert first["compound"] == "MEDIUM"
    assert first["start_lap"] == 1
    assert first["end_lap"] == 2
    assert first["recorded_laps"] == 2
    assert first["start_tyre_life"] == pytest.approx(1.0)
    assert first["end_tyre_life"] == pytest.approx(2.0)
    assert bool(first["is_first_stint"])
    assert not bool(first["is_last_stint"])
    assert bool(first["boundary_before_verified"])
    assert bool(first["boundary_after_verified"])
    assert bool(first["is_complete"])
    assert first["warning_count"] == 0
    assert first["warnings"] == ""

    assert second["stint_number"] == 2
    assert second["compound"] == "HARD"
    assert second["start_lap"] == 3
    assert second["end_lap"] == 4
    assert not bool(second["is_first_stint"])
    assert bool(second["is_last_stint"])
    assert bool(second["boundary_before_verified"])
    assert bool(second["boundary_after_verified"])
    assert bool(second["is_complete"])

    assert all(
        count == 0
        for count in result.warning_counts.values()
    )


def test_accepts_same_compound_pit_stop() -> None:
    """A driver may legally start a new stint on the same compound."""
    laps = make_laps()
    laps["Compound"] = "MEDIUM"

    result = reconstruct_stints(laps)

    assert result.stint_count == 2
    assert result.complete_stint_count == 2
    assert result.incomplete_stint_count == 0
    assert result.stints["compound"].tolist() == [
        "MEDIUM",
        "MEDIUM",
    ]


def test_flags_boundary_without_pit_evidence() -> None:
    """Missing pit timestamps must affect both adjacent stints."""
    laps = make_laps()
    laps.loc[1, "PitInTime"] = pd.NaT
    laps.loc[2, "PitOutTime"] = pd.NaT

    result = reconstruct_stints(laps)

    first = result.stints.iloc[0]
    second = result.stints.iloc[1]

    assert not bool(first["boundary_after_verified"])
    assert not bool(second["boundary_before_verified"])
    assert result.complete_stint_count == 0
    assert result.incomplete_stint_count == 2

    assert (
        StintWarning.MISSING_PIT_EVIDENCE_AFTER.value
        in warning_values(first["warnings"])
    )
    assert (
        StintWarning.MISSING_PIT_EVIDENCE_BEFORE.value
        in warning_values(second["warnings"])
    )

    assert (
        result.warning_counts[
            StintWarning.MISSING_PIT_EVIDENCE_AFTER.value
        ]
        == 1
    )
    assert (
        result.warning_counts[
            StintWarning.MISSING_PIT_EVIDENCE_BEFORE.value
        ]
        == 1
    )


def test_flags_missing_compound_and_tyre_life() -> None:
    """Missing stint attributes must remain visible."""
    laps = make_laps()
    laps.loc[2:, "Compound"] = None
    laps.loc[2:, "TyreLife"] = float("nan")

    result = reconstruct_stints(laps)
    second = result.stints.iloc[1]
    warnings = warning_values(second["warnings"])

    assert second["compound"] is None
    assert pd.isna(second["start_tyre_life"])
    assert pd.isna(second["end_tyre_life"])
    assert not bool(second["is_complete"])
    assert StintWarning.MISSING_COMPOUND.value in warnings
    assert StintWarning.MISSING_TYRE_LIFE.value in warnings


def test_flags_unsupported_compound() -> None:
    """A non-tyre placeholder must not form a complete stint."""
    laps = make_laps()
    laps.loc[2:, "Compound"] = "NONE"

    result = reconstruct_stints(laps)
    second = result.stints.iloc[1]
    warnings = warning_values(second["warnings"])

    assert second["compound"] == "NONE"
    assert not bool(second["is_complete"])
    assert (
        StintWarning.UNSUPPORTED_COMPOUND.value
        in warnings
    )
    assert (
        result.warning_counts[
            StintWarning.UNSUPPORTED_COMPOUND.value
        ]
        == 1
    )


def test_flags_multiple_compounds_inside_stint() -> None:
    """A single stint ID must not silently mix compounds."""
    laps = make_laps()
    laps.loc[1, "Compound"] = "SOFT"

    result = reconstruct_stints(laps)
    first = result.stints.iloc[0]
    warnings = warning_values(first["warnings"])

    assert first["compound"] == "MEDIUM|SOFT"
    assert not bool(first["is_complete"])
    assert (
        StintWarning.MULTIPLE_COMPOUNDS.value
        in warnings
    )


def test_flags_decreasing_tyre_life() -> None:
    """Tyre life must not decrease inside a continuous stint."""
    laps = make_laps()
    laps.loc[0, "TyreLife"] = 3.0
    laps.loc[1, "TyreLife"] = 2.0

    result = reconstruct_stints(laps)
    first = result.stints.iloc[0]
    warnings = warning_values(first["warnings"])

    assert (
        StintWarning.TYRE_LIFE_DECREASE.value
        in warnings
    )
    assert (
        StintWarning.TYRE_LIFE_STEP_MISMATCH.value
        in warnings
    )
    assert not bool(first["is_complete"])


def test_flags_lap_gap_and_tyre_step_mismatch() -> None:
    """Missing lap numbers must remain auditable."""
    laps = make_laps()
    laps["LapNumber"] = [
        1.0,
        3.0,
        4.0,
        5.0,
    ]

    result = reconstruct_stints(laps)
    first = result.stints.iloc[0]
    warnings = warning_values(first["warnings"])

    assert first["start_lap"] == 1
    assert first["end_lap"] == 3
    assert first["recorded_laps"] == 2
    assert StintWarning.LAP_NUMBER_GAP.value in warnings
    assert (
        StintWarning.TYRE_LIFE_STEP_MISMATCH.value
        in warnings
    )


def test_flags_disjoint_and_non_sequential_stints() -> None:
    """Reused or decreasing stint IDs must not be merged."""
    laps = make_laps().iloc[:3].copy()

    laps["Stint"] = [
        1.0,
        2.0,
        1.0,
    ]
    laps["Compound"] = [
        "MEDIUM",
        "HARD",
        "MEDIUM",
    ]
    laps["TyreLife"] = [
        1.0,
        1.0,
        2.0,
    ]
    laps["PitInTime"] = pd.to_timedelta(
        [
            100,
            200,
            None,
        ],
        unit="s",
    )
    laps["PitOutTime"] = pd.to_timedelta(
        [
            None,
            110,
            210,
        ],
        unit="s",
    )

    result = reconstruct_stints(laps)

    assert result.stint_count == 3
    assert (
        result.warning_counts[
            StintWarning.DISJOINT_STINT.value
        ]
        == 2
    )
    assert (
        result.warning_counts[
            StintWarning.NON_SEQUENTIAL_STINT.value
        ]
        == 1
    )

    final_warnings = warning_values(
        result.stints.iloc[2]["warnings"]
    )

    assert StintWarning.DISJOINT_STINT.value in (
        final_warnings
    )
    assert (
        StintWarning.NON_SEQUENTIAL_STINT.value
        in final_warnings
    )


def test_rejects_duplicate_lap_identity() -> None:
    """Duplicate driver-lap identities are ambiguous."""
    laps = make_laps()
    laps.loc[1, "LapNumber"] = 1.0

    with pytest.raises(
        StintReconstructionError,
        match="duplicate",
    ):
        reconstruct_stints(laps)


def test_rejects_missing_required_column() -> None:
    """Every reconstruction input must satisfy the contract."""
    laps = make_laps().drop(
        columns="Compound"
    )

    with pytest.raises(
        StintReconstructionError,
        match="Compound",
    ):
        reconstruct_stints(laps)


def test_accepts_empty_typed_table() -> None:
    """A typed empty input should produce an empty result."""
    laps = make_laps().iloc[0:0].copy()

    result = reconstruct_stints(laps)

    assert result.input_lap_count == 0
    assert result.driver_count == 0
    assert result.stint_count == 0
    assert result.complete_stint_count == 0
    assert result.incomplete_stint_count == 0
    assert result.stints.empty
    assert all(
        count == 0
        for count in result.warning_counts.values()
    )


def test_is_deterministic_and_preserves_input() -> None:
    """Reconstruction must not modify raw lap records."""
    laps = make_laps()
    original = laps.copy(deep=True)

    first = reconstruct_stints(laps)
    second = reconstruct_stints(laps)

    pd.testing.assert_frame_equal(
        first.stints,
        second.stints,
    )
    pd.testing.assert_frame_equal(
        laps,
        original,
    )

    assert first.input_lap_count == second.input_lap_count
    assert first.driver_count == second.driver_count
    assert first.stint_count == second.stint_count
    assert first.warning_counts == second.warning_counts