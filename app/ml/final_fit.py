"""Refit the selected Phase 6 candidate on all development races."""

from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter

import pandas as pd

from app.datasets.contracts import DEVELOPMENT_SEASONS
from app.ml.contracts import (
    APPROVED_FEATURE_COLUMNS,
    DEVELOPMENT_FOLDS,
    PRIMARY_TARGET_COLUMN,
    ModelTarget,
)
from app.ml.matrices import (
    MATRIX_IDENTITY_COLUMNS,
    FoldTrainingMatrix,
    TrainingMatrixPartition,
)
from app.ml.selection import SelectedPrimaryCandidate
from app.ml.training import TrainedCandidateModel, fit_candidate_model

FINAL_DEVELOPMENT_FIT_ID = "final_development_fit"


class FinalModelFitError(ValueError):
    """Raised when the selected candidate cannot be fit on all development data."""


@dataclass(frozen=True, slots=True)
class FinalModelFit:
    """The selected model, its full training population and fit timing."""

    model: TrainedCandidateModel
    training: TrainingMatrixPartition
    fit_duration_seconds: float


def build_final_development_partition(
    matrices: tuple[FoldTrainingMatrix, ...],
) -> TrainingMatrixPartition:
    """Combine the last expanding fold into one canonical 2022--2024 matrix."""
    if not isinstance(matrices, tuple):
        raise TypeError("matrices must be a tuple")
    by_fold: dict[str, FoldTrainingMatrix] = {}
    for matrix in matrices:
        if not isinstance(matrix, FoldTrainingMatrix):
            raise TypeError("every matrix must be a FoldTrainingMatrix")
        if matrix.target != ModelTarget.LAP_TIME:
            raise FinalModelFitError("final fit requires LAP_TIME matrices")
        if matrix.fold_id in by_fold:
            raise FinalModelFitError(f"duplicate matrix fold: {matrix.fold_id}")
        by_fold[matrix.fold_id] = matrix
    if set(by_fold) != set(DEVELOPMENT_FOLDS):
        raise FinalModelFitError(
            "final fit requires both frozen development folds"
        )

    final_fold = by_fold[DEVELOPMENT_FOLDS[-1]]
    combined = _combined_rows(final_fold)
    if combined["decision_id"].duplicated().any():
        raise FinalModelFitError("final development rows contain duplicate decisions")
    seasons = tuple(sorted(set(combined["season"].astype(int))))
    if seasons != DEVELOPMENT_SEASONS:
        raise FinalModelFitError(
            "final development matrix must contain 2022, 2023 and 2024"
        )
    combined = combined.sort_values(
        ["season", "session_id", "decision_lap", "driver", "decision_id"],
        kind="stable",
    ).reset_index(drop=True)
    return TrainingMatrixPartition(
        identities=combined.loc[:, MATRIX_IDENTITY_COLUMNS].reset_index(drop=True),
        features=combined.loc[:, APPROVED_FEATURE_COLUMNS].reset_index(drop=True),
        target=combined[PRIMARY_TARGET_COLUMN].reset_index(drop=True),
    )


def fit_final_development_model(
    *,
    matrices: tuple[FoldTrainingMatrix, ...],
    selected_candidate: SelectedPrimaryCandidate,
) -> FinalModelFit:
    """Fit the temporally selected candidate on every eligible development row."""
    if not isinstance(selected_candidate, SelectedPrimaryCandidate):
        raise TypeError(
            "selected_candidate must be a SelectedPrimaryCandidate"
        )
    try:
        parameters = json.loads(selected_candidate.parameters)
    except json.JSONDecodeError as error:
        raise FinalModelFitError(
            "selected candidate parameters are not valid JSON"
        ) from error
    if not isinstance(parameters, dict):
        raise FinalModelFitError(
            "selected candidate parameters must be a JSON object"
        )

    training = build_final_development_partition(matrices)
    started = perf_counter()
    model = fit_candidate_model(
        training,
        fold_id=FINAL_DEVELOPMENT_FIT_ID,
        target=ModelTarget.LAP_TIME,
        family=selected_candidate.family,
        parameters=parameters,
    )
    elapsed = perf_counter() - started
    if model.candidate_id != selected_candidate.candidate_id:
        raise FinalModelFitError(
            "final fitted model differs from the selected candidate"
        )
    return FinalModelFit(
        model=model,
        training=training,
        fit_duration_seconds=elapsed,
    )


def _combined_rows(matrix: FoldTrainingMatrix) -> pd.DataFrame:
    """Keep identities, features and target aligned while joining roles."""
    parts: list[pd.DataFrame] = []
    for partition in (matrix.training, matrix.validation):
        part = pd.concat(
            [
                partition.identities.reset_index(drop=True),
                partition.features.reset_index(drop=True),
                partition.target.rename(PRIMARY_TARGET_COLUMN).reset_index(drop=True),
            ],
            axis="columns",
        )
        parts.append(part)
    return pd.concat(parts, ignore_index=True)
