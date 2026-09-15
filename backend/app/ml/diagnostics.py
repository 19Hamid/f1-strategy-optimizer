"""Analyse selected-model residuals and tyre-age associations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final

import pandas as pd

from app.baselines.metrics import regression_metrics
from app.ml.contracts import (
    APPROVED_FEATURE_COLUMNS,
    IDENTITY_ABLATION_FEATURE_COLUMNS,
    PROTECTED_EVALUATION_SEASON,
    ModelTarget,
    PredictionFormulation,
)
from app.ml.matrices import FoldTrainingMatrix
from app.ml.selection import SelectedPrimaryCandidate
from app.ml.training import (
    FULL_FEATURE_SET_ID,
    IDENTITY_ABLATION_FEATURE_SET_ID,
    PREDICTION_COLUMNS,
    ResidualHybridModel,
    score_candidate_model,
    train_candidate_model,
)

TYRE_AGE_BINS: Final = (-1, 5, 15, float("inf"))
TYRE_AGE_LABELS: Final = ("NEW_0_5", "USED_6_15", "OLD_16_PLUS")
RACE_PROGRESS_BINS: Final = (-0.001, 1 / 3, 2 / 3, 1.001)
RACE_PROGRESS_LABELS: Final = ("EARLY", "MIDDLE", "LATE")
DIAGNOSTIC_DIMENSIONS: Final = (
    "session_id",
    "event_name",
    "current_compound",
    "tyre_age_band",
    "race_progress_band",
    "driver",
    "team",
)
SLICE_METRIC_COLUMNS: Final = (
    "target",
    "fold_id",
    "feature_set_id",
    "dimension",
    "value",
    "rows",
    "mean_absolute_error_seconds",
    "root_mean_squared_error_seconds",
    "median_absolute_error_seconds",
    "p90_absolute_error_seconds",
    "mean_signed_error_seconds",
)
DEGRADATION_CURVE_COLUMNS: Final = (
    "fold_id",
    "current_compound",
    "tyre_age_band",
    "rows",
    "mean_tyre_age_laps",
    "mean_observed_lap_time_delta_seconds",
    "mean_predicted_lap_time_delta_seconds",
    "mean_absolute_error_seconds",
    "mean_signed_error_seconds",
)
IDENTITY_DIAGNOSTIC_COLUMNS: Final = (
    "feature_set_id",
    "rows",
    "mean_absolute_error_seconds",
    "root_mean_squared_error_seconds",
    "median_absolute_error_seconds",
    "p90_absolute_error_seconds",
    "mean_signed_error_seconds",
    "mae_increase_from_full_seconds",
)


class DegradationDiagnosticError(ValueError):
    """Raised when selected-model diagnostics would be incomplete."""


@dataclass(frozen=True, slots=True)
class SelectedModelDiagnostics:
    """Sliced residual, degradation and identity-dependence evidence."""

    slice_metrics: pd.DataFrame
    degradation_curve: pd.DataFrame
    identity_dependence: pd.DataFrame

    def __post_init__(self) -> None:
        """Require exact non-empty diagnostic schemas."""
        frames = (
            (
                self.slice_metrics,
                SLICE_METRIC_COLUMNS,
                "slice metrics",
            ),
            (
                self.degradation_curve,
                DEGRADATION_CURVE_COLUMNS,
                "degradation curve",
            ),
            (
                self.identity_dependence,
                IDENTITY_DIAGNOSTIC_COLUMNS,
                "identity diagnostic",
            ),
        )
        for frame, columns, name in frames:
            if tuple(frame.columns) != columns:
                raise DegradationDiagnosticError(f"{name} columns differ from contract")
            if frame.empty:
                raise DegradationDiagnosticError(f"{name} must not be empty")


def build_selected_model_diagnostics(
    *,
    primary_matrices: tuple[FoldTrainingMatrix, ...],
    auxiliary_matrices: tuple[FoldTrainingMatrix, ...],
    selected_candidate: SelectedPrimaryCandidate,
) -> SelectedModelDiagnostics:
    """Retrain the winner and diagnose both targets across held-out races."""
    if not isinstance(selected_candidate, SelectedPrimaryCandidate):
        raise TypeError("selected_candidate must be a SelectedPrimaryCandidate")
    primary = _validate_matrices(
        primary_matrices,
        target=ModelTarget.LAP_TIME,
    )
    auxiliary = _validate_matrices(
        auxiliary_matrices,
        target=ModelTarget.LAP_TIME_DELTA,
    )
    if tuple(matrix.fold_id for matrix in primary) != tuple(
        matrix.fold_id for matrix in auxiliary
    ):
        raise DegradationDiagnosticError("primary and auxiliary folds do not align")
    parameters = _selected_parameters(selected_candidate)

    primary_frames: list[pd.DataFrame] = []
    auxiliary_frames: list[pd.DataFrame] = []
    auxiliary_by_fold = {matrix.fold_id: matrix for matrix in auxiliary}
    for matrix in primary:
        auxiliary_matrix = auxiliary_by_fold[matrix.fold_id]
        for features in (
            APPROVED_FEATURE_COLUMNS,
            IDENTITY_ABLATION_FEATURE_COLUMNS,
        ):
            direct_result = train_candidate_model(
                matrix,
                family=selected_candidate.family,
                parameters=parameters,
                feature_columns=features,
            )
            result = direct_result
            if selected_candidate.formulation == PredictionFormulation.RESIDUAL_HYBRID:
                delta_result = train_candidate_model(
                    auxiliary_matrix,
                    family=selected_candidate.family,
                    parameters=parameters,
                    feature_columns=features,
                )
                result = score_candidate_model(
                    ResidualHybridModel(
                        fold_id=matrix.fold_id,
                        direct_model=direct_result.model,
                        delta_model=delta_result.model,
                    ),
                    matrix,
                )
                if features == APPROVED_FEATURE_COLUMNS:
                    auxiliary_frames.append(
                        _scored_frame(auxiliary_matrix, delta_result)
                    )
            _require_selected_identity(result, selected_candidate)
            primary_frames.append(_scored_frame(matrix, result))
    if selected_candidate.formulation == PredictionFormulation.DIRECT_ABSOLUTE:
        for matrix in auxiliary:
            result = train_candidate_model(
                matrix,
                family=selected_candidate.family,
                parameters=parameters,
            )
            _require_selected_identity(result, selected_candidate)
            auxiliary_frames.append(_scored_frame(matrix, result))

    primary_scored = pd.concat(primary_frames, ignore_index=True)
    auxiliary_scored = pd.concat(auxiliary_frames, ignore_index=True)
    slices = _slice_metrics(primary_scored, auxiliary_scored)
    degradation = _degradation_curve(auxiliary_scored)
    identity = _identity_diagnostic(primary_scored)
    return SelectedModelDiagnostics(
        slice_metrics=slices,
        degradation_curve=degradation,
        identity_dependence=identity,
    )


def _scored_frame(
    matrix: FoldTrainingMatrix,
    result: object,
) -> pd.DataFrame:
    """Join held-out predictions to approved diagnostic context."""
    predictions = result.validation_predictions
    if tuple(predictions.columns) != PREDICTION_COLUMNS:
        raise DegradationDiagnosticError(
            "candidate prediction columns differ from contract"
        )
    if len(predictions) != matrix.validation.row_count:
        raise DegradationDiagnosticError(
            "candidate prediction count differs from validation rows"
        )
    expected = matrix.validation.identities.reset_index(drop=True)
    actual = predictions.loc[
        :,
        expected.columns,
    ].reset_index(drop=True)
    if not actual.equals(expected):
        raise DegradationDiagnosticError(
            "candidate predictions do not align with validation identity"
        )

    rows = predictions.loc[
        :,
        [
            "decision_id",
            "session_id",
            "season",
            "fold_id",
            "target",
            "feature_set_id",
            "target_seconds",
            "prediction_seconds",
            "absolute_error_seconds",
        ],
    ].copy()
    context = matrix.validation.features.loc[
        :,
        [
            "event_name",
            "current_compound",
            "tyre_age_laps",
            "decision_lap",
            "driver",
            "team",
        ],
    ].reset_index(drop=True)
    rows = pd.concat(
        [rows.reset_index(drop=True), context],
        axis=1,
    )
    rows["signed_error_seconds"] = rows["prediction_seconds"] - rows["target_seconds"]
    rows["tyre_age_band"] = pd.cut(
        pd.to_numeric(rows["tyre_age_laps"], errors="coerce"),
        bins=TYRE_AGE_BINS,
        labels=TYRE_AGE_LABELS,
        include_lowest=True,
    ).astype("string")
    maximum_lap = rows.groupby("session_id")["decision_lap"].transform("max")
    if maximum_lap.isna().any() or maximum_lap.le(0).any():
        raise DegradationDiagnosticError("race progress cannot be derived")
    progress = rows["decision_lap"] / maximum_lap
    rows["race_progress_band"] = pd.cut(
        progress,
        bins=RACE_PROGRESS_BINS,
        labels=RACE_PROGRESS_LABELS,
        include_lowest=True,
    ).astype("string")
    if rows[["tyre_age_band", "race_progress_band"]].isna().any().any():
        raise DegradationDiagnosticError("diagnostic bands contain missing values")
    return rows


def _slice_metrics(
    primary: pd.DataFrame,
    auxiliary: pd.DataFrame,
) -> pd.DataFrame:
    """Calculate required residual slices for both targets."""
    records: list[dict[str, object]] = []
    combined = pd.concat([primary, auxiliary], ignore_index=True)
    group_columns = ("target", "fold_id", "feature_set_id")
    for keys, task_rows in combined.groupby(
        list(group_columns),
        sort=True,
        dropna=False,
    ):
        target, fold_id, feature_set_id = keys
        for dimension in DIAGNOSTIC_DIMENSIONS:
            values = task_rows[dimension].astype("string").fillna("__MISSING__")
            for value in sorted(values.unique()):
                group = task_rows.loc[values.eq(value)]
                metrics = regression_metrics(
                    group["target_seconds"],
                    group["prediction_seconds"],
                )
                records.append(
                    {
                        "target": str(target),
                        "fold_id": str(fold_id),
                        "feature_set_id": str(feature_set_id),
                        "dimension": dimension,
                        "value": str(value),
                        "rows": metrics.rows,
                        **_metric_values(metrics),
                    }
                )
    return pd.DataFrame.from_records(
        records,
        columns=SLICE_METRIC_COLUMNS,
    )


def _degradation_curve(auxiliary: pd.DataFrame) -> pd.DataFrame:
    """Summarize observed and predicted lap change by tyre state."""
    full = auxiliary.loc[auxiliary["feature_set_id"].eq(FULL_FEATURE_SET_ID)].copy()
    if full.empty:
        raise DegradationDiagnosticError(
            "auxiliary full-feature predictions are missing"
        )
    records: list[dict[str, object]] = []
    for keys, rows in full.groupby(
        ["fold_id", "current_compound", "tyre_age_band"],
        sort=True,
        dropna=False,
    ):
        fold_id, compound, tyre_age_band = keys
        metrics = regression_metrics(
            rows["target_seconds"],
            rows["prediction_seconds"],
        )
        records.append(
            {
                "fold_id": str(fold_id),
                "current_compound": str(compound),
                "tyre_age_band": str(tyre_age_band),
                "rows": len(rows),
                "mean_tyre_age_laps": float(
                    pd.to_numeric(
                        rows["tyre_age_laps"],
                        errors="coerce",
                    ).mean()
                ),
                "mean_observed_lap_time_delta_seconds": float(
                    rows["target_seconds"].mean()
                ),
                "mean_predicted_lap_time_delta_seconds": float(
                    rows["prediction_seconds"].mean()
                ),
                "mean_absolute_error_seconds": (metrics.mean_absolute_error_seconds),
                "mean_signed_error_seconds": (metrics.mean_signed_error_seconds),
            }
        )
    result = pd.DataFrame.from_records(
        records,
        columns=DEGRADATION_CURVE_COLUMNS,
    )
    if (
        result[
            [
                "mean_tyre_age_laps",
                "mean_observed_lap_time_delta_seconds",
                "mean_predicted_lap_time_delta_seconds",
            ]
        ]
        .isna()
        .any()
        .any()
    ):
        raise DegradationDiagnosticError("degradation curve contains missing values")
    return result


def _identity_diagnostic(primary: pd.DataFrame) -> pd.DataFrame:
    """Quantify error change after removing driver and team identity."""
    records: list[dict[str, object]] = []
    full_mae: float | None = None
    ordered_sets = (
        FULL_FEATURE_SET_ID,
        IDENTITY_ABLATION_FEATURE_SET_ID,
    )
    for feature_set_id in ordered_sets:
        rows = primary.loc[primary["feature_set_id"].eq(feature_set_id)]
        if rows.empty:
            raise DegradationDiagnosticError(
                f"missing primary predictions for {feature_set_id}"
            )
        metrics = regression_metrics(
            rows["target_seconds"],
            rows["prediction_seconds"],
        )
        if feature_set_id == FULL_FEATURE_SET_ID:
            full_mae = metrics.mean_absolute_error_seconds
        if full_mae is None:
            raise DegradationDiagnosticError(
                "full identity diagnostic must be evaluated first"
            )
        records.append(
            {
                "feature_set_id": feature_set_id,
                "rows": metrics.rows,
                **_metric_values(metrics),
                "mae_increase_from_full_seconds": (
                    metrics.mean_absolute_error_seconds - full_mae
                ),
            }
        )
    return pd.DataFrame.from_records(
        records,
        columns=IDENTITY_DIAGNOSTIC_COLUMNS,
    )


def _metric_values(metrics: object) -> dict[str, float]:
    """Normalize the frozen regression metric attributes."""
    return {
        "mean_absolute_error_seconds": (metrics.mean_absolute_error_seconds),
        "root_mean_squared_error_seconds": (metrics.root_mean_squared_error_seconds),
        "median_absolute_error_seconds": (metrics.median_absolute_error_seconds),
        "p90_absolute_error_seconds": (metrics.p90_absolute_error_seconds),
        "mean_signed_error_seconds": metrics.mean_signed_error_seconds,
    }


def _selected_parameters(
    selected: SelectedPrimaryCandidate,
) -> dict[str, object]:
    """Parse and validate the selected deterministic parameter document."""
    try:
        parameters = json.loads(selected.parameters)
    except (json.JSONDecodeError, TypeError) as error:
        raise DegradationDiagnosticError(
            "selected candidate parameters are not valid JSON"
        ) from error
    if not isinstance(parameters, dict):
        raise DegradationDiagnosticError(
            "selected candidate parameters must be an object"
        )
    return parameters


def _require_selected_identity(
    result: object,
    selected: SelectedPrimaryCandidate,
) -> None:
    """Ensure retraining resolved to the exact selected grid candidate."""
    if (
        result.model.family != selected.family
        or result.model.candidate_id != selected.candidate_id
    ):
        raise DegradationDiagnosticError(
            "retrained candidate differs from selected identity"
        )


def _validate_matrices(
    matrices: tuple[FoldTrainingMatrix, ...],
    *,
    target: ModelTarget,
) -> tuple[FoldTrainingMatrix, ...]:
    """Require two ordered folds with the requested target and no 2025."""
    if not isinstance(matrices, tuple):
        raise TypeError("matrices must be a tuple")
    by_fold: dict[str, FoldTrainingMatrix] = {}
    for matrix in matrices:
        if not isinstance(matrix, FoldTrainingMatrix):
            raise TypeError("every matrix must be a FoldTrainingMatrix")
        if matrix.target != target:
            raise DegradationDiagnosticError(f"expected {target.value} matrices")
        if matrix.fold_id in by_fold:
            raise DegradationDiagnosticError(f"duplicate matrix fold: {matrix.fold_id}")
        seasons = pd.concat(
            [
                matrix.training.identities["season"],
                matrix.validation.identities["season"],
            ],
            ignore_index=True,
        )
        if seasons.eq(PROTECTED_EVALUATION_SEASON).any():
            raise DegradationDiagnosticError("diagnostics contain protected 2025 rows")
        by_fold[matrix.fold_id] = matrix
    expected = {"development_fold_1", "development_fold_2"}
    if set(by_fold) != expected:
        raise DegradationDiagnosticError("diagnostics require both development folds")
    return tuple(
        by_fold[fold_id] for fold_id in ("development_fold_1", "development_fold_2")
    )
