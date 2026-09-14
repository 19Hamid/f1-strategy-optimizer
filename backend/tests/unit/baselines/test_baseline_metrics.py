"""Tests for honest baseline regression metrics and coverage."""

import math

import numpy as np
import pandas as pd
import pytest

from app.baselines.metrics import (
    SCORED_ROW_COLUMNS,
    BaselineMetricError,
    regression_metrics,
    score_prediction_frame,
)


def test_regression_metrics_match_interpretable_seconds() -> None:
    """Calculate every frozen aggregate from signed residuals."""
    metrics = regression_metrics(
        np.array([10.0, 20.0, 30.0]),
        np.array([12.0, 18.0, 33.0]),
    )
    assert metrics.rows == 3
    assert metrics.mean_absolute_error_seconds == pytest.approx(7 / 3)
    assert metrics.root_mean_squared_error_seconds == pytest.approx(
        math.sqrt(17 / 3)
    )
    assert metrics.median_absolute_error_seconds == 2.0
    assert metrics.p90_absolute_error_seconds == pytest.approx(2.8)
    assert metrics.mean_signed_error_seconds == 1.0


def test_scoring_preserves_unavailable_rows_in_coverage() -> None:
    """Do not improve error by silently forgetting missing predictions."""
    targets = pd.DataFrame(
        {"decision_id": ["d1", "d2", "d3"], "target": [10.0, 20.0, 30.0]}
    )
    predictions = pd.DataFrame(
        {
            "decision_id": ["d1", "d2", "d3"],
            "prediction_seconds": [12.0, None, 27.0],
            "prediction_available": [True, False, True],
            "prediction_source": ["primary", "unavailable", "fallback"],
        }
    )
    result = score_prediction_frame(
        targets=targets,
        predictions=predictions,
        identity_column="decision_id",
        target_column="target",
    )

    assert result.coverage.eligible_targets == 3
    assert result.coverage.available_predictions == 2
    assert result.coverage.scored_predictions == 2
    assert result.coverage.unavailable_predictions == 1
    assert result.coverage.coverage_rate == pytest.approx(2 / 3)
    assert tuple(result.rows.columns) == SCORED_ROW_COLUMNS
    assert result.rows["row_id"].tolist() == ["d1", "d3"]
    assert result.metrics.mean_absolute_error_seconds == 2.5


def test_missing_prediction_identity_counts_as_unavailable() -> None:
    """Account for an eligible target even when no prediction row exists."""
    targets = pd.DataFrame({"id": ["a", "b"], "target": [1.0, 2.0]})
    predictions = pd.DataFrame(
        {
            "id": ["a"],
            "prediction_seconds": [1.5],
            "prediction_available": [True],
            "prediction_source": ["primary"],
        }
    )
    result = score_prediction_frame(
        targets=targets,
        predictions=predictions,
        identity_column="id",
        target_column="target",
    )
    assert result.coverage.eligible_targets == 2
    assert result.coverage.scored_predictions == 1
    assert result.coverage.unavailable_predictions == 1


def test_scoring_rejects_availability_value_disagreement() -> None:
    """Fail when metadata claims a missing prediction is usable."""
    targets = pd.DataFrame({"id": ["a"], "target": [1.0]})
    predictions = pd.DataFrame(
        {
            "id": ["a"],
            "prediction_seconds": [None],
            "prediction_available": [True],
            "prediction_source": ["primary"],
        }
    )
    with pytest.raises(BaselineMetricError, match="availability"):
        score_prediction_frame(
            targets=targets,
            predictions=predictions,
            identity_column="id",
            target_column="target",
        )


def test_scoring_rejects_predictions_outside_target_population() -> None:
    """Prevent cross-population rows from entering aggregate scores."""
    targets = pd.DataFrame({"id": ["a"], "target": [1.0]})
    predictions = pd.DataFrame(
        {
            "id": ["outside"],
            "prediction_seconds": [1.0],
            "prediction_available": [True],
            "prediction_source": ["primary"],
        }
    )
    with pytest.raises(BaselineMetricError, match="outside eligible"):
        score_prediction_frame(
            targets=targets,
            predictions=predictions,
            identity_column="id",
            target_column="target",
        )


@pytest.mark.parametrize(
    ("targets", "predictions", "message"),
    [
        ([1.0], [1.0, 2.0], "equal lengths"),
        ([], [], "at least one"),
        ([1.0, np.nan], [1.0, 2.0], "finite"),
    ],
)
def test_metrics_reject_invalid_vectors(
    targets: list[float],
    predictions: list[float],
    message: str,
) -> None:
    """Reject incomplete or contradictory metric inputs."""
    with pytest.raises(BaselineMetricError, match=message):
        regression_metrics(np.array(targets), np.array(predictions))


def test_scoring_rejects_duplicate_identity() -> None:
    """Require one target and at most one prediction per row."""
    targets = pd.DataFrame({"id": ["a", "a"], "target": [1.0, 1.0]})
    predictions = pd.DataFrame(
        {
            "id": ["a"],
            "prediction_seconds": [1.0],
            "prediction_available": [True],
            "prediction_source": ["primary"],
        }
    )
    with pytest.raises(BaselineMetricError, match="duplicate"):
        score_prediction_frame(
            targets=targets,
            predictions=predictions,
            identity_column="id",
            target_column="target",
        )
