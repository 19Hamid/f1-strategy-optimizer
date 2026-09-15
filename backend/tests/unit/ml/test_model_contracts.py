"""Tests for the frozen Phase 6 model contract."""

import pytest

from app.datasets import DECISION_MODEL_FEATURE_COLUMNS
from app.ml import (
    APPROVED_FEATURE_COLUMNS,
    AUXILIARY_TARGET_COLUMN,
    CATEGORICAL_FEATURE_COLUMNS,
    DEVELOPMENT_FOLDS,
    FORBIDDEN_MODEL_COLUMNS,
    IDENTITY_ABLATION_FEATURE_COLUMNS,
    IDENTITY_DEPENDENCE_COLUMNS,
    MINIMUM_PRIMARY_COVERAGE,
    MODEL_CONTRACT_VERSION,
    MODEL_RANDOM_SEED,
    MODEL_SPECS,
    NUMERIC_FEATURE_COLUMNS,
    PRIMARY_BASELINE_ID,
    PRIMARY_BASELINE_MAE_SECONDS,
    PRIMARY_TARGET_COLUMN,
    ModelContractError,
    ModelFamily,
    ModelSpec,
    ModelTarget,
    model_spec,
    validate_model_contract,
)


def test_contract_records_hamid_approved_scope() -> None:
    """Freeze the selected models, targets and full safe feature set."""
    assert MODEL_CONTRACT_VERSION == "1.0"
    assert MODEL_RANDOM_SEED == 42
    assert {specification.family for specification in MODEL_SPECS} == {
        ModelFamily.RIDGE,
        ModelFamily.RANDOM_FOREST,
        ModelFamily.HIST_GRADIENT_BOOSTING,
    }
    assert {target.value for target in ModelTarget} == {
        "LAP_TIME",
        "LAP_TIME_DELTA",
    }
    assert APPROVED_FEATURE_COLUMNS == DECISION_MODEL_FEATURE_COLUMNS


def test_feature_partitions_are_exact_and_disjoint() -> None:
    """Assign every approved feature to one preprocessing route."""
    partitions = (
        set(CATEGORICAL_FEATURE_COLUMNS),
        {"previous_lap_was_target_eligible"},
        set(NUMERIC_FEATURE_COLUMNS),
    )
    assert set().union(*partitions) == set(APPROVED_FEATURE_COLUMNS)
    assert all(
        not left & right
        for index, left in enumerate(partitions)
        for right in partitions[index + 1 :]
    )
    validate_model_contract()


def test_labels_targets_and_post_decision_quality_are_forbidden() -> None:
    """Keep answer columns outside the model matrix."""
    assert not set(APPROVED_FEATURE_COLUMNS) & FORBIDDEN_MODEL_COLUMNS
    assert PRIMARY_TARGET_COLUMN == "lap_time_target_seconds"
    assert AUXILIARY_TARGET_COLUMN == "lap_time_delta_seconds"
    assert {
        "historical_action",
        "did_pit",
        "is_lap_time_target_eligible",
        "is_decision_eligible",
    } <= FORBIDDEN_MODEL_COLUMNS


def test_identity_aware_primary_set_has_mandatory_ablation() -> None:
    """Measure dependence on driver and team instead of hiding it."""
    assert IDENTITY_DEPENDENCE_COLUMNS == ("driver", "team")
    assert set(IDENTITY_DEPENDENCE_COLUMNS).isdisjoint(
        IDENTITY_ABLATION_FEATURE_COLUMNS
    )
    assert set(IDENTITY_ABLATION_FEATURE_COLUMNS) == (
        set(APPROVED_FEATURE_COLUMNS) - set(IDENTITY_DEPENDENCE_COLUMNS)
    )
    assert "event_name" in IDENTITY_ABLATION_FEATURE_COLUMNS


def test_phase_five_threshold_is_frozen() -> None:
    """Prevent Phase 6 from moving the goalposts after training."""
    assert PRIMARY_BASELINE_ID == "previous_valid_lap"
    assert PRIMARY_BASELINE_MAE_SECONDS == pytest.approx(0.410049)
    assert MINIMUM_PRIMARY_COVERAGE == pytest.approx(0.970376)


def test_search_space_is_bounded_and_reproducible() -> None:
    """Keep candidate comparison meaningful on a student workstation."""
    grid_sizes = {
        specification.family: len(specification.parameter_grid)
        for specification in MODEL_SPECS
    }
    assert grid_sizes == {
        ModelFamily.RIDGE: 3,
        ModelFamily.RANDOM_FOREST: 4,
        ModelFamily.HIST_GRADIENT_BOOSTING: 8,
    }
    assert sum(grid_sizes.values()) == 15


def test_development_folds_exclude_protected_evaluation() -> None:
    """Use the same chronological folds as the Phase 5 benchmark."""
    assert DEVELOPMENT_FOLDS == (
        "development_fold_1",
        "development_fold_2",
    )


def test_unknown_model_family_is_rejected() -> None:
    """Callers cannot silently introduce an unreviewed algorithm."""
    with pytest.raises(ModelContractError, match="unknown model family"):
        model_spec("xgboost")


def test_model_spec_rejects_duplicate_parameters() -> None:
    """Each hyperparameter candidate must be uniquely identified."""
    with pytest.raises(ModelContractError, match="duplicates"):
        ModelSpec(
            family=ModelFamily.RIDGE,
            description="duplicate test",
            parameter_grid=({"alpha": 1.0}, {"alpha": 1.0}),
        )
