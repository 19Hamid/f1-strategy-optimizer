"""Frozen Phase 8 contracts for pit-now versus stay-out comparison."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from app.simulation import (
    SIMULATION_RANDOM_SEED,
    DryCompound,
    PitLossAssumption,
    PlannedPitStop,
    RaceState,
    SimulationMode,
    SimulationRequest,
    StrategyPlan,
)

OPTIMIZER_CONTRACT_VERSION: Final = "1.0"
STAY_OUT_DEFERRAL_LAPS: Final = 1
MINIMUM_DECISION_HORIZON_LAPS: Final = 3
DECISION_EQUALITY_ABS_TOLERANCE_SECONDS: Final = 1e-9


class OptimizerContractError(ValueError):
    """Raised when a Phase 8 comparison would be incomplete or asymmetric."""


class PitDecisionAction(StrEnum):
    """The two actions available at the start of decision lap t."""

    PIT_NOW = "PIT_NOW"
    STAY_OUT = "STAY_OUT"


class PitDecisionRecommendation(StrEnum):
    """Point-estimate outcome before uncertainty analysis is introduced."""

    PIT_NOW = "PIT_NOW"
    STAY_OUT = "STAY_OUT"
    NO_CLEAR_ADVANTAGE = "NO_CLEAR_ADVANTAGE"


@dataclass(frozen=True, slots=True)
class PitDecisionRequest:
    """One symmetric point-estimate comparison at the start of lap t."""

    state: RaceState
    target_compound: DryCompound
    pit_loss: PitLossAssumption
    random_seed: int = SIMULATION_RANDOM_SEED

    def __post_init__(self) -> None:
        """Normalize inputs and prove that both actions can reach the flag."""
        if not isinstance(self.state, RaceState):
            raise TypeError("state must be a RaceState")
        if not isinstance(self.pit_loss, PitLossAssumption):
            raise TypeError("pit_loss must be a PitLossAssumption")
        try:
            compound = DryCompound(self.target_compound)
        except (TypeError, ValueError) as error:
            raise OptimizerContractError(
                f"unsupported target compound: {self.target_compound!r}"
            ) from error
        object.__setattr__(self, "target_compound", compound)
        if self.remaining_laps < MINIMUM_DECISION_HORIZON_LAPS:
            raise OptimizerContractError(
                "pit-now versus one-lap deferral requires at least three "
                "remaining laps"
            )
        for action in PitDecisionAction:
            self.simulation_request_for(action)

    @property
    def remaining_laps(self) -> int:
        """Return the shared comparison horizon including decision lap t."""
        return self.state.total_laps - self.state.current_lap + 1

    def simulation_request_for(
        self,
        action: PitDecisionAction,
    ) -> SimulationRequest:
        """Build one complete strategy while keeping assumptions identical."""
        try:
            normalized = PitDecisionAction(action)
        except (TypeError, ValueError) as error:
            raise OptimizerContractError(
                f"unsupported pit-decision action: {action!r}"
            ) from error
        deferral = (
            0
            if normalized is PitDecisionAction.PIT_NOW
            else STAY_OUT_DEFERRAL_LAPS
        )
        stop_lap = self.state.current_lap + deferral
        strategy_id = (
            f"{normalized.value.lower()}-"
            f"{self.target_compound.value.lower()}-after-lap-{stop_lap}"
        )
        return SimulationRequest(
            state=self.state,
            strategy=StrategyPlan(
                strategy_id=strategy_id,
                stops=(
                    PlannedPitStop(
                        after_lap=stop_lap,
                        new_compound=self.target_compound,
                    ),
                ),
            ),
            pit_loss=self.pit_loss,
            mode=SimulationMode.COUNTERFACTUAL_STRATEGY,
            random_seed=self.random_seed,
        )


def validate_optimizer_contract() -> None:
    """Assert the stable identities used by downstream Phase 8 work."""
    if OPTIMIZER_CONTRACT_VERSION != "1.0":
        raise OptimizerContractError("optimizer contract version changed")
    if STAY_OUT_DEFERRAL_LAPS != 1:
        raise OptimizerContractError("stay-out action is no longer one-lap deferral")
    if MINIMUM_DECISION_HORIZON_LAPS != 3:
        raise OptimizerContractError("minimum comparison horizon changed")
    if DECISION_EQUALITY_ABS_TOLERANCE_SECONDS != 1e-9:
        raise OptimizerContractError("point-estimate equality tolerance changed")
    if set(PitDecisionAction) != {
        PitDecisionAction.PIT_NOW,
        PitDecisionAction.STAY_OUT,
    }:
        raise OptimizerContractError("pit-decision action set changed")
