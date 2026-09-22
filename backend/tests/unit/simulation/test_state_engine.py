"""Tests for deterministic Phase 7 lap state transitions."""

from dataclasses import replace

import pytest

from app.simulation import (
    DryCompound,
    PitLossAssumption,
    PitLossSource,
    PlannedPitStop,
    RaceState,
    SimulationMode,
    SimulationRequest,
    StrategyPlan,
)
from app.simulation.engine import (
    StateTransitionError,
    advance_one_lap,
    initialize_simulation_progress,
)


def _request(
    *,
    current_lap: int = 20,
    total_laps: int = 22,
    stops: tuple[PlannedPitStop, ...] = (
        PlannedPitStop(20, DryCompound.HARD),
    ),
    pit_loss_seconds: float = 21.5,
    compounds_used: tuple[DryCompound, ...] = (DryCompound.MEDIUM,),
) -> SimulationRequest:
    return SimulationRequest(
        state=RaceState(
            season=2024,
            session_id="2024-01-R",
            event_name="Bahrain Grand Prix",
            driver="VER",
            team="Red Bull Racing",
            current_lap=current_lap,
            total_laps=total_laps,
            current_compound=DryCompound.MEDIUM,
            tyre_age_laps=19,
            current_stint_laps_completed=19,
            completed_pit_stops=0,
            compounds_used=compounds_used,
            previous_position=1,
        ),
        strategy=StrategyPlan(
            strategy_id="medium-to-hard",
            stops=stops,
        ),
        pit_loss=PitLossAssumption(
            seconds=pit_loss_seconds,
            source=PitLossSource.EXPLICIT_ASSUMPTION,
            evidence="declared transition test assumption",
        ),
        mode=SimulationMode.COUNTERFACTUAL_STRATEGY,
    )


def test_initialize_progress_preserves_start_state() -> None:
    """Create a zero-elapsed engine state without mutating the request."""
    request = _request()
    progress = initialize_simulation_progress(request)

    assert progress.start_lap == 20
    assert progress.next_lap == 20
    assert progress.remaining_laps == 3
    assert progress.current_compound is DryCompound.MEDIUM
    assert progress.tyre_age_laps == 19
    assert progress.current_stint_laps_completed == 19
    assert progress.completed_simulation_laps == 0
    assert progress.elapsed_time_seconds == 0.0
    assert not progress.is_finished


def test_non_pit_lap_advances_tyre_stint_and_time() -> None:
    """Advance ordinary racing state by exactly one completed lap."""
    request = _request(
        stops=(PlannedPitStop(21, DryCompound.HARD),),
    )
    progress = initialize_simulation_progress(request)

    advanced, transition = advance_one_lap(
        progress,
        request,
        predicted_lap_time_seconds=91.25,
    )

    assert advanced.next_lap == 21
    assert advanced.remaining_laps == 2
    assert advanced.tyre_age_laps == 20
    assert advanced.current_stint_laps_completed == 20
    assert advanced.completed_pit_stops == 0
    assert advanced.elapsed_time_seconds == 91.25
    assert not transition.pitted
    assert transition.pit_loss_seconds == 0.0
    assert transition.total_lap_time_seconds == 91.25


def test_pit_lap_applies_loss_and_resets_new_stint() -> None:
    """Apply the declared cost once and begin the next lap on fresh tyres."""
    request = _request()
    progress = initialize_simulation_progress(request)

    advanced, transition = advance_one_lap(
        progress,
        request,
        predicted_lap_time_seconds=91.25,
    )

    assert advanced.next_lap == 21
    assert advanced.current_compound is DryCompound.HARD
    assert advanced.tyre_age_laps == 0
    assert advanced.current_stint_laps_completed == 0
    assert advanced.completed_pit_stops == 1
    assert advanced.compounds_used == (
        DryCompound.MEDIUM,
        DryCompound.HARD,
    )
    assert advanced.elapsed_time_seconds == 112.75
    assert transition.pitted
    assert transition.pit_stop == PlannedPitStop(20, DryCompound.HARD)
    assert transition.pit_loss_seconds == 21.5
    assert transition.total_lap_time_seconds == 112.75


def test_pit_loss_is_not_reapplied_on_next_lap() -> None:
    """Charge one scheduled stop on exactly its declared lap."""
    request = _request()
    progress = initialize_simulation_progress(request)
    progress, first = advance_one_lap(
        progress,
        request,
        predicted_lap_time_seconds=91.0,
    )
    progress, second = advance_one_lap(
        progress,
        request,
        predicted_lap_time_seconds=92.0,
    )

    assert first.pit_loss_seconds == 21.5
    assert second.pit_loss_seconds == 0.0
    assert progress.elapsed_time_seconds == 204.5


def test_reusing_compound_does_not_duplicate_history() -> None:
    """Preserve first-use compound order as stable state identity."""
    request = _request(
        stops=(PlannedPitStop(20, DryCompound.MEDIUM),),
        compounds_used=(DryCompound.MEDIUM, DryCompound.HARD),
    )
    progress, _ = advance_one_lap(
        initialize_simulation_progress(request),
        request,
        predicted_lap_time_seconds=90.0,
    )
    assert progress.compounds_used == (
        DryCompound.MEDIUM,
        DryCompound.HARD,
    )


def test_final_lap_marks_progress_finished() -> None:
    """Represent the terminal state without inventing another race lap."""
    request = _request(
        current_lap=22,
        total_laps=22,
        stops=(),
        compounds_used=(DryCompound.SOFT, DryCompound.MEDIUM),
    )
    progress, transition = advance_one_lap(
        initialize_simulation_progress(request),
        request,
        predicted_lap_time_seconds=90.0,
    )

    assert progress.next_lap == 23
    assert progress.remaining_laps == 0
    assert progress.completed_simulation_laps == 1
    assert progress.is_finished
    assert transition.finished


def test_finished_progress_cannot_advance() -> None:
    """Fail instead of silently simulating impossible extra laps."""
    request = _request(
        current_lap=22,
        total_laps=22,
        stops=(),
        compounds_used=(DryCompound.SOFT, DryCompound.MEDIUM),
    )
    progress, _ = advance_one_lap(
        initialize_simulation_progress(request),
        request,
        predicted_lap_time_seconds=90.0,
    )

    with pytest.raises(StateTransitionError, match="finished"):
        advance_one_lap(
            progress,
            request,
            predicted_lap_time_seconds=90.0,
        )


@pytest.mark.parametrize(
    "predicted_lap_time_seconds",
    [0.0, -1.0, float("inf"), float("nan"), True],
)
def test_transition_rejects_invalid_prediction(
    predicted_lap_time_seconds: object,
) -> None:
    """Prevent impossible model output from entering accumulated race time."""
    request = _request()
    with pytest.raises(StateTransitionError):
        advance_one_lap(
            initialize_simulation_progress(request),
            request,
            predicted_lap_time_seconds=predicted_lap_time_seconds,  # type: ignore[arg-type]
        )


def test_equal_inputs_produce_identical_transition() -> None:
    """Prove the engine step is deterministic and free of hidden mutation."""
    request = _request()
    progress = initialize_simulation_progress(request)

    first = advance_one_lap(
        progress,
        request,
        predicted_lap_time_seconds=91.25,
    )
    second = advance_one_lap(
        progress,
        request,
        predicted_lap_time_seconds=91.25,
    )

    assert first == second
    assert progress == initialize_simulation_progress(request)


def test_progress_from_another_request_is_rejected() -> None:
    """Prevent state from one driver or race leaking into another rollout."""
    request = _request()
    progress = replace(
        initialize_simulation_progress(request),
        session_id="2024-02-R",
    )

    with pytest.raises(StateTransitionError, match="session_id"):
        advance_one_lap(
            progress,
            request,
            predicted_lap_time_seconds=91.25,
        )


def test_progress_rejects_inconsistent_completed_lap_count() -> None:
    """Keep next-lap identity tied exactly to completed engine steps."""
    progress = initialize_simulation_progress(_request())
    with pytest.raises(StateTransitionError, match="differs"):
        replace(progress, completed_simulation_laps=1)


def test_transition_records_start_and_end_state() -> None:
    """Keep enough evidence to audit every deterministic state change."""
    request = _request()
    _, transition = advance_one_lap(
        initialize_simulation_progress(request),
        request,
        predicted_lap_time_seconds=91.25,
    )

    assert transition.lap_number == 20
    assert transition.start_compound is DryCompound.MEDIUM
    assert transition.start_tyre_age_laps == 19
    assert transition.start_stint_laps_completed == 19
    assert transition.next_compound is DryCompound.HARD
    assert transition.next_tyre_age_laps == 0
    assert transition.next_stint_laps_completed == 0
    assert transition.elapsed_time_after_lap_seconds == 112.75
