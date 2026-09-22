"""Pure deterministic lap-by-lap state transitions for Phase 7."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from app.simulation.contracts import (
    DryCompound,
    PlannedPitStop,
    SimulationContractError,
    SimulationRequest,
)


class StateTransitionError(SimulationContractError):
    """Raised when a lap transition would create impossible simulator state."""


@dataclass(frozen=True, slots=True)
class SimulationProgress:
    """Immutable state immediately before the next simulated lap."""

    season: int
    session_id: str
    event_name: str
    driver: str
    team: str
    start_lap: int
    next_lap: int
    total_laps: int
    current_compound: DryCompound
    tyre_age_laps: int
    current_stint_laps_completed: int
    completed_pit_stops: int
    compounds_used: tuple[DryCompound, ...]
    completed_simulation_laps: int
    elapsed_time_seconds: float

    def __post_init__(self) -> None:
        """Fail closed on internally inconsistent progress."""
        if self.start_lap < 1 or self.start_lap > self.total_laps:
            raise StateTransitionError("start_lap is outside the race horizon")
        if self.next_lap < self.start_lap or self.next_lap > self.total_laps + 1:
            raise StateTransitionError("next_lap is outside the simulation horizon")
        expected_completed = self.next_lap - self.start_lap
        if self.completed_simulation_laps != expected_completed:
            raise StateTransitionError(
                "completed_simulation_laps differs from lap progress"
            )
        if self.tyre_age_laps < 0:
            raise StateTransitionError("tyre_age_laps must be non-negative")
        if self.current_stint_laps_completed < 0:
            raise StateTransitionError(
                "current_stint_laps_completed must be non-negative"
            )
        if self.completed_pit_stops < 0:
            raise StateTransitionError("completed_pit_stops must be non-negative")
        if self.current_compound not in self.compounds_used:
            raise StateTransitionError(
                "current_compound must appear in compounds_used"
            )
        _positive_or_zero(self.elapsed_time_seconds, "elapsed_time_seconds")

    @property
    def is_finished(self) -> bool:
        """Return whether the final scheduled lap has been completed."""
        return self.next_lap > self.total_laps

    @property
    def remaining_laps(self) -> int:
        """Return the number of laps still to simulate."""
        return max(self.total_laps - self.next_lap + 1, 0)


@dataclass(frozen=True, slots=True)
class LapTransition:
    """Auditable result of advancing exactly one simulated lap."""

    lap_number: int
    start_compound: DryCompound
    start_tyre_age_laps: int
    start_stint_laps_completed: int
    predicted_lap_time_seconds: float
    pit_loss_seconds: float
    total_lap_time_seconds: float
    pit_stop: PlannedPitStop | None
    next_compound: DryCompound
    next_tyre_age_laps: int
    next_stint_laps_completed: int
    elapsed_time_after_lap_seconds: float
    finished: bool

    @property
    def pitted(self) -> bool:
        """Return whether this transition executed a planned stop."""
        return self.pit_stop is not None


def initialize_simulation_progress(
    request: SimulationRequest,
) -> SimulationProgress:
    """Create zero-elapsed immutable progress from a validated request."""
    if not isinstance(request, SimulationRequest):
        raise TypeError("request must be a SimulationRequest")
    state = request.state
    return SimulationProgress(
        season=state.season,
        session_id=state.session_id,
        event_name=state.event_name,
        driver=state.driver,
        team=state.team,
        start_lap=state.current_lap,
        next_lap=state.current_lap,
        total_laps=state.total_laps,
        current_compound=state.current_compound,
        tyre_age_laps=state.tyre_age_laps,
        current_stint_laps_completed=state.current_stint_laps_completed,
        completed_pit_stops=state.completed_pit_stops,
        compounds_used=state.compounds_used,
        completed_simulation_laps=0,
        elapsed_time_seconds=0.0,
    )


def advance_one_lap(
    progress: SimulationProgress,
    request: SimulationRequest,
    *,
    predicted_lap_time_seconds: float,
) -> tuple[SimulationProgress, LapTransition]:
    """Advance one lap without mutation, hidden state or implicit pit cost."""
    if not isinstance(progress, SimulationProgress):
        raise TypeError("progress must be SimulationProgress")
    if not isinstance(request, SimulationRequest):
        raise TypeError("request must be a SimulationRequest")
    _verify_progress_identity(progress, request)
    if progress.is_finished:
        raise StateTransitionError("cannot advance a finished simulation")

    predicted_time = _positive(
        predicted_lap_time_seconds,
        "predicted_lap_time_seconds",
    )
    pit_stop = _pit_stop_after_lap(request, progress.next_lap)
    pit_loss = request.pit_loss.seconds if pit_stop is not None else 0.0
    total_lap_time = predicted_time + pit_loss
    elapsed_time = progress.elapsed_time_seconds + total_lap_time

    if pit_stop is None:
        next_compound = progress.current_compound
        next_tyre_age = progress.tyre_age_laps + 1
        next_stint_laps = progress.current_stint_laps_completed + 1
        completed_pit_stops = progress.completed_pit_stops
        compounds_used = progress.compounds_used
    else:
        next_compound = pit_stop.new_compound
        next_tyre_age = 0
        next_stint_laps = 0
        completed_pit_stops = progress.completed_pit_stops + 1
        compounds_used = _append_compound_once(
            progress.compounds_used,
            next_compound,
        )

    next_progress = replace(
        progress,
        next_lap=progress.next_lap + 1,
        current_compound=next_compound,
        tyre_age_laps=next_tyre_age,
        current_stint_laps_completed=next_stint_laps,
        completed_pit_stops=completed_pit_stops,
        compounds_used=compounds_used,
        completed_simulation_laps=progress.completed_simulation_laps + 1,
        elapsed_time_seconds=elapsed_time,
    )
    transition = LapTransition(
        lap_number=progress.next_lap,
        start_compound=progress.current_compound,
        start_tyre_age_laps=progress.tyre_age_laps,
        start_stint_laps_completed=progress.current_stint_laps_completed,
        predicted_lap_time_seconds=predicted_time,
        pit_loss_seconds=pit_loss,
        total_lap_time_seconds=total_lap_time,
        pit_stop=pit_stop,
        next_compound=next_compound,
        next_tyre_age_laps=next_tyre_age,
        next_stint_laps_completed=next_stint_laps,
        elapsed_time_after_lap_seconds=elapsed_time,
        finished=next_progress.is_finished,
    )
    return next_progress, transition


def _verify_progress_identity(
    progress: SimulationProgress,
    request: SimulationRequest,
) -> None:
    state = request.state
    identities = (
        ("season", progress.season, state.season),
        ("session_id", progress.session_id, state.session_id),
        ("event_name", progress.event_name, state.event_name),
        ("driver", progress.driver, state.driver),
        ("team", progress.team, state.team),
        ("start_lap", progress.start_lap, state.current_lap),
        ("total_laps", progress.total_laps, state.total_laps),
    )
    mismatches = [name for name, actual, expected in identities if actual != expected]
    if mismatches:
        raise StateTransitionError(
            "progress and request differ: " + ", ".join(mismatches)
        )


def _pit_stop_after_lap(
    request: SimulationRequest,
    lap_number: int,
) -> PlannedPitStop | None:
    return next(
        (
            stop
            for stop in request.strategy.stops
            if stop.after_lap == lap_number
        ),
        None,
    )


def _append_compound_once(
    compounds: tuple[DryCompound, ...],
    compound: DryCompound,
) -> tuple[DryCompound, ...]:
    if compound in compounds:
        return compounds
    return (*compounds, compound)


def _positive(value: object, field_name: str) -> float:
    normalized = _number(value, field_name)
    if normalized <= 0:
        raise StateTransitionError(f"{field_name} must be positive")
    return normalized


def _positive_or_zero(value: object, field_name: str) -> float:
    normalized = _number(value, field_name)
    if normalized < 0:
        raise StateTransitionError(f"{field_name} must be non-negative")
    return normalized


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StateTransitionError(f"{field_name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise StateTransitionError(f"{field_name} must be finite")
    return normalized
