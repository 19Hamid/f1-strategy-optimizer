"""Tests for deterministic Phase 8 pit-decision comparison."""

from __future__ import annotations

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
    ActionEvaluation,
    OptimizerContractError,
    PitDecisionAction,
    PitDecisionComparison,
    PitDecisionRecommendation,
    PitDecisionRequest,
    compare_pit_decision,
)
from app.simulation import (
    DryCompound,
    Phase6ModelAdapter,
    PitLossAssumption,
    PitLossSource,
    RaceState,
    SimulationFeatureContext,
)
from app.simulation.model_adapter import SELECTED_SIMULATOR_CANDIDATE_ID


class _TyreAgeModel:
    """Penalize tyre age so the immediate stop is faster."""

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        return 90.0 + features["tyre_age_laps"].to_numpy(dtype="float64")


class _HardPenaltyModel:
    """Penalize the target compound so one extra medium lap is faster."""

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        hard = features["current_compound"].eq("HARD").to_numpy(dtype="float64")
        return 90.0 + 10.0 * hard


class _ConstantModel:
    """Return equal racing time regardless of controlled state."""

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        return np.full(len(features), 90.0, dtype="float64")


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


def _request() -> PitDecisionRequest:
    return PitDecisionRequest(
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
            compounds_used=(DryCompound.MEDIUM,),
            previous_position=1,
        ),
        target_compound=DryCompound.HARD,
        pit_loss=PitLossAssumption(
            seconds=20.0,
            source=PitLossSource.EXPLICIT_ASSUMPTION,
            evidence="comparison unit-test assumption",
        ),
    )


def _compare(model: object) -> PitDecisionComparison:
    return compare_pit_decision(
        _request(),
        context=_context(),
        adapter=_adapter(model),
    )


def test_comparison_recommends_pit_now_when_it_is_faster() -> None:
    """Choose the lower complete remaining-time point estimate."""
    comparison = _compare(_TyreAgeModel())

    assert comparison.pit_now.expected_remaining_time_seconds == pytest.approx(310.0)
    assert comparison.stay_out.expected_remaining_time_seconds == pytest.approx(329.0)
    assert comparison.pit_now_advantage_seconds == pytest.approx(19.0)
    assert comparison.recommendation is PitDecisionRecommendation.PIT_NOW
    assert comparison.regret_seconds(PitDecisionAction.PIT_NOW) == 0.0
    assert comparison.regret_seconds(PitDecisionAction.STAY_OUT) == pytest.approx(19.0)


def test_comparison_recommends_stay_out_when_it_is_faster() -> None:
    """Allow the deferred action to win under identical assumptions."""
    comparison = _compare(_HardPenaltyModel())

    assert comparison.pit_now.expected_remaining_time_seconds == pytest.approx(310.0)
    assert comparison.stay_out.expected_remaining_time_seconds == pytest.approx(300.0)
    assert comparison.pit_now_advantage_seconds == pytest.approx(-10.0)
    assert comparison.recommendation is PitDecisionRecommendation.STAY_OUT
    assert comparison.regret_seconds(PitDecisionAction.PIT_NOW) == pytest.approx(10.0)
    assert comparison.regret_seconds(PitDecisionAction.STAY_OUT) == 0.0


def test_comparison_reports_no_clear_point_estimate_advantage() -> None:
    """Do not break an exact tie with an undocumented action preference."""
    comparison = _compare(_ConstantModel())

    assert comparison.pit_now.expected_remaining_time_seconds == pytest.approx(290.0)
    assert comparison.stay_out.expected_remaining_time_seconds == pytest.approx(290.0)
    assert comparison.pit_now_advantage_seconds == pytest.approx(0.0)
    assert comparison.recommendation is (
        PitDecisionRecommendation.NO_CLEAR_ADVANTAGE
    )
    assert comparison.regret_seconds(PitDecisionAction.PIT_NOW) == 0.0
    assert comparison.regret_seconds(PitDecisionAction.STAY_OUT) == 0.0


def test_comparison_changes_only_the_declared_action() -> None:
    """Keep model, state, pit cost, seed and horizon symmetric."""
    comparison = _compare(_TyreAgeModel())
    pit_request = comparison.pit_now.simulation.request
    stay_request = comparison.stay_out.simulation.request

    assert pit_request.state is stay_request.state
    assert pit_request.pit_loss is stay_request.pit_loss
    assert pit_request.random_seed == stay_request.random_seed
    assert comparison.pit_now.simulation.laps_simulated == 3
    assert comparison.stay_out.simulation.laps_simulated == 3
    assert pit_request.strategy.stops[0].after_lap == 20
    assert stay_request.strategy.stops[0].after_lap == 21


def test_comparison_is_exactly_deterministic() -> None:
    """Return equal immutable evidence for identical point-estimate inputs."""
    assert _compare(_TyreAgeModel()) == _compare(_TyreAgeModel())


def test_comparison_does_not_mutate_the_shared_feature_seed() -> None:
    """Start both action rollouts from the same untouched context."""
    context = _context()

    compare_pit_decision(
        _request(),
        context=context,
        adapter=_adapter(_TyreAgeModel()),
    )

    assert context.simulated_lap_times_seconds == ()
    assert context.base_features.equals(_base_features())


def test_result_rejects_missing_or_reordered_action_evidence() -> None:
    """Require both canonical actions exactly once and in stable order."""
    comparison = _compare(_TyreAgeModel())

    with pytest.raises(OptimizerContractError, match="PIT_NOW then STAY_OUT"):
        PitDecisionComparison(
            request=comparison.request,
            evaluations=(comparison.stay_out, comparison.pit_now),
        )
    with pytest.raises(OptimizerContractError, match="PIT_NOW then STAY_OUT"):
        PitDecisionComparison(
            request=comparison.request,
            evaluations=(comparison.pit_now,),
        )


def test_result_rejects_simulation_from_another_request() -> None:
    """Do not compare a trajectory built with changed shared assumptions."""
    comparison = _compare(_TyreAgeModel())
    wrong_action = ActionEvaluation(
        action=PitDecisionAction.STAY_OUT,
        simulation=comparison.pit_now.simulation,
    )

    with pytest.raises(OptimizerContractError, match="changed shared assumptions"):
        PitDecisionComparison(
            request=comparison.request,
            evaluations=(comparison.pit_now, wrong_action),
        )


def test_comparison_rejects_unverified_boundary_types() -> None:
    """Require the frozen request, feature context and model adapter."""
    with pytest.raises(TypeError, match="request"):
        compare_pit_decision(  # type: ignore[arg-type]
            object(),
            context=_context(),
            adapter=_adapter(_TyreAgeModel()),
        )
    with pytest.raises(TypeError, match="context"):
        compare_pit_decision(
            _request(),
            context=object(),  # type: ignore[arg-type]
            adapter=_adapter(_TyreAgeModel()),
        )
    with pytest.raises(TypeError, match="adapter"):
        compare_pit_decision(
            _request(),
            context=_context(),
            adapter=object(),  # type: ignore[arg-type]
        )


def test_regret_rejects_unknown_action() -> None:
    """Do not silently coerce an action outside the frozen binary choice."""
    with pytest.raises(OptimizerContractError, match="regret action"):
        _compare(_TyreAgeModel()).regret_seconds("BOX_BOX")  # type: ignore[arg-type]
