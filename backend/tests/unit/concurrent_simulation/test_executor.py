"""Tests for bounded deterministic Phase 9 concurrent execution."""

from __future__ import annotations

import time
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import app.concurrent_simulation.executor as executor_module
from app.concurrent_simulation import (
    UNCERTAINTY_CALIBRATION_METHOD_ID,
    ScenarioBatch,
    ScenarioBatchRequest,
    UncertaintyCalibration,
    generate_scenario_batch,
)
from app.concurrent_simulation.aggregation import (
    SequentialScenarioEvaluation,
    evaluate_scenario_batch_sequentially,
)
from app.concurrent_simulation.executor import (
    CONCURRENT_EXECUTOR_ID,
    DEFAULT_MAX_WORKERS,
    MAXIMUM_CONCURRENT_WORKERS,
    ConcurrentExecutionError,
    ConcurrentExecutionResult,
    evaluate_scenario_batch_concurrently,
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
from app.optimizer import PitDecisionRequest
from app.simulation import (
    DryCompound,
    Phase6ModelAdapter,
    PitLossAssumption,
    PitLossSource,
    RaceState,
    SimulationFeatureContext,
)
from app.simulation.model_adapter import SELECTED_SIMULATOR_CANDIDATE_ID


class _TyreAgeModel:
    def predict(self, features: pd.DataFrame) -> np.ndarray:
        return 90.0 + features["tyre_age_laps"].to_numpy(dtype="float64")


def _adapter() -> Phase6ModelAdapter:
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
            model=_TyreAgeModel(),  # type: ignore[arg-type]
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
            evidence="concurrent executor unit-test assumption",
        ),
    )


def _batch(scenario_count: int = 6) -> ScenarioBatch:
    return generate_scenario_batch(
        ScenarioBatchRequest(
            _decision_request(),
            scenario_count=scenario_count,
            root_seed=456,
        )
    )


def _calibration() -> UncertaintyCalibration:
    return UncertaintyCalibration(
        calibration_id="executor-unit-calibration",
        method_id=UNCERTAINTY_CALIBRATION_METHOD_ID,
        training_seasons=(2022, 2023, 2024),
        shared_pace_scale_seconds=0.1,
        pit_loss_scale_seconds=0.1,
        lap_time_residual_scale_seconds=0.1,
        replay_count=10,
        lap_count=100,
        pit_loss_profile_count=3,
        evidence="executor unit-test development evidence",
    )


def _sequential() -> SequentialScenarioEvaluation:
    return evaluate_scenario_batch_sequentially(
        _batch(),
        calibration=_calibration(),
        context=_context(),
        adapter=_adapter(),
    )


def _concurrent(max_workers: int = 3) -> ConcurrentExecutionResult:
    return evaluate_scenario_batch_concurrently(
        _batch(),
        calibration=_calibration(),
        context=_context(),
        adapter=_adapter(),
        max_workers=max_workers,
    )


def test_executor_contract_freezes_identity_and_worker_bounds() -> None:
    assert CONCURRENT_EXECUTOR_ID == "thread-pool-paired-scenario-v1"
    assert DEFAULT_MAX_WORKERS == 4
    assert MAXIMUM_CONCURRENT_WORKERS == 32


@pytest.mark.parametrize("max_workers", [1, 2, 4])
def test_concurrent_output_exactly_equals_sequential_output(
    max_workers: int,
) -> None:
    sequential = _sequential()
    concurrent = _concurrent(max_workers)

    assert concurrent.evaluation == sequential
    concurrent.assert_equivalent_to(sequential)


def test_concurrent_execution_is_exactly_deterministic() -> None:
    assert _concurrent() == _concurrent()


def test_completion_order_cannot_change_canonical_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = executor_module.evaluate_scenario_outcome

    def delayed(*args: object, scenario_index: int, **kwargs: object):
        time.sleep((6 - scenario_index) * 0.001)
        return original(
            *args,
            scenario_index=scenario_index,
            **kwargs,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(executor_module, "evaluate_scenario_outcome", delayed)

    result = _concurrent(max_workers=3)

    assert tuple(
        outcome.scenario_index for outcome in result.evaluation.outcomes
    ) == tuple(range(6))
    result.assert_equivalent_to(_sequential())


def test_concurrent_execution_preserves_input_context() -> None:
    context = _context()

    evaluate_scenario_batch_concurrently(
        _batch(),
        calibration=_calibration(),
        context=context,
        adapter=_adapter(),
        max_workers=2,
    )

    assert context.simulated_lap_times_seconds == ()


@pytest.mark.parametrize("max_workers", [0, -1, 33, True, 1.5])
def test_executor_rejects_invalid_worker_counts(max_workers: object) -> None:
    with pytest.raises(ConcurrentExecutionError, match="max_workers"):
        evaluate_scenario_batch_concurrently(
            _batch(),
            calibration=_calibration(),
            context=_context(),
            adapter=_adapter(),
            max_workers=max_workers,  # type: ignore[arg-type]
        )


def test_worker_failure_names_the_failed_scenario(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = executor_module.evaluate_scenario_outcome

    def fail_one(*args: object, scenario_index: int, **kwargs: object):
        if scenario_index == 2:
            raise RuntimeError("synthetic worker failure")
        return original(
            *args,
            scenario_index=scenario_index,
            **kwargs,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(executor_module, "evaluate_scenario_outcome", fail_one)

    with pytest.raises(ConcurrentExecutionError, match="scenario 2"):
        _concurrent(max_workers=3)


def test_worker_returning_wrong_identity_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = executor_module.evaluate_scenario_outcome

    def wrong_identity(*args: object, scenario_index: int, **kwargs: object):
        outcome = original(
            *args,
            scenario_index=scenario_index,
            **kwargs,  # type: ignore[arg-type]
        )
        if scenario_index == 1:
            return replace(outcome, scenario_index=0)
        return outcome

    monkeypatch.setattr(
        executor_module,
        "evaluate_scenario_outcome",
        wrong_identity,
    )

    with pytest.raises(ConcurrentExecutionError, match="wrong scenario"):
        _concurrent(max_workers=3)


def test_equivalence_check_detects_tampered_outcome() -> None:
    concurrent = _concurrent()
    sequential = _sequential()
    first = sequential.outcomes[0]
    tampered = replace(
        first,
        pit_now_remaining_time_seconds=(
            first.pit_now_remaining_time_seconds + 1.0
        ),
        stay_out_remaining_time_seconds=(
            first.stay_out_remaining_time_seconds + 1.0
        ),
    )
    changed = replace(
        sequential,
        outcomes=(tampered, *sequential.outcomes[1:]),
    )

    with pytest.raises(ConcurrentExecutionError, match="scenario 0"):
        concurrent.assert_equivalent_to(changed)


def test_result_rejects_unknown_executor_identity() -> None:
    result = _concurrent()

    with pytest.raises(ConcurrentExecutionError, match="executor"):
        replace(result, executor_id="process-pool-maybe-v0")


def test_equivalence_check_requires_sequential_evidence() -> None:
    with pytest.raises(TypeError, match="sequential"):
        _concurrent().assert_equivalent_to(object())  # type: ignore[arg-type]


def test_executor_rejects_wrong_batch_type() -> None:
    with pytest.raises(TypeError, match="batch"):
        evaluate_scenario_batch_concurrently(  # type: ignore[arg-type]
            object(),
            calibration=_calibration(),
            context=_context(),
            adapter=_adapter(),
        )
