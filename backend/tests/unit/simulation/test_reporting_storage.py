"""Tests for reproducible Phase 7 reporting and immutable storage."""

from __future__ import annotations

import json
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
from app.simulation import (
    SIMULATION_CONTRACT_VERSION,
    SIMULATION_RANDOM_SEED,
    DryCompound,
    ObservedReplayEvaluation,
    ObservedReplayLap,
    ObservedStrategyTrace,
    Phase6ModelAdapter,
    PitLossAssumption,
    PitLossSource,
    RaceState,
    SimulationFeatureContext,
    SimulationMetricScope,
    SimulationMode,
    SimulationReportingError,
    SimulationReportPaths,
    SimulationReportProvenance,
    SimulationRequest,
    SimulationStorageError,
    StrategyPlan,
    build_simulation_report,
    replay_observed_strategy,
    simulation_provenance_document,
    validate_simulation_report_tables,
    verify_simulation_report,
    write_simulation_report,
)
from app.simulation.model_adapter import SELECTED_SIMULATOR_CANDIDATE_ID


class _LapNumberModel:
    def predict(self, features: pd.DataFrame) -> np.ndarray:
        assert tuple(features.columns) == APPROVED_FEATURE_COLUMNS
        return 90.0 + (features["decision_lap"].to_numpy(dtype="float64") / 100.0)


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


def _base_features(event_name: str) -> pd.DataFrame:
    values: dict[str, object] = {
        "event_name": event_name,
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


def _replay(
    *,
    session_id: str,
    event_name: str,
    total_laps: int,
):
    request = SimulationRequest(
        state=RaceState(
            season=2024,
            session_id=session_id,
            event_name=event_name,
            driver="VER",
            team="Red Bull Racing",
            current_lap=20,
            total_laps=total_laps,
            current_compound=DryCompound.MEDIUM,
            tyre_age_laps=19,
            current_stint_laps_completed=19,
            completed_pit_stops=0,
            compounds_used=(DryCompound.HARD, DryCompound.MEDIUM),
            previous_position=1,
        ),
        strategy=StrategyPlan(strategy_id=f"observed-{session_id}"),
        pit_loss=PitLossAssumption(
            seconds=20.0,
            source=PitLossSource.EXPLICIT_ASSUMPTION,
            evidence="unit-test sensitivity assumption",
        ),
        mode=SimulationMode.OBSERVED_STRATEGY_REPLAY,
    )
    lap_numbers = tuple(range(20, total_laps + 1))
    observed = ObservedStrategyTrace(
        season=2024,
        session_id=session_id,
        event_name=event_name,
        driver="VER",
        team="Red Bull Racing",
        start_lap=20,
        total_laps=total_laps,
        laps=tuple(
            ObservedReplayLap(
                lap_number=lap_number,
                observed_total_lap_time_seconds=91.0,
            )
            for lap_number in lap_numbers
        ),
    )
    context = SimulationFeatureContext(
        base_features=_base_features(event_name),
        recent_lap_times_seconds=(90.0, 91.0, 92.0, 93.0, 94.0),
    )
    return replay_observed_strategy(
        request,
        context=context,
        adapter=Phase6ModelAdapter(_artifact()),
        observed=observed,
    )


def _evaluation() -> ObservedReplayEvaluation:
    return ObservedReplayEvaluation(
        (
            _replay(
                session_id="2024-01-R",
                event_name="Bahrain Grand Prix",
                total_laps=22,
            ),
            _replay(
                session_id="2024-02-R",
                event_name="Bahrain Grand Prix",
                total_laps=30,
            ),
            _replay(
                session_id="2024-03-R",
                event_name="Italian Grand Prix",
                total_laps=45,
            ),
        )
    )


def _provenance() -> SimulationReportProvenance:
    return SimulationReportProvenance(
        simulation_contract_version=SIMULATION_CONTRACT_VERSION,
        model_contract_version=MODEL_CONTRACT_VERSION,
        model_artifact_id="phase-6-final-audit-lap-time",
        dataset_contract_version="1.0",
        dataset_build_identifier="development-build",
        development_sessions=3,
        protected_evaluation_rows=0,
        random_seed=SIMULATION_RANDOM_SEED,
        dependency_versions=(
            ("numpy", "2"),
            ("pandas", "2"),
            ("pyarrow", "25"),
            ("python", "3.14"),
        ),
        execution_duration_seconds=1.25,
    )


def _tables():
    return build_simulation_report(
        evaluation=_evaluation(),
        provenance=_provenance(),
    )


def test_reporting_preserves_metrics_trajectories_and_assumptions() -> None:
    """Store aggregate diagnostics and complete reproducibility evidence."""
    tables = _tables()

    assert len(tables.replays) == 3
    assert len(tables.trajectories) == 40
    assert len(tables.metrics) == 9
    assert set(tables.metrics["scope"]) == {
        scope.value for scope in SimulationMetricScope
    }
    horizons = tables.metrics.loc[
        tables.metrics["scope"].eq(SimulationMetricScope.HORIZON_REMAINING.value),
        "value",
    ]
    assert len(horizons) == 3
    event_rows = tables.metrics["scope"].isin(
        {
            SimulationMetricScope.EVENT_LAP.value,
            SimulationMetricScope.EVENT_REMAINING.value,
        }
    )
    assert tables.metrics.loc[event_rows, "value"].nunique() == 2
    assert tables.replays["pit_loss_seconds_per_stop"].eq(20.0).all()
    assert tables.replays["pit_loss_evidence"].str.contains("sensitivity").all()
    features = json.loads(tables.trajectories.iloc[0]["model_features_json"])
    assert tuple(item[0] for item in features) == APPROVED_FEATURE_COLUMNS


def test_reporting_is_deterministic_and_reconciles_metrics() -> None:
    """Equal replay evidence must produce byte-equivalent table values."""
    first = _tables()
    second = _tables()

    pd.testing.assert_frame_equal(first.metrics, second.metrics)
    pd.testing.assert_frame_equal(first.replays, second.replays)
    pd.testing.assert_frame_equal(first.trajectories, second.trajectories)
    validate_simulation_report_tables(first)


def test_reporting_rejects_provenance_session_mismatch() -> None:
    """Prevent incomplete development populations from being mislabelled."""
    with pytest.raises(
        SimulationReportingError,
        match="session count differs",
    ):
        build_simulation_report(
            evaluation=_evaluation(),
            provenance=replace(_provenance(), development_sessions=2),
        )


def test_reporting_rejects_tampered_metrics() -> None:
    """Recompute stored metrics from replay rows before publication."""
    tables = _tables()
    altered = tables.metrics.copy()
    altered.loc[0, "mean_absolute_error_seconds"] = 999.0

    with pytest.raises(
        SimulationReportingError,
        match="metrics differ",
    ):
        validate_simulation_report_tables(replace(tables, metrics=altered))


def test_provenance_document_records_exact_table_counts() -> None:
    document = simulation_provenance_document(_tables())

    assert document["metric_rows"] == 9
    assert document["replay_rows"] == 3
    assert document["trajectory_rows"] == 40
    assert document["protected_evaluation_rows"] == 0


def test_provenance_rejects_protected_rows_and_wrong_seed() -> None:
    with pytest.raises(SimulationReportingError, match="protected"):
        replace(_provenance(), protected_evaluation_rows=1)
    with pytest.raises(SimulationReportingError, match="random seed"):
        replace(_provenance(), random_seed=7)


@pytest.mark.parametrize("run_id", ("", ".", "..", "../escape", "a/b", "a\\b"))
def test_paths_reject_unsafe_run_identity(tmp_path, run_id: str) -> None:
    with pytest.raises(SimulationStorageError, match="safe path segment"):
        SimulationReportPaths(tmp_path, run_id)


def test_storage_writes_and_verifies_immutable_report(tmp_path) -> None:
    paths = SimulationReportPaths(tmp_path, "phase-7-test")

    manifest = write_simulation_report(paths=paths, tables=_tables())
    verification = verify_simulation_report(paths)

    assert manifest["run_id"] == "phase-7-test"
    assert set(manifest["artifacts"]) == {
        "metrics.parquet",
        "replays.parquet",
        "trajectories.parquet",
        "provenance.json",
    }
    assert verification.valid
    assert verification.artifact_count == 4
    assert verification.issues == ()
    with pytest.raises(SimulationStorageError, match="already exists"):
        write_simulation_report(paths=paths, tables=_tables())


def test_verification_detects_corrupted_artifact(tmp_path) -> None:
    paths = SimulationReportPaths(tmp_path, "phase-7-test")
    write_simulation_report(paths=paths, tables=_tables())
    with (paths.root / "trajectories.parquet").open("ab") as stream:
        stream.write(b"corruption")

    verification = verify_simulation_report(paths)

    assert not verification.valid
    assert any("trajectories.parquet" in issue for issue in verification.issues)
    with pytest.raises(SimulationStorageError, match="verification failed"):
        verification.raise_for_errors()
