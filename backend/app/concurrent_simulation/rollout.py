"""Calibrated paired stochastic action rollouts for Phase 9."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Final

from app.concurrent_simulation.calibration import UncertaintyCalibration
from app.concurrent_simulation.contracts import (
    ConcurrentSimulationContractError,
    ScenarioBatch,
    UncertaintyScenario,
)
from app.optimizer.contracts import PitDecisionAction, PitDecisionRequest
from app.simulation import (
    LapTransition,
    Phase6ModelAdapter,
    SimulationFeatureContext,
    SimulationProgress,
    SimulationRequest,
    advance_one_lap,
    initialize_simulation_progress,
)

MINIMUM_REALIZED_LAP_TIME_SECONDS: Final = 1e-6


@dataclass(frozen=True, slots=True)
class StochasticLap:
    """One nominal model prediction plus its explicit scenario adjustments."""

    transition: LapTransition
    nominal_model_seconds: float
    shared_pace_adjustment_seconds: float
    lap_residual_adjustment_seconds: float
    unclipped_racing_time_seconds: float

    def __post_init__(self) -> None:
        if not isinstance(self.transition, LapTransition):
            raise TypeError("transition must be a LapTransition")
        nominal = _positive(self.nominal_model_seconds, "nominal_model_seconds")
        shared = _finite(
            self.shared_pace_adjustment_seconds,
            "shared_pace_adjustment_seconds",
        )
        residual = _finite(
            self.lap_residual_adjustment_seconds,
            "lap_residual_adjustment_seconds",
        )
        unclipped = _finite(
            self.unclipped_racing_time_seconds,
            "unclipped_racing_time_seconds",
        )
        if not math.isclose(
            unclipped,
            nominal + shared + residual,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ConcurrentSimulationContractError(
                "stochastic lap adjustments do not reconcile"
            )
        expected_realized = max(
            unclipped,
            MINIMUM_REALIZED_LAP_TIME_SECONDS,
        )
        if not math.isclose(
            self.transition.predicted_lap_time_seconds,
            expected_realized,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ConcurrentSimulationContractError(
                "transition racing time differs from calibrated perturbation"
            )

    @property
    def realized_racing_time_seconds(self) -> float:
        return self.transition.predicted_lap_time_seconds

    @property
    def was_clipped(self) -> bool:
        return self.unclipped_racing_time_seconds < MINIMUM_REALIZED_LAP_TIME_SECONDS


@dataclass(frozen=True, slots=True)
class StochasticActionRollout:
    """One complete perturbed action trajectory in a declared race world."""

    action: PitDecisionAction
    nominal_request: SimulationRequest
    perturbed_request: SimulationRequest
    scenario_index: int
    scenario_seed: int
    calibration_id: str
    unclipped_pit_loss_seconds: float
    laps: tuple[StochasticLap, ...]
    final_progress: SimulationProgress

    def __post_init__(self) -> None:
        try:
            action = PitDecisionAction(self.action)
        except (TypeError, ValueError) as error:
            raise ConcurrentSimulationContractError(
                f"unsupported stochastic action: {self.action!r}"
            ) from error
        object.__setattr__(self, "action", action)
        if not isinstance(self.nominal_request, SimulationRequest):
            raise TypeError("nominal_request must be a SimulationRequest")
        if not isinstance(self.perturbed_request, SimulationRequest):
            raise TypeError("perturbed_request must be a SimulationRequest")
        if replace(
            self.perturbed_request,
            pit_loss=self.nominal_request.pit_loss,
        ) != self.nominal_request:
            raise ConcurrentSimulationContractError(
                "stochastic action may change only the pit-loss assumption"
            )
        _integer_at_least(self.scenario_index, "scenario_index", 0)
        _integer_at_least(self.scenario_seed, "scenario_seed", 0)
        _text(self.calibration_id, "calibration_id")
        unclipped_pit_loss = _finite(
            self.unclipped_pit_loss_seconds,
            "unclipped_pit_loss_seconds",
        )
        if not math.isclose(
            self.perturbed_request.pit_loss.seconds,
            max(unclipped_pit_loss, 0.0),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ConcurrentSimulationContractError(
                "perturbed pit loss does not reconcile"
            )
        if not isinstance(self.laps, tuple) or not self.laps:
            raise ConcurrentSimulationContractError("laps must be a non-empty tuple")
        if any(not isinstance(lap, StochasticLap) for lap in self.laps):
            raise ConcurrentSimulationContractError(
                "every stochastic lap must be a StochasticLap"
            )
        if not isinstance(self.final_progress, SimulationProgress):
            raise TypeError("final_progress must be a SimulationProgress")
        expected_laps = tuple(
            range(
                self.nominal_request.state.current_lap,
                self.nominal_request.state.total_laps + 1,
            )
        )
        actual_laps = tuple(lap.transition.lap_number for lap in self.laps)
        if actual_laps != expected_laps:
            raise ConcurrentSimulationContractError(
                "stochastic trajectory differs from the decision horizon"
            )
        if not self.final_progress.is_finished:
            raise ConcurrentSimulationContractError(
                "stochastic trajectory has not reached the flag"
            )
        if self.final_progress.completed_simulation_laps != len(self.laps):
            raise ConcurrentSimulationContractError(
                "final progress differs from stochastic trajectory length"
            )
        if not math.isclose(
            self.final_progress.elapsed_time_seconds,
            self.remaining_time_seconds,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ConcurrentSimulationContractError(
                "stochastic trajectory total does not reconcile"
            )

    @property
    def pit_loss_adjustment_seconds(self) -> float:
        return (
            self.perturbed_request.pit_loss.seconds
            - self.nominal_request.pit_loss.seconds
        )

    @property
    def pit_loss_was_clipped(self) -> bool:
        return self.unclipped_pit_loss_seconds < 0.0

    @property
    def remaining_time_seconds(self) -> float:
        return math.fsum(lap.transition.total_lap_time_seconds for lap in self.laps)


@dataclass(frozen=True, slots=True)
class PairedScenarioRollout:
    """Both actions evaluated inside exactly one calibrated race world."""

    decision_request: PitDecisionRequest
    scenario: UncertaintyScenario
    calibration: UncertaintyCalibration
    actions: tuple[StochasticActionRollout, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.decision_request, PitDecisionRequest):
            raise TypeError("decision_request must be a PitDecisionRequest")
        if not isinstance(self.scenario, UncertaintyScenario):
            raise TypeError("scenario must be an UncertaintyScenario")
        if not isinstance(self.calibration, UncertaintyCalibration):
            raise TypeError("calibration must be an UncertaintyCalibration")
        expected_laps = tuple(
            range(
                self.decision_request.state.current_lap,
                self.decision_request.state.total_laps + 1,
            )
        )
        if self.scenario.lap_numbers != expected_laps:
            raise ConcurrentSimulationContractError(
                "scenario coordinates differ from the decision horizon"
            )
        if not isinstance(self.actions, tuple):
            raise ConcurrentSimulationContractError("actions must be a tuple")
        if any(
            not isinstance(action, StochasticActionRollout)
            for action in self.actions
        ):
            raise ConcurrentSimulationContractError(
                "every paired action must be a StochasticActionRollout"
            )
        if tuple(action.action for action in self.actions) != tuple(PitDecisionAction):
            raise ConcurrentSimulationContractError(
                "paired rollout must contain PIT_NOW then STAY_OUT exactly once"
            )
        for action in self.actions:
            if action.nominal_request != self.decision_request.simulation_request_for(
                action.action
            ):
                raise ConcurrentSimulationContractError(
                    "paired action changed the Phase 8 decision request"
                )
            if (
                action.scenario_index != self.scenario.scenario_index
                or action.scenario_seed != self.scenario.scenario_seed
                or action.calibration_id != self.calibration.calibration_id
            ):
                raise ConcurrentSimulationContractError(
                    "paired actions must share scenario and calibration identity"
                )
        if not math.isclose(
            self.pit_now.pit_loss_adjustment_seconds,
            self.stay_out.pit_loss_adjustment_seconds,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ConcurrentSimulationContractError(
                "paired actions must share the pit-loss perturbation"
            )
        for pit_lap, stay_lap in zip(
            self.pit_now.laps,
            self.stay_out.laps,
            strict=True,
        ):
            if (
                pit_lap.transition.lap_number != stay_lap.transition.lap_number
                or pit_lap.shared_pace_adjustment_seconds
                != stay_lap.shared_pace_adjustment_seconds
                or pit_lap.lap_residual_adjustment_seconds
                != stay_lap.lap_residual_adjustment_seconds
            ):
                raise ConcurrentSimulationContractError(
                    "paired actions must share absolute-lap perturbations"
                )

    @property
    def pit_now(self) -> StochasticActionRollout:
        return self.actions[0]

    @property
    def stay_out(self) -> StochasticActionRollout:
        return self.actions[1]

    @property
    def pit_now_advantage_seconds(self) -> float:
        return (
            self.stay_out.remaining_time_seconds
            - self.pit_now.remaining_time_seconds
        )


def rollout_paired_scenario(
    batch: ScenarioBatch,
    *,
    scenario_index: int,
    calibration: UncertaintyCalibration,
    context: SimulationFeatureContext,
    adapter: Phase6ModelAdapter,
) -> PairedScenarioRollout:
    """Run both complete Phase 8 actions in one paired calibrated scenario."""
    if not isinstance(batch, ScenarioBatch):
        raise TypeError("batch must be a ScenarioBatch")
    if not isinstance(calibration, UncertaintyCalibration):
        raise TypeError("calibration must be an UncertaintyCalibration")
    if not isinstance(context, SimulationFeatureContext):
        raise TypeError("context must be a SimulationFeatureContext")
    if not isinstance(adapter, Phase6ModelAdapter):
        raise TypeError("adapter must be a Phase6ModelAdapter")
    scenario = batch.scenario_for(scenario_index)
    actions = tuple(
        _rollout_action(
            batch.request.decision_request,
            action=action,
            scenario=scenario,
            calibration=calibration,
            context=context,
            adapter=adapter,
        )
        for action in PitDecisionAction
    )
    return PairedScenarioRollout(
        decision_request=batch.request.decision_request,
        scenario=scenario,
        calibration=calibration,
        actions=actions,
    )


def _rollout_action(
    decision_request: PitDecisionRequest,
    *,
    action: PitDecisionAction,
    scenario: UncertaintyScenario,
    calibration: UncertaintyCalibration,
    context: SimulationFeatureContext,
    adapter: Phase6ModelAdapter,
) -> StochasticActionRollout:
    nominal_request = decision_request.simulation_request_for(action)
    unclipped_pit_loss = (
        nominal_request.pit_loss.seconds
        + scenario.pit_loss_z * calibration.pit_loss_scale_seconds
    )
    perturbed_pit_loss = replace(
        nominal_request.pit_loss,
        seconds=max(unclipped_pit_loss, 0.0),
        evidence=(
            f"{nominal_request.pit_loss.evidence}; "
            f"phase9_calibration={calibration.calibration_id}; "
            f"scenario_index={scenario.scenario_index}"
        ),
    )
    perturbed_request = replace(
        nominal_request,
        pit_loss=perturbed_pit_loss,
    )

    progress = initialize_simulation_progress(perturbed_request)
    current_context = context
    laps: list[StochasticLap] = []
    shared_adjustment = (
        scenario.shared_pace_z * calibration.shared_pace_scale_seconds
    )
    while not progress.is_finished:
        prediction = adapter.predict_next_lap(
            context=current_context,
            progress=progress,
        )
        residual_adjustment = (
            scenario.lap_time_z_for(progress.next_lap)
            * calibration.lap_time_residual_scale_seconds
        )
        unclipped_racing_time = (
            prediction.seconds + shared_adjustment + residual_adjustment
        )
        realized_racing_time = max(
            unclipped_racing_time,
            MINIMUM_REALIZED_LAP_TIME_SECONDS,
        )
        progress, transition = advance_one_lap(
            progress,
            perturbed_request,
            predicted_lap_time_seconds=realized_racing_time,
        )
        laps.append(
            StochasticLap(
                transition=transition,
                nominal_model_seconds=prediction.seconds,
                shared_pace_adjustment_seconds=shared_adjustment,
                lap_residual_adjustment_seconds=residual_adjustment,
                unclipped_racing_time_seconds=unclipped_racing_time,
            )
        )
        current_context = current_context.record_simulated_lap(
            realized_racing_time
        )

    return StochasticActionRollout(
        action=action,
        nominal_request=nominal_request,
        perturbed_request=perturbed_request,
        scenario_index=scenario.scenario_index,
        scenario_seed=scenario.scenario_seed,
        calibration_id=calibration.calibration_id,
        unclipped_pit_loss_seconds=unclipped_pit_loss,
        laps=tuple(laps),
        final_progress=progress,
    )


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConcurrentSimulationContractError(
            f"{field_name} must not be blank"
        )
    return value.strip()


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
