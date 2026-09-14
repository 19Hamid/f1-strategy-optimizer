"""Tests for frozen Phase 5 baseline contracts."""

import pytest

from app.baselines import (
    BASELINE_CONTRACT_VERSION,
    BASELINE_RANDOM_SEED,
    BASELINE_SPECS,
    DEVELOPMENT_EVALUATION_FOLDS,
    LAP_TIME_BASELINES,
    PIT_DURATION_BASELINES,
    PRIMARY_METRIC,
    REQUIRED_EXPERIMENT_PROVENANCE,
    SECONDARY_METRICS,
    BaselineContractError,
    BaselineId,
    BaselineTask,
    baseline_spec,
    validate_baseline_contract,
)


def test_contract_identity_and_temporal_folds_are_frozen() -> None:
    """Keep Phase 5 on development folds without touching 2025."""
    assert BASELINE_CONTRACT_VERSION == "1.0"
    assert BASELINE_RANDOM_SEED == 42
    assert DEVELOPMENT_EVALUATION_FOLDS == (
        "development_fold_1",
        "development_fold_2",
    )


def test_all_seven_baselines_have_unique_stable_ids() -> None:
    """Expose four lap and three pit-duration reference methods."""
    assert tuple(spec.baseline_id for spec in BASELINE_SPECS) == (
        BaselineId.PREVIOUS_VALID_LAP,
        BaselineId.ROLLING_MEDIAN_3,
        BaselineId.STINT_LINEAR_TREND,
        BaselineId.CIRCUIT_COMPOUND_MEDIAN,
        BaselineId.PIT_GLOBAL_MEDIAN,
        BaselineId.PIT_CIRCUIT_MEDIAN,
        BaselineId.PIT_CIRCUIT_TRANSITION_MEDIAN,
    )
    assert len(LAP_TIME_BASELINES) == 4
    assert len(PIT_DURATION_BASELINES) == 3


def test_lap_baselines_keep_fitted_and_online_sources_distinct() -> None:
    """Require training fits only for the historical aggregate."""
    assert [spec.fit_required for spec in LAP_TIME_BASELINES] == [
        False,
        False,
        False,
        True,
    ]
    assert all(spec.task == BaselineTask.LAP_TIME for spec in LAP_TIME_BASELINES)


def test_pit_duration_baselines_are_training_only_estimators() -> None:
    """Every pit-duration estimate must be learned from training races."""
    assert all(spec.fit_required for spec in PIT_DURATION_BASELINES)
    assert all(
        spec.task == BaselineTask.PIT_DURATION
        for spec in PIT_DURATION_BASELINES
    )


def test_fallback_chains_are_explicit_and_task_local() -> None:
    """Prevent validation-driven or cross-target fallback invention."""
    assert baseline_spec(BaselineId.ROLLING_MEDIAN_3).fallback_ids == (
        BaselineId.PREVIOUS_VALID_LAP,
    )
    assert baseline_spec(
        BaselineId.PIT_CIRCUIT_TRANSITION_MEDIAN
    ).fallback_ids == (
        BaselineId.PIT_CIRCUIT_MEDIAN,
        BaselineId.PIT_GLOBAL_MEDIAN,
    )
    validate_baseline_contract()


def test_unknown_baseline_identity_fails_closed() -> None:
    """Reject unregistered methods before an experiment begins."""
    with pytest.raises(BaselineContractError, match="unknown baseline_id"):
        baseline_spec("definitely_not_science")


def test_metrics_and_provenance_are_frozen() -> None:
    """Preserve the evaluation scorecard and experiment identity."""
    assert PRIMARY_METRIC == "mean_absolute_error_seconds"
    assert SECONDARY_METRICS == (
        "root_mean_squared_error_seconds",
        "median_absolute_error_seconds",
        "p90_absolute_error_seconds",
        "mean_signed_error_seconds",
    )
    assert {
        "dataset_contract_version",
        "dataset_build_identifier",
        "fold_id",
        "training_sessions",
        "validation_sessions",
        "baseline_id",
        "fallback_counts",
        "dependency_versions",
        "execution_time_seconds",
    } <= set(REQUIRED_EXPERIMENT_PROVENANCE)
