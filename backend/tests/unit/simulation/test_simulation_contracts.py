"""Tests for the frozen Phase 7 race-simulation contract."""

from dataclasses import replace

import pytest

from app.simulation import (
    DEVELOPMENT_SEASONS,
    PROTECTED_EVALUATION_SEASON,
    SIMULATION_CONTRACT_VERSION,
    SIMULATION_RANDOM_SEED,
    DryCompound,
    PitLossAssumption,
    PitLossSource,
    PlannedPitStop,
    RaceState,
    SimulationContractError,
    SimulationMode,
    SimulationRequest,
    StrategyPlan,
    validate_simulation_contract,
)


def _state(**changes: object) -> RaceState:
    values: dict[str, object] = {
        "season": 2024,
        "session_id": "2024-01-R",
        "event_name": "Bahrain Grand Prix",
        "driver": "VER",
        "team": "Red Bull Racing",
        "current_lap": 20,
        "total_laps": 57,
        "current_compound": DryCompound.MEDIUM,
        "tyre_age_laps": 19,
        "current_stint_laps_completed": 19,
        "completed_pit_stops": 0,
        "compounds_used": (DryCompound.MEDIUM,),
        "previous_position": 1,
    }
    values.update(changes)
    return RaceState(**values)  # type: ignore[arg-type]


def _request(**changes: object) -> SimulationRequest:
    values: dict[str, object] = {
        "state": _state(),
        "strategy": StrategyPlan(
            strategy_id="medium-to-hard",
            stops=(PlannedPitStop(30, DryCompound.HARD),),
        ),
        "pit_loss": PitLossAssumption(
            seconds=21.5,
            source=PitLossSource.EXPLICIT_ASSUMPTION,
            evidence="declared V1 sensitivity parameter",
        ),
        "mode": SimulationMode.COUNTERFACTUAL_STRATEGY,
    }
    values.update(changes)
    return SimulationRequest(**values)  # type: ignore[arg-type]


def test_contract_freezes_scope_and_seed() -> None:
    """Record the exact initial simulator scope."""
    assert SIMULATION_CONTRACT_VERSION == "1.2"
    assert SIMULATION_RANDOM_SEED == 42
    assert DEVELOPMENT_SEASONS == (2022, 2023, 2024)
    assert PROTECTED_EVALUATION_SEASON == 2025
    assert {compound.value for compound in DryCompound} == {
        "SOFT",
        "MEDIUM",
        "HARD",
    }
    validate_simulation_contract()


@pytest.mark.parametrize("season", DEVELOPMENT_SEASONS)
def test_state_accepts_development_seasons(season: int) -> None:
    """Keep simulator development inside the frozen period."""
    assert _state(season=season).season == season


def test_state_rejects_protected_2025() -> None:
    """Prevent holdout data from influencing simulator development."""
    with pytest.raises(
        SimulationContractError,
        match="protected 2025 data",
    ):
        _state(season=2025)


@pytest.mark.parametrize("season", [2021, 2026])
def test_state_rejects_other_seasons(season: int) -> None:
    """Reject accidental scope expansion without a contract revision."""
    with pytest.raises(SimulationContractError, match="outside"):
        _state(season=season)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"current_lap": 0}, "current_lap"),
        ({"current_lap": 58}, "must not exceed"),
        ({"total_laps": 0}, "total_laps"),
        ({"tyre_age_laps": -1}, "tyre_age_laps"),
        (
            {"current_stint_laps_completed": -1},
            "current_stint_laps_completed",
        ),
        ({"completed_pit_stops": -1}, "completed_pit_stops"),
        ({"previous_position": 21}, "previous_position"),
    ],
)
def test_state_rejects_impossible_values(
    changes: dict[str, object],
    message: str,
) -> None:
    """Fail closed before impossible state reaches the simulator."""
    with pytest.raises(SimulationContractError, match=message):
        _state(**changes)


def test_state_normalizes_compounds() -> None:
    """Allow serialized enum values while preserving the typed contract."""
    state = _state(
        current_compound="MEDIUM",
        compounds_used=("SOFT", "MEDIUM"),
    )
    assert state.current_compound is DryCompound.MEDIUM
    assert state.compounds_used == (
        DryCompound.SOFT,
        DryCompound.MEDIUM,
    )


def test_state_requires_current_compound_in_history() -> None:
    """Keep the current stint consistent with compounds already used."""
    with pytest.raises(SimulationContractError, match="must appear"):
        _state(compounds_used=(DryCompound.SOFT,))


@pytest.mark.parametrize("field_name", ["session_id", "event_name", "driver", "team"])
def test_state_rejects_blank_identity(field_name: str) -> None:
    """Preserve auditable race and participant identity."""
    with pytest.raises(SimulationContractError, match=field_name):
        _state(**{field_name: "  "})


def test_strategy_requires_canonical_stop_order() -> None:
    """Make equivalent strategies serialize and compare identically."""
    with pytest.raises(SimulationContractError, match="sorted"):
        StrategyPlan(
            strategy_id="unordered",
            stops=(
                PlannedPitStop(40, DryCompound.SOFT),
                PlannedPitStop(30, DryCompound.HARD),
            ),
        )


def test_strategy_rejects_duplicate_stop_laps() -> None:
    """Forbid two incompatible tyre transitions after one lap."""
    with pytest.raises(SimulationContractError, match="unique"):
        StrategyPlan(
            strategy_id="duplicate",
            stops=(
                PlannedPitStop(30, DryCompound.HARD),
                PlannedPitStop(30, DryCompound.SOFT),
            ),
        )


@pytest.mark.parametrize("after_lap", [19, 57, 58])
def test_request_rejects_stop_outside_remaining_horizon(after_lap: int) -> None:
    """Apply pit cost only to legal remaining-race stops."""
    strategy = StrategyPlan(
        strategy_id="invalid-horizon",
        stops=(PlannedPitStop(after_lap, DryCompound.HARD),),
    )
    with pytest.raises(SimulationContractError, match="pit stop"):
        _request(strategy=strategy)


def test_request_enforces_two_dry_compounds() -> None:
    """Encode the controlled dry-race tyre-use rule."""
    with pytest.raises(SimulationContractError, match="at least two"):
        _request(strategy=StrategyPlan(strategy_id="no-stop"))


def test_request_accepts_no_future_stop_after_two_compounds_used() -> None:
    """Allow a completed mandatory compound change before the decision."""
    request = _request(
        state=_state(
            completed_pit_stops=1,
            compounds_used=(DryCompound.SOFT, DryCompound.MEDIUM),
        ),
        strategy=StrategyPlan(strategy_id="stay-out-to-finish"),
        mode=SimulationMode.OBSERVED_STRATEGY_REPLAY,
    )
    assert request.strategy.stops == ()


@pytest.mark.parametrize("seconds", [-0.1, float("inf"), float("nan")])
def test_pit_loss_rejects_invalid_seconds(seconds: float) -> None:
    """Never allow an invalid additive time cost."""
    with pytest.raises(SimulationContractError, match="finite and non-negative"):
        PitLossAssumption(
            seconds=seconds,
            source=PitLossSource.EXPLICIT_ASSUMPTION,
            evidence="test",
        )


def test_pit_loss_requires_evidence() -> None:
    """Keep the counterfactual pit-cost assumption visible."""
    with pytest.raises(SimulationContractError, match="evidence"):
        PitLossAssumption(
            seconds=20.0,
            source=PitLossSource.EXPLICIT_ASSUMPTION,
            evidence=" ",
        )


@pytest.mark.parametrize("random_seed", [-1, 2**32, True])
def test_request_rejects_invalid_seed(random_seed: int) -> None:
    """Keep stochastic extensions deterministic and reproducible."""
    with pytest.raises(SimulationContractError, match="random_seed"):
        _request(random_seed=random_seed)


def test_equal_inputs_produce_equal_contract_objects() -> None:
    """Make deterministic input identity testable before engine work begins."""
    first = _request()
    second = replace(first)
    assert first == second
    assert hash(first) == hash(second)
