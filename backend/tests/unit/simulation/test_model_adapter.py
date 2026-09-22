"""Tests for the verified Phase 6 model simulation adapter."""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

import app.simulation.model_adapter as adapter_module
from app.datasets.contracts import DEVELOPMENT_SEASONS
from app.ml import (
    APPROVED_FEATURE_COLUMNS,
    FINAL_DEVELOPMENT_FIT_ID,
    FULL_FEATURE_SET_ID,
    MODEL_CONTRACT_VERSION,
    LoadedModelArtifact,
    ModelArtifactPaths,
    ModelFamily,
    ModelTarget,
    PredictionFormulation,
)
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
from app.simulation.model_adapter import (
    SELECTED_SIMULATOR_CANDIDATE_ID,
    ModelAdapterError,
    Phase6ModelAdapter,
    SimulationFeatureContext,
    build_simulation_features,
)


@dataclass
class _FakeModel:
    predictions: tuple[float, ...]

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        assert tuple(features.columns) == APPROVED_FEATURE_COLUMNS
        return np.asarray(self.predictions, dtype="float64")


def _provenance(**changes: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "model_contract_version": MODEL_CONTRACT_VERSION,
        "fold_id": FINAL_DEVELOPMENT_FIT_ID,
        "target": ModelTarget.LAP_TIME,
        "formulation": PredictionFormulation.RESIDUAL_HYBRID,
        "family": ModelFamily.XGBOOST,
        "candidate_id": SELECTED_SIMULATOR_CANDIDATE_ID,
        "feature_set_id": FULL_FEATURE_SET_ID,
        "feature_columns": APPROVED_FEATURE_COLUMNS,
        "training_seasons": DEVELOPMENT_SEASONS,
        "validation_session_ids": (),
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _artifact(
    predictions: tuple[float, ...] = (91.25,),
    **provenance_changes: object,
) -> LoadedModelArtifact:
    return LoadedModelArtifact(
        model=_FakeModel(predictions),  # type: ignore[arg-type]
        provenance=_provenance(**provenance_changes),  # type: ignore[arg-type]
    )


def _base_features() -> pd.DataFrame:
    values: dict[str, Any] = {
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


def _request(
    *,
    stops: tuple[PlannedPitStop, ...] = (
        PlannedPitStop(21, DryCompound.HARD),
    ),
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
            compounds_used=(DryCompound.MEDIUM,),
            previous_position=1,
        ),
        strategy=StrategyPlan(
            strategy_id="medium-to-hard",
            stops=stops,
        ),
        pit_loss=PitLossAssumption(
            seconds=20.0,
            source=PitLossSource.EXPLICIT_ASSUMPTION,
            evidence="adapter test assumption",
        ),
        mode=SimulationMode.COUNTERFACTUAL_STRATEGY,
    )


def _context() -> SimulationFeatureContext:
    return SimulationFeatureContext(
        base_features=_base_features(),
        recent_lap_times_seconds=(90.0, 91.0, 92.0, 93.0, 94.0),
    )


def test_adapter_requires_exact_selected_phase_6_artifact() -> None:
    """Accept only the final full-feature XGBoost residual hybrid."""
    adapter = Phase6ModelAdapter(_artifact())
    assert adapter.artifact.provenance.candidate_id == "xgboost_02"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_contract_version", "0"),
        ("fold_id", "development_fold_2"),
        ("target", ModelTarget.LAP_TIME_DELTA),
        ("formulation", PredictionFormulation.DIRECT_ABSOLUTE),
        ("family", ModelFamily.RANDOM_FOREST),
        ("candidate_id", "xgboost_01"),
        ("feature_set_id", "without_driver_team"),
        ("feature_columns", APPROVED_FEATURE_COLUMNS[:-1]),
        ("training_seasons", (2022, 2023)),
    ],
)
def test_adapter_rejects_wrong_artifact_identity(
    field: str,
    value: object,
) -> None:
    """Prevent a different model from silently entering the simulator."""
    with pytest.raises(ModelAdapterError, match="differs"):
        Phase6ModelAdapter(_artifact(**{field: value}))


def test_adapter_rejects_validation_bound_final_artifact() -> None:
    """Require the refit artifact trained on all development seasons."""
    with pytest.raises(ModelAdapterError, match="validation sessions"):
        Phase6ModelAdapter(
            _artifact(validation_session_ids=("2024-01-R",))
        )


def test_context_requires_one_exact_ordered_feature_row() -> None:
    """Reject missing, additional, reordered or multi-row model input."""
    base = _base_features()
    with pytest.raises(ModelAdapterError, match="columns"):
        SimulationFeatureContext(
            base_features=base.loc[:, reversed(APPROVED_FEATURE_COLUMNS)],
            recent_lap_times_seconds=(),
        )
    with pytest.raises(ModelAdapterError, match="one row"):
        SimulationFeatureContext(
            base_features=pd.concat([base, base], ignore_index=True),
            recent_lap_times_seconds=(),
        )


def test_context_copies_mutable_base_frame() -> None:
    """Prevent external mutation from changing later simulation inference."""
    base = _base_features()
    context = SimulationFeatureContext(
        base_features=base,
        recent_lap_times_seconds=(90.0, 91.0, 92.0),
    )
    base.at[0, "driver"] = "HAM"
    assert context.base_features.at[0, "driver"] == "VER"


def test_initial_feature_row_reproduces_historical_seed() -> None:
    """Use the audited decision row unchanged for the first prediction."""
    context = _context()
    progress = initialize_simulation_progress(_request())
    features = build_simulation_features(
        context=context,
        progress=progress,
    )
    pd.testing.assert_frame_equal(
        features,
        context.base_features,
        check_dtype=False,
    )


def test_future_feature_row_updates_only_simulated_state() -> None:
    """Advance dynamic features using predictions rather than future data."""
    request = _request()
    progress = initialize_simulation_progress(request)
    progress, transition = advance_one_lap(
        progress,
        request,
        predicted_lap_time_seconds=91.0,
    )
    context = _context().record_simulated_lap(
        transition.predicted_lap_time_seconds
    )
    features = build_simulation_features(
        context=context,
        progress=progress,
    )
    row = features.iloc[0]

    assert row["decision_lap"] == 21
    assert row["current_compound"] == "MEDIUM"
    assert row["tyre_age_laps"] == 20
    assert row["current_stint_laps_completed"] == 20
    assert row["previous_lap_was_target_eligible"] == True  # noqa: E712
    assert row["previous_lap_time_seconds"] == 91.0
    assert pd.isna(row["previous_sector1_time_seconds"])
    assert pd.isna(row["previous_sector2_time_seconds"])
    assert pd.isna(row["previous_sector3_time_seconds"])
    assert row["eligible_laps_completed"] == 11
    assert row["weather_age_seconds"] == 96.0
    assert row["air_temperature_celsius"] == 24.0
    assert row["previous_position"] == 1

    expected_history = np.asarray(
        [91.0, 92.0, 93.0, 94.0, 91.0],
        dtype="float64",
    )
    assert row["rolling_lap_time_median_3"] == 93.0
    assert row["rolling_lap_time_median_5"] == 92.0
    assert row["rolling_lap_time_std_5"] == pytest.approx(
        float(np.std(expected_history, ddof=0))
    )


def test_first_lap_after_stop_forces_direct_model_fallback() -> None:
    """Never form a residual across an old-tyre to new-tyre transition."""
    request = _request(
        stops=(PlannedPitStop(20, DryCompound.HARD),),
    )
    progress, transition = advance_one_lap(
        initialize_simulation_progress(request),
        request,
        predicted_lap_time_seconds=91.0,
    )
    context = _context().record_simulated_lap(
        transition.predicted_lap_time_seconds
    )
    row = build_simulation_features(
        context=context,
        progress=progress,
    ).iloc[0]

    assert row["current_compound"] == "HARD"
    assert row["tyre_age_laps"] == 0
    assert row["current_stint_laps_completed"] == 0
    assert row["completed_pit_stops"] == 1
    assert row["previous_lap_was_target_eligible"] == False  # noqa: E712
    assert pd.isna(row["previous_lap_time_seconds"])
    assert row["weather_age_seconds"] == 116.0


def test_history_count_must_equal_engine_progress() -> None:
    """Keep model feedback synchronized exactly with completed engine laps."""
    context = _context().record_simulated_lap(91.0)
    progress = initialize_simulation_progress(_request())
    with pytest.raises(ModelAdapterError, match="history differs"):
        build_simulation_features(
            context=context,
            progress=progress,
        )


def test_seed_identity_must_match_simulated_race() -> None:
    """Reject accidental cross-driver, event or decision-row reuse."""
    context = _context()
    progress = replace(
        initialize_simulation_progress(_request()),
        driver="HAM",
    )
    with pytest.raises(ModelAdapterError, match="driver"):
        build_simulation_features(
            context=context,
            progress=progress,
        )


@pytest.mark.parametrize("prediction", [0.0, -1.0, float("nan"), float("inf")])
def test_adapter_rejects_invalid_model_prediction(prediction: float) -> None:
    """Keep impossible inference output out of the transition engine."""
    adapter = Phase6ModelAdapter(_artifact((prediction,)))
    with pytest.raises(ModelAdapterError, match="model prediction"):
        adapter.predict_next_lap(
            context=_context(),
            progress=initialize_simulation_progress(_request()),
        )


def test_adapter_rejects_wrong_prediction_count() -> None:
    """Require one prediction for the one-row simulator interface."""
    adapter = Phase6ModelAdapter(_artifact((91.0, 92.0)))
    with pytest.raises(ModelAdapterError, match="prediction count"):
        adapter.predict_next_lap(
            context=_context(),
            progress=initialize_simulation_progress(_request()),
        )


def test_adapter_returns_prediction_with_exact_audit_features() -> None:
    """Expose the precise feature row that generated each simulated lap."""
    adapter = Phase6ModelAdapter(_artifact((91.25,)))
    prediction = adapter.predict_next_lap(
        context=_context(),
        progress=initialize_simulation_progress(_request()),
    )
    assert prediction.seconds == 91.25
    assert tuple(prediction.features.columns) == APPROVED_FEATURE_COLUMNS
    assert len(prediction.features) == 1


def test_from_paths_uses_verified_phase_6_loader(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """Never deserialize a fitted model outside the integrity-checking loader."""
    artifact = _artifact()
    paths = ModelArtifactPaths(
        artifacts_root=tmp_path,
        artifact_id="phase-6-final-audit-lap-time",
    )
    calls: list[ModelArtifactPaths] = []

    def fake_loader(received: ModelArtifactPaths) -> LoadedModelArtifact:
        calls.append(received)
        return artifact

    monkeypatch.setattr(adapter_module, "load_model_artifact", fake_loader)
    adapter = Phase6ModelAdapter.from_paths(paths)

    assert adapter.artifact is artifact
    assert calls == [paths]
