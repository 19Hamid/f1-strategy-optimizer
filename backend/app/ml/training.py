"""Train deterministic Phase 6 candidate regressors."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
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
from xgboost import XGBRegressor

from app.ml.contracts import (
    APPROVED_FEATURE_COLUMNS,
    IDENTITY_ABLATION_FEATURE_COLUMNS,
    MODEL_CANDIDATE_COUNT,
    MODEL_RANDOM_SEED,
    MODEL_SPECS,
    ModelFamily,
    ModelTarget,
    PredictionFormulation,
    model_spec,
)
from app.ml.matrices import FoldTrainingMatrix, TrainingMatrixPartition
from app.ml.preprocessing import (
    FittedModelPreprocessor,
    fit_model_preprocessor,
)

FULL_FEATURE_SET_ID: Final = "full"
IDENTITY_ABLATION_FEATURE_SET_ID: Final = "without_driver_team"
RANDOM_FOREST_N_JOBS: Final = -1
XGBOOST_DEVICE_ENVIRONMENT_VARIABLE: Final = "F1_STRATEGY_XGBOOST_DEVICE"
XGBOOST_DEFAULT_DEVICE: Final = "cpu"
XGBOOST_ALLOWED_DEVICES: Final = frozenset({"cpu", "cuda"})
XGBOOST_N_JOBS: Final = -1
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
    execution_device: str = "cpu"

    @property
    def formulation(self) -> PredictionFormulation:
        """Identify direct absolute-target prediction."""
        return PredictionFormulation.DIRECT_ABSOLUTE

    @property
    def feature_columns(self) -> tuple[str, ...]:
        """Return the raw feature schema expected at inference."""
        return self.preprocessor.feature_columns

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
            raise CandidateTrainingError("estimator returned non-finite predictions")
        return predictions


@dataclass(frozen=True, slots=True)
class ResidualHybridModel:
    """Use predicted lap change with a direct fallback for full coverage."""

    fold_id: str
    direct_model: TrainedCandidateModel
    delta_model: TrainedCandidateModel

    def __post_init__(self) -> None:
        """Require matching candidates trained for complementary targets."""
        if not self.fold_id.strip():
            raise CandidateTrainingError("hybrid fold_id must not be blank")
        if self.direct_model.fold_id != self.fold_id:
            raise CandidateTrainingError("direct model fold differs from hybrid")
        if self.delta_model.fold_id != self.fold_id:
            raise CandidateTrainingError("delta model fold differs from hybrid")
        if self.direct_model.target != ModelTarget.LAP_TIME:
            raise CandidateTrainingError("hybrid direct model must predict LAP_TIME")
        if self.delta_model.target != ModelTarget.LAP_TIME_DELTA:
            raise CandidateTrainingError(
                "hybrid residual model must predict LAP_TIME_DELTA"
            )
        attributes = (
            "family",
            "candidate_id",
            "feature_set_id",
            "parameters",
            "feature_columns",
            "execution_device",
        )
        mismatches = [
            name
            for name in attributes
            if getattr(self.direct_model, name) != getattr(self.delta_model, name)
        ]
        if mismatches:
            raise CandidateTrainingError(
                "hybrid component models differ: " + ", ".join(mismatches)
            )

    @property
    def target(self) -> ModelTarget:
        """Expose the absolute prediction returned by the hybrid."""
        return ModelTarget.LAP_TIME

    @property
    def formulation(self) -> PredictionFormulation:
        """Identify residual prediction with direct fallback."""
        return PredictionFormulation.RESIDUAL_HYBRID

    @property
    def family(self) -> ModelFamily:
        """Return the shared estimator family."""
        return self.direct_model.family

    @property
    def candidate_id(self) -> str:
        """Return the shared frozen grid identity."""
        return self.direct_model.candidate_id

    @property
    def feature_set_id(self) -> str:
        """Return the shared full or ablated feature identity."""
        return self.direct_model.feature_set_id

    @property
    def parameters(self) -> tuple[tuple[str, object], ...]:
        """Return shared canonical estimator parameters."""
        return self.direct_model.parameters

    @property
    def feature_columns(self) -> tuple[str, ...]:
        """Return the raw feature schema expected at inference."""
        return self.direct_model.feature_columns

    @property
    def execution_device(self) -> str:
        """Return the shared component execution device."""
        return self.direct_model.execution_device

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        """Predict absolute lap time while retaining direct fallback rows."""
        direct = self.direct_model.predict(features)
        previous = pd.to_numeric(
            features["previous_lap_time_seconds"],
            errors="coerce",
        ).to_numpy(dtype="float64")
        previous_valid = (
            features["previous_lap_was_target_eligible"].eq(True).to_numpy()
        )
        residual_mask = previous_valid & np.isfinite(previous) & (previous > 0)
        if residual_mask.any():
            residual_features = features.loc[residual_mask].reset_index(drop=True)
            predicted_delta = self.delta_model.predict(residual_features)
            direct[residual_mask] = previous[residual_mask] + predicted_delta
        if not np.isfinite(direct).all():
            raise CandidateTrainingError("hybrid model returned non-finite predictions")
        return direct


CandidateModel = TrainedCandidateModel | ResidualHybridModel


@dataclass(frozen=True, slots=True)
class CandidateTrainingResult:
    """A fitted candidate and its held-out validation predictions."""

    model: CandidateModel
    validation_predictions: pd.DataFrame

    def __post_init__(self) -> None:
        """Require the exact auditable prediction schema."""
        if tuple(self.validation_predictions.columns) != PREDICTION_COLUMNS:
            raise CandidateTrainingError(
                "validation prediction columns differ from contract"
            )
        if self.validation_predictions.empty:
            raise CandidateTrainingError("validation predictions must not be empty")

    @property
    def mean_absolute_error_seconds(self) -> float:
        """Return held-out mean absolute error for quick diagnostics."""
        return float(self.validation_predictions["absolute_error_seconds"].mean())


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
    model = fit_candidate_model(
        matrix.training,
        fold_id=matrix.fold_id,
        target=matrix.target,
        family=family,
        parameters=parameters,
        feature_columns=feature_columns,
    )
    return score_candidate_model(model, matrix)


def score_candidate_model(
    model: CandidateModel,
    matrix: FoldTrainingMatrix,
) -> CandidateTrainingResult:
    """Score a fitted direct or residual-hybrid model on one held-out fold."""
    if not isinstance(model, (TrainedCandidateModel, ResidualHybridModel)):
        raise TypeError("model must be a trained candidate model")
    if not isinstance(matrix, FoldTrainingMatrix):
        raise TypeError("matrix must be a FoldTrainingMatrix")
    if model.fold_id != matrix.fold_id:
        raise CandidateTrainingError("model and validation fold differ")
    if model.target != matrix.target:
        raise CandidateTrainingError("model and validation target differ")
    validation_target = _finite_target(
        matrix.validation.target,
        source="validation target",
    )
    predictions = model.predict(matrix.validation.features)
    validation_rows = matrix.validation.identities.copy()
    validation_rows["fold_id"] = matrix.fold_id
    validation_rows["target"] = matrix.target.value
    validation_rows["model_family"] = model.family.value
    validation_rows["candidate_id"] = model.candidate_id
    validation_rows["feature_set_id"] = model.feature_set_id
    validation_rows["target_seconds"] = validation_target
    validation_rows["prediction_seconds"] = predictions
    validation_rows["absolute_error_seconds"] = np.abs(validation_target - predictions)
    validation_rows = validation_rows.loc[:, PREDICTION_COLUMNS]
    return CandidateTrainingResult(
        model=model,
        validation_predictions=validation_rows,
    )


def fit_candidate_model(
    training: TrainingMatrixPartition,
    *,
    fold_id: str,
    target: ModelTarget | str,
    family: ModelFamily | str,
    parameters: dict[str, object],
    feature_columns: tuple[str, ...] = APPROVED_FEATURE_COLUMNS,
) -> TrainedCandidateModel:
    """Fit one approved candidate without requiring a validation partition."""
    if not isinstance(training, TrainingMatrixPartition):
        raise TypeError("training must be a TrainingMatrixPartition")
    normalized_fold = fold_id.strip()
    if not normalized_fold:
        raise CandidateTrainingError("fold_id must not be blank")
    try:
        normalized_target = ModelTarget(target)
    except (TypeError, ValueError) as error:
        raise CandidateTrainingError(f"unknown model target: {target!r}") from error
    normalized_family = _normalize_family(family)
    normalized_parameters = _validate_parameters(
        family=normalized_family,
        parameters=parameters,
    )
    feature_set_id = _feature_set_id(feature_columns)
    preprocessor = fit_model_preprocessor(
        training.features,
        family=normalized_family,
        feature_columns=feature_columns,
    )
    training_features = preprocessor.transform(training.features)
    training_target = _finite_target(
        training.target,
        source="training target",
    )
    estimator = _build_estimator(
        family=normalized_family,
        parameters=dict(normalized_parameters),
    )
    estimator.fit(training_features, training_target)

    return TrainedCandidateModel(
        fold_id=normalized_fold,
        target=normalized_target,
        family=normalized_family,
        candidate_id=_candidate_id(
            normalized_family,
            dict(normalized_parameters),
        ),
        feature_set_id=feature_set_id,
        parameters=normalized_parameters,
        preprocessor=preprocessor,
        estimator=estimator,
        execution_device=(
            xgboost_execution_device()
            if normalized_family == ModelFamily.XGBOOST
            else "cpu"
        ),
    )


def train_fold_candidates(
    matrix: FoldTrainingMatrix,
    *,
    feature_columns: tuple[str, ...] = APPROVED_FEATURE_COLUMNS,
    progress: Callable[[int, int, str], None] | None = None,
) -> tuple[CandidateTrainingResult, ...]:
    """Fit every frozen configuration for one target and fold."""
    candidates = tuple(
        (specification.family, dict(parameters))
        for specification in MODEL_SPECS
        for parameters in specification.parameter_grid
    )
    expected = MODEL_CANDIDATE_COUNT
    results: list[CandidateTrainingResult] = []
    for ordinal, (family, parameters) in enumerate(candidates, start=1):
        candidate_id = _candidate_id(family, parameters)
        if progress is not None:
            progress(ordinal, expected, candidate_id)
        results.append(
            train_candidate_model(
                matrix,
                family=family,
                parameters=parameters,
                feature_columns=feature_columns,
            )
        )
    if len(results) != expected:
        raise CandidateTrainingError(
            f"expected {expected} candidate results, received {len(results)}"
        )
    identities = tuple(result.model.candidate_id for result in results)
    if len(identities) != len(set(identities)):
        raise CandidateTrainingError("candidate identities are not unique")
    return tuple(results)


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
            n_jobs=RANDOM_FOREST_N_JOBS,
        )
    if family == ModelFamily.HIST_GRADIENT_BOOSTING:
        return HistGradientBoostingRegressor(
            **parameters,
            random_state=MODEL_RANDOM_SEED,
        )
    if family == ModelFamily.XGBOOST:
        return XGBRegressor(
            **parameters,
            device=xgboost_execution_device(),
            tree_method="hist",
            random_state=MODEL_RANDOM_SEED,
            n_jobs=XGBOOST_N_JOBS,
            verbosity=0,
        )
    raise CandidateTrainingError(f"unsupported model family: {family.value}")


def xgboost_execution_device() -> str:
    """Return the explicit CPU or CUDA device selected for XGBoost."""
    device = os.environ.get(
        XGBOOST_DEVICE_ENVIRONMENT_VARIABLE,
        XGBOOST_DEFAULT_DEVICE,
    ).strip().lower()
    if device not in XGBOOST_ALLOWED_DEVICES:
        allowed = ", ".join(sorted(XGBOOST_ALLOWED_DEVICES))
        raise CandidateTrainingError(
            f"{XGBOOST_DEVICE_ENVIRONMENT_VARIABLE} must be one of: {allowed}"
        )
    return device


def validate_xgboost_runtime() -> str:
    """Fail early when the requested XGBoost device is unavailable."""
    requested = xgboost_execution_device()
    estimator = XGBRegressor(
        n_estimators=1,
        max_depth=1,
        objective="reg:squarederror",
        tree_method="hist",
        device=requested,
        random_state=MODEL_RANDOM_SEED,
        n_jobs=XGBOOST_N_JOBS,
        verbosity=0,
    )
    estimator.fit(
        np.asarray([[0.0], [1.0], [2.0], [3.0]], dtype="float64"),
        np.asarray([0.0, 1.0, 2.0, 3.0], dtype="float64"),
    )
    configuration = json.loads(estimator.get_booster().save_config())
    actual = str(configuration["learner"]["generic_param"]["device"])
    if requested == "cuda" and not actual.startswith("cuda"):
        raise CandidateTrainingError(
            "XGBoost requested CUDA but initialized a non-CUDA device"
        )
    if requested == "cpu" and actual != "cpu":
        raise CandidateTrainingError(
            "XGBoost requested CPU but initialized a different device"
        )
    return actual


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
    raise CandidateTrainingError(f"parameters are outside the {family.value} grid")


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
        raise CandidateTrainingError(f"parameters are outside the {family.value} grid")
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
        raise CandidateTrainingError(f"unknown model family: {family!r}") from error
