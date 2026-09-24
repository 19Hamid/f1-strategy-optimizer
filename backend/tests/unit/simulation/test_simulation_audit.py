"""Tests for the deterministic Phase 7 development simulation audit."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

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
from app.pipeline import SessionKey
from app.simulation import (
    CircuitPitLossProfile,
    Phase6ModelAdapter,
    PitLossRegistry,
    PitLossSource,
    ReplayHorizon,
    build_session_audit_candidates,
    replay_audit_candidates,
)
from app.simulation.cli import (
    DEFAULT_MODEL_ARTIFACT_ID,
    DEFAULT_RUN_ID,
    build_parser,
)
from app.simulation.model_adapter import SELECTED_SIMULATOR_CANDIDATE_ID


class _LapNumberModel:
    def predict(self, features: pd.DataFrame) -> np.ndarray:
        return 90.0 + (features["decision_lap"].to_numpy(dtype="float64") / 100.0)


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
        model=_LapNumberModel(),  # type: ignore[arg-type]
        provenance=provenance,  # type: ignore[arg-type]
    )
    return Phase6ModelAdapter(artifact)


def _feature_row(*, decision_lap: int) -> dict[str, object]:
    compound = "MEDIUM" if decision_lap <= 19 else "HARD"
    completed_stops = 0 if decision_lap <= 19 else 1
    stint_laps = decision_lap - 1 if completed_stops == 0 else decision_lap - 20
    values: dict[str, object] = {
        "event_name": "Bahrain Grand Prix",
        "driver": "VER",
        "team": "Red Bull Racing",
        "decision_lap": decision_lap,
        "current_compound": compound,
        "tyre_age_laps": stint_laps,
        "current_stint_laps_completed": stint_laps,
        "completed_pit_stops": completed_stops,
        "previous_position": 1,
        "previous_lap_was_target_eligible": True,
        "previous_lap_time_seconds": 91.0,
        "previous_sector1_time_seconds": 30.0,
        "previous_sector2_time_seconds": 30.0,
        "previous_sector3_time_seconds": 31.0,
        "eligible_laps_completed": decision_lap - 1,
        "rolling_lap_time_median_3": 91.0,
        "rolling_lap_time_median_5": 91.0,
        "rolling_lap_time_std_5": 0.0,
        "rolling_lap_time_trend_5": 0.0,
        "weather_age_seconds": 5.0,
        "air_temperature_celsius": 24.0,
        "humidity_percent": 40.0,
        "pressure_mbar": 1012.0,
        "track_temperature_celsius": 31.0,
        "wind_direction_degrees": 180.0,
        "wind_speed_mps": 2.5,
    }
    return values


def _decision_rows() -> pd.DataFrame:
    rows = []
    for decision_lap in (6, 21, 31):
        values = _feature_row(decision_lap=decision_lap)
        values.update(
            {
                "session_id": "2024-01-R",
                "season": 2024,
                "is_decision_eligible": True,
            }
        )
        rows.append(values)
    identity = ("session_id", "season", "is_decision_eligible")
    return pd.DataFrame(rows, columns=(*identity, *APPROVED_FEATURE_COLUMNS))


def _processed_laps() -> pd.DataFrame:
    lap_numbers = tuple(range(1, 36))
    return pd.DataFrame(
        {
            "Season": [2024] * len(lap_numbers),
            "SessionType": ["R"] * len(lap_numbers),
            "EventName": ["Bahrain Grand Prix"] * len(lap_numbers),
            "Driver": ["VER"] * len(lap_numbers),
            "Team": ["Red Bull Racing"] * len(lap_numbers),
            "LapNumber": lap_numbers,
            "LapTimeSeconds": [91.0] * len(lap_numbers),
            "Compound": ["MEDIUM"] * 19 + ["HARD"] * 16,
            "PitInTime": [None] * 18 + ["00:00:01"] + [None] * 16,
            "Rainfall": [False] * len(lap_numbers),
            "TrackStatus": ["1"] * len(lap_numbers),
            "IsEligible": [True] * len(lap_numbers),
        }
    )


def _registry() -> PitLossRegistry:
    return PitLossRegistry(
        (
            CircuitPitLossProfile(
                event_name="Bahrain Grand Prix",
                low_seconds=15.0,
                nominal_seconds=20.0,
                high_seconds=25.0,
                source=PitLossSource.EXPLICIT_ASSUMPTION,
                evidence="unit-test final-audit sensitivity assumption",
            ),
        )
    )


def _candidates():
    return build_session_audit_candidates(
        session_key=SessionKey(2024, 1, "R"),
        decision_rows=_decision_rows(),
        processed_laps=_processed_laps(),
        pit_loss_registry=_registry(),
    )


def test_selector_builds_one_exact_candidate_per_horizon() -> None:
    """Select canonical complete suffixes and reconstruct observed stops."""
    candidates = _candidates()

    assert tuple(candidate.observed.remaining_laps for candidate in candidates) == (
        5,
        15,
        30,
    )
    assert tuple(candidate.horizon for candidate in candidates) == tuple(ReplayHorizon)
    assert tuple(candidate.request.state.current_lap for candidate in candidates) == (
        31,
        21,
        6,
    )
    long_candidate = candidates[-1]
    assert tuple(stop.after_lap for stop in long_candidate.request.strategy.stops) == (
        19,
    )
    assert long_candidate.request.pit_loss.seconds == 20.0
    assert "sensitivity assumption" in long_candidate.request.pit_loss.evidence
    assert "range_seconds=15.000000/20.000000/25.000000" in (
        long_candidate.request.pit_loss.evidence
    )


def test_selector_excludes_non_green_suffixes_without_coercion() -> None:
    """Historical suffixes outside dry-green scope remain excluded."""
    laps = _processed_laps()
    laps.loc[laps["LapNumber"].eq(35), "TrackStatus"] = "4"

    candidates = build_session_audit_candidates(
        session_key=SessionKey(2024, 1, "R"),
        decision_rows=_decision_rows(),
        processed_laps=laps,
        pit_loss_registry=_registry(),
    )

    assert candidates == ()


def test_replay_population_is_exactly_deterministic() -> None:
    """The audit executes every selected trajectory twice with equal output."""
    evaluation = replay_audit_candidates(_candidates(), adapter=_adapter())

    assert evaluation.replay_count == 3
    assert evaluation.lap_count == 50
    assert tuple(slice_.horizon for slice_ in evaluation.horizon_slices) == tuple(
        ReplayHorizon
    )
    assert all(
        replay.simulation.laps_simulated == replay.observed.remaining_laps
        for replay in evaluation.replays
    )


def test_cli_defaults_target_the_final_phase_6_artifact() -> None:
    """The one-command audit uses the canonical final run identities."""
    arguments = build_parser().parse_args(["audit"])

    assert arguments.run_id == DEFAULT_RUN_ID
    assert arguments.model_artifact_id == DEFAULT_MODEL_ARTIFACT_ID
