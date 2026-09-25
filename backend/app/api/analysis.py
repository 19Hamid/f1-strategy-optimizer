"""Controlled analysis orchestration over the frozen Phase 8 and 9 engines."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.concurrent_simulation.aggregation import (
    MINIMUM_STABILITY_SCENARIO_COUNT,
    SequentialScenarioEvaluation,
)
from app.concurrent_simulation.calibration import UncertaintyCalibration
from app.concurrent_simulation.contracts import (
    MAXIMUM_SCENARIO_COUNT,
    ScenarioBatchRequest,
)
from app.concurrent_simulation.executor import (
    DEFAULT_MAX_WORKERS,
    MAXIMUM_CONCURRENT_WORKERS,
    evaluate_scenario_batch_concurrently,
)
from app.concurrent_simulation.scenarios import generate_scenario_batch
from app.optimizer.comparison import PitDecisionComparison, compare_pit_decision
from app.optimizer.contracts import PitDecisionRecommendation, PitDecisionRequest
from app.simulation import (
    SIMULATION_RANDOM_SEED,
    Phase6ModelAdapter,
    SimulationFeatureContext,
)


class AnalysisMode(StrEnum):
    """The two public execution modes from the frozen API contract."""

    DETERMINISTIC = "DETERMINISTIC"
    PAIRED_SCENARIO = "PAIRED_SCENARIO"


class AnalysisRequestError(ValueError):
    """An analysis request does not satisfy the controlled V1 boundary."""


@dataclass(frozen=True, slots=True)
class StrategyAnalysisResult:
    """A point comparison and, when requested, paired uncertainty evidence."""

    mode: AnalysisMode
    comparison: PitDecisionComparison
    scenarios: SequentialScenarioEvaluation | None

    def __post_init__(self) -> None:
        try:
            mode = AnalysisMode(self.mode)
        except (TypeError, ValueError) as error:
            raise AnalysisRequestError("unsupported analysis mode") from error
        object.__setattr__(self, "mode", mode)
        if not isinstance(self.comparison, PitDecisionComparison):
            raise TypeError("comparison must be a PitDecisionComparison")
        if (self.scenarios is None) != (mode is AnalysisMode.DETERMINISTIC):
            raise AnalysisRequestError("scenario evidence differs from analysis mode")
        if self.scenarios is not None:
            if not isinstance(self.scenarios, SequentialScenarioEvaluation):
                raise TypeError("scenarios must be a SequentialScenarioEvaluation")
            if self.scenarios.batch.request.decision_request != self.comparison.request:
                raise AnalysisRequestError(
                    "scenario and point comparison use different decisions"
                )

    @property
    def recommendation(self) -> PitDecisionRecommendation:
        """Expose scenario stability when available, else the point estimate."""
        if self.scenarios is not None:
            return self.scenarios.recommendation
        return self.comparison.recommendation

    @property
    def recommendation_is_stable(self) -> bool:
        """A point estimate alone never establishes stability."""
        return self.scenarios is not None and self.scenarios.recommendation_is_stable


def run_strategy_analysis(
    decision: PitDecisionRequest,
    *,
    context: SimulationFeatureContext,
    adapter: Phase6ModelAdapter,
    mode: AnalysisMode = AnalysisMode.DETERMINISTIC,
    calibration: UncertaintyCalibration | None = None,
    scenario_count: int | None = None,
    root_seed: int = SIMULATION_RANDOM_SEED,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> StrategyAnalysisResult:
    """Run symmetric full-horizon comparison with optional paired worlds.

    The caller must supply a verified model, development decision context and
    development-only calibration. No counterfactual correctness claim follows
    from either result.
    """
    if not isinstance(decision, PitDecisionRequest):
        raise TypeError("decision must be a PitDecisionRequest")
    if not isinstance(context, SimulationFeatureContext):
        raise TypeError("context must be a SimulationFeatureContext")
    if not isinstance(adapter, Phase6ModelAdapter):
        raise TypeError("adapter must be a Phase6ModelAdapter")
    try:
        normalized_mode = AnalysisMode(mode)
    except (TypeError, ValueError) as error:
        raise AnalysisRequestError("unsupported analysis mode") from error
    if normalized_mode is AnalysisMode.DETERMINISTIC:
        if calibration is not None or scenario_count is not None:
            raise AnalysisRequestError(
                "deterministic analysis cannot accept scenario inputs"
            )
        comparison = compare_pit_decision(
            decision,
            context=context,
            adapter=adapter,
        )
        return StrategyAnalysisResult(normalized_mode, comparison, None)

    if not isinstance(calibration, UncertaintyCalibration):
        raise AnalysisRequestError("paired analysis requires verified calibration")
    if (
        isinstance(scenario_count, bool)
        or not isinstance(scenario_count, int)
        or not MINIMUM_STABILITY_SCENARIO_COUNT
        <= scenario_count
        <= MAXIMUM_SCENARIO_COUNT
    ):
        raise AnalysisRequestError(
            "paired scenario_count must be between "
            f"{MINIMUM_STABILITY_SCENARIO_COUNT} and {MAXIMUM_SCENARIO_COUNT}"
        )
    if (
        isinstance(max_workers, bool)
        or not isinstance(max_workers, int)
        or not 1 <= max_workers <= MAXIMUM_CONCURRENT_WORKERS
    ):
        raise AnalysisRequestError("max_workers is outside the executor boundary")
    batch_request = ScenarioBatchRequest(
        decision_request=decision,
        scenario_count=scenario_count,
        root_seed=root_seed,
    )
    comparison = compare_pit_decision(
        decision,
        context=context,
        adapter=adapter,
    )
    execution = evaluate_scenario_batch_concurrently(
        generate_scenario_batch(batch_request),
        calibration=calibration,
        context=context,
        adapter=adapter,
        max_workers=max_workers,
    )
    return StrategyAnalysisResult(
        normalized_mode,
        comparison,
        execution.evaluation,
    )
