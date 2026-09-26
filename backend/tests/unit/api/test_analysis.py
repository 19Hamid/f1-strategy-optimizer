"""End-to-end analysis service tests using a tiny controlled model."""

from __future__ import annotations

from threading import Event
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.api import main
from app.api.analysis import (
    AnalysisMode,
    AnalysisRequestError,
    run_strategy_analysis,
)
from app.api.evidence import ApiEvidenceError
from app.api.historical import AnalysisSelectionError
from app.api.jobs import JobCancelledError, _evaluate_cancellable_batch
from app.api.main import app
from app.api.schemas import build_deterministic_analysis_response
from app.concurrent_simulation import (
    ScenarioBatchRequest,
    UNCERTAINTY_CALIBRATION_METHOD_ID,
    UncertaintyCalibration,
    generate_scenario_batch,
)
from app.concurrent_simulation.executor import evaluate_scenario_batch_concurrently
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
from app.optimizer import PitDecisionRequest
from app.simulation import (
    DryCompound,
    Phase6ModelAdapter,
    PitLossAssumption,
    PitLossSource,
    RaceState,
    SimulationFeatureContext,
)
from app.simulation.model_adapter import SELECTED_SIMULATOR_CANDIDATE_ID


class _Model:
    def predict(self, features: pd.DataFrame) -> np.ndarray:
        return 90.0 + features["tyre_age_laps"].to_numpy(dtype="float64")


def _adapter() -> Phase6ModelAdapter:
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
        training_seasons=(2022, 2023, 2024),
        validation_session_ids=(),
    )
    return Phase6ModelAdapter(
        LoadedModelArtifact(
            model=_Model(),  # type: ignore[arg-type]
            provenance=provenance,  # type: ignore[arg-type]
        )
    )


def _context() -> SimulationFeatureContext:
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
    return SimulationFeatureContext(
        base_features=pd.DataFrame([values], columns=APPROVED_FEATURE_COLUMNS),
        recent_lap_times_seconds=(90.0, 91.0, 92.0, 93.0, 94.0),
    )


def _decision() -> PitDecisionRequest:
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
            evidence="controlled API analysis test assumption",
        ),
    )


def _calibration() -> UncertaintyCalibration:
    return UncertaintyCalibration(
        calibration_id="api-analysis-test",
        method_id=UNCERTAINTY_CALIBRATION_METHOD_ID,
        training_seasons=(2022, 2023, 2024),
        shared_pace_scale_seconds=0.1,
        pit_loss_scale_seconds=0.1,
        lap_time_residual_scale_seconds=0.1,
        replay_count=10,
        lap_count=100,
        pit_loss_profile_count=3,
        evidence="synthetic development calibration for unit tests",
    )


def test_deterministic_comparison_has_no_stability_claim() -> None:
    result = run_strategy_analysis(
        _decision(),
        context=_context(),
        adapter=_adapter(),
    )

    assert result.mode is AnalysisMode.DETERMINISTIC
    assert result.comparison.pit_now.simulation.laps_simulated == 3
    assert result.comparison.stay_out.simulation.laps_simulated == 3
    assert result.recommendation == result.comparison.recommendation
    assert result.scenarios is None
    assert result.recommendation_is_stable is False


def test_paired_mode_preserves_point_comparison_and_uses_interval_decision() -> None:
    decision, context, adapter = _decision(), _context(), _adapter()
    point = run_strategy_analysis(decision, context=context, adapter=adapter)
    result = run_strategy_analysis(
        decision,
        context=context,
        adapter=adapter,
        mode=AnalysisMode.PAIRED_SCENARIO,
        calibration=_calibration(),
        scenario_count=100,
        root_seed=456,
        max_workers=2,
    )

    assert result.comparison == point.comparison
    assert result.scenarios is not None
    assert result.scenarios.scenario_count == 100
    assert result.recommendation == result.scenarios.recommendation
    assert result.recommendation_is_stable == result.scenarios.recommendation_is_stable
    assert context.simulated_lap_times_seconds == ()


@pytest.mark.parametrize("scenario_count", [99, 100_001, True])
def test_paired_mode_rejects_invalid_work_before_model_execution(
    scenario_count: object,
) -> None:
    with pytest.raises(AnalysisRequestError, match="scenario_count"):
        run_strategy_analysis(
            _decision(),
            context=_context(),
            adapter=_adapter(),
            mode=AnalysisMode.PAIRED_SCENARIO,
            calibration=_calibration(),
            scenario_count=scenario_count,  # type: ignore[arg-type]
        )


def test_paired_mode_requires_calibration() -> None:
    with pytest.raises(AnalysisRequestError, match="calibration"):
        run_strategy_analysis(
            _decision(),
            context=_context(),
            adapter=_adapter(),
            mode=AnalysisMode.PAIRED_SCENARIO,
            scenario_count=100,
        )


def _request_body() -> dict[str, object]:
    return {
        "season": 2024,
        "session_id": "2024-01-R",
        "driver": "VER",
        "decision_lap": 20,
        "target_compound": "HARD",
    }


def test_deterministic_endpoint_returns_both_reconciled_trajectories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision, context, adapter = _decision(), _context(), _adapter()
    monkeypatch.setattr(
        main,
        "load_verified_historical_analysis",
        lambda key: SimpleNamespace(
            decision=decision,
            context=context,
            adapter=adapter,
        ),
    )

    response = TestClient(app).post(
        "/api/v1/analysis/deterministic",
        json=_request_body(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["pit_now"]["laps"]) == 3
    assert len(payload["stay_out"]["laps"]) == 3
    assert payload["pit_now"]["laps"][0]["pitted_after_lap"] is True
    assert payload["stay_out"]["laps"][1]["pitted_after_lap"] is True
    assert payload["pit_now_advantage_seconds"] == pytest.approx(
        payload["stay_out"]["expected_remaining_time_seconds"]
        - payload["pit_now"]["expected_remaining_time_seconds"]
    )
    assert payload["recommendation_basis"] == "POINT_ESTIMATE_ONLY"
    assert payload["recommendation_is_stable"] is False
    assert payload["uncertainty_evaluated"] is False
    assert payload["counterfactual_strategy_accuracy_is_proven"] is False


def test_protected_season_never_loads_historical_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main,
        "load_verified_historical_analysis",
        lambda key: pytest.fail("protected input reached evidence loader"),
    )
    body = {**_request_body(), "season": 2025, "session_id": "2025-01-R"}
    response = TestClient(app).post(
        "/api/v1/analysis/deterministic", json=body
    )
    assert response.status_code == 422


def test_unavailable_decision_and_evidence_have_stable_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(key: object) -> None:
        raise AnalysisSelectionError("/hidden/decision/path")

    monkeypatch.setattr(main, "load_verified_historical_analysis", unavailable)
    client = TestClient(app)
    missing = client.post("/api/v1/analysis/deterministic", json=_request_body())
    assert missing.status_code == 404
    assert missing.json()["code"] == "DECISION_NOT_AVAILABLE"
    assert "/hidden/" not in missing.text

    def invalid_evidence(key: object) -> None:
        raise ApiEvidenceError("/hidden/model/path")

    monkeypatch.setattr(
        main,
        "load_verified_historical_analysis",
        invalid_evidence,
    )
    failed = client.post("/api/v1/analysis/deterministic", json=_request_body())
    assert failed.status_code == 503
    assert failed.json()["code"] == "EVIDENCE_UNAVAILABLE"
    assert "/hidden/" not in failed.text


def test_point_response_rejects_scenario_result() -> None:
    paired = run_strategy_analysis(
        _decision(),
        context=_context(),
        adapter=_adapter(),
        mode=AnalysisMode.PAIRED_SCENARIO,
        calibration=_calibration(),
        scenario_count=100,
        max_workers=2,
    )
    with pytest.raises(ValueError, match="scenario evidence"):
        build_deterministic_analysis_response(paired)


def test_chunked_job_outcomes_equal_frozen_phase9_executor() -> None:
    decision, context, adapter, calibration = (
        _decision(),
        _context(),
        _adapter(),
        _calibration(),
    )
    batch = generate_scenario_batch(
        ScenarioBatchRequest(decision, scenario_count=100, root_seed=456)
    )
    expected = evaluate_scenario_batch_concurrently(
        batch,
        calibration=calibration,
        context=context,
        adapter=adapter,
        max_workers=2,
    ).evaluation
    completed: list[int] = []
    actual = _evaluate_cancellable_batch(
        batch,
        calibration=calibration,
        context=context,
        adapter=adapter,
        max_workers=2,
        cancel=Event(),
        progress=completed.append,
    )
    assert actual == expected
    assert completed[-1] == 100
    assert completed == sorted(completed)


def test_chunked_job_does_not_publish_partial_cancelled_evidence() -> None:
    event = Event()
    event.set()
    batch = generate_scenario_batch(
        ScenarioBatchRequest(_decision(), scenario_count=100)
    )
    with pytest.raises(JobCancelledError, match="cancelled"):
        _evaluate_cancellable_batch(
            batch,
            calibration=_calibration(),
            context=_context(),
            adapter=_adapter(),
            max_workers=2,
            cancel=event,
            progress=lambda completed: pytest.fail("partial result published"),
        )


def test_chunked_job_stops_after_requested_cancellation() -> None:
    event = Event()
    completed: list[int] = []
    batch = generate_scenario_batch(
        ScenarioBatchRequest(_decision(), scenario_count=100)
    )

    def request_cancel(count: int) -> None:
        completed.append(count)
        event.set()

    with pytest.raises(JobCancelledError, match="cancelled"):
        _evaluate_cancellable_batch(
            batch,
            calibration=_calibration(),
            context=_context(),
            adapter=_adapter(),
            max_workers=2,
            cancel=event,
            progress=request_cancel,
        )
    assert completed == [4]
