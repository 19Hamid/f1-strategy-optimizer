"""Evaluate and select Phase 6 candidates across temporal folds."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

import numpy as np
import pandas as pd

from app.ml.contracts import (
    DEVELOPMENT_FOLDS,
    IDENTITY_ABLATION_FEATURE_COLUMNS,
    MINIMUM_PRIMARY_COVERAGE,
    PRIMARY_BASELINE_MAE_SECONDS,
    ModelFamily,
    ModelTarget,
)
from app.ml.matrices import FoldTrainingMatrix
from app.ml.training import (
    FULL_FEATURE_SET_ID,
    IDENTITY_ABLATION_FEATURE_SET_ID,
    PREDICTION_COLUMNS,
    train_fold_candidates,
)

FOLD_METRIC_COLUMNS: Final = (
    "fold_id",
    "target",
    "model_family",
    "candidate_id",
    "feature_set_id",
    "parameters",
    "eligible_targets",
    "scored_predictions",
    "coverage_rate",
    "mean_absolute_error_seconds",
    "root_mean_squared_error_seconds",
    "median_absolute_error_seconds",
    "p90_absolute_error_seconds",
    "mean_signed_error_seconds",
    "common_rows",
    "common_mean_absolute_error_seconds",
    "common_root_mean_squared_error_seconds",
    "common_median_absolute_error_seconds",
    "common_p90_absolute_error_seconds",
    "common_mean_signed_error_seconds",
    "baseline_common_mean_absolute_error_seconds",
)
POOLED_METRIC_COLUMNS: Final = (
    "target",
    "model_family",
    "candidate_id",
    "feature_set_id",
    "parameters",
    "fold_count",
    "eligible_targets",
    "scored_predictions",
    "coverage_rate",
    "mean_absolute_error_seconds",
    "root_mean_squared_error_seconds",
    "median_absolute_error_seconds",
    "p90_absolute_error_seconds",
    "mean_signed_error_seconds",
    "common_rows",
    "common_mean_absolute_error_seconds",
    "common_root_mean_squared_error_seconds",
    "common_median_absolute_error_seconds",
    "common_p90_absolute_error_seconds",
    "common_mean_signed_error_seconds",
    "baseline_common_mean_absolute_error_seconds",
)
SELECTION_COLUMNS: Final = (
    "model_family",
    "candidate_id",
    "parameters",
    "full_mean_absolute_error_seconds",
    "full_common_mean_absolute_error_seconds",
    "ablated_common_mean_absolute_error_seconds",
    "baseline_common_mean_absolute_error_seconds",
    "coverage_rate",
    "fold_count",
    "beats_frozen_baseline",
    "beats_comparable_baseline",
    "ablation_passes",
    "minimum_coverage_passes",
    "both_folds_present",
    "meets_selection_contract",
    "selected",
)


class TemporalSelectionError(ValueError):
    """Raised when temporal model selection is incomplete or misleading."""


@dataclass(frozen=True, slots=True)
class SelectedPrimaryCandidate:
    """The strongest qualifying primary candidate, when one exists."""

    family: ModelFamily
    candidate_id: str
    parameters: str
    pooled_mean_absolute_error_seconds: float
    common_mean_absolute_error_seconds: float
    ablated_common_mean_absolute_error_seconds: float
    coverage_rate: float


@dataclass(frozen=True, slots=True)
class TemporalSelectionReport:
    """Fold, pooled and selection evidence for primary lap-time models."""

    fold_metrics: pd.DataFrame
    pooled_metrics: pd.DataFrame
    selection: pd.DataFrame
    selected_candidate: SelectedPrimaryCandidate | None


@dataclass(slots=True)
class _PooledEvidence:
    """Compact error vectors accumulated across validation folds."""

    metadata: dict[str, Any]
    signed_errors: list[np.ndarray]
    common_signed_errors: list[np.ndarray]
    baseline_common_signed_errors: list[np.ndarray]
    eligible_targets: int = 0
    scored_predictions: int = 0
    fold_count: int = 0


def evaluate_primary_temporal_candidates(
    matrices: tuple[FoldTrainingMatrix, ...],
) -> TemporalSelectionReport:
    """Train, score and select candidates on both chronological folds."""
    ordered = _validate_primary_matrices(matrices)
    fold_records: list[dict[str, Any]] = []
    pooled: dict[tuple[str, str], _PooledEvidence] = {}

    for matrix in ordered:
        for feature_columns in (
            matrix.training.features.columns.to_list(),
            list(IDENTITY_ABLATION_FEATURE_COLUMNS),
        ):
            selected_features = tuple(feature_columns)
            results = train_fold_candidates(
                matrix,
                feature_columns=selected_features,
            )
            for result in results:
                evidence = _candidate_evidence(
                    matrix=matrix,
                    result=result,
                )
                fold_records.append(evidence["record"])
                key = (
                    result.model.candidate_id,
                    result.model.feature_set_id,
                )
                accumulator = pooled.setdefault(
                    key,
                    _PooledEvidence(
                        metadata={
                            "target": matrix.target.value,
                            "model_family": result.model.family.value,
                            "candidate_id": result.model.candidate_id,
                            "feature_set_id": result.model.feature_set_id,
                            "parameters": _parameters_json(
                                result.model.parameters
                            ),
                        },
                        signed_errors=[],
                        common_signed_errors=[],
                        baseline_common_signed_errors=[],
                    ),
                )
                accumulator.signed_errors.append(evidence["signed_errors"])
                accumulator.common_signed_errors.append(
                    evidence["common_signed_errors"]
                )
                accumulator.baseline_common_signed_errors.append(
                    evidence["baseline_common_signed_errors"]
                )
                accumulator.eligible_targets += int(
                    evidence["eligible_targets"]
                )
                accumulator.scored_predictions += int(
                    evidence["scored_predictions"]
                )
                accumulator.fold_count += 1

    fold_metrics = pd.DataFrame.from_records(
        fold_records,
        columns=FOLD_METRIC_COLUMNS,
    )
    expected_fold_rows = len(DEVELOPMENT_FOLDS) * 15 * 2
    if len(fold_metrics) != expected_fold_rows:
        raise TemporalSelectionError(
            f"expected {expected_fold_rows} fold metrics, "
            f"received {len(fold_metrics)}"
        )
    pooled_metrics = _pooled_metric_table(pooled)
    selection, selected = select_primary_candidate(pooled_metrics)
    return TemporalSelectionReport(
        fold_metrics=fold_metrics,
        pooled_metrics=pooled_metrics,
        selection=selection,
        selected_candidate=selected,
    )


def select_primary_candidate(
    pooled_metrics: pd.DataFrame,
) -> tuple[pd.DataFrame, SelectedPrimaryCandidate | None]:
    """Apply frozen baseline, coverage and identity-ablation gates."""
    if not isinstance(pooled_metrics, pd.DataFrame):
        raise TypeError("pooled_metrics must be a pandas DataFrame")
    missing = sorted(
        set(POOLED_METRIC_COLUMNS).difference(pooled_metrics.columns)
    )
    if missing:
        raise TemporalSelectionError(
            "pooled metrics missing columns: " + ", ".join(missing)
        )
    if pooled_metrics.loc[
        :,
        ["candidate_id", "feature_set_id"],
    ].duplicated().any():
        raise TemporalSelectionError(
            "pooled candidate-feature identities are duplicated"
        )

    full = pooled_metrics.loc[
        pooled_metrics["feature_set_id"].eq(FULL_FEATURE_SET_ID)
    ].copy()
    ablated = pooled_metrics.loc[
        pooled_metrics["feature_set_id"].eq(
            IDENTITY_ABLATION_FEATURE_SET_ID
        )
    ].copy()
    if len(full) != 15 or len(ablated) != 15:
        raise TemporalSelectionError(
            "selection requires 15 full and 15 ablated candidates"
        )

    ablation_columns = {
        "common_mean_absolute_error_seconds": (
            "ablated_common_mean_absolute_error_seconds"
        ),
        "baseline_common_mean_absolute_error_seconds": (
            "ablated_baseline_common_mean_absolute_error_seconds"
        ),
        "coverage_rate": "ablated_coverage_rate",
        "fold_count": "ablated_fold_count",
    }
    comparison = full.merge(
        ablated.loc[
            :,
            ["candidate_id", *ablation_columns],
        ].rename(columns=ablation_columns),
        on="candidate_id",
        how="inner",
        validate="one_to_one",
    )
    rows: list[dict[str, Any]] = []
    for row in comparison.itertuples(index=False):
        beats_frozen = (
            row.common_mean_absolute_error_seconds
            < PRIMARY_BASELINE_MAE_SECONDS
        )
        beats_comparable = (
            row.common_mean_absolute_error_seconds
            < row.baseline_common_mean_absolute_error_seconds
        )
        ablation_passes = (
            row.ablated_common_mean_absolute_error_seconds
            < PRIMARY_BASELINE_MAE_SECONDS
            and row.ablated_common_mean_absolute_error_seconds
            < row.ablated_baseline_common_mean_absolute_error_seconds
        )
        coverage_passes = (
            row.coverage_rate >= MINIMUM_PRIMARY_COVERAGE
            and row.ablated_coverage_rate >= MINIMUM_PRIMARY_COVERAGE
        )
        both_folds = (
            row.fold_count == len(DEVELOPMENT_FOLDS)
            and row.ablated_fold_count == len(DEVELOPMENT_FOLDS)
        )
        meets_contract = (
            beats_frozen
            and beats_comparable
            and ablation_passes
            and coverage_passes
            and both_folds
        )
        rows.append(
            {
                "model_family": row.model_family,
                "candidate_id": row.candidate_id,
                "parameters": row.parameters,
                "full_mean_absolute_error_seconds": (
                    row.mean_absolute_error_seconds
                ),
                "full_common_mean_absolute_error_seconds": (
                    row.common_mean_absolute_error_seconds
                ),
                "ablated_common_mean_absolute_error_seconds": (
                    row.ablated_common_mean_absolute_error_seconds
                ),
                "baseline_common_mean_absolute_error_seconds": (
                    row.baseline_common_mean_absolute_error_seconds
                ),
                "coverage_rate": row.coverage_rate,
                "fold_count": row.fold_count,
                "beats_frozen_baseline": beats_frozen,
                "beats_comparable_baseline": beats_comparable,
                "ablation_passes": ablation_passes,
                "minimum_coverage_passes": coverage_passes,
                "both_folds_present": both_folds,
                "meets_selection_contract": meets_contract,
                "selected": False,
            }
        )

    selection = pd.DataFrame.from_records(rows, columns=SELECTION_COLUMNS)
    eligible = selection.loc[
        selection["meets_selection_contract"].eq(True)
    ].sort_values(
        [
            "full_mean_absolute_error_seconds",
            "full_common_mean_absolute_error_seconds",
            "candidate_id",
        ],
        kind="stable",
    )
    if eligible.empty:
        return selection, None

    winner_index = int(eligible.index[0])
    selection.loc[winner_index, "selected"] = True
    winner = selection.loc[winner_index]
    return selection, SelectedPrimaryCandidate(
        family=ModelFamily(str(winner["model_family"])),
        candidate_id=str(winner["candidate_id"]),
        parameters=str(winner["parameters"]),
        pooled_mean_absolute_error_seconds=float(
            winner["full_mean_absolute_error_seconds"]
        ),
        common_mean_absolute_error_seconds=float(
            winner["full_common_mean_absolute_error_seconds"]
        ),
        ablated_common_mean_absolute_error_seconds=float(
            winner["ablated_common_mean_absolute_error_seconds"]
        ),
        coverage_rate=float(winner["coverage_rate"]),
    )


def _candidate_evidence(
    *,
    matrix: FoldTrainingMatrix,
    result: Any,
) -> dict[str, Any]:
    """Calculate honest fold metrics and common-row baseline evidence."""
    predictions = result.validation_predictions
    if tuple(predictions.columns) != PREDICTION_COLUMNS:
        raise TemporalSelectionError(
            "candidate prediction columns differ from contract"
        )
    if len(predictions) != matrix.validation.row_count:
        raise TemporalSelectionError(
            "candidate predictions do not cover validation rows"
        )
    expected_ids = matrix.validation.identities["decision_id"].astype(str)
    actual_ids = predictions["decision_id"].astype(str)
    if not actual_ids.reset_index(drop=True).equals(
        expected_ids.reset_index(drop=True)
    ):
        raise TemporalSelectionError(
            "candidate predictions are not aligned to validation identities"
        )

    targets = matrix.validation.target.to_numpy(dtype="float64")
    recorded_targets = predictions["target_seconds"].to_numpy(dtype="float64")
    if not np.array_equal(targets, recorded_targets):
        raise TemporalSelectionError(
            "candidate predictions record different validation targets"
        )
    predicted = predictions["prediction_seconds"].to_numpy(dtype="float64")
    if not np.isfinite(predicted).all():
        raise TemporalSelectionError(
            "candidate predictions contain non-finite values"
        )
    signed = predicted - targets

    previous = pd.to_numeric(
        matrix.validation.features["previous_lap_time_seconds"],
        errors="coerce",
    ).to_numpy(dtype="float64")
    previous_valid = matrix.validation.features[
        "previous_lap_was_target_eligible"
    ].eq(True).to_numpy()
    common_mask = (
        previous_valid
        & np.isfinite(previous)
        & (previous > 0)
    )
    if not common_mask.any():
        raise TemporalSelectionError(
            "validation fold has no rows comparable with the baseline"
        )
    common_signed = signed[common_mask]
    baseline_common_signed = previous[common_mask] - targets[common_mask]
    metrics = _metrics(signed)
    common_metrics = _metrics(common_signed)
    baseline_metrics = _metrics(baseline_common_signed)
    parameters = _parameters_json(result.model.parameters)
    record = {
        "fold_id": matrix.fold_id,
        "target": matrix.target.value,
        "model_family": result.model.family.value,
        "candidate_id": result.model.candidate_id,
        "feature_set_id": result.model.feature_set_id,
        "parameters": parameters,
        "eligible_targets": len(targets),
        "scored_predictions": len(predicted),
        "coverage_rate": len(predicted) / len(targets),
        **metrics,
        "common_rows": len(common_signed),
        **{
            f"common_{key}": value
            for key, value in common_metrics.items()
        },
        "baseline_common_mean_absolute_error_seconds": (
            baseline_metrics["mean_absolute_error_seconds"]
        ),
    }
    return {
        "record": record,
        "signed_errors": signed,
        "common_signed_errors": common_signed,
        "baseline_common_signed_errors": baseline_common_signed,
        "eligible_targets": len(targets),
        "scored_predictions": len(predicted),
    }


def _pooled_metric_table(
    evidence_by_candidate: dict[tuple[str, str], _PooledEvidence],
) -> pd.DataFrame:
    """Pool row-level errors exactly across both validation seasons."""
    records: list[dict[str, Any]] = []
    for key in sorted(evidence_by_candidate):
        evidence = evidence_by_candidate[key]
        signed = np.concatenate(evidence.signed_errors)
        common = np.concatenate(evidence.common_signed_errors)
        baseline = np.concatenate(evidence.baseline_common_signed_errors)
        records.append(
            {
                **evidence.metadata,
                "fold_count": evidence.fold_count,
                "eligible_targets": evidence.eligible_targets,
                "scored_predictions": evidence.scored_predictions,
                "coverage_rate": (
                    evidence.scored_predictions
                    / evidence.eligible_targets
                ),
                **_metrics(signed),
                "common_rows": len(common),
                **{
                    f"common_{metric}": value
                    for metric, value in _metrics(common).items()
                },
                "baseline_common_mean_absolute_error_seconds": (
                    _metrics(baseline)["mean_absolute_error_seconds"]
                ),
            }
        )
    table = pd.DataFrame.from_records(
        records,
        columns=POOLED_METRIC_COLUMNS,
    )
    if len(table) != 30:
        raise TemporalSelectionError(
            f"expected 30 pooled metrics, received {len(table)}"
        )
    return table


def _metrics(signed_errors: np.ndarray) -> dict[str, float]:
    """Calculate the frozen regression metric set from signed errors."""
    values = np.asarray(signed_errors, dtype="float64")
    if values.ndim != 1 or len(values) == 0:
        raise TemporalSelectionError("metrics require a non-empty vector")
    if not np.isfinite(values).all():
        raise TemporalSelectionError("metrics require finite errors")
    absolute = np.abs(values)
    return {
        "mean_absolute_error_seconds": float(np.mean(absolute)),
        "root_mean_squared_error_seconds": float(
            np.sqrt(np.mean(np.square(values)))
        ),
        "median_absolute_error_seconds": float(np.median(absolute)),
        "p90_absolute_error_seconds": float(
            np.quantile(absolute, 0.9, method="linear")
        ),
        "mean_signed_error_seconds": float(np.mean(values)),
    }


def _parameters_json(
    parameters: tuple[tuple[str, object], ...],
) -> str:
    """Serialize frozen hyperparameters deterministically."""
    return json.dumps(
        dict(parameters),
        sort_keys=True,
        separators=(",", ":"),
    )


def _validate_primary_matrices(
    matrices: tuple[FoldTrainingMatrix, ...],
) -> tuple[FoldTrainingMatrix, ...]:
    """Require exactly both primary temporal folds."""
    if not isinstance(matrices, tuple):
        raise TypeError("matrices must be a tuple")
    if len(matrices) != len(DEVELOPMENT_FOLDS):
        raise TemporalSelectionError(
            "selection requires exactly both development folds"
        )
    by_fold: dict[str, FoldTrainingMatrix] = {}
    for matrix in matrices:
        if not isinstance(matrix, FoldTrainingMatrix):
            raise TypeError("every matrix must be a FoldTrainingMatrix")
        if matrix.target != ModelTarget.LAP_TIME:
            raise TemporalSelectionError(
                "primary selection requires LAP_TIME matrices"
            )
        if matrix.fold_id in by_fold:
            raise TemporalSelectionError(
                f"duplicate matrix fold: {matrix.fold_id}"
            )
        by_fold[matrix.fold_id] = matrix
    if set(by_fold) != set(DEVELOPMENT_FOLDS):
        raise TemporalSelectionError(
            "matrix folds differ from the development contract"
        )
    return tuple(by_fold[fold_id] for fold_id in DEVELOPMENT_FOLDS)
