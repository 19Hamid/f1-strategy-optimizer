"""Honest wall-clock scaling benchmarks for paired Phase 9 scenarios."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from statistics import median
from time import perf_counter
from typing import Final

from app.concurrent_simulation.aggregation import (
    SequentialScenarioEvaluation,
    evaluate_scenario_batch_sequentially,
)
from app.concurrent_simulation.calibration import UncertaintyCalibration
from app.concurrent_simulation.contracts import (
    MAXIMUM_SCENARIO_COUNT,
    ConcurrentSimulationContractError,
    ScenarioBatch,
    ScenarioBatchRequest,
)
from app.concurrent_simulation.executor import (
    MAXIMUM_CONCURRENT_WORKERS,
    ConcurrentExecutionResult,
    evaluate_scenario_batch_concurrently,
)
from app.concurrent_simulation.scenarios import generate_scenario_batch
from app.simulation import Phase6ModelAdapter, SimulationFeatureContext

PERFORMANCE_BENCHMARK_ID: Final = "paired-scenario-wall-clock-scaling-v1"
DEFAULT_BENCHMARK_SCENARIO_COUNTS: Final = (100, 1_000, 10_000)
DEFAULT_BENCHMARK_WORKER_COUNTS: Final = (1, 2, 4, 8)
DEFAULT_BENCHMARK_REPETITIONS: Final = 1
MAXIMUM_BENCHMARK_REPETITIONS: Final = 5

Clock = Callable[[], float]
ProgressCallback = Callable[[str], None]


class PerformanceBenchmarkError(ConcurrentSimulationContractError):
    """Raised when benchmark evidence is invalid or incomparable."""


class BenchmarkExecutionMode(StrEnum):
    """Execution path measured by one benchmark observation."""

    SEQUENTIAL = "SEQUENTIAL"
    CONCURRENT = "CONCURRENT"


@dataclass(frozen=True, slots=True)
class ScenarioBenchmarkMeasurement:
    """Validated timing and derived throughput for one execution path."""

    execution_mode: BenchmarkExecutionMode
    scenario_count: int
    max_workers: int | None
    durations_seconds: tuple[float, ...]
    median_duration_seconds: float
    scenarios_per_second: float
    speedup_vs_sequential: float
    worker_efficiency: float | None

    def __post_init__(self) -> None:
        try:
            mode = BenchmarkExecutionMode(self.execution_mode)
        except (TypeError, ValueError) as error:
            raise PerformanceBenchmarkError(
                f"unsupported benchmark execution mode: {self.execution_mode!r}"
            ) from error
        _integer_between(
            self.scenario_count,
            "scenario_count",
            minimum=1,
            maximum=MAXIMUM_SCENARIO_COUNT,
        )
        if not isinstance(self.durations_seconds, tuple) or not self.durations_seconds:
            raise PerformanceBenchmarkError(
                "durations_seconds must be a non-empty tuple"
            )
        durations = tuple(
            _positive(value, "duration_seconds")
            for value in self.durations_seconds
        )
        measured_median = _positive(
            self.median_duration_seconds,
            "median_duration_seconds",
        )
        _reconciles(measured_median, median(durations), "median duration")
        throughput = _positive(
            self.scenarios_per_second,
            "scenarios_per_second",
        )
        _reconciles(
            throughput,
            self.scenario_count / measured_median,
            "scenario throughput",
        )
        speedup = _positive(
            self.speedup_vs_sequential,
            "speedup_vs_sequential",
        )
        if mode is BenchmarkExecutionMode.SEQUENTIAL:
            if self.max_workers is not None:
                raise PerformanceBenchmarkError(
                    "sequential measurement cannot declare workers"
                )
            _reconciles(speedup, 1.0, "sequential speedup")
            if self.worker_efficiency is not None:
                raise PerformanceBenchmarkError(
                    "sequential measurement cannot declare worker efficiency"
                )
        else:
            workers = _integer_between(
                self.max_workers,
                "max_workers",
                minimum=1,
                maximum=MAXIMUM_CONCURRENT_WORKERS,
            )
            efficiency = _positive(
                self.worker_efficiency,
                "worker_efficiency",
            )
            _reconciles(
                efficiency,
                speedup / workers,
                "worker efficiency",
            )
        object.__setattr__(self, "execution_mode", mode)
        object.__setattr__(self, "durations_seconds", durations)


@dataclass(frozen=True, slots=True)
class ScenarioPerformanceBenchmark:
    """Sequential baseline and exactly equivalent concurrent measurements."""

    benchmark_id: str
    request: ScenarioBatchRequest
    repetitions: int
    measurements: tuple[ScenarioBenchmarkMeasurement, ...]

    def __post_init__(self) -> None:
        if self.benchmark_id != PERFORMANCE_BENCHMARK_ID:
            raise PerformanceBenchmarkError(
                "performance benchmark differs from the frozen contract"
            )
        if not isinstance(self.request, ScenarioBatchRequest):
            raise TypeError("request must be a ScenarioBatchRequest")
        repetitions = _repetition_count(self.repetitions)
        if not isinstance(self.measurements, tuple) or len(self.measurements) < 2:
            raise PerformanceBenchmarkError(
                "benchmark requires sequential and concurrent measurements"
            )
        if any(
            not isinstance(measurement, ScenarioBenchmarkMeasurement)
            for measurement in self.measurements
        ):
            raise TypeError(
                "measurements must contain ScenarioBenchmarkMeasurement values"
            )
        baseline = self.measurements[0]
        if baseline.execution_mode is not BenchmarkExecutionMode.SEQUENTIAL:
            raise PerformanceBenchmarkError(
                "first benchmark measurement must be sequential"
            )
        workers: list[int] = []
        for measurement in self.measurements:
            if measurement.scenario_count != self.request.scenario_count:
                raise PerformanceBenchmarkError(
                    "measurement scenario count differs from its request"
                )
            if len(measurement.durations_seconds) != repetitions:
                raise PerformanceBenchmarkError(
                    "measurement duration count differs from repetitions"
                )
            expected_speedup = (
                baseline.median_duration_seconds
                / measurement.median_duration_seconds
            )
            _reconciles(
                measurement.speedup_vs_sequential,
                expected_speedup,
                "measurement speedup",
            )
            if measurement.execution_mode is BenchmarkExecutionMode.CONCURRENT:
                if measurement.max_workers is None:
                    raise PerformanceBenchmarkError(
                        "concurrent measurement must declare workers"
                    )
                workers.append(measurement.max_workers)
        if tuple(workers) != tuple(sorted(set(workers))):
            raise PerformanceBenchmarkError(
                "concurrent worker counts must be unique and increasing"
            )

    @property
    def baseline(self) -> ScenarioBenchmarkMeasurement:
        """Return the sequential reference measurement."""
        return self.measurements[0]

    @property
    def concurrent_measurements(
        self,
    ) -> tuple[ScenarioBenchmarkMeasurement, ...]:
        """Return the ordered worker-scaling measurements."""
        return self.measurements[1:]

    @property
    def fastest_measurement(self) -> ScenarioBenchmarkMeasurement:
        """Return the measured path with the highest scenario throughput."""
        return max(
            self.measurements,
            key=lambda measurement: measurement.scenarios_per_second,
        )

    @property
    def concurrency_improves_throughput(self) -> bool:
        """Report the measured result without assuming concurrency is faster."""
        return any(
            measurement.speedup_vs_sequential > 1.0
            for measurement in self.concurrent_measurements
        )


@dataclass(frozen=True, slots=True)
class ScenarioScalingBenchmark:
    """Ordered benchmark results across increasing scenario populations."""

    benchmark_id: str
    results: tuple[ScenarioPerformanceBenchmark, ...]

    def __post_init__(self) -> None:
        if self.benchmark_id != PERFORMANCE_BENCHMARK_ID:
            raise PerformanceBenchmarkError(
                "scaling benchmark differs from the frozen contract"
            )
        if not isinstance(self.results, tuple) or not self.results:
            raise PerformanceBenchmarkError(
                "scaling benchmark results must be a non-empty tuple"
            )
        if any(
            not isinstance(result, ScenarioPerformanceBenchmark)
            for result in self.results
        ):
            raise TypeError(
                "results must contain ScenarioPerformanceBenchmark values"
            )
        first = self.results[0]
        scenario_counts = tuple(
            result.request.scenario_count for result in self.results
        )
        if scenario_counts != tuple(sorted(set(scenario_counts))):
            raise PerformanceBenchmarkError(
                "benchmark scenario counts must be unique and increasing"
            )
        worker_counts = tuple(
            measurement.max_workers
            for measurement in first.concurrent_measurements
        )
        for result in self.results:
            if result.request.decision_request != first.request.decision_request:
                raise PerformanceBenchmarkError(
                    "scaling results must share one decision request"
                )
            if result.request.root_seed != first.request.root_seed:
                raise PerformanceBenchmarkError(
                    "scaling results must share one root seed"
                )
            if result.repetitions != first.repetitions:
                raise PerformanceBenchmarkError(
                    "scaling results must share one repetition count"
                )
            current_workers = tuple(
                measurement.max_workers
                for measurement in result.concurrent_measurements
            )
            if current_workers != worker_counts:
                raise PerformanceBenchmarkError(
                    "scaling results must share one worker grid"
                )

    @property
    def scenario_counts(self) -> tuple[int, ...]:
        """Return the increasing measured population sizes."""
        return tuple(result.request.scenario_count for result in self.results)


def benchmark_scenario_batch(
    batch: ScenarioBatch,
    *,
    calibration: UncertaintyCalibration,
    context: SimulationFeatureContext,
    adapter: Phase6ModelAdapter,
    worker_counts: tuple[int, ...] = DEFAULT_BENCHMARK_WORKER_COUNTS,
    repetitions: int = DEFAULT_BENCHMARK_REPETITIONS,
    clock: Clock = perf_counter,
    progress: ProgressCallback | None = None,
) -> ScenarioPerformanceBenchmark:
    """Measure complete calls and reject any concurrent evidence difference."""
    if not isinstance(batch, ScenarioBatch):
        raise TypeError("batch must be a ScenarioBatch")
    if not isinstance(calibration, UncertaintyCalibration):
        raise TypeError("calibration must be an UncertaintyCalibration")
    if not isinstance(context, SimulationFeatureContext):
        raise TypeError("context must be a SimulationFeatureContext")
    if not isinstance(adapter, Phase6ModelAdapter):
        raise TypeError("adapter must be a Phase6ModelAdapter")
    workers = _worker_counts(worker_counts)
    repetition_count = _repetition_count(repetitions)
    if not callable(clock):
        raise TypeError("clock must be callable")

    _announce(progress, "Warming sequential and concurrent execution paths")
    warmup_batch = generate_scenario_batch(
        replace(batch.request, scenario_count=1)
    )
    warmup_sequential = evaluate_scenario_batch_sequentially(
        warmup_batch,
        calibration=calibration,
        context=context,
        adapter=adapter,
    )
    for max_workers in workers:
        warmup_concurrent = evaluate_scenario_batch_concurrently(
            warmup_batch,
            calibration=calibration,
            context=context,
            adapter=adapter,
            max_workers=max_workers,
        )
        _assert_equivalent(warmup_concurrent, warmup_sequential)

    sequential_durations: list[float] = []
    concurrent_durations = {max_workers: [] for max_workers in workers}
    reference: SequentialScenarioEvaluation | None = None
    for repetition in range(1, repetition_count + 1):
        _announce(
            progress,
            f"Measuring sequential repetition {repetition}/{repetition_count}",
        )
        started = _clock_value(clock())
        sequential = evaluate_scenario_batch_sequentially(
            batch,
            calibration=calibration,
            context=context,
            adapter=adapter,
        )
        sequential_durations.append(_elapsed(started, _clock_value(clock())))
        if reference is None:
            reference = sequential
        elif sequential != reference:
            raise PerformanceBenchmarkError(
                "sequential benchmark output changed between repetitions"
            )

        for max_workers in workers:
            _announce(
                progress,
                "Measuring concurrent repetition "
                f"{repetition}/{repetition_count} with {max_workers} workers",
            )
            started = _clock_value(clock())
            concurrent = evaluate_scenario_batch_concurrently(
                batch,
                calibration=calibration,
                context=context,
                adapter=adapter,
                max_workers=max_workers,
            )
            concurrent_durations[max_workers].append(
                _elapsed(started, _clock_value(clock()))
            )
            _assert_equivalent(concurrent, sequential)
            if concurrent.evaluation != reference:
                raise PerformanceBenchmarkError(
                    "concurrent benchmark differs from the reference output"
                )

    baseline_duration = median(sequential_durations)
    measurements = [
        _measurement(
            execution_mode=BenchmarkExecutionMode.SEQUENTIAL,
            scenario_count=batch.request.scenario_count,
            max_workers=None,
            durations_seconds=tuple(sequential_durations),
            baseline_duration_seconds=baseline_duration,
        )
    ]
    measurements.extend(
        _measurement(
            execution_mode=BenchmarkExecutionMode.CONCURRENT,
            scenario_count=batch.request.scenario_count,
            max_workers=max_workers,
            durations_seconds=tuple(concurrent_durations[max_workers]),
            baseline_duration_seconds=baseline_duration,
        )
        for max_workers in workers
    )
    return ScenarioPerformanceBenchmark(
        benchmark_id=PERFORMANCE_BENCHMARK_ID,
        request=batch.request,
        repetitions=repetition_count,
        measurements=tuple(measurements),
    )


def benchmark_scenario_scaling(
    request: ScenarioBatchRequest,
    *,
    calibration: UncertaintyCalibration,
    context: SimulationFeatureContext,
    adapter: Phase6ModelAdapter,
    scenario_counts: tuple[int, ...] = DEFAULT_BENCHMARK_SCENARIO_COUNTS,
    worker_counts: tuple[int, ...] = DEFAULT_BENCHMARK_WORKER_COUNTS,
    repetitions: int = DEFAULT_BENCHMARK_REPETITIONS,
    clock: Clock = perf_counter,
    progress: ProgressCallback | None = None,
) -> ScenarioScalingBenchmark:
    """Measure the same deterministic prefix through 10,000 scenarios."""
    if not isinstance(request, ScenarioBatchRequest):
        raise TypeError("request must be a ScenarioBatchRequest")
    counts = _scenario_counts(scenario_counts)
    workers = _worker_counts(worker_counts)
    repetition_count = _repetition_count(repetitions)
    results: list[ScenarioPerformanceBenchmark] = []
    for scenario_count in counts:
        _announce(progress, f"Benchmarking {scenario_count} paired scenarios")
        batch = generate_scenario_batch(
            replace(request, scenario_count=scenario_count)
        )
        results.append(
            benchmark_scenario_batch(
                batch,
                calibration=calibration,
                context=context,
                adapter=adapter,
                worker_counts=workers,
                repetitions=repetition_count,
                clock=clock,
                progress=progress,
            )
        )
    return ScenarioScalingBenchmark(
        benchmark_id=PERFORMANCE_BENCHMARK_ID,
        results=tuple(results),
    )


def _measurement(
    *,
    execution_mode: BenchmarkExecutionMode,
    scenario_count: int,
    max_workers: int | None,
    durations_seconds: tuple[float, ...],
    baseline_duration_seconds: float,
) -> ScenarioBenchmarkMeasurement:
    measured_median = median(durations_seconds)
    speedup = baseline_duration_seconds / measured_median
    efficiency = (
        None if max_workers is None else speedup / max_workers
    )
    return ScenarioBenchmarkMeasurement(
        execution_mode=execution_mode,
        scenario_count=scenario_count,
        max_workers=max_workers,
        durations_seconds=durations_seconds,
        median_duration_seconds=measured_median,
        scenarios_per_second=scenario_count / measured_median,
        speedup_vs_sequential=speedup,
        worker_efficiency=efficiency,
    )


def _assert_equivalent(
    concurrent: ConcurrentExecutionResult,
    sequential: SequentialScenarioEvaluation,
) -> None:
    try:
        concurrent.assert_equivalent_to(sequential)
    except ConcurrentSimulationContractError as error:
        raise PerformanceBenchmarkError(
            "concurrent benchmark output differs from sequential output"
        ) from error


def _scenario_counts(values: object) -> tuple[int, ...]:
    if not isinstance(values, tuple) or not values:
        raise PerformanceBenchmarkError(
            "scenario_counts must be a non-empty tuple"
        )
    counts = tuple(
        _integer_between(
            value,
            "scenario_count",
            minimum=1,
            maximum=MAXIMUM_SCENARIO_COUNT,
        )
        for value in values
    )
    if counts != tuple(sorted(set(counts))):
        raise PerformanceBenchmarkError(
            "scenario_counts must be unique and increasing"
        )
    return counts


def _worker_counts(values: object) -> tuple[int, ...]:
    if not isinstance(values, tuple) or not values:
        raise PerformanceBenchmarkError(
            "worker_counts must be a non-empty tuple"
        )
    workers = tuple(
        _integer_between(
            value,
            "max_workers",
            minimum=1,
            maximum=MAXIMUM_CONCURRENT_WORKERS,
        )
        for value in values
    )
    if workers != tuple(sorted(set(workers))):
        raise PerformanceBenchmarkError(
            "worker_counts must be unique and increasing"
        )
    return workers


def _repetition_count(value: object) -> int:
    return _integer_between(
        value,
        "repetitions",
        minimum=1,
        maximum=MAXIMUM_BENCHMARK_REPETITIONS,
    )


def _integer_between(
    value: object,
    field_name: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        raise PerformanceBenchmarkError(
            f"{field_name} must be an integer between {minimum} and {maximum}"
        )
    return value


def _clock_value(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PerformanceBenchmarkError("clock must return a finite number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise PerformanceBenchmarkError("clock must return a finite number")
    return normalized


def _elapsed(started: float, finished: float) -> float:
    elapsed = finished - started
    if elapsed <= 0:
        raise PerformanceBenchmarkError(
            "benchmark clock must advance by a positive duration"
        )
    return elapsed


def _positive(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PerformanceBenchmarkError(f"{field_name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0:
        raise PerformanceBenchmarkError(f"{field_name} must be positive")
    return normalized


def _reconciles(actual: float, expected: float, field_name: str) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12):
        raise PerformanceBenchmarkError(f"{field_name} does not reconcile")


def _announce(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)
