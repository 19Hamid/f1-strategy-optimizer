"""Tests for controlled Phase 8 decision sensitivity."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.datasets.contracts import DEVELOPMENT_SEASONS
from app.ml import (
    APPROVED_FEATURE_COLUMNS,
    FINAL_DEVELOPMENT_FIT_ID,
    FULL_FEATURE_SET_ID,
    MODEL_CONTRACT_VERSION,
    LoadedModelArtifact,
    ModelFamily,
    ModelTarget,
    PredictionFormulation,
)
from app.optimizer import (
    OptimizerContractError,
    PitDecisionRequest,
    PitDecisionSensitivity,
    PitDecisionSensitivityCase,
    TyreAgeSensitivityScenario,
    analyze_pit_decision_sensitivity,
    compare_pit_decision,
)
from app.simulation import (
    CircuitPitLossProfile,
    DryCompound,
    Phase6ModelAdapter,
    PitLossAssumption,
    PitLossRegistry,
    PitLossScenario,
    PitLossSource,
    RaceState,
    SimulationFeatureContext,
)
from app.simulation.model_adapter import SELECTED_SIMULATOR_CANDIDATE_ID


class _TyreAgeModel:
    """Expose current-stint tyre-age sensitivity exactly."""

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        return 90.0 + features["tyre_age_laps"].to_numpy(dtype="float64")


class _WeatherAgeModel:
    """Expose the effect of stop timing on elapsed-time-derived features."""

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        weather_age = features["weather_age_seconds"].to_numpy(dtype="float64")
        return 90.0 + weather_age * 0.001


def _artifact(model: object) -> LoadedModelArtifact:
    provenance = SimpleNamespace(
        model_contract_version=MODEL_CONTRACT_VERSION,
        fold_id=FINAL_DEVELOPMENT_FIT_ID,
        target=ModelTarget.LAP_TIME,
        formulation=PredictionFormulation.RESIDUAL_HYBRID,
        family=ModelFamily.XGBOOST,
        candidate_id=SELECTED_SIMULATOR_CANDIDATE_ID,
        feature_set_id=FULL_FEATURE_SET_ID,
        execution_device="cuda",
        feature_columns=APPROVED_FEATURE_COLUMNS,
        training_seasons=DEVELOPMENT_SEASONS,
        validation_session_ids=(),
    )
    return LoadedModelArtifact(
        model=model,  # type: ignore[arg-type]
        provenance=provenance,  # type: ignore[arg-type]
    )


def _adapter(model: object) -> Phase6ModelAdapter:
    return Phase6ModelAdapter(_artifact(model))


def _base_features() -> pd.DataFrame:
    values: dict[str, object] = {
        "event_name": "Bahrain Grand Prix",
        "driver": "VER",
        "team": "Red Bull Racing",
        "decision_lap": 20,
        "current_compound": "MEDIUM",
        "tyre_age_laps": 19,
        "current_stint_laps_completed": 19,
        "completed_pit_stops": 0,
        "previous_position": 1,
        "previous_lap_was_target_eligible": True,
        "previous_lap_time_seconds": 94.0,
        "previous_sector1_time_seconds": 30.0,
        "previous_sector2_time_seconds": 31.0,
        "previous_sector3_time_seconds": 33.0,
        "eligible_laps_completed": 10,
        "rolling_lap_time_median_3": 93.0,
        "rolling_lap_time_median_5": 92.0,
        "rolling_lap_time_std_5": 1.414,
        "rolling_lap_time_trend_5": 1.0,
        "weather_age_seconds": 5.0,
        "air_temperature_celsius": 24.0,
        "humidity_percent": 40.0,
        "pressure_mbar": 1012.0,
        "track_temperature_celsius": 31.0,
        "wind_direction_degrees": 180.0,
        "wind_speed_mps": 2.5,
    }
    return pd.DataFrame([values], columns=APPROVED_FEATURE_COLUMNS)


def _context() -> SimulationFeatureContext:
    return SimulationFeatureContext(
        base_features=_base_features(),
        recent_lap_times_seconds=(90.0, 91.0, 92.0, 93.0, 94.0),
    )


def _request(**state_changes: object) -> PitDecisionRequest:
    state_values: dict[str, object] = {
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
    state_values.update(state_changes)
    return PitDecisionRequest(
        state=RaceState(**state_values),  # type: ignore[arg-type]
        target_compound=DryCompound.HARD,
        pit_loss=PitLossAssumption(
            seconds=999.0,
            source=PitLossSource.EXPLICIT_ASSUMPTION,
            evidence="placeholder replaced by sensitivity registry",
        ),
    )


def _registry() -> PitLossRegistry:
    return PitLossRegistry(
        profiles=(
            CircuitPitLossProfile(
                event_name="Bahrain Grand Prix",
                low_seconds=18.0,
                nominal_seconds=20.0,
                high_seconds=22.0,
                source=PitLossSource.TRAINING_ONLY_CIRCUIT_ESTIMATE,
                evidence="training-only circuit sensitivity estimate",
                training_seasons=(2022, 2023, 2024),
            ),
        )
    )


def _sensitivity(model: object = None) -> PitDecisionSensitivity:
    return analyze_pit_decision_sensitivity(
        _request(),
        context=_context(),
        adapter=_adapter(model or _TyreAgeModel()),
        pit_loss_registry=_registry(),
    )


def test_sensitivity_builds_canonical_three_by_three_grid() -> None:
    """Cover every controlled tyre-age and pit-loss case exactly once."""
    sensitivity = _sensitivity()

    assert len(sensitivity.cases) == 9
    assert tuple(
        (
            case.tyre_age_scenario,
            case.pit_loss_resolution.scenario,
        )
        for case in sensitivity.cases
    ) == tuple(
        (tyre_age, pit_loss)
        for tyre_age in TyreAgeSensitivityScenario
        for pit_loss in PitLossScenario
    )
    assert {
        case.pit_loss_resolution.assumption.seconds
        for case in sensitivity.cases
    } == {18.0, 20.0, 22.0}


def test_nominal_cell_matches_direct_comparison() -> None:
    """Keep the centre cell identical to the declared nominal decision."""
    request = _request()
    registry = _registry()
    resolution = registry.resolve(
        event_name=request.state.event_name,
        scenario=PitLossScenario.NOMINAL,
    )
    direct = compare_pit_decision(
        replace(request, pit_loss=resolution.assumption),
        context=_context(),
        adapter=_adapter(_TyreAgeModel()),
    )

    assert _sensitivity().nominal == direct


def test_tyre_age_axis_isolates_current_stint_exposure() -> None:
    """Vary only the paired tyre-age inputs and retain recent pace evidence."""
    sensitivity = _sensitivity()
    expected = {
        TyreAgeSensitivityScenario.YOUNGER: (17, 17.0),
        TyreAgeSensitivityScenario.NOMINAL: (19, 19.0),
        TyreAgeSensitivityScenario.OLDER: (21, 21.0),
    }

    for scenario, (age, advantage) in expected.items():
        case = sensitivity.case_for(
            tyre_age_scenario=scenario,
            pit_loss_scenario=PitLossScenario.NOMINAL,
        )
        assert case.comparison.request.state.tyre_age_laps == age
        assert (
            case.comparison.request.state.current_stint_laps_completed == age
        )
        first_features = dict(
            case.comparison.pit_now.simulation.laps[0].model_features
        )
        assert first_features["tyre_age_laps"] == age
        assert first_features["current_stint_laps_completed"] == age
        assert case.comparison.pit_now_advantage_seconds == pytest.approx(
            advantage
        )


def test_equal_stop_counts_can_cancel_direct_pit_loss() -> None:
    """Show that explicit pit cost cancels when the model ignores stop timing."""
    sensitivity = _sensitivity()

    for tyre_age in TyreAgeSensitivityScenario:
        advantages = {
            sensitivity.case_for(
                tyre_age_scenario=tyre_age,
                pit_loss_scenario=pit_loss,
            ).comparison.pit_now_advantage_seconds
            for pit_loss in PitLossScenario
        }
        assert len(advantages) == 1


def test_elapsed_time_features_can_make_pit_loss_timing_matter() -> None:
    """Retain indirect model effects instead of assuming pit cost cancels."""
    sensitivity = _sensitivity(_WeatherAgeModel())
    low = sensitivity.case_for(
        tyre_age_scenario=TyreAgeSensitivityScenario.NOMINAL,
        pit_loss_scenario=PitLossScenario.LOW,
    )
    high = sensitivity.case_for(
        tyre_age_scenario=TyreAgeSensitivityScenario.NOMINAL,
        pit_loss_scenario=PitLossScenario.HIGH,
    )

    assert high.comparison.pit_now_advantage_seconds < (
        low.comparison.pit_now_advantage_seconds
    )


def test_sensitivity_reports_raw_advantage_range() -> None:
    """Expose the numerical envelope without claiming calibrated stability."""
    assert _sensitivity().pit_now_advantage_range_seconds == pytest.approx(
        (17.0, 21.0)
    )


def test_sensitivity_is_deterministic_and_does_not_mutate_inputs() -> None:
    """Return equal evidence while preserving the base request and context."""
    request = _request()
    context = _context()
    before_features = context.base_features.copy(deep=True)
    arguments = {
        "context": context,
        "adapter": _adapter(_TyreAgeModel()),
        "pit_loss_registry": _registry(),
    }

    first = analyze_pit_decision_sensitivity(request, **arguments)
    second = analyze_pit_decision_sensitivity(request, **arguments)

    assert first == second
    assert request.pit_loss.seconds == 999.0
    assert request.state.tyre_age_laps == 19
    assert context.base_features.equals(before_features)
    assert context.simulated_lap_times_seconds == ()


def test_sensitivity_rejects_too_young_current_stint() -> None:
    """Fail instead of clamping an incomplete younger perturbation."""
    request = _request(tyre_age_laps=1, current_stint_laps_completed=1)
    features = _base_features()
    features.loc[0, "tyre_age_laps"] = 1
    features.loc[0, "current_stint_laps_completed"] = 1
    context = replace(_context(), base_features=features)

    with pytest.raises(OptimizerContractError, match="at least two"):
        analyze_pit_decision_sensitivity(
            request,
            context=context,
            adapter=_adapter(_TyreAgeModel()),
            pit_loss_registry=_registry(),
        )


def test_sensitivity_rejects_mismatched_or_advanced_feature_seed() -> None:
    """Require the untouched feature row for the declared base decision."""
    features = _base_features()
    features.loc[0, "driver"] = "LEC"
    mismatched = replace(_context(), base_features=features)
    advanced = replace(
        _context(),
        simulated_lap_times_seconds=(95.0,),
    )

    with pytest.raises(OptimizerContractError, match="differs"):
        analyze_pit_decision_sensitivity(
            _request(),
            context=mismatched,
            adapter=_adapter(_TyreAgeModel()),
            pit_loss_registry=_registry(),
        )
    with pytest.raises(OptimizerContractError, match="before any simulated"):
        analyze_pit_decision_sensitivity(
            _request(),
            context=advanced,
            adapter=_adapter(_TyreAgeModel()),
            pit_loss_registry=_registry(),
        )


def test_sensitivity_lookup_rejects_unknown_axes() -> None:
    """Do not silently substitute an unsupported sensitivity case."""
    sensitivity = _sensitivity()

    with pytest.raises(OptimizerContractError, match="tyre-age"):
        sensitivity.case_for(
            tyre_age_scenario="ANCIENT",
            pit_loss_scenario=PitLossScenario.NOMINAL,
        )
    with pytest.raises(OptimizerContractError, match="pit-loss"):
        sensitivity.case_for(
            tyre_age_scenario=TyreAgeSensitivityScenario.NOMINAL,
            pit_loss_scenario="EXTREME",
        )


def test_sensitivity_result_rejects_incomplete_or_reordered_grid() -> None:
    """Require the canonical nine cells before exposing an envelope."""
    sensitivity = _sensitivity()

    with pytest.raises(OptimizerContractError, match="canonical nine"):
        PitDecisionSensitivity(
            base_request=sensitivity.base_request,
            cases=sensitivity.cases[:-1],
        )
    with pytest.raises(OptimizerContractError, match="canonical nine"):
        PitDecisionSensitivity(
            base_request=sensitivity.base_request,
            cases=tuple(reversed(sensitivity.cases)),
        )


def test_sensitivity_case_rejects_changed_resolution() -> None:
    """Bind every comparison to the pit-loss evidence used to create it."""
    sensitivity = _sensitivity()
    nominal = sensitivity.case_for(
        tyre_age_scenario=TyreAgeSensitivityScenario.NOMINAL,
        pit_loss_scenario=PitLossScenario.NOMINAL,
    )
    high_resolution = _registry().resolve(
        event_name="Bahrain Grand Prix",
        scenario=PitLossScenario.HIGH,
    )

    with pytest.raises(OptimizerContractError, match="differs"):
        PitDecisionSensitivityCase(
            tyre_age_scenario=nominal.tyre_age_scenario,
            tyre_age_delta_laps=nominal.tyre_age_delta_laps,
            pit_loss_resolution=high_resolution,
            comparison=nominal.comparison,
        )


def test_sensitivity_rejects_unverified_boundary_types() -> None:
    """Keep public optimizer inputs explicit and typed."""
    valid = {
        "request": _request(),
        "context": _context(),
        "adapter": _adapter(_TyreAgeModel()),
        "pit_loss_registry": _registry(),
    }
    for name in tuple(valid):
        arguments = dict(valid)
        arguments[name] = object()
        with pytest.raises(TypeError, match=name):
            analyze_pit_decision_sensitivity(**arguments)  # type: ignore[arg-type]
