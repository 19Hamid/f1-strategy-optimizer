"""Tests for leakage-safe lap-time baseline estimators."""

import math

import pandas as pd
import pytest

from app.baselines import BaselineId
from app.baselines.lap_times import (
    PREDICTION_COLUMNS,
    LapTimeBaselineError,
    fit_lap_time_baseline,
)


def _prediction_rows() -> pd.DataFrame:
    """Build decision-time inputs without any target column."""
    return pd.DataFrame(
        {
            "decision_id": ["d1", "d2", "d3"],
            "previous_lap_was_target_eligible": [True, True, False],
            "previous_lap_time_seconds": [90.0, 92.0, 94.0],
            "rolling_lap_time_median_3": [89.5, None, None],
            "rolling_lap_time_trend_5": [0.4, None, 0.2],
            "event_name": ["Bahrain GP", "Bahrain GP", "New GP"],
            "current_compound": ["MEDIUM", "HARD", "UNKNOWN"],
        }
    )


def _training_rows() -> pd.DataFrame:
    """Build eligible and deliberately excluded aggregate sources."""
    return pd.DataFrame(
        {
            "event_name": [
                "Bahrain GP",
                "Bahrain GP",
                "Bahrain GP",
                "Monaco GP",
                "Bahrain GP",
            ],
            "current_compound": [
                "MEDIUM",
                "MEDIUM",
                "HARD",
                "SOFT",
                "MEDIUM",
            ],
            "is_decision_eligible": [True, True, True, True, False],
            "is_lap_time_target_eligible": [True, True, True, True, True],
            "lap_time_target_seconds": [90.0, 92.0, 95.0, 80.0, 999.0],
        }
    )


def test_previous_lap_predicts_only_from_eligible_past_lap() -> None:
    """Never use a previous lap explicitly marked target-ineligible."""
    result = fit_lap_time_baseline(
        BaselineId.PREVIOUS_VALID_LAP
    ).predict(_prediction_rows())

    assert tuple(result.columns) == PREDICTION_COLUMNS
    assert result["prediction_seconds"].tolist()[:2] == [90.0, 92.0]
    assert math.isnan(result.loc[2, "prediction_seconds"])
    assert result["prediction_source"].tolist() == [
        "previous_valid_lap",
        "previous_valid_lap",
        "unavailable",
    ]
    assert result["prediction_available"].tolist() == [True, True, False]


def test_rolling_median_uses_previous_lap_fallback() -> None:
    """Apply the frozen fallback without reading validation targets."""
    result = fit_lap_time_baseline(
        BaselineId.ROLLING_MEDIAN_3
    ).predict(_prediction_rows())

    assert result["prediction_seconds"].tolist()[:2] == [89.5, 92.0]
    assert result["prediction_source"].tolist() == [
        "rolling_median_3",
        "previous_valid_lap_fallback",
        "unavailable",
    ]


def test_stint_trend_advances_one_step_then_falls_back() -> None:
    """Use past-only slope and deterministic rolling/previous fallbacks."""
    result = fit_lap_time_baseline(
        BaselineId.STINT_LINEAR_TREND
    ).predict(_prediction_rows())

    assert result["prediction_seconds"].tolist()[:2] == [90.4, 92.0]
    assert result["prediction_source"].tolist() == [
        "stint_linear_trend",
        "previous_valid_lap_fallback",
        "unavailable",
    ]


def test_historical_medians_fit_only_eligible_training_intersection() -> None:
    """Exclude an ineligible 999-second value from every fitted median."""
    model = fit_lap_time_baseline(
        BaselineId.CIRCUIT_COMPOUND_MEDIAN,
        _training_rows(),
    )

    assert model.event_compound_medians == {
        ("Bahrain GP", "HARD"): 95.0,
        ("Bahrain GP", "MEDIUM"): 91.0,
        ("Monaco GP", "SOFT"): 80.0,
    }
    assert model.compound_medians == {
        "HARD": 95.0,
        "MEDIUM": 91.0,
        "SOFT": 80.0,
    }
    assert model.global_median == 91.0


def test_historical_prediction_uses_frozen_fallback_hierarchy() -> None:
    """Use event-compound, compound and global estimates in order."""
    model = fit_lap_time_baseline(
        BaselineId.CIRCUIT_COMPOUND_MEDIAN,
        _training_rows(),
    )
    rows = _prediction_rows()
    rows.loc[1, "event_name"] = "Different GP"
    result = model.predict(rows)

    assert result["prediction_seconds"].tolist() == [91.0, 95.0, 91.0]
    assert result["prediction_source"].tolist() == [
        "event_compound_median",
        "compound_median_fallback",
        "global_median_fallback",
    ]


def test_prediction_does_not_require_or_read_target_column() -> None:
    """Keep held-out outcomes absent while producing predictions."""
    rows = _prediction_rows()
    assert "lap_time_target_seconds" not in rows
    result = fit_lap_time_baseline(
        BaselineId.CIRCUIT_COMPOUND_MEDIAN,
        _training_rows(),
    ).predict(rows)
    assert len(result) == len(rows)


@pytest.mark.parametrize(
    "baseline_id",
    [
        BaselineId.PREVIOUS_VALID_LAP,
        BaselineId.ROLLING_MEDIAN_3,
        BaselineId.STINT_LINEAR_TREND,
    ],
)
def test_online_baselines_require_no_fit_data(
    baseline_id: BaselineId,
) -> None:
    """Decision-local baselines carry no learned validation information."""
    model = fit_lap_time_baseline(baseline_id)
    assert model.global_median is None
    assert model.event_compound_medians == {}
    assert model.compound_medians == {}


def test_historical_baseline_requires_explicit_training_rows() -> None:
    """Prevent accidental fit against prediction or validation rows."""
    with pytest.raises(
        LapTimeBaselineError,
        match="requires explicit training rows",
    ):
        fit_lap_time_baseline(BaselineId.CIRCUIT_COMPOUND_MEDIAN)


def test_historical_fit_rejects_empty_eligible_population() -> None:
    """Fail instead of emitting a NaN aggregate."""
    rows = _training_rows()
    rows["is_decision_eligible"] = False
    with pytest.raises(LapTimeBaselineError, match="no eligible"):
        fit_lap_time_baseline(
            BaselineId.CIRCUIT_COMPOUND_MEDIAN,
            rows,
        )


def test_prediction_rejects_missing_columns() -> None:
    """Name every missing decision-time dependency."""
    rows = _prediction_rows().drop(columns=["previous_lap_time_seconds"])
    with pytest.raises(
        LapTimeBaselineError,
        match="previous_lap_time_seconds",
    ):
        fit_lap_time_baseline(
            BaselineId.PREVIOUS_VALID_LAP
        ).predict(rows)


def test_prediction_rejects_duplicate_decision_identity() -> None:
    """Keep exactly one prediction per canonical decision."""
    rows = _prediction_rows()
    rows.loc[1, "decision_id"] = "d1"
    with pytest.raises(LapTimeBaselineError, match="duplicate"):
        fit_lap_time_baseline(
            BaselineId.PREVIOUS_VALID_LAP
        ).predict(rows)


def test_pit_baseline_identity_is_rejected() -> None:
    """Keep lap and pit-duration tasks separated."""
    with pytest.raises(LapTimeBaselineError, match="not a lap-time"):
        fit_lap_time_baseline(BaselineId.PIT_GLOBAL_MEDIAN)
