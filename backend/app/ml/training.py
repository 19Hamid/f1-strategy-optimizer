"""Train deterministic Phase 6 candidate regressors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd
from sklearn.base import RegressorMixin
from sklearn.ensemble import (
    HistGradientBoostingRegressor,
    RandomForestRegressor,
)
from sklearn.linear_model import Ridge

from app.ml.contracts import (
    APPROVED_FEATURE_COLUMNS,
    IDENTITY_ABLATION_FEATURE_COLUMNS,
    MODEL_RANDOM_SEED,
    MODEL_SPECS,
    ModelFamily,
    ModelTarget,
    model_spec,
)
from app.ml.matrices import FoldTrainingMatrix
from app.ml.preprocessing import (
    FittedModelPreprocessor,
    fit_model_preprocessor,
)

FULL_FEATURE_SET_ID: Final = "full"
IDENTITY_ABLATION_FEATURE_SET_ID: Final = "without_driver_team"
PREDICTION_COLUMNS: Final = (
    "decision_id",
    "session_id",
    "season",
    "fold_id",
    "target",
    "model_family",
    "candidate_id",
    "feature_set_id",
    "target_seconds",
    "prediction_seconds",
    "absolute_error_seconds",
)


class CandidateTrainingError(ValueError):
    """Raised when a candidate violates the frozen modelling contract."""


@dataclass(frozen=True, slots=True)
class TrainedCandidateModel:
    """One fitted estimator bundled with its training-only preprocessor."""

    fold_id: str
    target: ModelTarget
    family: ModelFamily
    candidate_id: str
    feature_set_id: str
    parameters: tuple[tuple[str, object], ...]
    preprocessor: FittedModelPreprocessor
    estimator: RegressorMixin

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        """Transform with frozen state and return finite predictions."""
        transformed = self.preprocessor.transform(features)
        predictions = np.asarray(
            self.estimator.predict(transformed),
            dtype="float64",
        ).reshape(-1)
        if len(predictions) != len(features):
            raise CandidateTrainingError(
                "estimator returned the wrong prediction count"
            )
        if not np.isfinite(predictions).all():
            raise CandidateTrainingError(
                "estimator returned non-finite predictions"
            )
        return predictions


@dataclass(frozen=True, slots=True)
class CandidateTrainingResult:
    """A fitted candidate and its held-out validation predictions."""

    model: TrainedCandidateModel
    validation_predictions: pd.DataFrame

    def __post_init__(self) -> None:
        """Require the exact auditable prediction schema."""
        if tuple(self.validation_predictions.columns) != PREDICTION_COLUMNS:
            raise CandidateTrainingError(
                "validation prediction columns differ from contract"
            )
        if self.validation_predictions.empty:
            raise CandidateTrainingError(
                "validation predictions must not be empty"
            )

    @property
    def mean_absolute_error_seconds(self) -> float:
        """Return held-out mean absolute error for quick diagnostics."""
        return float(
            self.validation_predictions["absolute_error_seconds"].mean()
        )


def train_candidate_model(
    matrix: FoldTrainingMatrix,
    *,
    family: ModelFamily | str,
    parameters: dict[str, object],
    feature_columns: tuple[str, ...] = APPROVED_FEATURE_COLUMNS,
) -> CandidateTrainingResult:
    """Fit one approved candidate and score its validation partition."""
    if not isinstance(matrix, FoldTrainingMatrix):
        raise TypeError("matrix must be a FoldTrainingMatrix")
    normalized_family = _normalize_family(family)
    normalized_parameters = _validate_parameters(
        family=normalized_family,
        parameters=parameters,
    )
    feature_set_id = _feature_set_id(feature_columns)
    preprocessor = fit_model_preprocessor(
        matrix.training.features,
        family=normalized_family,
        feature_columns=feature_columns,
    )
    training_features = preprocessor.transform(matrix.training.features)
    training_target = _finite_target(
        matrix.training.target,
        source="training target",
    )
    estimator = _build_estimator(
        family=normalized_family,
        parameters=dict(normalized_parameters),
    )
    estimator.fit(training_features, training_target)

    model = TrainedCandidateModel(
        fold_id=matrix.fold_id,
        target=matrix.target,
        family=normalized_family,
        candidate_id=_candidate_id(
            normalized_family,
            dict(normalized_parameters),
        ),
        feature_set_id=feature_set_id,
        parameters=normalized_parameters,
        preprocessor=preprocessor,
        estimator=estimator,
    )
    validation_target = _finite_target(
        matrix.validation.target,
        source="validation target",
    )
    predictions = model.predict(matrix.validation.features)
    validation_rows = matrix.validation.identities.copy()
    validation_rows["fold_id"] = matrix.fold_id
    validation_rows["target"] = matrix.target.value
    validation_rows["model_family"] = normalized_family.value
    validation_rows["candidate_id"] = model.candidate_id
    validation_rows["feature_set_id"] = feature_set_id
    validation_rows["target_seconds"] = validation_target
    validation_rows["prediction_seconds"] = predictions
    validation_rows["absolute_error_seconds"] = np.abs(
        validation_target - predictions
    )
    validation_rows = validation_rows.loc[:, PREDICTION_COLUMNS]
    return CandidateTrainingResult(
        model=model,
        validation_predictions=validation_rows,
    )


def train_fold_candidates(
    matrix: FoldTrainingMatrix,
    *,
    feature_columns: tuple[str, ...] = APPROVED_FEATURE_COLUMNS,
) -> tuple[CandidateTrainingResult, ...]:
    """Fit all 15 frozen configurations for one target and fold."""
    results = tuple(
        train_candidate_model(
            matrix,
            family=specification.family,
            parameters=dict(parameters),
            feature_columns=feature_columns,
        )
        for specification in MODEL_SPECS
        for parameters in specification.parameter_grid
    )
    expected = sum(
        len(specification.parameter_grid)
        for specification in MODEL_SPECS
    )
    if len(results) != expected:
        raise CandidateTrainingError(
            f"expected {expected} candidate results, received {len(results)}"
        )
    identities = tuple(
        result.model.candidate_id
        for result in results
    )
    if len(identities) != len(set(identities)):
        raise CandidateTrainingError("candidate identities are not unique")
    return results


def _build_estimator(
    *,
    family: ModelFamily,
    parameters: dict[str, object],
) -> RegressorMixin:
    """Instantiate one approved deterministic scikit-learn regressor."""
    if family == ModelFamily.RIDGE:
        return Ridge(**parameters)
    if family == ModelFamily.RANDOM_FOREST:
        return RandomForestRegressor(
            **parameters,
            random_state=MODEL_RANDOM_SEED,
            n_jobs=1,
        )
    if family == ModelFamily.HIST_GRADIENT_BOOSTING:
        return HistGradientBoostingRegressor(
            **parameters,
            random_state=MODEL_RANDOM_SEED,
        )
    raise CandidateTrainingError(f"unsupported model family: {family.value}")


def _candidate_id(
    family: ModelFamily,
    parameters: dict[str, object],
) -> str:
    """Return the stable one-based grid identity for a configuration."""
    specification = model_spec(family)
    for index, candidate in enumerate(
        specification.parameter_grid,
        start=1,
    ):
        if candidate == parameters:
            return f"{family.value}_{index:02d}"
    raise CandidateTrainingError(
        f"parameters are outside the {family.value} grid"
    )


def _validate_parameters(
    *,
    family: ModelFamily,
    parameters: dict[str, object],
) -> tuple[tuple[str, object], ...]:
    """Require an exact declared grid member and freeze key ordering."""
    if not isinstance(parameters, dict):
        raise TypeError("parameters must be a dictionary")
    candidate = dict(parameters)
    if candidate not in model_spec(family).parameter_grid:
        raise CandidateTrainingError(
            f"parameters are outside the {family.value} grid"
        )
    return tuple(sorted(candidate.items()))


def _feature_set_id(feature_columns: tuple[str, ...]) -> str:
    """Name either the approved full or identity-ablation feature set."""
    selected = tuple(feature_columns)
    if selected == APPROVED_FEATURE_COLUMNS:
        return FULL_FEATURE_SET_ID
    if selected == IDENTITY_ABLATION_FEATURE_COLUMNS:
        return IDENTITY_ABLATION_FEATURE_SET_ID
    raise CandidateTrainingError("candidate feature set is not approved")


def _finite_target(target: pd.Series, *, source: str) -> np.ndarray:
    """Return a finite one-dimensional floating-point target."""
    values = pd.to_numeric(target, errors="coerce").to_numpy(dtype="float64")
    if values.ndim != 1 or len(values) == 0:
        raise CandidateTrainingError(f"{source} must be one-dimensional")
    if not np.isfinite(values).all():
        raise CandidateTrainingError(f"{source} contains non-finite values")
    return values


def _normalize_family(family: ModelFamily | str) -> ModelFamily:
    """Return one approved model family."""
    try:
        return ModelFamily(family)
    except (TypeError, ValueError) as error:
        raise CandidateTrainingError(
            f"unknown model family: {family!r}"
        ) from error
