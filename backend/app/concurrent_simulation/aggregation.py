"""Deterministic sequential aggregation of paired Phase 9 scenarios."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from statistics import fmean, pstdev
from typing import Final

from app.concurrent_simulation.calibration import UncertaintyCalibration
from app.concurrent_simulation.contracts import (
    ConcurrentSimulationContractError,
    ScenarioBatch,
)
from app.concurrent_simulation.rollout import rollout_paired_scenario
from app.optimizer.contracts import (
    DECISION_EQUALITY_ABS_TOLERANCE_SECONDS,
    PitDecisionRecommendation,
)
from app.simulation import Phase6ModelAdapter, SimulationFeatureContext

SEQUENTIAL_AGGREGATOR_ID: Final = "ordered-paired-scenario-aggregation-v1"
SCENARIO_INTERVAL_LOWER_QUANTILE: Final = 0.05
SCENARIO_INTERVAL_UPPER_QUANTILE: Final = 0.95
MINIMUM_STABILITY_SCENARIO_COUNT: Final = 100


class ScenarioPreference(StrEnum):
    """Which action is faster inside one paired simulated race world."""

    PIT_NOW = "PIT_NOW"
    STAY_OUT = "STAY_OUT"
    TIE = "TIE"


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    """Compact complete-time evidence from one paired scenario rollout."""

    scenario_index: int
    scenario_seed: int
    pit_now_remaining_time_seconds: float
    stay_out_remaining_time_seconds: float
    pit_now_advantage_seconds: float
    preference: ScenarioPreference

    def __post_init__(self) -> None:
        _integer_at_least(self.scenario_index, "scenario_index", 0)
        _integer_at_least(self.scenario_seed, "scenario_seed", 0)
        pit_now = _positive(
            self.pit_now_remaining_time_seconds,
            "pit_now_remaining_time_seconds",
        )
        stay_out = _positive(
            self.stay_out_remaining_time_seconds,
            "stay_out_remaining_time_seconds",
        )
        advantage = _finite(
            self.pit_now_advantage_seconds,
            "pit_now_advantage_seconds",
        )
        if not math.isclose(
            advantage,
            stay_out - pit_now,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ConcurrentSimulationContractError(
                "scenario advantage does not reconcile with action times"
            )
        try:
            preference = ScenarioPreference(self.preference)
        except (TypeError, ValueError) as error:
            raise ConcurrentSimulationContractError(
                f"unsupported scenario preference: {self.preference!r}"
            ) from error
        expected = _preference_for_advantage(advantage)
        if preference is not expected:
            raise ConcurrentSimulationContractError(
                "scenario preference differs from its paired advantage"
            )
        object.__setattr__(self, "preference", preference)


@dataclass(frozen=True, slots=True)
class ScenarioDistribution:
    """Frozen descriptive summary of one ordered scenario metric."""

    count: int
    mean: float
    standard_deviation: float
    minimum: float
    p05: float
    median: float
    p95: float
    maximum: float

    def __post_init__(self) -> None:
        _integer_at_least(self.count, "count", 1)
        values = tuple(
            _finite(value, field_name)
            for field_name, value in (
                ("mean", self.mean),
                ("standard_deviation", self.standard_deviation),
                ("minimum", self.minimum),
                ("p05", self.p05),
                ("median", self.median),
                ("p95", self.p95),
                ("maximum", self.maximum),
            )
        )
        _, standard_deviation, minimum, p05, median, p95, maximum = values
        if standard_deviation < 0:
            raise ConcurrentSimulationContractError(
                "distribution standard_deviation must be non-negative"
            )
        if not minimum <= p05 <= median <= p95 <= maximum:
            raise ConcurrentSimulationContractError(
                "distribution quantiles must be ordered"
            )
        if not minimum <= self.mean <= maximum:
            raise ConcurrentSimulationContractError(
                "distribution mean must lie inside its range"
            )


@dataclass(frozen=True, slots=True)
class SequentialScenarioEvaluation:
    """Ordered paired outcomes and honest descriptive scenario summaries."""

    batch: ScenarioBatch
    calibration: UncertaintyCalibration
    aggregator_id: str
    outcomes: tuple[ScenarioOutcome, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.batch, ScenarioBatch):
            raise TypeError("batch must be a ScenarioBatch")
        if not isinstance(self.calibration, UncertaintyCalibration):
            raise TypeError("calibration must be an UncertaintyCalibration")
        if self.aggregator_id != SEQUENTIAL_AGGREGATOR_ID:
            raise ConcurrentSimulationContractError(
                "sequential aggregator differs from the frozen contract"
            )
        if not isinstance(self.outcomes, tuple):
            raise ConcurrentSimulationContractError("outcomes must be a tuple")
        if any(not isinstance(item, ScenarioOutcome) for item in self.outcomes):
            raise ConcurrentSimulationContractError(
                "every outcome must be a ScenarioOutcome"
            )
        if len(self.outcomes) != self.batch.request.scenario_count:
            raise ConcurrentSimulationContractError(
                "outcome count differs from the scenario batch"
            )
        if tuple(item.scenario_index for item in self.outcomes) != tuple(
            range(self.batch.request.scenario_count)
        ):
            raise ConcurrentSimulationContractError(
                "scenario outcomes must remain ordered and contiguous"
            )
        if tuple(item.scenario_seed for item in self.outcomes) != tuple(
            scenario.scenario_seed for scenario in self.batch.scenarios
        ):
            raise ConcurrentSimulationContractError(
                "scenario outcome seeds differ from the generated batch"
            )

    @property
    def scenario_count(self) -> int:
        return len(self.outcomes)

    @property
    def pit_now_distribution(self) -> ScenarioDistribution:
        return summarize_scenario_distribution(
            tuple(
                item.pit_now_remaining_time_seconds for item in self.outcomes
            )
        )

    @property
    def stay_out_distribution(self) -> ScenarioDistribution:
        return summarize_scenario_distribution(
            tuple(
                item.stay_out_remaining_time_seconds for item in self.outcomes
            )
        )

    @property
    def advantage_distribution(self) -> ScenarioDistribution:
        return summarize_scenario_distribution(
            tuple(item.pit_now_advantage_seconds for item in self.outcomes)
        )

    @property
    def pit_now_scenario_share(self) -> float:
        return self._share(ScenarioPreference.PIT_NOW)

    @property
    def stay_out_scenario_share(self) -> float:
        return self._share(ScenarioPreference.STAY_OUT)

    @property
    def tie_scenario_share(self) -> float:
        return self._share(ScenarioPreference.TIE)

    @property
    def recommendation(self) -> PitDecisionRecommendation:
        """Classify interval stability without claiming correctness probability."""
        if self.scenario_count < MINIMUM_STABILITY_SCENARIO_COUNT:
            return PitDecisionRecommendation.NO_CLEAR_ADVANTAGE
        distribution = self.advantage_distribution
        if distribution.p05 > DECISION_EQUALITY_ABS_TOLERANCE_SECONDS:
            return PitDecisionRecommendation.PIT_NOW
        if distribution.p95 < -DECISION_EQUALITY_ABS_TOLERANCE_SECONDS:
            return PitDecisionRecommendation.STAY_OUT
        return PitDecisionRecommendation.NO_CLEAR_ADVANTAGE

    @property
    def recommendation_is_stable(self) -> bool:
        return (
            self.recommendation
            is not PitDecisionRecommendation.NO_CLEAR_ADVANTAGE
        )

    def _share(self, preference: ScenarioPreference) -> float:
        matching = sum(
            item.preference is preference for item in self.outcomes
        )
        return matching / self.scenario_count


def evaluate_scenario_batch_sequentially(
    batch: ScenarioBatch,
    *,
    calibration: UncertaintyCalibration,
    context: SimulationFeatureContext,
    adapter: Phase6ModelAdapter,
) -> SequentialScenarioEvaluation:
    """Execute every paired scenario in canonical order on the current process."""
    if not isinstance(batch, ScenarioBatch):
        raise TypeError("batch must be a ScenarioBatch")
    if not isinstance(calibration, UncertaintyCalibration):
        raise TypeError("calibration must be an UncertaintyCalibration")
    if not isinstance(context, SimulationFeatureContext):
        raise TypeError("context must be a SimulationFeatureContext")
    if not isinstance(adapter, Phase6ModelAdapter):
        raise TypeError("adapter must be a Phase6ModelAdapter")

    outcomes: list[ScenarioOutcome] = []
    for scenario in batch.scenarios:
        rollout = rollout_paired_scenario(
            batch,
            scenario_index=scenario.scenario_index,
            calibration=calibration,
            context=context,
            adapter=adapter,
        )
        advantage = rollout.pit_now_advantage_seconds
        outcomes.append(
            ScenarioOutcome(
                scenario_index=scenario.scenario_index,
                scenario_seed=scenario.scenario_seed,
                pit_now_remaining_time_seconds=(
                    rollout.pit_now.remaining_time_seconds
                ),
                stay_out_remaining_time_seconds=(
                    rollout.stay_out.remaining_time_seconds
                ),
                pit_now_advantage_seconds=advantage,
                preference=_preference_for_advantage(advantage),
            )
        )
    return SequentialScenarioEvaluation(
        batch=batch,
        calibration=calibration,
        aggregator_id=SEQUENTIAL_AGGREGATOR_ID,
        outcomes=tuple(outcomes),
    )


def summarize_scenario_distribution(
    values: tuple[float, ...],
) -> ScenarioDistribution:
    """Return deterministic linear-interpolation descriptive quantiles."""
    if not isinstance(values, tuple):
        raise ConcurrentSimulationContractError("distribution values must be a tuple")
    if not values:
        raise ConcurrentSimulationContractError(
            "distribution values must not be empty"
        )
    normalized = tuple(_finite(value, "distribution value") for value in values)
    ordered = tuple(sorted(normalized))
    return ScenarioDistribution(
        count=len(ordered),
        mean=fmean(ordered),
        standard_deviation=pstdev(ordered),
        minimum=ordered[0],
        p05=_linear_quantile(ordered, SCENARIO_INTERVAL_LOWER_QUANTILE),
        median=_linear_quantile(ordered, 0.5),
        p95=_linear_quantile(ordered, SCENARIO_INTERVAL_UPPER_QUANTILE),
        maximum=ordered[-1],
    )


def _linear_quantile(ordered: tuple[float, ...], quantile: float) -> float:
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] + weight * (ordered[upper] - ordered[lower])


def _preference_for_advantage(advantage: float) -> ScenarioPreference:
    if math.isclose(
        advantage,
        0.0,
        rel_tol=0.0,
        abs_tol=DECISION_EQUALITY_ABS_TOLERANCE_SECONDS,
    ):
        return ScenarioPreference.TIE
    if advantage > 0:
        return ScenarioPreference.PIT_NOW
    return ScenarioPreference.STAY_OUT


def _finite(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConcurrentSimulationContractError(f"{field_name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ConcurrentSimulationContractError(f"{field_name} must be finite")
    return normalized


def _positive(value: object, field_name: str) -> float:
    normalized = _finite(value, field_name)
    if normalized <= 0:
        raise ConcurrentSimulationContractError(f"{field_name} must be positive")
    return normalized


def _integer_at_least(value: object, field_name: str, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConcurrentSimulationContractError(
            f"{field_name} must be an integer of at least {minimum}"
        )
