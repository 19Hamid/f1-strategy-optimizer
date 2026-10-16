"""Complete deterministic remaining-race rollouts for Phase 7."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.ml import APPROVED_FEATURE_COLUMNS
from app.simulation.contracts import SimulationContractError, SimulationRequest
from app.simulation.engine import (
    LapTransition,
    SimulationProgress,
    advance_one_lap,
    initialize_simulation_progress,
)
from app.simulation.model_adapter import (
    Phase6ModelAdapter,
    SimulationFeatureContext,
)


class StrategyRolloutError(SimulationContractError):
    """Raised when a complete strategy trajectory cannot be reconciled."""


@dataclass(frozen=True, slots=True)
class SimulationLap:
    """One model-backed transition and its immutable inference evidence."""

    transition: LapTransition
    model_features: tuple[tuple[str, object], ...]

    def __post_init__(self) -> None:
        """Require one canonical snapshot of the exact Phase 6 feature row."""
        if not isinstance(self.transition, LapTransition):
            raise TypeError("transition must be a LapTransition")
        if not isinstance(self.model_features, tuple):
            raise StrategyRolloutError("model_features must be a tuple")
        names = tuple(name for name, _ in self.model_features)
        if names != APPROVED_FEATURE_COLUMNS:
            raise StrategyRolloutError(
                "model feature snapshot differs from the Phase 6 contract"
            )


@dataclass(frozen=True, slots=True)
class StrategySimulationResult:
    """Reconciled complete trajectory for one explicit strategy request."""

    request: SimulationRequest
    laps: tuple[SimulationLap, ...]
    final_progress: SimulationProgress

    def __post_init__(self) -> None:
        """Prove that the trajectory reaches the flag without lost cost."""
        if not isinstance(self.request, SimulationRequest):
            raise TypeError("request must be a SimulationRequest")
        if not isinstance(self.laps, tuple) or not self.laps:
            raise StrategyRolloutError("laps must be a non-empty tuple")
        if any(not isinstance(lap, SimulationLap) for lap in self.laps):
            raise StrategyRolloutError("every lap must be a SimulationLap")
        if not isinstance(self.final_progress, SimulationProgress):
            raise TypeError("final_progress must be SimulationProgress")

        state = self.request.state
        expected_numbers = tuple(range(state.current_lap, state.total_laps + 1))
        actual_numbers = tuple(lap.transition.lap_number for lap in self.laps)
        if actual_numbers != expected_numbers:
            raise StrategyRolloutError(
                "trajectory lap numbers differ from the requested horizon"
            )
        if not self.final_progress.is_finished:
            raise StrategyRolloutError("final progress has not reached the flag")
        if self.final_progress.completed_simulation_laps != len(self.laps):
            raise StrategyRolloutError(
                "final progress lap count differs from the trajectory"
            )

        expected_compound = state.current_compound
        expected_tyre_age = state.tyre_age_laps
        expected_stint_laps = state.current_stint_laps_completed
        cumulative_time = 0.0
        for index, lap in enumerate(self.laps):
            transition = lap.transition
            start_state = (
                transition.start_compound,
                transition.start_tyre_age_laps,
                transition.start_stint_laps_completed,
            )
            expected_start_state = (
                expected_compound,
                expected_tyre_age,
                expected_stint_laps,
            )
            if start_state != expected_start_state:
                raise StrategyRolloutError(
                    "consecutive lap states do not form one trajectory"
                )
            if not math.isclose(
                transition.predicted_lap_time_seconds
                + transition.pit_loss_seconds,
                transition.total_lap_time_seconds,
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                raise StrategyRolloutError(
                    "lap racing time and pit loss do not reconcile"
                )
            cumulative_time += transition.total_lap_time_seconds
            if not math.isclose(
                cumulative_time,
                transition.elapsed_time_after_lap_seconds,
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                raise StrategyRolloutError(
                    "lap elapsed time differs from the trajectory total"
                )
            if transition.finished != (index == len(self.laps) - 1):
                raise StrategyRolloutError(
                    "finished marker does not identify only the final lap"
                )
            expected_compound = transition.next_compound
            expected_tyre_age = transition.next_tyre_age_laps
            expected_stint_laps = transition.next_stint_laps_completed

        final_state = (
            self.final_progress.current_compound,
            self.final_progress.tyre_age_laps,
            self.final_progress.current_stint_laps_completed,
        )
        if final_state != (
            expected_compound,
            expected_tyre_age,
            expected_stint_laps,
        ):
            raise StrategyRolloutError(
                "final engine state differs from the final lap transition"
            )

        executed_stops = tuple(
            lap.transition.pit_stop
            for lap in self.laps
            if lap.transition.pit_stop is not None
        )
        if executed_stops != self.request.strategy.stops:
            raise StrategyRolloutError(
                "executed pit stops differ from the requested strategy"
            )
        expected_stop_count = (
            state.completed_pit_stops + len(self.request.strategy.stops)
        )
        if self.final_progress.completed_pit_stops != expected_stop_count:
            raise StrategyRolloutError(
                "final pit-stop count differs from the requested strategy"
            )

        expected_total = self.racing_time_seconds + self.pit_loss_seconds
        if not math.isclose(
            expected_total,
            self.remaining_time_seconds,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise StrategyRolloutError(
                "racing time and pit loss do not reconcile with lap totals"
            )
        if not math.isclose(
            self.remaining_time_seconds,
            self.final_progress.elapsed_time_seconds,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise StrategyRolloutError(
                "trajectory total differs from final engine progress"
            )

    @property
    def strategy_id(self) -> str:
        """Return the explicit strategy identity."""
        return self.request.strategy.strategy_id

    @property
    def laps_simulated(self) -> int:
        """Return the number of predicted remaining laps."""
        return len(self.laps)

    @property
    def pit_stops_simulated(self) -> int:
        """Return the number of executed planned pit stops."""
        return sum(lap.transition.pitted for lap in self.laps)

    @property
    def racing_time_seconds(self) -> float:
        """Return model-predicted racing time without pit loss."""
        return math.fsum(
            lap.transition.predicted_lap_time_seconds for lap in self.laps
        )

    @property
    def pit_loss_seconds(self) -> float:
        """Return separately accounted additive pit cost."""
        return math.fsum(lap.transition.pit_loss_seconds for lap in self.laps)

    @property
    def remaining_time_seconds(self) -> float:
        """Return total predicted time from the decision lap to the flag."""
        return math.fsum(lap.transition.total_lap_time_seconds for lap in self.laps)


def simulate_strategy(
    request: SimulationRequest,
    *,
    context: SimulationFeatureContext,
    adapter: Phase6ModelAdapter,
) -> StrategySimulationResult:
    """Predict and advance every remaining lap for one declared strategy."""
    if not isinstance(request, SimulationRequest):
        raise TypeError("request must be a SimulationRequest")
    if not isinstance(context, SimulationFeatureContext):
        raise TypeError("context must be a SimulationFeatureContext")
    if not isinstance(adapter, Phase6ModelAdapter):
        raise TypeError("adapter must be a Phase6ModelAdapter")

    progress = initialize_simulation_progress(request)
    current_context = context
    laps: list[SimulationLap] = []
    while not progress.is_finished:
        prediction = adapter.predict_next_lap(
            context=current_context,
            progress=progress,
        )
        progress, transition = advance_one_lap(
            progress,
            request,
            predicted_lap_time_seconds=prediction.seconds,
        )
        laps.append(
            SimulationLap(
                transition=transition,
                model_features=_snapshot_features(prediction.features),
            )
        )
        current_context = current_context.record_simulated_lap(
            prediction.seconds
        )

    return StrategySimulationResult(
        request=request,
        laps=tuple(laps),
        final_progress=progress,
    )


def _snapshot_features(frame: pd.DataFrame) -> tuple[tuple[str, object], ...]:
    if not isinstance(frame, pd.DataFrame):
        raise StrategyRolloutError("model features must be a pandas DataFrame")
    if tuple(frame.columns) != APPROVED_FEATURE_COLUMNS or len(frame) != 1:
        raise StrategyRolloutError(
            "model features differ from the one-row Phase 6 contract"
        )
    row = frame.iloc[0]
    return tuple(
        (column, _immutable_scalar(row[column]))
        for column in APPROVED_FEATURE_COLUMNS
    )


def _immutable_scalar(value: object) -> object:
    if pd.isna(value):
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if not isinstance(value, (str, int, float, bool)):
        raise StrategyRolloutError(
            "model feature snapshot contains a non-scalar value"
        )
    return value
