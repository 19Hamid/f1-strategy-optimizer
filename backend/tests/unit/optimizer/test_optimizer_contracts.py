"""Tests for the frozen Phase 8 optimizer contract."""

from dataclasses import replace

import pytest

from app.optimizer import (
    DECISION_EQUALITY_ABS_TOLERANCE_SECONDS,
    MINIMUM_DECISION_HORIZON_LAPS,
    OPTIMIZER_CONTRACT_VERSION,
    STAY_OUT_DEFERRAL_LAPS,
    OptimizerContractError,
    PitDecisionAction,
    PitDecisionRequest,
    validate_optimizer_contract,
)
from app.simulation import (
    SIMULATION_RANDOM_SEED,
    DryCompound,
    PitLossAssumption,
    PitLossSource,
    RaceState,
    SimulationMode,
)


def _state(**overrides: object) -> RaceState:
    values: dict[str, object] = {
        "season": 2024,
        "session_id": "2024-01-R",
        "event_name": "Bahrain Grand Prix",
        "driver": "VER",
        "team": "Red Bull Racing",
        "current_lap": 20,
        "total_laps": 22,
        "current_compound": DryCompound.MEDIUM,
        "tyre_age_laps": 19,
        "current_stint_laps_completed": 19,
        "completed_pit_stops": 0,
        "compounds_used": (DryCompound.MEDIUM,),
        "previous_position": 1,
    }
    values.update(overrides)
    return RaceState(**values)  # type: ignore[arg-type]


def _pit_loss() -> PitLossAssumption:
    return PitLossAssumption(
        seconds=20.0,
        source=PitLossSource.EXPLICIT_ASSUMPTION,
        evidence="optimizer unit-test assumption",
    )


def _request(**overrides: object) -> PitDecisionRequest:
    values: dict[str, object] = {
        "state": _state(),
        "target_compound": DryCompound.HARD,
        "pit_loss": _pit_loss(),
    }
    values.update(overrides)
    return PitDecisionRequest(**values)  # type: ignore[arg-type]


def test_contract_constants_are_frozen() -> None:
    """Expose the stable identities needed by later optimizer milestones."""
    validate_optimizer_contract()

    assert OPTIMIZER_CONTRACT_VERSION == "1.0"
    assert STAY_OUT_DEFERRAL_LAPS == 1
    assert MINIMUM_DECISION_HORIZON_LAPS == 3
    assert DECISION_EQUALITY_ABS_TOLERANCE_SECONDS == 1e-9
    assert tuple(PitDecisionAction) == (
        PitDecisionAction.PIT_NOW,
        PitDecisionAction.STAY_OUT,
    )


def test_actions_build_symmetric_complete_strategy_requests() -> None:
    """Change only the stop lap while preserving every shared assumption."""
    request = _request()
    pit_now = request.simulation_request_for(PitDecisionAction.PIT_NOW)
    stay_out = request.simulation_request_for(PitDecisionAction.STAY_OUT)

    assert pit_now.state is stay_out.state is request.state
    assert pit_now.pit_loss is stay_out.pit_loss is request.pit_loss
    assert pit_now.random_seed == stay_out.random_seed == SIMULATION_RANDOM_SEED
    assert pit_now.mode is stay_out.mode is SimulationMode.COUNTERFACTUAL_STRATEGY
    assert pit_now.strategy.stops[0].after_lap == 20
    assert stay_out.strategy.stops[0].after_lap == 21
    assert pit_now.strategy.stops[0].new_compound is DryCompound.HARD
    assert stay_out.strategy.stops[0].new_compound is DryCompound.HARD


def test_request_normalizes_supported_compound_text() -> None:
    """Accept canonical serialized compound values at the public boundary."""
    request = _request(target_compound="HARD")

    assert request.target_compound is DryCompound.HARD


def test_same_compound_stop_is_legal_after_two_compounds_were_used() -> None:
    """Allow a fresh same-compound tyre set when the race tyre rule is met."""
    state = _state(
        current_compound=DryCompound.HARD,
        compounds_used=(DryCompound.MEDIUM, DryCompound.HARD),
    )
    request = _request(state=state, target_compound=DryCompound.HARD)

    assert request.simulation_request_for(
        PitDecisionAction.PIT_NOW
    ).strategy.stops[0].new_compound is DryCompound.HARD


def test_request_rejects_horizon_too_short_for_fair_deferral() -> None:
    """Do not compare an immediate stop with an impossible deferred stop."""
    with pytest.raises(OptimizerContractError, match="at least three"):
        _request(state=_state(current_lap=21, total_laps=22))


def test_request_rejects_unknown_compound_and_action() -> None:
    """Fail closed on values outside the controlled dry-race action space."""
    with pytest.raises(OptimizerContractError, match="target compound"):
        _request(target_compound="INTERMEDIATE")

    with pytest.raises(OptimizerContractError, match="action"):
        _request().simulation_request_for("BOX_BOX")  # type: ignore[arg-type]


def test_request_rejects_incomplete_boundary_types() -> None:
    """Require verified simulator state and explicit pit-loss evidence."""
    with pytest.raises(TypeError, match="state"):
        _request(state=object())
    with pytest.raises(TypeError, match="pit_loss"):
        _request(pit_loss=object())


def test_simulator_contract_still_enforces_two_compounds() -> None:
    """Do not let Phase 8 bypass the inherited dry-race tyre rule."""
    with pytest.raises(ValueError, match="at least two compounds"):
        _request(target_compound=DryCompound.MEDIUM)


def test_shortened_state_remains_invalid_after_replacement() -> None:
    """Revalidate a copied request instead of trusting stale construction."""
    request = _request()

    with pytest.raises(OptimizerContractError, match="at least three"):
        replace(request, state=_state(current_lap=22, total_laps=22))
