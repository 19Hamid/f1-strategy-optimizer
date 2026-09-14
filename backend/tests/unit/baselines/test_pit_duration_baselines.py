"""Tests for training-only pit-duration baseline estimators."""

import pandas as pd
import pytest

from app.baselines import BaselineId
from app.baselines.pit_durations import (
    PIT_PREDICTION_COLUMNS,
    PitDurationBaselineError,
    fit_pit_duration_baseline,
)


def _training_rows() -> pd.DataFrame:
    """Build eligible observations plus excluded extreme evidence."""
    return pd.DataFrame(
        {
            "event_name": [
                "Bahrain GP",
                "Bahrain GP",
                "Bahrain GP",
                "Monaco GP",
                "Bahrain GP",
            ],
            "compound_before": [
                "SOFT",
                "SOFT",
                "MEDIUM",
                "HARD",
                "SOFT",
            ],
            "compound_after": [
                "HARD",
                "HARD",
                "HARD",
                "MEDIUM",
                "HARD",
            ],
            "is_pit_duration_target_eligible": [
                True,
                True,
                True,
                True,
                False,
            ],
            "pit_duration_target_seconds": [24.0, 26.0, 28.0, 20.0, 999.0],
        }
    )


def _prediction_rows() -> pd.DataFrame:
    """Build held-out inputs without target outcomes."""
    return pd.DataFrame(
        {
            "pit_event_id": ["p1", "p2", "p3", "p4"],
            "event_name": [
                "Bahrain GP",
                "Bahrain GP",
                "Different GP",
                "Unknown GP",
            ],
            "compound_before": ["SOFT", "HARD", "SOFT", "UNKNOWN"],
            "compound_after": ["HARD", "MEDIUM", "HARD", "UNKNOWN"],
        }
    )


def test_global_median_uses_only_eligible_training_events() -> None:
    """Exclude the ineligible extreme and predict every held-out event."""
    model = fit_pit_duration_baseline(
        BaselineId.PIT_GLOBAL_MEDIAN,
        _training_rows(),
    )
    result = model.predict(_prediction_rows())

    assert model.global_median == 25.0
    assert tuple(result.columns) == PIT_PREDICTION_COLUMNS
    assert result["prediction_seconds"].tolist() == [25.0] * 4
    assert result["prediction_source"].tolist() == ["global_median"] * 4
    assert result["prediction_available"].tolist() == [True] * 4


def test_event_median_uses_global_fallback() -> None:
    """Fit event values on training rows and cover unseen circuits."""
    model = fit_pit_duration_baseline(
        BaselineId.PIT_CIRCUIT_MEDIAN,
        _training_rows(),
    )
    result = model.predict(_prediction_rows())

    assert model.event_medians == {
        "Bahrain GP": 26.0,
        "Monaco GP": 20.0,
    }
    assert result["prediction_seconds"].tolist() == [
        26.0,
        26.0,
        25.0,
        25.0,
    ]
    assert result["prediction_source"].tolist() == [
        "event_median",
        "event_median",
        "global_median_fallback",
        "global_median_fallback",
    ]


def test_event_transition_uses_complete_fallback_hierarchy() -> None:
    """Apply event-transition, event, transition and global estimates."""
    model = fit_pit_duration_baseline(
        BaselineId.PIT_CIRCUIT_TRANSITION_MEDIAN,
        _training_rows(),
    )
    result = model.predict(_prediction_rows())

    assert model.event_transition_medians[
        ("Bahrain GP", "SOFT", "HARD")
    ] == 25.0
    assert model.transition_medians[("SOFT", "HARD")] == 25.0
    assert result["prediction_seconds"].tolist() == [
        25.0,
        26.0,
        25.0,
        25.0,
    ]
    assert result["prediction_source"].tolist() == [
        "event_transition_median",
        "event_median_fallback",
        "transition_median_fallback",
        "global_median_fallback",
    ]


@pytest.mark.parametrize(
    "baseline_id",
    [
        BaselineId.PIT_GLOBAL_MEDIAN,
        BaselineId.PIT_CIRCUIT_MEDIAN,
        BaselineId.PIT_CIRCUIT_TRANSITION_MEDIAN,
    ],
)
def test_prediction_never_requires_held_out_target(
    baseline_id: BaselineId,
) -> None:
    """Produce predictions while target outcomes remain hidden."""
    rows = _prediction_rows()
    assert "pit_duration_target_seconds" not in rows
    result = fit_pit_duration_baseline(
        baseline_id,
        _training_rows(),
    ).predict(rows)
    assert len(result) == len(rows)


def test_fit_rejects_empty_eligible_population() -> None:
    """Fail closed instead of fitting NaN duration estimates."""
    rows = _training_rows()
    rows["is_pit_duration_target_eligible"] = False
    with pytest.raises(PitDurationBaselineError, match="no eligible"):
        fit_pit_duration_baseline(
            BaselineId.PIT_GLOBAL_MEDIAN,
            rows,
        )


def test_fit_rejects_lap_time_identity() -> None:
    """Keep target families isolated."""
    with pytest.raises(PitDurationBaselineError, match="not a pit-duration"):
        fit_pit_duration_baseline(
            BaselineId.PREVIOUS_VALID_LAP,
            _training_rows(),
        )


def test_prediction_rejects_missing_grouping_columns() -> None:
    """Name missing dependencies before prediction."""
    rows = _prediction_rows().drop(columns=["compound_after"])
    model = fit_pit_duration_baseline(
        BaselineId.PIT_CIRCUIT_TRANSITION_MEDIAN,
        _training_rows(),
    )
    with pytest.raises(
        PitDurationBaselineError,
        match="compound_after",
    ):
        model.predict(rows)


def test_prediction_rejects_duplicate_event_identity() -> None:
    """Require exactly one result per canonical pit event."""
    rows = _prediction_rows()
    rows.loc[1, "pit_event_id"] = "p1"
    model = fit_pit_duration_baseline(
        BaselineId.PIT_GLOBAL_MEDIAN,
        _training_rows(),
    )
    with pytest.raises(PitDurationBaselineError, match="duplicate"):
        model.predict(rows)


def test_missing_prediction_group_falls_back_without_fake_text() -> None:
    """Treat null compound evidence as unavailable grouping evidence."""
    rows = _prediction_rows()
    rows.loc[0, "compound_before"] = None
    model = fit_pit_duration_baseline(
        BaselineId.PIT_CIRCUIT_TRANSITION_MEDIAN,
        _training_rows(),
    )
    result = model.predict(rows.iloc[[0]])
    assert result.loc[0, "prediction_seconds"] == 26.0
    assert result.loc[0, "prediction_source"] == "event_median_fallback"
