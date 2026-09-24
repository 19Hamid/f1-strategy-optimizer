"""Tests for honest Phase 9 sequential-versus-concurrent benchmarks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import app.concurrent_simulation.benchmark as benchmark_module
from app.concurrent_simulation import (
    UNCERTAINTY_CALIBRATION_METHOD_ID,
    ScenarioBatch,
    ScenarioBatchRequest,
    UncertaintyCalibration,
    generate_scenario_batch,
)
from app.concurrent_simulation.benchmark import (
    DEFAULT_BENCHMARK_REPETITIONS,
    DEFAULT_BENCHMARK_SCENARIO_COUNTS,
    DEFAULT_BENCHMARK_WORKER_COUNTS,
    MAXIMUM_BENCHMARK_REPETITIONS,
    PERFORMANCE_BENCHMARK_ID,
    BenchmarkExecutionMode,
    PerformanceBenchmarkError,
    ScenarioPerformanceBenchmark,
    ScenarioScalingBenchmark,
    benchmark_scenario_batch,
    benchmark_scenario_scaling,
)
from app.concurrent_simulation.executor import ConcurrentExecutionResult
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
            evidence="performance benchmark unit-test assumption",
        ),
    )


def _request(scenario_count: int = 4) -> ScenarioBatchRequest:
    return ScenarioBatchRequest(
        _decision_request(),
        scenario_count=scenario_count,
        root_seed=789,
    )


def _batch(scenario_count: int = 4) -> ScenarioBatch:
    return generate_scenario_batch(_request(scenario_count))


def _calibration() -> UncertaintyCalibration:
    return UncertaintyCalibration(
        calibration_id="benchmark-unit-calibration",
        method_id=UNCERTAINTY_CALIBRATION_METHOD_ID,
        training_seasons=(2022, 2023, 2024),
        shared_pace_scale_seconds=0.1,
        pit_loss_scale_seconds=0.1,
        lap_time_residual_scale_seconds=0.1,
        replay_count=10,
        lap_count=100,
        pit_loss_profile_count=3,
        evidence="benchmark unit-test development evidence",
    )


def _clock(values: tuple[float, ...]) -> Callable[[], float]:
    iterator = iter(values)
    return lambda: next(iterator)


def _benchmark(
    *,
    worker_counts: tuple[int, ...] = (1, 2),
    repetitions: int = 2,
    clock_values: tuple[float, ...] = (
        0.0,
        2.0,
        2.0,
        3.0,
        3.0,
        3.5,
        10.0,
        14.0,
        14.0,
        16.0,
        16.0,
        17.0,
    ),
) -> ScenarioPerformanceBenchmark:
    return benchmark_scenario_batch(
        _batch(),
        calibration=_calibration(),
        context=_context(),
        adapter=_adapter(),
        worker_counts=worker_counts,
        repetitions=repetitions,
        clock=_clock(clock_values),
    )


def test_benchmark_contract_freezes_default_scaling_plan() -> None:
    assert PERFORMANCE_BENCHMARK_ID == "paired-scenario-wall-clock-scaling-v1"
    assert DEFAULT_BENCHMARK_SCENARIO_COUNTS == (100, 1_000, 10_000)
    assert DEFAULT_BENCHMARK_WORKER_COUNTS == (1, 2, 4, 8)
    assert DEFAULT_BENCHMARK_REPETITIONS == 1
    assert MAXIMUM_BENCHMARK_REPETITIONS == 5


def test_batch_benchmark_reconciles_throughput_speedup_and_efficiency() -> None:
    result = _benchmark()

    assert result.benchmark_id == PERFORMANCE_BENCHMARK_ID
    assert result.repetitions == 2
    assert result.baseline.execution_mode is BenchmarkExecutionMode.SEQUENTIAL
    assert result.baseline.durations_seconds == (2.0, 4.0)
    assert result.baseline.median_duration_seconds == 3.0
    assert result.baseline.scenarios_per_second == pytest.approx(4 / 3)
    one_worker, two_workers = result.concurrent_measurements
    assert one_worker.durations_seconds == (1.0, 2.0)
    assert one_worker.speedup_vs_sequential == 2.0
    assert one_worker.worker_efficiency == 2.0
    assert two_workers.durations_seconds == (0.5, 1.0)
    assert two_workers.speedup_vs_sequential == 4.0
    assert two_workers.worker_efficiency == 2.0
    assert result.fastest_measurement is two_workers
    assert result.concurrency_improves_throughput


def test_benchmark_does_not_assume_concurrency_is_faster() -> None:
    result = _benchmark(
        worker_counts=(2,),
        repetitions=1,
        clock_values=(0.0, 1.0, 2.0, 4.0),
    )

    assert result.concurrent_measurements[0].speedup_vs_sequential == 0.5
    assert result.fastest_measurement is result.baseline
    assert not result.concurrency_improves_throughput


def test_benchmark_preserves_input_context() -> None:
    context = _context()

    benchmark_scenario_batch(
        _batch(2),
        calibration=_calibration(),
        context=context,
        adapter=_adapter(),
        worker_counts=(2,),
        repetitions=1,
        clock=_clock((0.0, 1.0, 2.0, 3.0)),
    )

    assert context.simulated_lap_times_seconds == ()


def test_benchmark_emits_measurement_progress() -> None:
    messages: list[str] = []

    benchmark_scenario_batch(
        _batch(2),
        calibration=_calibration(),
        context=_context(),
        adapter=_adapter(),
        worker_counts=(2,),
        repetitions=1,
        clock=_clock((0.0, 1.0, 2.0, 3.0)),
        progress=messages.append,
    )

    assert messages == [
        "Warming sequential and concurrent execution paths",
        "Measuring sequential repetition 1/1",
        "Measuring concurrent repetition 1/1 with 2 workers",
    ]


def test_scaling_benchmark_preserves_prefix_identity_and_order() -> None:
    result = benchmark_scenario_scaling(
        _request(2),
        calibration=_calibration(),
        context=_context(),
        adapter=_adapter(),
        scenario_counts=(2, 4),
        worker_counts=(2,),
        repetitions=1,
        clock=_clock((0.0, 2.0, 2.0, 3.0, 10.0, 14.0, 14.0, 16.0)),
    )

    assert isinstance(result, ScenarioScalingBenchmark)
    assert result.scenario_counts == (2, 4)
    assert tuple(item.request.root_seed for item in result.results) == (789, 789)
    assert tuple(
        item.concurrent_measurements[0].speedup_vs_sequential
        for item in result.results
    ) == (2.0, 2.0)


@pytest.mark.parametrize(
    "worker_counts",
    [(), (2, 1), (1, 1), (0,), (33,), [1, 2]],
)
def test_benchmark_rejects_invalid_worker_grids(worker_counts: object) -> None:
    with pytest.raises(PerformanceBenchmarkError, match="worker_counts|max_workers"):
        benchmark_scenario_batch(
            _batch(2),
            calibration=_calibration(),
            context=_context(),
            adapter=_adapter(),
            worker_counts=worker_counts,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("repetitions", [0, 6, True, 1.5])
def test_benchmark_rejects_invalid_repetition_counts(
    repetitions: object,
) -> None:
    with pytest.raises(PerformanceBenchmarkError, match="repetitions"):
        benchmark_scenario_batch(
            _batch(2),
            calibration=_calibration(),
            context=_context(),
            adapter=_adapter(),
            worker_counts=(1,),
            repetitions=repetitions,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "scenario_counts",
    [(), (4, 2), (2, 2), (0,), (100_001,), [2, 4]],
)
def test_scaling_benchmark_rejects_invalid_population_grids(
    scenario_counts: object,
) -> None:
    with pytest.raises(
        PerformanceBenchmarkError,
        match="scenario_counts|scenario_count",
    ):
        benchmark_scenario_scaling(
            _request(2),
            calibration=_calibration(),
            context=_context(),
            adapter=_adapter(),
            scenario_counts=scenario_counts,  # type: ignore[arg-type]
            worker_counts=(1,),
        )


def test_benchmark_rejects_non_advancing_clock() -> None:
    with pytest.raises(PerformanceBenchmarkError, match="advance"):
        benchmark_scenario_batch(
            _batch(2),
            calibration=_calibration(),
            context=_context(),
            adapter=_adapter(),
            worker_counts=(1,),
            repetitions=1,
            clock=_clock((0.0, 0.0)),
        )


def test_benchmark_rejects_non_numeric_clock() -> None:
    with pytest.raises(PerformanceBenchmarkError, match="clock"):
        benchmark_scenario_batch(
            _batch(2),
            calibration=_calibration(),
            context=_context(),
            adapter=_adapter(),
            worker_counts=(1,),
            repetitions=1,
            clock=lambda: "not-a-time",  # type: ignore[return-value]
        )


def test_benchmark_rejects_concurrent_output_difference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = benchmark_module.evaluate_scenario_batch_concurrently

    def tampered(*args: object, **kwargs: object) -> ConcurrentExecutionResult:
        result = original(*args, **kwargs)  # type: ignore[arg-type]
        first = result.evaluation.outcomes[0]
        changed = replace(
            first,
            pit_now_remaining_time_seconds=(
                first.pit_now_remaining_time_seconds + 1.0
            ),
            stay_out_remaining_time_seconds=(
                first.stay_out_remaining_time_seconds + 1.0
            ),
        )
        return replace(
            result,
            evaluation=replace(
                result.evaluation,
                outcomes=(changed, *result.evaluation.outcomes[1:]),
            ),
        )

    monkeypatch.setattr(
        benchmark_module,
        "evaluate_scenario_batch_concurrently",
        tampered,
    )

    with pytest.raises(PerformanceBenchmarkError, match="differs"):
        benchmark_scenario_batch(
            _batch(2),
            calibration=_calibration(),
            context=_context(),
            adapter=_adapter(),
            worker_counts=(1,),
            repetitions=1,
        )


def test_measurement_rejects_non_reconciling_throughput() -> None:
    result = _benchmark(worker_counts=(1,), repetitions=1, clock_values=(0, 2, 2, 3))

    with pytest.raises(PerformanceBenchmarkError, match="throughput"):
        replace(result.baseline, scenarios_per_second=999.0)


def test_result_rejects_unknown_benchmark_identity() -> None:
    result = _benchmark(worker_counts=(1,), repetitions=1, clock_values=(0, 2, 2, 3))

    with pytest.raises(PerformanceBenchmarkError, match="frozen contract"):
        replace(result, benchmark_id="unscientific-stopwatch-v0")


def test_benchmark_rejects_wrong_batch_type() -> None:
    with pytest.raises(TypeError, match="batch"):
        benchmark_scenario_batch(  # type: ignore[arg-type]
            object(),
            calibration=_calibration(),
            context=_context(),
            adapter=_adapter(),
        )
