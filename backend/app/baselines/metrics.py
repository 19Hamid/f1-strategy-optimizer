"""Regression metrics and coverage accounting for Phase 5."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

SCORED_ROW_COLUMNS: Final = (
    "row_id",
    "target_seconds",
    "prediction_seconds",
    "signed_error_seconds",
    "absolute_error_seconds",
    "squared_error_seconds",
    "prediction_source",
)


class BaselineMetricError(ValueError):
    """Raised when predictions cannot be scored honestly."""


@dataclass(frozen=True, slots=True)
class RegressionMetrics:
    """Frozen aggregate regression metrics in seconds."""

    rows: int
    mean_absolute_error_seconds: float
    root_mean_squared_error_seconds: float
    median_absolute_error_seconds: float
    p90_absolute_error_seconds: float
    mean_signed_error_seconds: float


@dataclass(frozen=True, slots=True)
class PredictionCoverage:
    """Account for every eligible target and unavailable prediction."""

    eligible_targets: int
    available_predictions: int
    scored_predictions: int

    @property
    def unavailable_predictions(self) -> int:
        """Return eligible targets without an available prediction."""
        return self.eligible_targets - self.available_predictions

    @property
    def coverage_rate(self) -> float:
        """Return scored coverage over the complete eligible population."""
        if self.eligible_targets == 0:
            return 0.0
        return self.scored_predictions / self.eligible_targets


@dataclass(frozen=True, slots=True)
class ScoredPredictions:
    """Hold aggregate metrics, coverage and row-level residual evidence."""

    metrics: RegressionMetrics
    coverage: PredictionCoverage
    rows: pd.DataFrame


def regression_metrics(
    targets: np.ndarray | pd.Series,
    predictions: np.ndarray | pd.Series,
) -> RegressionMetrics:
    """Calculate the frozen Phase 5 metric set."""
    actual = _finite_vector(targets, name="targets")
    predicted = _finite_vector(predictions, name="predictions")
    if len(actual) != len(predicted):
        raise BaselineMetricError(
            "targets and predictions must have equal lengths"
        )
    if len(actual) == 0:
        raise BaselineMetricError("metrics require at least one scored row")

    signed = predicted - actual
    absolute = np.abs(signed)
    return RegressionMetrics(
        rows=len(actual),
        mean_absolute_error_seconds=float(np.mean(absolute)),
        root_mean_squared_error_seconds=float(
            np.sqrt(np.mean(np.square(signed)))
        ),
        median_absolute_error_seconds=float(np.median(absolute)),
        p90_absolute_error_seconds=float(
            np.quantile(absolute, 0.9, method="linear")
        ),
        mean_signed_error_seconds=float(np.mean(signed)),
    )


def score_prediction_frame(
    *,
    targets: pd.DataFrame,
    predictions: pd.DataFrame,
    identity_column: str,
    target_column: str,
) -> ScoredPredictions:
    """Score available predictions while preserving complete coverage."""
    _require_frame(targets, source="targets")
    _require_frame(predictions, source="predictions")
    _require_columns(
        targets,
        (identity_column, target_column),
        source="targets",
    )
    _require_columns(
        predictions,
        (
            identity_column,
            "prediction_seconds",
            "prediction_available",
            "prediction_source",
        ),
        source="predictions",
    )
    _require_unique(targets, identity_column, source="targets")
    _require_unique(predictions, identity_column, source="predictions")

    target_ids = set(targets[identity_column].astype("string"))
    prediction_ids = set(predictions[identity_column].astype("string"))
    unexpected = sorted(prediction_ids.difference(target_ids))
    if unexpected:
        raise BaselineMetricError(
            "predictions contain identities outside eligible targets: "
            + ", ".join(unexpected[:5])
        )

    joined = targets.loc[:, [identity_column, target_column]].merge(
        predictions.loc[
            :,
            [
                identity_column,
                "prediction_seconds",
                "prediction_available",
                "prediction_source",
            ],
        ],
        on=identity_column,
        how="left",
        validate="one_to_one",
    )
    target_values = pd.to_numeric(joined[target_column], errors="coerce")
    if (
        target_values.isna().any()
        or (~np.isfinite(target_values)).any()
        or target_values.le(0).any()
    ):
        raise BaselineMetricError(
            "eligible targets must be finite positive seconds"
        )

    declared_available = (
        joined["prediction_available"].eq(True).fillna(False)
    )
    prediction_values = pd.to_numeric(
        joined["prediction_seconds"],
        errors="coerce",
    )
    numeric_available = (
        prediction_values.notna()
        & np.isfinite(prediction_values)
        & prediction_values.gt(0)
    )
    inconsistent = declared_available.ne(numeric_available)
    if inconsistent.any():
        raise BaselineMetricError(
            "prediction availability disagrees with prediction values"
        )

    scored = joined.loc[numeric_available].copy()
    if scored.empty:
        raise BaselineMetricError(
            "baseline produced no scorable predictions"
        )
    actual = target_values.loc[numeric_available].to_numpy(dtype=float)
    predicted = prediction_values.loc[numeric_available].to_numpy(dtype=float)
    signed = predicted - actual
    scored_rows = pd.DataFrame(
        {
            "row_id": scored[identity_column].astype("string").array,
            "target_seconds": actual,
            "prediction_seconds": predicted,
            "signed_error_seconds": signed,
            "absolute_error_seconds": np.abs(signed),
            "squared_error_seconds": np.square(signed),
            "prediction_source": scored["prediction_source"]
            .astype("string")
            .array,
        },
        columns=SCORED_ROW_COLUMNS,
    )
    coverage = PredictionCoverage(
        eligible_targets=len(targets),
        available_predictions=int(declared_available.sum()),
        scored_predictions=len(scored_rows),
    )
    return ScoredPredictions(
        metrics=regression_metrics(actual, predicted),
        coverage=coverage,
        rows=scored_rows,
    )


def _finite_vector(
    values: np.ndarray | pd.Series,
    *,
    name: str,
) -> np.ndarray:
    """Return one finite one-dimensional float vector."""
    array = np.asarray(values, dtype=float)
    if array.ndim != 1:
        raise BaselineMetricError(f"{name} must be one-dimensional")
    if not np.isfinite(array).all():
        raise BaselineMetricError(f"{name} must contain only finite values")
    return array


def _require_frame(value: object, *, source: str) -> None:
    """Require explicit tabular inputs."""
    if not isinstance(value, pd.DataFrame):
        raise TypeError(f"{source} must be a pandas DataFrame")


def _require_columns(
    rows: pd.DataFrame,
    required: tuple[str, ...],
    *,
    source: str,
) -> None:
    """Require all scoring dependencies."""
    missing = sorted(set(required).difference(rows.columns))
    if missing:
        raise BaselineMetricError(
            f"{source} missing required columns: {', '.join(missing)}"
        )


def _require_unique(
    rows: pd.DataFrame,
    identity_column: str,
    *,
    source: str,
) -> None:
    """Require non-null unique row identities."""
    identities = rows[identity_column]
    if identities.isna().any():
        raise BaselineMetricError(
            f"{source} contain null {identity_column}"
        )
    if identities.astype("string").duplicated().any():
        raise BaselineMetricError(
            f"{source} contain duplicate {identity_column}"
        )
