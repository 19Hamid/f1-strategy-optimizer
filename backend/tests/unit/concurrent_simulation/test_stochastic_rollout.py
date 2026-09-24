"""Tests for calibrated paired Phase 9 stochastic action rollouts."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.concurrent_simulation import (
    SCENARIO_GENERATOR_ID,
    UNCERTAINTY_CALIBRATION_METHOD_ID,
    ConcurrentSimulationContractError,
    ScenarioBatch,
    ScenarioBatchRequest,
    UncertaintyCalibration,
    UncertaintyScenario,
    rollout_paired_scenario,
)
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
from app.optimizer import PitDecisionAction, PitDecisionRequest
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
            evidence="stochastic rollout unit-test assumption",
        ),
    )


def _scenario(**changes: object) -> UncertaintyScenario:
    values: dict[str, object] = {
        "scenario_index": 0,
        "scenario_seed": 123,
        "shared_pace_z": 1.0,
        "pit_loss_z": 0.5,
        "lap_time_residual_z": ((20, 0.5), (21, -0.5), (22, 0.0)),
    }
    values.update(changes)
    return UncertaintyScenario(**values)  # type: ignore[arg-type]


def _batch(scenario: UncertaintyScenario | None = None) -> ScenarioBatch:
    return ScenarioBatch(
        request=ScenarioBatchRequest(_decision_request(), scenario_count=1),
        generator_id=SCENARIO_GENERATOR_ID,
        scenarios=(scenario or _scenario(),),
    )


def _calibration(**changes: object) -> UncertaintyCalibration:
    values: dict[str, object] = {
        "calibration_id": "unit-calibration",
        "method_id": UNCERTAINTY_CALIBRATION_METHOD_ID,
        "training_seasons": (2022, 2023, 2024),
        "shared_pace_scale_seconds": 2.0,
        "pit_loss_scale_seconds": 2.0,
        "lap_time_residual_scale_seconds": 1.0,
        "replay_count": 10,
        "lap_count": 100,
        "pit_loss_profile_count": 3,
        "evidence": "unit-test development evidence",
    }
    values.update(changes)
    return UncertaintyCalibration(**values)  # type: ignore[arg-type]


def _rollout(model: object = None):
    return rollout_paired_scenario(
        _batch(),
        scenario_index=0,
        calibration=_calibration(),
        context=_context(),
        adapter=_adapter(model or _ConstantModel()),
    )


def test_rollout_applies_seconds_without_losing_nominal_evidence() -> None:
    result = _rollout()

    pit_laps = result.pit_now.laps
    assert tuple(lap.nominal_model_seconds for lap in pit_laps) == (90.0,) * 3
    assert tuple(lap.shared_pace_adjustment_seconds for lap in pit_laps) == (
        2.0,
    ) * 3
    assert tuple(lap.lap_residual_adjustment_seconds for lap in pit_laps) == (
        0.5,
        -0.5,
        0.0,
    )
    assert tuple(lap.realized_racing_time_seconds for lap in pit_laps) == (
        92.5,
        91.5,
        92.0,
    )
    assert result.pit_now.perturbed_request.pit_loss.seconds == 21.0
    assert result.pit_now.remaining_time_seconds == pytest.approx(297.0)


def test_actions_share_one_world_but_keep_different_strategy_timing() -> None:
    result = _rollout(_TyreAgeModel())

    assert result.pit_now.scenario_seed == result.stay_out.scenario_seed
    assert result.pit_now.pit_loss_adjustment_seconds == (
        result.stay_out.pit_loss_adjustment_seconds
    )
    assert tuple(
        lap.shared_pace_adjustment_seconds for lap in result.pit_now.laps
    ) == tuple(
        lap.shared_pace_adjustment_seconds for lap in result.stay_out.laps
    )
    assert tuple(
        lap.lap_residual_adjustment_seconds for lap in result.pit_now.laps
    ) == tuple(
        lap.lap_residual_adjustment_seconds for lap in result.stay_out.laps
    )
    assert (
        result.pit_now.nominal_request.strategy.stops[0].after_lap == 20
    )
    assert (
        result.stay_out.nominal_request.strategy.stops[0].after_lap == 21
    )


def test_paired_rollout_is_exactly_deterministic() -> None:
    assert _rollout(_TyreAgeModel()) == _rollout(_TyreAgeModel())


def test_rollout_preserves_input_context_and_phase_8_request() -> None:
    batch = _batch()
    context = _context()
    decision_before = repr(batch.request.decision_request)

    rollout_paired_scenario(
        batch,
        scenario_index=0,
        calibration=_calibration(),
        context=context,
        adapter=_adapter(_ConstantModel()),
    )

    assert repr(batch.request.decision_request) == decision_before
    assert context.simulated_lap_times_seconds == ()


def test_negative_extreme_draws_are_clipped_and_disclosed() -> None:
    scenario = _scenario(
        shared_pace_z=-100.0,
        pit_loss_z=-100.0,
        lap_time_residual_z=((20, 0.0), (21, 0.0), (22, 0.0)),
    )
    result = rollout_paired_scenario(
        _batch(scenario),
        scenario_index=0,
        calibration=_calibration(),
        context=_context(),
        adapter=_adapter(_ConstantModel()),
    )

    assert result.pit_now.pit_loss_was_clipped
    assert result.pit_now.perturbed_request.pit_loss.seconds == 0.0
    assert all(lap.was_clipped for lap in result.pit_now.laps)
    assert all(lap.realized_racing_time_seconds > 0 for lap in result.pit_now.laps)


@pytest.mark.parametrize(
    "changes",
    [
        {"shared_pace_scale_seconds": 0.0},
        {"pit_loss_scale_seconds": float("nan")},
        {"lap_time_residual_scale_seconds": -1.0},
        {"training_seasons": (2022, 2025)},
        {"method_id": "invented"},
    ],
)
def test_calibration_contract_rejects_unverifiable_inputs(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ConcurrentSimulationContractError):
        _calibration(**changes)


def test_rollout_rejects_wrong_boundary_types() -> None:
    with pytest.raises(TypeError, match="batch"):
        rollout_paired_scenario(  # type: ignore[arg-type]
            object(),
            scenario_index=0,
            calibration=_calibration(),
            context=_context(),
            adapter=_adapter(_ConstantModel()),
        )


def test_paired_result_rejects_reordered_actions() -> None:
    result = _rollout()

    with pytest.raises(ConcurrentSimulationContractError, match="PIT_NOW"):
        replace(result, actions=tuple(reversed(result.actions)))


def test_rollout_rejects_scenario_outside_batch() -> None:
    with pytest.raises(ConcurrentSimulationContractError, match="scenario_index"):
        rollout_paired_scenario(
            _batch(),
            scenario_index=1,
            calibration=_calibration(),
            context=_context(),
            adapter=_adapter(_ConstantModel()),
        )


def test_paired_advantage_uses_complete_remaining_time() -> None:
    result = _rollout(_TyreAgeModel())

    assert result.pit_now_advantage_seconds == pytest.approx(
        result.stay_out.remaining_time_seconds
        - result.pit_now.remaining_time_seconds
    )
    assert result.pit_now.final_progress.is_finished
    assert result.stay_out.final_progress.is_finished


def test_result_rejects_changed_scenario_identity() -> None:
    result = _rollout()
    tampered = replace(result.stay_out, scenario_seed=999)

    with pytest.raises(ConcurrentSimulationContractError, match="scenario"):
        replace(result, actions=(result.pit_now, tampered))


def test_result_rejects_action_with_changed_non_pit_assumption() -> None:
    result = _rollout()
    changed_nominal = replace(
        result.pit_now.nominal_request,
        random_seed=result.pit_now.nominal_request.random_seed + 1,
    )

    with pytest.raises(ConcurrentSimulationContractError, match="only the pit-loss"):
        replace(result.pit_now, nominal_request=changed_nominal)


def test_scenario_coordinates_remain_absolute_race_laps() -> None:
    result = _rollout()

    assert result.scenario.lap_numbers == (20, 21, 22)
    assert tuple(lap.transition.lap_number for lap in result.pit_now.laps) == (
        20,
        21,
        22,
    )
    assert tuple(lap.transition.lap_number for lap in result.stay_out.laps) == (
        20,
        21,
        22,
    )
