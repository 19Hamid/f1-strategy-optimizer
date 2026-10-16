"""Tests for the complete Phase 8 development optimizer audit."""

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
    DecisionUncertaintyAssumption,
    OptimizerAuditCandidate,
    OptimizerAuditError,
    PitDecisionAction,
    build_session_optimizer_audit_candidates,
    evaluate_optimizer_audit_candidates,
)
from app.optimizer.cli import (
    DEFAULT_MODEL_ARTIFACT_ID,
    DEFAULT_RUN_ID,
    DEFAULT_SIMULATION_RUN_ID,
    build_parser,
)
from app.pipeline import SessionKey
from app.simulation import (
    CircuitPitLossProfile,
    DryCompound,
    Phase6ModelAdapter,
    PitLossRegistry,
    PitLossSource,
)
from app.simulation.model_adapter import SELECTED_SIMULATOR_CANDIDATE_ID


class _AuditModel:
    """Return deterministic, state-sensitive future lap times."""

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        age = features["tyre_age_laps"].to_numpy(dtype="float64")
        hard = features["current_compound"].eq("HARD").to_numpy(dtype="float64")
        return 90.0 + (age * 0.2) + hard


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
        training_seasons=DEVELOPMENT_SEASONS,
        validation_session_ids=(),
    )
    artifact = LoadedModelArtifact(
        model=_AuditModel(),  # type: ignore[arg-type]
        provenance=provenance,  # type: ignore[arg-type]
    )
    return Phase6ModelAdapter(artifact)


def _registry() -> PitLossRegistry:
    return PitLossRegistry(
        profiles=(
            CircuitPitLossProfile(
                event_name="Test Grand Prix",
                low_seconds=15.0,
                nominal_seconds=20.0,
                high_seconds=25.0,
                source=PitLossSource.EXPLICIT_ASSUMPTION,
                evidence="controlled audit test assumption",
            ),
        )
    )


def _feature_row(decision_lap: int) -> dict[str, object]:
    tyre_age = decision_lap - 1
    return {
        "event_name": "Test Grand Prix",
        "driver": "AAA",
        "team": "Test Team",
        "decision_lap": decision_lap,
        "current_compound": "MEDIUM",
        "tyre_age_laps": tyre_age,
        "current_stint_laps_completed": tyre_age,
        "completed_pit_stops": 0,
        "previous_position": 4,
        "previous_lap_was_target_eligible": True,
        "previous_lap_time_seconds": 91.0,
        "previous_sector1_time_seconds": 30.0,
        "previous_sector2_time_seconds": 30.0,
        "previous_sector3_time_seconds": 31.0,
        "eligible_laps_completed": decision_lap - 1,
        "rolling_lap_time_median_3": 91.0,
        "rolling_lap_time_median_5": 91.0,
        "rolling_lap_time_std_5": 0.2,
        "rolling_lap_time_trend_5": 0.05,
        "weather_age_seconds": 5.0,
        "air_temperature_celsius": 24.0,
        "humidity_percent": 45.0,
        "pressure_mbar": 1012.0,
        "track_temperature_celsius": 31.0,
        "wind_direction_degrees": 180.0,
        "wind_speed_mps": 2.5,
    }


def _decision_rows(*, eligible: bool = True) -> pd.DataFrame:
    records = []
    for decision_lap in (7, 8):
        record = _feature_row(decision_lap)
        record.update(
            {
                "session_id": "2024-01-R",
                "season": 2024,
                "is_decision_eligible": eligible,
            }
        )
        records.append(record)
    columns = (
        "session_id",
        "season",
        "is_decision_eligible",
        *APPROVED_FEATURE_COLUMNS,
    )
    return pd.DataFrame.from_records(records, columns=columns)


def _processed_laps(*, raining: bool = False) -> pd.DataFrame:
    lap_numbers = tuple(range(1, 13))
    return pd.DataFrame(
        {
            "Season": [2024] * len(lap_numbers),
            "SessionType": ["R"] * len(lap_numbers),
            "EventName": ["Test Grand Prix"] * len(lap_numbers),
            "Driver": ["AAA"] * len(lap_numbers),
            "Team": ["Test Team"] * len(lap_numbers),
            "LapNumber": lap_numbers,
            "LapTimeSeconds": [90.0 + lap / 10 for lap in lap_numbers],
            "Compound": ["MEDIUM"] * 8 + ["HARD"] * 4,
            "PitInTime": [None] * 7 + ["00:00:01"] + [None] * 4,
            "Rainfall": [False] * 7 + [raining] + [False] * 4,
            "TrackStatus": ["1"] * len(lap_numbers),
            "IsEligible": [True] * len(lap_numbers),
        }
    )


def _candidates() -> tuple[OptimizerAuditCandidate, ...]:
    return build_session_optimizer_audit_candidates(
        session_key=SessionKey(2024, 1, "R"),
        decision_rows=_decision_rows(),
        processed_laps=_processed_laps(),
        pit_loss_registry=_registry(),
    )


def test_selector_builds_one_exact_historical_action_pair() -> None:
    """Bind consecutive decisions to the same observed stop and compound."""
    candidates = _candidates()

    assert len(candidates) == 2
    stay_out, pit_now = candidates
    assert stay_out.observed_action is PitDecisionAction.STAY_OUT
    assert pit_now.observed_action is PitDecisionAction.PIT_NOW
    assert stay_out.request.state.current_lap == 7
    assert pit_now.request.state.current_lap == 8
    assert stay_out.observed_pit_lap == pit_now.observed_pit_lap == 8
    assert {candidate.request.target_compound for candidate in candidates} == {
        DryCompound.HARD
    }
    assert tuple(stay_out.context.base_features.columns) == (
        APPROVED_FEATURE_COLUMNS
    )
    assert stay_out.context.recent_lap_times_seconds == (
        90.2,
        90.3,
        90.4,
        90.5,
        90.6,
    )


@pytest.mark.parametrize(
    ("decision_rows", "processed_laps"),
    (
        (_decision_rows(eligible=False), _processed_laps()),
        (_decision_rows(), _processed_laps(raining=True)),
    ),
)
def test_selector_excludes_incomplete_or_wet_action_pairs(
    decision_rows: pd.DataFrame,
    processed_laps: pd.DataFrame,
) -> None:
    """Do not turn ineligible or wet historical windows into evidence."""
    assert (
        build_session_optimizer_audit_candidates(
            session_key=SessionKey(2024, 1, "R"),
            decision_rows=decision_rows,
            processed_laps=processed_laps,
            pit_loss_registry=_registry(),
        )
        == ()
    )


def test_candidate_rejects_action_that_does_not_match_observed_stop() -> None:
    """Keep observed labels mechanically bound to their decision lap."""
    candidate = _candidates()[0]

    with pytest.raises(OptimizerAuditError, match="does not match"):
        replace(candidate, observed_pit_lap=9)


def test_population_evaluation_is_deterministic_and_reconciled() -> None:
    """Evaluate both labels through the same sensitivity and stability path."""
    candidates = _candidates()
    uncertainty = DecisionUncertaintyAssumption(
        action_time_margin_seconds=1.0,
        evidence="synthetic development-only replay margin",
    )

    first = evaluate_optimizer_audit_candidates(
        candidates,
        adapter=_adapter(),
        pit_loss_registry=_registry(),
        uncertainty=uncertainty,
    )
    second = evaluate_optimizer_audit_candidates(
        candidates,
        adapter=_adapter(),
        pit_loss_registry=_registry(),
        uncertainty=uncertainty,
    )

    assert first == second
    assert len(first.decisions) == 2
    assert first.overall.decisions == 2
    assert first.overall.observed_pit_now == 1
    assert first.overall.observed_stay_out == 1
    assert (
        first.overall.stable_pit_now
        + first.overall.stable_stay_out
        + first.overall.no_clear_advantage
        == 2
    )
    assert all(len(item.stability.sensitivity.cases) == 9 for item in first.decisions)


def test_population_evaluator_rejects_empty_or_wrong_inputs() -> None:
    uncertainty = DecisionUncertaintyAssumption(1.0, "test margin")

    with pytest.raises(OptimizerAuditError, match="non-empty tuple"):
        evaluate_optimizer_audit_candidates(
            (),
            adapter=_adapter(),
            pit_loss_registry=_registry(),
            uncertainty=uncertainty,
        )
    with pytest.raises(TypeError, match="every audit candidate"):
        evaluate_optimizer_audit_candidates(
            (object(),),  # type: ignore[arg-type]
            adapter=_adapter(),
            pit_loss_registry=_registry(),
            uncertainty=uncertainty,
        )


def test_audit_cli_defaults_are_bound_to_final_phase_evidence() -> None:
    arguments = build_parser().parse_args(["audit"])

    assert arguments.run_id == DEFAULT_RUN_ID == "phase-8-final-audit"
    assert (
        arguments.model_artifact_id
        == DEFAULT_MODEL_ARTIFACT_ID
        == "phase-6-final-audit-lap-time"
    )
    assert (
        arguments.simulation_run_id
        == DEFAULT_SIMULATION_RUN_ID
        == "phase-7-final-audit"
    )
