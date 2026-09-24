"""Deterministic Phase 8 comparison using the verified Phase 7 rollout."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.optimizer.contracts import (
    DECISION_EQUALITY_ABS_TOLERANCE_SECONDS,
    OptimizerContractError,
    PitDecisionAction,
    PitDecisionRecommendation,
    PitDecisionRequest,
)
from app.simulation import (
    Phase6ModelAdapter,
    SimulationFeatureContext,
    StrategySimulationResult,
    simulate_strategy,
)


@dataclass(frozen=True, slots=True)
class ActionEvaluation:
    """One action and its complete remaining-race trajectory."""

    action: PitDecisionAction
    simulation: StrategySimulationResult

    def __post_init__(self) -> None:
        """Require canonical action and simulation types."""
        try:
            action = PitDecisionAction(self.action)
        except (TypeError, ValueError) as error:
            raise OptimizerContractError(
                f"unsupported evaluated action: {self.action!r}"
            ) from error
        if not isinstance(self.simulation, StrategySimulationResult):
            raise TypeError("simulation must be a StrategySimulationResult")
        object.__setattr__(self, "action", action)

    @property
    def expected_remaining_time_seconds(self) -> float:
        """Return the model point estimate from decision lap to the flag."""
        return self.simulation.remaining_time_seconds


@dataclass(frozen=True, slots=True)
class PitDecisionComparison:
    """Reconciled pit-now and stay-out point estimates under one request."""

    request: PitDecisionRequest
    evaluations: tuple[ActionEvaluation, ...]

    def __post_init__(self) -> None:
        """Prove that both actions used the exact shared assumptions."""
        if not isinstance(self.request, PitDecisionRequest):
            raise TypeError("request must be a PitDecisionRequest")
        if not isinstance(self.evaluations, tuple):
            raise OptimizerContractError("evaluations must be a tuple")
        if any(
            not isinstance(evaluation, ActionEvaluation)
            for evaluation in self.evaluations
        ):
            raise OptimizerContractError(
                "every evaluation must be an ActionEvaluation"
            )
        expected_actions = tuple(PitDecisionAction)
        actual_actions = tuple(
            evaluation.action for evaluation in self.evaluations
        )
        if actual_actions != expected_actions:
            raise OptimizerContractError(
                "comparison must contain PIT_NOW then STAY_OUT exactly once"
            )
        for evaluation in self.evaluations:
            expected_request = self.request.simulation_request_for(
                evaluation.action
            )
            if evaluation.simulation.request != expected_request:
                raise OptimizerContractError(
                    f"{evaluation.action.value} simulation changed shared assumptions"
                )

    @property
    def pit_now(self) -> ActionEvaluation:
        """Return the canonical immediate-stop evaluation."""
        return self.evaluations[0]

    @property
    def stay_out(self) -> ActionEvaluation:
        """Return the canonical one-lap-deferral evaluation."""
        return self.evaluations[1]

    @property
    def pit_now_advantage_seconds(self) -> float:
        """Return positive seconds when PIT_NOW is faster than STAY_OUT."""
        return (
            self.stay_out.expected_remaining_time_seconds
            - self.pit_now.expected_remaining_time_seconds
        )

    @property
    def recommendation(self) -> PitDecisionRecommendation:
        """Choose the lower point estimate without claiming certainty."""
        advantage = self.pit_now_advantage_seconds
        if math.isclose(
            advantage,
            0.0,
            rel_tol=0.0,
            abs_tol=DECISION_EQUALITY_ABS_TOLERANCE_SECONDS,
        ):
            return PitDecisionRecommendation.NO_CLEAR_ADVANTAGE
        if advantage > 0:
            return PitDecisionRecommendation.PIT_NOW
        return PitDecisionRecommendation.STAY_OUT

    def regret_seconds(self, action: PitDecisionAction) -> float:
        """Return point-estimate regret under the identical simulator inputs."""
        try:
            normalized = PitDecisionAction(action)
        except (TypeError, ValueError) as error:
            raise OptimizerContractError(
                f"unsupported regret action: {action!r}"
            ) from error
        times = {
            evaluation.action: evaluation.expected_remaining_time_seconds
            for evaluation in self.evaluations
        }
        return times[normalized] - min(times.values())


def compare_pit_decision(
    request: PitDecisionRequest,
    *,
    context: SimulationFeatureContext,
    adapter: Phase6ModelAdapter,
) -> PitDecisionComparison:
    """Simulate both actions from one state and compare remaining time."""
    if not isinstance(request, PitDecisionRequest):
        raise TypeError("request must be a PitDecisionRequest")
    if not isinstance(context, SimulationFeatureContext):
        raise TypeError("context must be a SimulationFeatureContext")
    if not isinstance(adapter, Phase6ModelAdapter):
        raise TypeError("adapter must be a Phase6ModelAdapter")
    evaluations = tuple(
        ActionEvaluation(
            action=action,
            simulation=simulate_strategy(
                request.simulation_request_for(action),
                context=context,
                adapter=adapter,
            ),
        )
        for action in PitDecisionAction
    )
    return PitDecisionComparison(
        request=request,
        evaluations=evaluations,
    )
