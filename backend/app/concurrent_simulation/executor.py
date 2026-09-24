"""Bounded deterministic concurrent execution for Phase 9 scenarios."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Final

from app.concurrent_simulation.aggregation import (
    SEQUENTIAL_AGGREGATOR_ID,
    ScenarioOutcome,
    SequentialScenarioEvaluation,
    evaluate_scenario_outcome,
)
from app.concurrent_simulation.calibration import UncertaintyCalibration
from app.concurrent_simulation.contracts import (
    ConcurrentSimulationContractError,
    ScenarioBatch,
)
from app.simulation import Phase6ModelAdapter, SimulationFeatureContext

CONCURRENT_EXECUTOR_ID: Final = "thread-pool-paired-scenario-v1"
DEFAULT_MAX_WORKERS: Final = 4
MAXIMUM_CONCURRENT_WORKERS: Final = 32


class ConcurrentExecutionError(ConcurrentSimulationContractError):
    """Raised when bounded concurrent execution cannot produce exact evidence."""


@dataclass(frozen=True, slots=True)
class ConcurrentExecutionResult:
    """One concurrent run with canonical sequential-compatible evidence."""

    executor_id: str
    max_workers: int
    evaluation: SequentialScenarioEvaluation

    def __post_init__(self) -> None:
        if self.executor_id != CONCURRENT_EXECUTOR_ID:
            raise ConcurrentExecutionError(
                "concurrent executor differs from the frozen contract"
            )
        _worker_count(self.max_workers)
        if not isinstance(self.evaluation, SequentialScenarioEvaluation):
            raise TypeError(
                "evaluation must be a SequentialScenarioEvaluation"
            )

    def assert_equivalent_to(
        self,
        sequential: SequentialScenarioEvaluation,
    ) -> None:
        """Fail closed unless every ordered outcome and summary is identical."""
        if not isinstance(sequential, SequentialScenarioEvaluation):
            raise TypeError(
                "sequential must be a SequentialScenarioEvaluation"
            )
        if self.evaluation != sequential:
            mismatch = _first_mismatch(self.evaluation, sequential)
            raise ConcurrentExecutionError(
                "concurrent output differs from sequential output"
                + (f" at scenario {mismatch}" if mismatch is not None else "")
            )


def evaluate_scenario_batch_concurrently(
    batch: ScenarioBatch,
    *,
    calibration: UncertaintyCalibration,
    context: SimulationFeatureContext,
    adapter: Phase6ModelAdapter,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> ConcurrentExecutionResult:
    """Evaluate independent paired worlds concurrently and restore their order."""
    if not isinstance(batch, ScenarioBatch):
        raise TypeError("batch must be a ScenarioBatch")
    if not isinstance(calibration, UncertaintyCalibration):
        raise TypeError("calibration must be an UncertaintyCalibration")
    if not isinstance(context, SimulationFeatureContext):
        raise TypeError("context must be a SimulationFeatureContext")
    if not isinstance(adapter, Phase6ModelAdapter):
        raise TypeError("adapter must be a Phase6ModelAdapter")
    workers = _worker_count(max_workers)

    ordered: list[ScenarioOutcome | None] = [None] * batch.request.scenario_count
    with ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="phase9-scenario",
    ) as pool:
        futures: dict[Future[ScenarioOutcome], int] = {
            pool.submit(
                evaluate_scenario_outcome,
                batch,
                scenario_index=scenario.scenario_index,
                calibration=calibration,
                context=context,
                adapter=adapter,
            ): scenario.scenario_index
            for scenario in batch.scenarios
        }
        for future in as_completed(futures):
            scenario_index = futures[future]
            try:
                outcome = future.result()
            except Exception as error:
                for pending in futures:
                    pending.cancel()
                raise ConcurrentExecutionError(
                    f"concurrent scenario {scenario_index} failed"
                ) from error
            if outcome.scenario_index != scenario_index:
                raise ConcurrentExecutionError(
                    "worker returned an outcome for the wrong scenario"
                )
            ordered[scenario_index] = outcome

    if any(outcome is None for outcome in ordered):
        raise ConcurrentExecutionError(
            "concurrent execution produced incomplete scenario evidence"
        )
    outcomes = tuple(
        outcome
        for outcome in ordered
        if outcome is not None
    )
    evaluation = SequentialScenarioEvaluation(
        batch=batch,
        calibration=calibration,
        aggregator_id=SEQUENTIAL_AGGREGATOR_ID,
        outcomes=outcomes,
    )
    return ConcurrentExecutionResult(
        executor_id=CONCURRENT_EXECUTOR_ID,
        max_workers=workers,
        evaluation=evaluation,
    )


def _first_mismatch(
    concurrent: SequentialScenarioEvaluation,
    sequential: SequentialScenarioEvaluation,
) -> int | None:
    if (
        concurrent.batch != sequential.batch
        or concurrent.calibration != sequential.calibration
        or len(concurrent.outcomes) != len(sequential.outcomes)
    ):
        return None
    for concurrent_outcome, sequential_outcome in zip(
        concurrent.outcomes,
        sequential.outcomes,
        strict=True,
    ):
        if concurrent_outcome != sequential_outcome:
            return concurrent_outcome.scenario_index
    return None


def _worker_count(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > MAXIMUM_CONCURRENT_WORKERS
    ):
        raise ConcurrentExecutionError(
            "max_workers must be an integer between 1 and "
            f"{MAXIMUM_CONCURRENT_WORKERS}"
        )
    return value
