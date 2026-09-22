"""Tests for circuit-aware Phase 7 pit-loss sensitivity."""

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
    advance_one_lap,
    initialize_simulation_progress,
)
from app.simulation.pit_loss import (
    CircuitPitLossProfile,
    PitLossError,
    PitLossRegistry,
    PitLossScenario,
    apply_pit_loss_scenario,
)


def _profile(**changes: object) -> CircuitPitLossProfile:
    values: dict[str, object] = {
        "event_name": "Bahrain Grand Prix",
        "low_seconds": 19.0,
        "nominal_seconds": 21.0,
        "high_seconds": 23.0,
        "source": PitLossSource.TRAINING_ONLY_CIRCUIT_ESTIMATE,
        "evidence": "training-only circuit replay estimate",
        "training_seasons": (2022, 2023, 2024),
    }
    values.update(changes)
    return CircuitPitLossProfile(**values)  # type: ignore[arg-type]


def _request(
    *,
    stops: tuple[PlannedPitStop, ...] = (
        PlannedPitStop(20, DryCompound.HARD),
    ),
    compounds_used: tuple[DryCompound, ...] = (DryCompound.MEDIUM,),
) -> SimulationRequest:
    return SimulationRequest(
        state=RaceState(
            season=2024,
            session_id="2024-01-R",
            event_name="Bahrain Grand Prix",
            driver="VER",
            team="Red Bull Racing",
            current_lap=20,
            total_laps=22,
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
            seconds=999.0,
            source=PitLossSource.EXPLICIT_ASSUMPTION,
            evidence="placeholder replaced by registry",
        ),
        mode=SimulationMode.COUNTERFACTUAL_STRATEGY,
    )


def test_training_profile_preserves_canonical_provenance() -> None:
    """Record circuit, range, source and development seasons explicitly."""
    profile = _profile()
    assert profile.event_name == "Bahrain Grand Prix"
    assert profile.training_seasons == (2022, 2023, 2024)
    assert profile.source is PitLossSource.TRAINING_ONLY_CIRCUIT_ESTIMATE


def test_explicit_profile_must_not_claim_training_seasons() -> None:
    """Keep expert assumptions separate from fitted circuit evidence."""
    profile = _profile(
        source=PitLossSource.EXPLICIT_ASSUMPTION,
        training_seasons=(),
    )
    assert profile.training_seasons == ()

    with pytest.raises(PitLossError, match="must not claim"):
        _profile(source=PitLossSource.EXPLICIT_ASSUMPTION)


def test_training_profile_requires_training_seasons() -> None:
    """Reject training-only labels without a training population."""
    with pytest.raises(PitLossError, match="requires training seasons"):
        _profile(training_seasons=())


@pytest.mark.parametrize(
    "training_seasons",
    [(2025,), (2021, 2022), (2023, 2022), (2022, 2022)],
)
def test_profile_rejects_invalid_training_scope(
    training_seasons: tuple[int, ...],
) -> None:
    """Protect 2025 and require canonical known development seasons."""
    with pytest.raises(PitLossError):
        _profile(training_seasons=training_seasons)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"low_seconds": 22.0}, "low <= nominal <= high"),
        ({"nominal_seconds": 24.0}, "low <= nominal <= high"),
        ({"high_seconds": 20.0}, "low <= nominal <= high"),
        ({"low_seconds": -1.0}, "finite and non-negative"),
        ({"nominal_seconds": float("nan")}, "finite and non-negative"),
        ({"high_seconds": float("inf")}, "finite and non-negative"),
    ],
)
def test_profile_rejects_invalid_sensitivity_range(
    changes: dict[str, object],
    message: str,
) -> None:
    """Require an ordered finite uncertainty interval."""
    with pytest.raises(PitLossError, match=message):
        _profile(**changes)


def test_registry_rejects_duplicate_event_identity() -> None:
    """Prevent ambiguous circuit resolution hidden by capitalization."""
    with pytest.raises(PitLossError, match="unique"):
        PitLossRegistry(
            profiles=(
                _profile(),
                _profile(event_name="bahrain grand prix"),
            )
        )


def test_registry_has_no_silent_global_fallback() -> None:
    """Fail when a circuit has no declared assumption."""
    registry = PitLossRegistry(profiles=(_profile(),))
    with pytest.raises(PitLossError, match="no circuit"):
        registry.resolve(
            event_name="Monaco Grand Prix",
            scenario=PitLossScenario.NOMINAL,
        )


@pytest.mark.parametrize(
    ("scenario", "expected_seconds"),
    [
        (PitLossScenario.LOW, 19.0),
        (PitLossScenario.NOMINAL, 21.0),
        (PitLossScenario.HIGH, 23.0),
        ("LOW", 19.0),
    ],
)
def test_registry_resolves_declared_sensitivity(
    scenario: PitLossScenario | str,
    expected_seconds: float,
) -> None:
    """Resolve each case without changing the profile."""
    registry = PitLossRegistry(profiles=(_profile(),))
    resolution = registry.resolve(
        event_name="bahrain grand prix",
        scenario=scenario,
    )
    assert resolution.assumption.seconds == expected_seconds
    assert resolution.event_name == "Bahrain Grand Prix"
    assert resolution.training_seasons == (2022, 2023, 2024)
    assert "range_seconds=19.000000/21.000000/23.000000" in (
        resolution.assumption.evidence
    )


def test_apply_scenario_returns_new_request_with_full_evidence() -> None:
    """Keep original input immutable and expose the chosen sensitivity."""
    request = _request()
    registry = PitLossRegistry(profiles=(_profile(),))

    resolved_request, resolution = apply_pit_loss_scenario(
        request,
        registry=registry,
        scenario=PitLossScenario.NOMINAL,
    )

    assert request.pit_loss.seconds == 999.0
    assert resolved_request.pit_loss.seconds == 21.0
    assert resolved_request.pit_loss.source is (
        PitLossSource.TRAINING_ONLY_CIRCUIT_ESTIMATE
    )
    assert resolution.scenario is PitLossScenario.NOMINAL
    assert "scenario=NOMINAL" in resolved_request.pit_loss.evidence


def test_pit_lap_time_changes_exactly_with_sensitivity() -> None:
    """Make uncertainty affect only the explicitly charged pit cost."""
    request = _request()
    registry = PitLossRegistry(profiles=(_profile(),))
    low_request, _ = apply_pit_loss_scenario(
        request,
        registry=registry,
        scenario=PitLossScenario.LOW,
    )
    high_request, _ = apply_pit_loss_scenario(
        request,
        registry=registry,
        scenario=PitLossScenario.HIGH,
    )

    _, low_transition = advance_one_lap(
        initialize_simulation_progress(low_request),
        low_request,
        predicted_lap_time_seconds=91.0,
    )
    _, high_transition = advance_one_lap(
        initialize_simulation_progress(high_request),
        high_request,
        predicted_lap_time_seconds=91.0,
    )

    assert low_transition.total_lap_time_seconds == 110.0
    assert high_transition.total_lap_time_seconds == 114.0
    assert (
        high_transition.total_lap_time_seconds
        - low_transition.total_lap_time_seconds
        == 4.0
    )


def test_no_stop_lap_is_unchanged_by_pit_loss_scenario() -> None:
    """Do not leak pit assumptions into ordinary racing laps."""
    request = _request(
        stops=(),
        compounds_used=(DryCompound.SOFT, DryCompound.MEDIUM),
    )
    registry = PitLossRegistry(profiles=(_profile(),))
    low_request, _ = apply_pit_loss_scenario(
        request,
        registry=registry,
        scenario=PitLossScenario.LOW,
    )
    high_request, _ = apply_pit_loss_scenario(
        request,
        registry=registry,
        scenario=PitLossScenario.HIGH,
    )

    _, low_transition = advance_one_lap(
        initialize_simulation_progress(low_request),
        low_request,
        predicted_lap_time_seconds=91.0,
    )
    _, high_transition = advance_one_lap(
        initialize_simulation_progress(high_request),
        high_request,
        predicted_lap_time_seconds=91.0,
    )

    assert low_transition.pit_loss_seconds == 0.0
    assert high_transition.pit_loss_seconds == 0.0
    assert low_transition.total_lap_time_seconds == 91.0
    assert high_transition.total_lap_time_seconds == 91.0


def test_resolution_uses_request_event_identity() -> None:
    """Prevent a profile from another circuit entering the request."""
    request = replace(
        _request(),
        state=replace(
            _request().state,
            event_name="Monaco Grand Prix",
        ),
    )
    registry = PitLossRegistry(profiles=(_profile(),))
    with pytest.raises(PitLossError, match="Monaco"):
        apply_pit_loss_scenario(
            request,
            registry=registry,
            scenario=PitLossScenario.NOMINAL,
        )
