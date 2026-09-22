"""Tests for complete deterministic Phase 7 strategy rollouts."""

from __future__ import annotations

from dataclasses import dataclass, replace
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
from app.simulation import (
    DryCompound,
    Phase6ModelAdapter,
    PitLossAssumption,
    PitLossSource,
    PlannedPitStop,
    RaceState,
    SimulationFeatureContext,
    SimulationMode,
    SimulationRequest,
    StrategyPlan,
)
from app.simulation.model_adapter import SELECTED_SIMULATOR_CANDIDATE_ID
from app.simulation.rollout import (
    SimulationLap,
    StrategyRolloutError,
    StrategySimulationResult,
    simulate_strategy,
)


@dataclass
class _LapNumberModel:
    """Return a deterministic positive time derived from decision lap."""

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        assert tuple(features.columns) == APPROVED_FEATURE_COLUMNS
        laps = features["decision_lap"].to_numpy(dtype="float64")
        return 90.0 + (laps / 100.0)


def _artifact() -> LoadedModelArtifact:
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
        model=_LapNumberModel(),  # type: ignore[arg-type]
        provenance=provenance,  # type: ignore[arg-type]
    )


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


def _request(
    *,
    stops: tuple[PlannedPitStop, ...] = (
        PlannedPitStop(21, DryCompound.HARD),
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
        strategy=StrategyPlan(strategy_id="medium-to-hard", stops=stops),
        pit_loss=PitLossAssumption(
            seconds=20.0,
            source=PitLossSource.EXPLICIT_ASSUMPTION,
            evidence="rollout test assumption",
        ),
        mode=SimulationMode.COUNTERFACTUAL_STRATEGY,
    )


def _simulate(
    request: SimulationRequest | None = None,
) -> StrategySimulationResult:
    return simulate_strategy(
        request or _request(),
        context=_context(),
        adapter=Phase6ModelAdapter(_artifact()),
    )


def test_rollout_reaches_flag_and_predicts_every_remaining_lap() -> None:
    """Generate exactly one model-backed transition per remaining lap."""
    result = _simulate()

    assert result.strategy_id == "medium-to-hard"
    assert result.laps_simulated == 3
    assert tuple(lap.transition.lap_number for lap in result.laps) == (
        20,
        21,
        22,
    )
    assert tuple(
        lap.transition.predicted_lap_time_seconds for lap in result.laps
    ) == pytest.approx((90.20, 90.21, 90.22))
    assert result.final_progress.is_finished
    assert result.final_progress.next_lap == 23


def test_rollout_executes_declared_stop_once_and_resets_stint() -> None:
    """Charge and apply the planned stop only after its declared lap."""
    result = _simulate()
    stop_lap = result.laps[1].transition
    final_lap = result.laps[2].transition

    assert result.pit_stops_simulated == 1
    assert stop_lap.pitted
    assert stop_lap.pit_loss_seconds == 20.0
    assert stop_lap.next_compound is DryCompound.HARD
    assert stop_lap.next_tyre_age_laps == 0
    assert stop_lap.next_stint_laps_completed == 0
    assert not final_lap.pitted
    assert final_lap.start_compound is DryCompound.HARD
    assert result.final_progress.completed_pit_stops == 1


def test_rollout_keeps_racing_time_and_pit_loss_reconciled() -> None:
    """Expose a transparent remaining-time sum with no hidden pit cost."""
    result = _simulate()

    assert result.racing_time_seconds == pytest.approx(270.63)
    assert result.pit_loss_seconds == 20.0
    assert result.remaining_time_seconds == pytest.approx(290.63)
    assert result.final_progress.elapsed_time_seconds == pytest.approx(290.63)


def test_rollout_feeds_predictions_forward_without_cross_stint_residual() -> None:
    """Use predicted history, then force the safe direct path after a stop."""
    result = _simulate()
    second = dict(result.laps[1].model_features)
    third = dict(result.laps[2].model_features)

    assert second["previous_lap_time_seconds"] == pytest.approx(90.20)
    assert second["previous_lap_was_target_eligible"] is True
    assert third["current_compound"] == "HARD"
    assert third["tyre_age_laps"] == 0
    assert third["previous_lap_time_seconds"] is None
    assert third["previous_lap_was_target_eligible"] is False


def test_rollout_preserves_exact_feature_evidence_for_every_lap() -> None:
    """Keep an ordered immutable snapshot of every model inference row."""
    result = _simulate()
    assert all(
        tuple(name for name, _ in lap.model_features)
        == APPROVED_FEATURE_COLUMNS
        for lap in result.laps
    )
    assert dict(result.laps[0].model_features)["decision_lap"] == 20
    assert dict(result.laps[-1].model_features)["decision_lap"] == 22


def test_no_stop_rollout_never_adds_pit_loss() -> None:
    """Complete a legal already-two-compound strategy without a hidden stop."""
    request = _request(
        stops=(),
        compounds_used=(DryCompound.HARD, DryCompound.MEDIUM),
    )
    result = _simulate(request)

    assert result.pit_stops_simulated == 0
    assert result.pit_loss_seconds == 0.0
    assert result.remaining_time_seconds == pytest.approx(
        result.racing_time_seconds
    )
    assert result.final_progress.current_compound is DryCompound.MEDIUM


def test_rollout_is_deterministic_for_identical_inputs() -> None:
    """Return byte-comparable scalar evidence for the same request and seed."""
    assert _simulate() == _simulate()


def test_result_rejects_missing_lap_or_tampered_total() -> None:
    """Fail closed when stored trajectory evidence no longer reconciles."""
    result = _simulate()
    with pytest.raises(StrategyRolloutError, match="lap numbers"):
        replace(result, laps=result.laps[:-1])

    altered_transition = replace(
        result.laps[0].transition,
        total_lap_time_seconds=999.0,
    )
    altered_lap = SimulationLap(
        transition=altered_transition,
        model_features=result.laps[0].model_features,
    )
    with pytest.raises(StrategyRolloutError, match="do not reconcile"):
        replace(result, laps=(altered_lap, *result.laps[1:]))


def test_rollout_requires_verified_boundary_types() -> None:
    """Reject unverified predictor or feature-context substitutes."""
    with pytest.raises(TypeError, match="request"):
        simulate_strategy(  # type: ignore[arg-type]
            object(),
            context=_context(),
            adapter=Phase6ModelAdapter(_artifact()),
        )
    with pytest.raises(TypeError, match="adapter"):
        simulate_strategy(
            _request(),
            context=_context(),
            adapter=object(),  # type: ignore[arg-type]
        )
