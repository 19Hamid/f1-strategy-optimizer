"""Tests for deterministic sequential Phase 9 scenario aggregation."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.concurrent_simulation import (
    SCENARIO_GENERATOR_ID,
    UNCERTAINTY_CALIBRATION_METHOD_ID,
    ScenarioBatch,
    ScenarioBatchRequest,
    UncertaintyCalibration,
    generate_scenario_batch,
)
from app.concurrent_simulation.aggregation import (
    MINIMUM_STABILITY_SCENARIO_COUNT,
    SCENARIO_INTERVAL_LOWER_QUANTILE,
    SCENARIO_INTERVAL_UPPER_QUANTILE,
    SEQUENTIAL_AGGREGATOR_ID,
    ScenarioOutcome,
    ScenarioPreference,
    SequentialScenarioEvaluation,
    evaluate_scenario_batch_sequentially,
    summarize_scenario_distribution,
)
from app.concurrent_simulation.contracts import ConcurrentSimulationContractError
from app.datasets.contracts import DEVELOPMENT_SEASONS
from app.ml import (
    APPROVED_FEATURE_COLUMNS,
    FINAL_DEVELOPMENT_FIT_ID,
    FULL_FEATURE_SET_ID,
    MODEL_CONTRACT_VERSION,
    LoadedModelArtifact,
    ModelFamily,
    ModelTarget,
    PredictionFormulation,
)
from app.optimizer import PitDecisionRecommendation, PitDecisionRequest
from app.simulation import (
    DryCompound,
    Phase6ModelAdapter,
    PitLossAssumption,
    PitLossSource,
    RaceState,
    SimulationFeatureContext,
)
from app.simulation.model_adapter import SELECTED_SIMULATOR_CANDIDATE_ID


class _ConstantModel:
    def predict(self, features: pd.DataFrame) -> np.ndarray:
        return np.full(len(features), 90.0, dtype="float64")


class _TyreAgeModel:
    def predict(self, features: pd.DataFrame) -> np.ndarray:
        return 90.0 + features["tyre_age_laps"].to_numpy(dtype="float64")


def _adapter(model: object) -> Phase6ModelAdapter:
    provenance = SimpleNamespace(
        model_contract_version=MODEL_CONTRACT_VERSION,
        fold_id=FINAL_DEVELOPMENT_FIT_ID,
        target=ModelTarget.LAP_TIME,
        formulation=PredictionFormulation.RESIDUAL_HYBRID,
        family=ModelFamily.XGBOOST,
        candidate_id=SELECTED_SIMULATOR_CANDIDATE_ID,
        feature_set_id=FULL_FEATURE_SET_ID,
        execution_device="cuda",
        feature_columns=APPROVED_FEATURE_COLUMNS,
        training_seasons=DEVELOPMENT_SEASONS,
        validation_session_ids=(),
    )
    return Phase6ModelAdapter(
        LoadedModelArtifact(
            model=model,  # type: ignore[arg-type]
            provenance=provenance,  # type: ignore[arg-type]
        )
    )


def _context() -> SimulationFeatureContext:
    values: dict[str, object] = {
        "event_name": "Bahrain Grand Prix",
        "driver": "VER",
        "team": "Red Bull Racing",
        "decision_lap": 20,
        "current_compound": "MEDIUM",
        "tyre_age_laps": 19,
        "current_stint_laps_completed": 19,
        "completed_pit_stops": 0,
        "previous_position": 1,
        "previous_lap_was_target_eligible": True,
        "previous_lap_time_seconds": 94.0,
        "previous_sector1_time_seconds": 30.0,
        "previous_sector2_time_seconds": 31.0,
        "previous_sector3_time_seconds": 33.0,
        "eligible_laps_completed": 10,
        "rolling_lap_time_median_3": 93.0,
        "rolling_lap_time_median_5": 92.0,
        "rolling_lap_time_std_5": 1.414,
        "rolling_lap_time_trend_5": 1.0,
        "weather_age_seconds": 5.0,
        "air_temperature_celsius": 24.0,
        "humidity_percent": 40.0,
        "pressure_mbar": 1012.0,
        "track_temperature_celsius": 31.0,
        "wind_direction_degrees": 180.0,
        "wind_speed_mps": 2.5,
    }
    return SimulationFeatureContext(
        base_features=pd.DataFrame([values], columns=APPROVED_FEATURE_COLUMNS),
        recent_lap_times_seconds=(90.0, 91.0, 92.0, 93.0, 94.0),
    )


def _decision_request() -> PitDecisionRequest:
    return PitDecisionRequest(
        state=RaceState(
            season=2024,
            session_id="2024-01-R",
            event_name="Bahrain Grand Prix",
            driver="VER",
            team="Red Bull Racing",
            current_lap=20,
            total_laps=22,
            current_compound=DryCompound.MEDIUM,
            tyre_age_laps=19,
            current_stint_laps_completed=19,
            completed_pit_stops=0,
            compounds_used=(DryCompound.MEDIUM,),
            previous_position=1,
        ),
        target_compound=DryCompound.HARD,
        pit_loss=PitLossAssumption(
            seconds=20.0,
            source=PitLossSource.EXPLICIT_ASSUMPTION,
            evidence="aggregation unit-test assumption",
        ),
    )


def _batch(scenario_count: int = 3) -> ScenarioBatch:
    return generate_scenario_batch(
        ScenarioBatchRequest(
            _decision_request(),
            scenario_count=scenario_count,
            root_seed=123,
        )
    )


def _calibration() -> UncertaintyCalibration:
    return UncertaintyCalibration(
        calibration_id="aggregation-unit-calibration",
        method_id=UNCERTAINTY_CALIBRATION_METHOD_ID,
        training_seasons=(2022, 2023, 2024),
        shared_pace_scale_seconds=0.1,
        pit_loss_scale_seconds=0.1,
        lap_time_residual_scale_seconds=0.1,
        replay_count=10,
        lap_count=100,
        pit_loss_profile_count=3,
        evidence="aggregation unit-test development evidence",
    )


def _evaluate(model: object):
    return evaluate_scenario_batch_sequentially(
        _batch(),
        calibration=_calibration(),
        context=_context(),
        adapter=_adapter(model),
    )


def _preference(advantage: float) -> ScenarioPreference:
    if advantage > 0:
        return ScenarioPreference.PIT_NOW
    if advantage < 0:
        return ScenarioPreference.STAY_OUT
    return ScenarioPreference.TIE


def _evaluation_with_advantages(
    advantages: tuple[float, ...],
) -> SequentialScenarioEvaluation:
    batch = _batch(len(advantages))
    outcomes = tuple(
        ScenarioOutcome(
            scenario_index=scenario.scenario_index,
            scenario_seed=scenario.scenario_seed,
            pit_now_remaining_time_seconds=300.0,
            stay_out_remaining_time_seconds=300.0 + advantage,
            pit_now_advantage_seconds=advantage,
            preference=_preference(advantage),
        )
        for scenario, advantage in zip(
            batch.scenarios,
            advantages,
            strict=True,
        )
    )
    return SequentialScenarioEvaluation(
        batch=batch,
        calibration=_calibration(),
        aggregator_id=SEQUENTIAL_AGGREGATOR_ID,
        outcomes=outcomes,
    )


def test_distribution_uses_frozen_linear_quantiles() -> None:
    distribution = summarize_scenario_distribution((0.0, 10.0, 20.0))

    assert SCENARIO_INTERVAL_LOWER_QUANTILE == 0.05
    assert SCENARIO_INTERVAL_UPPER_QUANTILE == 0.95
    assert distribution.count == 3
    assert distribution.mean == pytest.approx(10.0)
    assert distribution.standard_deviation == pytest.approx(8.1649658093)
    assert distribution.minimum == 0.0
    assert distribution.p05 == pytest.approx(1.0)
    assert distribution.median == 10.0
    assert distribution.p95 == pytest.approx(19.0)
    assert distribution.maximum == 20.0


def test_sequential_execution_keeps_generated_order_and_identity() -> None:
    evaluation = _evaluate(_TyreAgeModel())

    assert evaluation.aggregator_id == SEQUENTIAL_AGGREGATOR_ID
    assert tuple(item.scenario_index for item in evaluation.outcomes) == (0, 1, 2)
    assert tuple(item.scenario_seed for item in evaluation.outcomes) == tuple(
        scenario.scenario_seed for scenario in evaluation.batch.scenarios
    )
    assert all(
        item.preference is ScenarioPreference.PIT_NOW
        for item in evaluation.outcomes
    )


def test_sequential_execution_is_exactly_deterministic() -> None:
    assert _evaluate(_TyreAgeModel()) == _evaluate(_TyreAgeModel())


def test_sequential_execution_preserves_input_context() -> None:
    context = _context()

    evaluate_scenario_batch_sequentially(
        _batch(),
        calibration=_calibration(),
        context=context,
        adapter=_adapter(_TyreAgeModel()),
    )

    assert context.simulated_lap_times_seconds == ()


def test_scenario_shares_are_descriptive_and_reconcile() -> None:
    evaluation = _evaluation_with_advantages((2.0, 1.0, -1.0, 0.0))

    assert evaluation.pit_now_scenario_share == pytest.approx(0.5)
    assert evaluation.stay_out_scenario_share == pytest.approx(0.25)
    assert evaluation.tie_scenario_share == pytest.approx(0.25)
    assert (
        evaluation.pit_now_scenario_share
        + evaluation.stay_out_scenario_share
        + evaluation.tie_scenario_share
    ) == pytest.approx(1.0)


def test_stable_pit_now_requires_complete_positive_central_interval() -> None:
    evaluation = _evaluation_with_advantages((1.0,) * 100)

    assert MINIMUM_STABILITY_SCENARIO_COUNT == 100
    assert evaluation.advantage_distribution.p05 == 1.0
    assert evaluation.recommendation is PitDecisionRecommendation.PIT_NOW
    assert evaluation.recommendation_is_stable


def test_stable_stay_out_requires_complete_negative_central_interval() -> None:
    evaluation = _evaluation_with_advantages((-1.0,) * 100)

    assert evaluation.advantage_distribution.p95 == -1.0
    assert evaluation.recommendation is PitDecisionRecommendation.STAY_OUT
    assert evaluation.recommendation_is_stable


def test_interval_crossing_zero_abstains() -> None:
    evaluation = _evaluation_with_advantages((-1.0,) * 50 + (1.0,) * 50)

    assert evaluation.advantage_distribution.p05 < 0
    assert evaluation.advantage_distribution.p95 > 0
    assert evaluation.recommendation is (
        PitDecisionRecommendation.NO_CLEAR_ADVANTAGE
    )
    assert not evaluation.recommendation_is_stable


def test_small_scenario_population_never_claims_stability() -> None:
    evaluation = _evaluation_with_advantages((10.0,) * 99)

    assert evaluation.advantage_distribution.p05 > 0
    assert evaluation.recommendation is (
        PitDecisionRecommendation.NO_CLEAR_ADVANTAGE
    )


def test_constant_model_produces_tied_worlds_without_fake_preference() -> None:
    evaluation = _evaluate(_ConstantModel())

    assert evaluation.tie_scenario_share == 1.0
    assert evaluation.advantage_distribution.minimum == pytest.approx(0.0)
    assert evaluation.advantage_distribution.maximum == pytest.approx(0.0)
    assert evaluation.recommendation is (
        PitDecisionRecommendation.NO_CLEAR_ADVANTAGE
    )


def test_outcome_rejects_unreconciled_advantage() -> None:
    with pytest.raises(ConcurrentSimulationContractError, match="reconcile"):
        ScenarioOutcome(
            scenario_index=0,
            scenario_seed=1,
            pit_now_remaining_time_seconds=100.0,
            stay_out_remaining_time_seconds=101.0,
            pit_now_advantage_seconds=2.0,
            preference=ScenarioPreference.PIT_NOW,
        )


def test_outcome_rejects_preference_inconsistent_with_advantage() -> None:
    with pytest.raises(ConcurrentSimulationContractError, match="preference"):
        ScenarioOutcome(
            scenario_index=0,
            scenario_seed=1,
            pit_now_remaining_time_seconds=100.0,
            stay_out_remaining_time_seconds=101.0,
            pit_now_advantage_seconds=1.0,
            preference=ScenarioPreference.STAY_OUT,
        )


def test_evaluation_rejects_reordered_outcomes() -> None:
    evaluation = _evaluation_with_advantages((1.0, 2.0))

    with pytest.raises(ConcurrentSimulationContractError, match="ordered"):
        replace(evaluation, outcomes=tuple(reversed(evaluation.outcomes)))


def test_evaluation_rejects_unknown_aggregator() -> None:
    evaluation = _evaluation_with_advantages((1.0, 2.0))

    with pytest.raises(ConcurrentSimulationContractError, match="aggregator"):
        replace(evaluation, aggregator_id="unordered-magic")


@pytest.mark.parametrize("values", [(), [1.0], (float("nan"),)])
def test_distribution_rejects_invalid_values(values: object) -> None:
    with pytest.raises(ConcurrentSimulationContractError):
        summarize_scenario_distribution(values)  # type: ignore[arg-type]


def test_evaluator_rejects_wrong_boundary_types() -> None:
    with pytest.raises(TypeError, match="batch"):
        evaluate_scenario_batch_sequentially(  # type: ignore[arg-type]
            object(),
            calibration=_calibration(),
            context=_context(),
            adapter=_adapter(_ConstantModel()),
        )


def test_generated_batch_contract_identity_remains_unchanged() -> None:
    assert _batch().generator_id == SCENARIO_GENERATOR_ID
