"""Tests for deterministic Phase 6 candidate training."""

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from xgboost import XGBRegressor

from app.ml import (
    APPROVED_FEATURE_COLUMNS,
    IDENTITY_ABLATION_FEATURE_COLUMNS,
    MODEL_CANDIDATE_COUNT,
    NUMERIC_FEATURE_COLUMNS,
    FoldTrainingMatrix,
    ModelFamily,
    ModelTarget,
    PredictionFormulation,
    ResidualHybridModel,
    TrainingMatrixPartition,
    model_spec,
    training,
)
from app.ml.training import (
    FULL_FEATURE_SET_ID,
    IDENTITY_ABLATION_FEATURE_SET_ID,
    PREDICTION_COLUMNS,
    RANDOM_FOREST_N_JOBS,
    XGBOOST_DEVICE_ENVIRONMENT_VARIABLE,
    XGBOOST_N_JOBS,
    CandidateTrainingError,
    score_candidate_model,
    train_candidate_model,
    train_fold_candidates,
    validate_xgboost_runtime,
    xgboost_execution_device,
)


def _features(rows: int, *, offset: int = 0) -> pd.DataFrame:
    """Build an exact model feature frame with learnable variation."""
    records: list[dict[str, object]] = []
    for index in range(rows):
        value = index + offset
        record: dict[str, object] = {
            column: float(value + column_index + 1)
            for column_index, column in enumerate(NUMERIC_FEATURE_COLUMNS)
        }
        record.update(
            {
                "event_name": ("Bahrain GP", "Saudi GP")[value % 2],
                "driver": ("HAM", "LEC", "RUS")[value % 3],
                "team": ("Ferrari", "Mercedes")[value % 2],
                "current_compound": ("SOFT", "MEDIUM", "HARD")[value % 3],
                "previous_lap_was_target_eligible": value % 2 == 0,
            }
        )
        records.append(record)
    return pd.DataFrame.from_records(
        records,
        columns=APPROVED_FEATURE_COLUMNS,
    )


def _partition(
    rows: int,
    *,
    season: int,
    prefix: str,
    target: ModelTarget,
    offset: int = 0,
) -> TrainingMatrixPartition:
    """Build one aligned synthetic model partition."""
    features = _features(rows, offset=offset)
    identities = pd.DataFrame(
        {
            "decision_id": [f"{prefix}-decision-{index}" for index in range(rows)],
            "session_id": [f"{season}-01-R"] * rows,
            "season": [season] * rows,
        }
    )
    base = 70.0 + features["decision_lap"] * 0.2 + features["tyre_age_laps"] * 0.05
    if target == ModelTarget.LAP_TIME_DELTA:
        base = base - base.mean()
        name = "lap_time_delta_seconds"
    else:
        name = "lap_time_target_seconds"
    return TrainingMatrixPartition(
        identities=identities,
        features=features,
        target=base.astype("float64").rename(name).reset_index(drop=True),
    )


def _matrix(
    target: ModelTarget = ModelTarget.LAP_TIME,
) -> FoldTrainingMatrix:
    """Build one chronological fold for candidate tests."""
    return FoldTrainingMatrix(
        fold_id="development_fold_1",
        target=target,
        training=_partition(
            12,
            season=2022,
            prefix="train",
            target=target,
        ),
        validation=_partition(
            5,
            season=2023,
            prefix="validation",
            target=target,
            offset=20,
        ),
    )


def _first_parameters(family: ModelFamily) -> dict[str, object]:
    """Return the first frozen grid entry for a family."""
    return dict(model_spec(family).parameter_grid[0])


def _patch_fast_xgboost(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep unit tests small without changing the frozen production grid."""
    original = training._build_estimator

    def build(*, family: ModelFamily, parameters: dict[str, object]):
        if family != ModelFamily.XGBOOST:
            return original(family=family, parameters=parameters)
        lightweight = {**parameters, "n_estimators": 2}
        return XGBRegressor(
            **lightweight,
            device=training.xgboost_execution_device(),
            tree_method="hist",
            random_state=training.MODEL_RANDOM_SEED,
            n_jobs=XGBOOST_N_JOBS,
            verbosity=0,
        )

    monkeypatch.setattr(training, "_build_estimator", build)


@pytest.mark.parametrize("family", tuple(ModelFamily))
def test_each_model_family_fits_and_predicts(
    family: ModelFamily,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Train every approved estimator through the same safe interface."""
    _patch_fast_xgboost(monkeypatch)
    matrix = _matrix()
    result = train_candidate_model(
        matrix,
        family=family,
        parameters=_first_parameters(family),
    )
    assert result.model.family == family
    assert result.model.feature_set_id == FULL_FEATURE_SET_ID
    assert tuple(result.validation_predictions.columns) == PREDICTION_COLUMNS
    assert len(result.validation_predictions) == matrix.validation.row_count
    assert np.isfinite(result.validation_predictions["prediction_seconds"]).all()
    assert result.mean_absolute_error_seconds >= 0.0


def test_full_fold_training_runs_every_frozen_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fit every bounded grid member exactly once."""
    _patch_fast_xgboost(monkeypatch)
    results = train_fold_candidates(_matrix())
    assert len(results) == MODEL_CANDIDATE_COUNT == 23
    identities = tuple(result.model.candidate_id for result in results)
    assert len(identities) == len(set(identities))
    assert {result.model.family for result in results} == set(ModelFamily)
    assert identities[:3] == ("ridge_01", "ridge_02", "ridge_03")


def test_random_forest_is_reproducible_with_frozen_seed() -> None:
    """Produce identical predictions across repeated deterministic fits."""
    matrix = _matrix()
    parameters = _first_parameters(ModelFamily.RANDOM_FOREST)
    first = train_candidate_model(
        matrix,
        family=ModelFamily.RANDOM_FOREST,
        parameters=parameters,
    )
    second = train_candidate_model(
        matrix,
        family=ModelFamily.RANDOM_FOREST,
        parameters=parameters,
    )
    assert np.array_equal(
        first.validation_predictions["prediction_seconds"],
        second.validation_predictions["prediction_seconds"],
    )
    assert first.model.estimator.n_jobs == RANDOM_FOREST_N_JOBS == -1


def test_fold_training_reports_each_candidate_before_fitting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expose granular progress during the expensive real-data audit."""
    _patch_fast_xgboost(monkeypatch)
    updates: list[tuple[int, int, str]] = []

    train_fold_candidates(_matrix(), progress=lambda *values: updates.append(values))

    assert len(updates) == MODEL_CANDIDATE_COUNT
    assert updates[0] == (1, MODEL_CANDIDATE_COUNT, "ridge_01")
    assert updates[-1] == (
        MODEL_CANDIDATE_COUNT,
        MODEL_CANDIDATE_COUNT,
        "xgboost_08",
    )


def test_xgboost_uses_explicit_cpu_device_and_full_thread_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep unit fits portable while preserving the production device switch."""
    monkeypatch.setenv(XGBOOST_DEVICE_ENVIRONMENT_VARIABLE, "cpu")
    parameters = _first_parameters(ModelFamily.XGBOOST)
    estimator = training._build_estimator(
        family=ModelFamily.XGBOOST,
        parameters=parameters,
    )

    assert estimator.n_estimators == parameters["n_estimators"] == 800
    assert estimator.device == "cpu"
    assert estimator.tree_method == "hist"
    assert estimator.n_jobs == XGBOOST_N_JOBS == -1
    assert validate_xgboost_runtime() == "cpu"


def test_xgboost_device_configuration_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject typos instead of silently training on unintended hardware."""
    monkeypatch.setenv(XGBOOST_DEVICE_ENVIRONMENT_VARIABLE, "magic")

    with pytest.raises(CandidateTrainingError, match="must be one of"):
        xgboost_execution_device()


def test_validation_predictions_preserve_audit_identity() -> None:
    """Keep race and decision identity beside every held-out estimate."""
    matrix = _matrix()
    result = train_candidate_model(
        matrix,
        family=ModelFamily.RIDGE,
        parameters=_first_parameters(ModelFamily.RIDGE),
    )
    predictions = result.validation_predictions
    assert tuple(predictions["decision_id"]) == tuple(
        matrix.validation.identities["decision_id"]
    )
    assert predictions["fold_id"].eq(matrix.fold_id).all()
    assert predictions["target"].eq(ModelTarget.LAP_TIME.value).all()
    assert predictions["model_family"].eq(ModelFamily.RIDGE.value).all()


def test_identity_ablation_uses_separate_candidate_schema() -> None:
    """Train without driver and team while retaining all other features."""
    result = train_candidate_model(
        _matrix(),
        family=ModelFamily.RIDGE,
        parameters=_first_parameters(ModelFamily.RIDGE),
        feature_columns=IDENTITY_ABLATION_FEATURE_COLUMNS,
    )
    assert result.model.feature_set_id == IDENTITY_ABLATION_FEATURE_SET_ID
    assert result.model.preprocessor.feature_columns == (
        IDENTITY_ABLATION_FEATURE_COLUMNS
    )
    assert not any(
        column.startswith(("driver==", "team=="))
        for column in result.model.preprocessor.output_columns
    )


def test_auxiliary_target_can_contain_negative_changes() -> None:
    """Allow valid faster and slower lap changes around zero."""
    matrix = _matrix(ModelTarget.LAP_TIME_DELTA)
    result = train_candidate_model(
        matrix,
        family=ModelFamily.RIDGE,
        parameters=_first_parameters(ModelFamily.RIDGE),
    )
    assert result.validation_predictions["target_seconds"].lt(0).any()
    assert result.validation_predictions["target_seconds"].gt(0).any()


def test_residual_hybrid_uses_delta_only_with_valid_previous_lap() -> None:
    """Preserve full coverage by falling back to the direct prediction."""
    primary = _matrix()
    auxiliary = _matrix(ModelTarget.LAP_TIME_DELTA)
    parameters = _first_parameters(ModelFamily.RIDGE)
    direct = train_candidate_model(
        primary,
        family=ModelFamily.RIDGE,
        parameters=parameters,
    ).model
    delta = train_candidate_model(
        auxiliary,
        family=ModelFamily.RIDGE,
        parameters=parameters,
    ).model
    hybrid = ResidualHybridModel(
        fold_id=primary.fold_id,
        direct_model=direct,
        delta_model=delta,
    )
    features = primary.validation.features
    valid = features["previous_lap_was_target_eligible"].eq(True).to_numpy()
    expected = direct.predict(features)
    expected[valid] = features.loc[
        valid, "previous_lap_time_seconds"
    ].to_numpy() + delta.predict(features.loc[valid].reset_index(drop=True))

    result = score_candidate_model(hybrid, primary)

    assert hybrid.formulation == PredictionFormulation.RESIDUAL_HYBRID
    assert np.array_equal(
        result.validation_predictions["prediction_seconds"],
        expected,
    )
    assert len(result.validation_predictions) == primary.validation.row_count


def test_training_does_not_mutate_source_feature_frames() -> None:
    """Keep authoritative matrices unchanged after fit and prediction."""
    matrix = _matrix()
    training_before = matrix.training.features.copy(deep=True)
    validation_before = matrix.validation.features.copy(deep=True)
    train_candidate_model(
        matrix,
        family=ModelFamily.HIST_GRADIENT_BOOSTING,
        parameters=_first_parameters(ModelFamily.HIST_GRADIENT_BOOSTING),
    )
    assert_frame_equal(matrix.training.features, training_before)
    assert_frame_equal(matrix.validation.features, validation_before)


def test_parameters_outside_frozen_grid_are_rejected() -> None:
    """Prevent silent tuning beyond the owner-approved search space."""
    with pytest.raises(CandidateTrainingError, match="outside the ridge grid"):
        train_candidate_model(
            _matrix(),
            family=ModelFamily.RIDGE,
            parameters={"alpha": 999.0},
        )


def test_unapproved_feature_subset_is_rejected() -> None:
    """Restrict training to full features or the mandated ablation."""
    with pytest.raises(CandidateTrainingError, match="not approved"):
        train_candidate_model(
            _matrix(),
            family=ModelFamily.RIDGE,
            parameters=_first_parameters(ModelFamily.RIDGE),
            feature_columns=APPROVED_FEATURE_COLUMNS[:-1],
        )


@pytest.mark.parametrize("partition_name", ("training", "validation"))
def test_non_finite_target_is_rejected(partition_name: str) -> None:
    """Fail closed when either fit or score targets are invalid."""
    matrix = _matrix()
    partition = getattr(matrix, partition_name)
    partition.target.iloc[0] = np.nan
    with pytest.raises(CandidateTrainingError, match="non-finite"):
        train_candidate_model(
            matrix,
            family=ModelFamily.RIDGE,
            parameters=_first_parameters(ModelFamily.RIDGE),
        )


def test_unknown_model_family_is_rejected() -> None:
    """Only instantiate a family frozen in the modelling contract."""
    with pytest.raises(CandidateTrainingError, match="unknown model family"):
        train_candidate_model(
            _matrix(),
            family="neural_network",
            parameters={},
        )
