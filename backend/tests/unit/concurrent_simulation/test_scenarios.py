"""Tests for the frozen paired Phase 9 scenario contract."""

from dataclasses import replace
from statistics import fmean, pstdev

import pytest

from app.concurrent_simulation import (
    CONCURRENT_SIMULATION_CONTRACT_VERSION,
    DEFAULT_SCENARIO_COUNT,
    MAXIMUM_SCENARIO_COUNT,
    SCENARIO_GENERATOR_ID,
    ConcurrentSimulationContractError,
    ScenarioBatchRequest,
    UncertaintyScenario,
    generate_scenario_batch,
    validate_concurrent_simulation_contract,
)
from app.optimizer import PitDecisionRequest
from app.simulation import (
    SIMULATION_RANDOM_SEED,
    DryCompound,
    PitLossAssumption,
    PitLossSource,
    RaceState,
)


def _decision_request(**state_changes: object) -> PitDecisionRequest:
    state_values: dict[str, object] = {
        "season": 2024,
        "session_id": "2024-01-R",
        "event_name": "Bahrain Grand Prix",
        "driver": "VER",
        "team": "Red Bull Racing",
        "current_lap": 55,
        "total_laps": 57,
        "current_compound": DryCompound.MEDIUM,
        "tyre_age_laps": 20,
        "current_stint_laps_completed": 20,
        "completed_pit_stops": 0,
        "compounds_used": (DryCompound.MEDIUM,),
        "previous_position": 1,
    }
    state_values.update(state_changes)
    return PitDecisionRequest(
        state=RaceState(**state_values),  # type: ignore[arg-type]
        target_compound=DryCompound.HARD,
        pit_loss=PitLossAssumption(
            seconds=20.0,
            source=PitLossSource.EXPLICIT_ASSUMPTION,
            evidence="Phase 9 scenario unit-test assumption",
        ),
    )


def _batch_request(**changes: object) -> ScenarioBatchRequest:
    values: dict[str, object] = {
        "decision_request": _decision_request(),
        "scenario_count": 4,
        "root_seed": SIMULATION_RANDOM_SEED,
    }
    values.update(changes)
    return ScenarioBatchRequest(**values)  # type: ignore[arg-type]


def test_contract_freezes_generator_and_benchmark_identity() -> None:
    """Keep later sequential and concurrent runners on one scenario stream."""
    validate_concurrent_simulation_contract()

    assert CONCURRENT_SIMULATION_CONTRACT_VERSION == "1.0"
    assert SCENARIO_GENERATOR_ID == "sha256-box-muller-standard-normal-v1"
    assert DEFAULT_SCENARIO_COUNT == 10_000
    assert MAXIMUM_SCENARIO_COUNT == 100_000


def test_batch_generation_is_exactly_reproducible() -> None:
    """Generate byte-equivalent value evidence for identical requests."""
    request = _batch_request()

    first = generate_scenario_batch(request)
    second = generate_scenario_batch(request)

    assert first == second
    assert first.request is request
    assert first.generator_id == SCENARIO_GENERATOR_ID


def test_scenario_snapshot_is_frozen() -> None:
    """Detect accidental seed derivation or draw-order changes."""
    scenario = generate_scenario_batch(_batch_request(scenario_count=1)).scenarios[0]

    assert scenario.scenario_seed == 17650700849020152642
    assert scenario.shared_pace_z == pytest.approx(1.4640745439824292)
    assert scenario.pit_loss_z == pytest.approx(-0.6496826140069858)
    assert scenario.lap_numbers == (55, 56, 57)
    assert tuple(
        z_score for _, z_score in scenario.lap_time_residual_z
    ) == pytest.approx(
        (-0.9991272103652423, -0.18625792375973482, -0.5906968943808837)
    )


def test_scenario_prefix_is_independent_of_requested_batch_size() -> None:
    """Keep scenario identities stable across benchmark scaling runs."""
    short = generate_scenario_batch(_batch_request(scenario_count=2))
    longer = generate_scenario_batch(_batch_request(scenario_count=5))

    assert longer.scenarios[:2] == short.scenarios


def test_different_root_seed_changes_the_complete_stream() -> None:
    """Expose intentional reproducible experiment variation."""
    first = generate_scenario_batch(_batch_request(root_seed=42))
    second = generate_scenario_batch(_batch_request(root_seed=43))

    assert first.scenarios != second.scenarios
    assert {
        scenario.scenario_seed for scenario in first.scenarios
    }.isdisjoint(scenario.scenario_seed for scenario in second.scenarios)


def test_scenario_uses_complete_absolute_lap_horizon() -> None:
    """Bind common random numbers to race laps, not action-local offsets."""
    batch = generate_scenario_batch(_batch_request())

    assert batch.request.lap_numbers == (55, 56, 57)
    assert all(scenario.lap_numbers == (55, 56, 57) for scenario in batch.scenarios)
    assert batch.scenario_for(2) is batch.scenarios[2]
    assert batch.scenario_for(2).lap_time_z_for(56) == (
        batch.scenarios[2].lap_time_residual_z[1][1]
    )


def test_generated_standardized_draws_have_expected_shape() -> None:
    """Catch a badly biased generator before calibration is introduced."""
    batch = generate_scenario_batch(_batch_request(scenario_count=10_000))
    draws = [scenario.shared_pace_z for scenario in batch.scenarios]

    assert abs(fmean(draws)) < 0.03
    assert pstdev(draws) == pytest.approx(1.0, abs=0.03)


@pytest.mark.parametrize("scenario_count", [0, -1, 100_001, True])
def test_batch_request_rejects_invalid_scenario_count(
    scenario_count: object,
) -> None:
    with pytest.raises(ConcurrentSimulationContractError, match="scenario_count"):
        _batch_request(scenario_count=scenario_count)


@pytest.mark.parametrize("root_seed", [-1, 2**32, True])
def test_batch_request_rejects_invalid_root_seed(root_seed: object) -> None:
    with pytest.raises(ConcurrentSimulationContractError, match="root_seed"):
        _batch_request(root_seed=root_seed)


def test_batch_request_requires_phase_8_decision() -> None:
    with pytest.raises(TypeError, match="decision_request"):
        _batch_request(decision_request=object())


@pytest.mark.parametrize(
    "changes",
    [
        {"shared_pace_z": float("nan")},
        {"pit_loss_z": float("inf")},
        {"lap_time_residual_z": ((55, 0.0), (57, 0.0))},
        {"lap_time_residual_z": ((55, 0.0), (55, 1.0))},
    ],
)
def test_scenario_rejects_invalid_draw_evidence(
    changes: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "scenario_index": 0,
        "scenario_seed": 1,
        "shared_pace_z": 0.0,
        "pit_loss_z": 0.0,
        "lap_time_residual_z": ((55, 0.0), (56, 0.0), (57, 0.0)),
    }
    values.update(changes)

    with pytest.raises(ConcurrentSimulationContractError):
        UncertaintyScenario(**values)  # type: ignore[arg-type]


def test_scenario_rejects_lap_outside_its_horizon() -> None:
    scenario = generate_scenario_batch(_batch_request(scenario_count=1)).scenarios[0]

    with pytest.raises(ConcurrentSimulationContractError, match="no residual"):
        scenario.lap_time_z_for(54)


def test_batch_rejects_tampered_order_horizon_and_generator() -> None:
    batch = generate_scenario_batch(_batch_request(scenario_count=2))

    with pytest.raises(ConcurrentSimulationContractError, match="indices"):
        replace(batch, scenarios=tuple(reversed(batch.scenarios)))
    with pytest.raises(ConcurrentSimulationContractError, match="generator"):
        replace(batch, generator_id="unknown")
    wrong_horizon = replace(
        batch.scenarios[0],
        lap_time_residual_z=((54, 0.0), (55, 0.0), (56, 0.0)),
    )
    with pytest.raises(ConcurrentSimulationContractError, match="coordinates"):
        replace(batch, scenarios=(wrong_horizon, batch.scenarios[1]))


def test_batch_rejects_duplicate_scenario_seeds() -> None:
    batch = generate_scenario_batch(_batch_request(scenario_count=2))
    duplicate = replace(
        batch.scenarios[1],
        scenario_seed=batch.scenarios[0].scenario_seed,
    )

    with pytest.raises(ConcurrentSimulationContractError, match="seeds"):
        replace(batch, scenarios=(batch.scenarios[0], duplicate))


def test_generation_preserves_the_phase_8_request() -> None:
    """Do not let stochastic preparation mutate the deterministic baseline."""
    decision = _decision_request()
    request = ScenarioBatchRequest(decision, scenario_count=3)
    before = repr(decision)

    generate_scenario_batch(request)

    assert repr(decision) == before
    assert request.decision_request is decision


def test_protected_2025_remains_rejected_by_the_inherited_boundary() -> None:
    with pytest.raises(ValueError, match="protected 2025"):
        _decision_request(season=2025)
