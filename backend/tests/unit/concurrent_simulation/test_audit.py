"""Tests for the complete Phase 9 development audit."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from app.concurrent_simulation import (
    UNCERTAINTY_CALIBRATION_METHOD_ID,
    UncertaintyCalibration,
)
from app.concurrent_simulation.audit import (
    CENTRAL_90_NORMAL_QUANTILE,
    ConcurrentSimulationAuditError,
    DevelopmentCoverageSummary,
    build_pit_loss_range_observations,
    build_replay_error_observations,
    reconcile_optimizer_candidates,
    select_representative_candidate,
    summarize_development_coverage,
)
from app.concurrent_simulation.calibration import ReplayLapErrorObservation
from app.concurrent_simulation.cli import (
    DEFAULT_MODEL_ARTIFACT_ID,
    DEFAULT_OPTIMIZER_RUN_ID,
    DEFAULT_RUN_ID,
    DEFAULT_SIMULATION_RUN_ID,
    build_parser,
)
from app.ml import APPROVED_FEATURE_COLUMNS
from app.optimizer import (
    OptimizerAuditCandidate,
    PitDecisionAction,
    PitDecisionRequest,
)
from app.simulation import (
    AUDIT_PIT_LOSS_SECONDS,
    DryCompound,
    PitLossAssumption,
    PitLossSource,
    RaceState,
    SimulationFeatureContext,
)


def _context() -> SimulationFeatureContext:
    values: dict[str, object] = {
        "event_name": "Test Grand Prix",
        "driver": "AAA",
        "team": "Test Team",
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


def _candidate(
    current_lap: int = 20,
    *,
    total_laps: int = 30,
    driver: str = "AAA",
) -> OptimizerAuditCandidate:
    request = PitDecisionRequest(
        state=RaceState(
            season=2024,
            session_id="2024-01-R",
            event_name="Test Grand Prix",
            driver=driver,
            team="Test Team",
            current_lap=current_lap,
            total_laps=total_laps,
            current_compound=DryCompound.MEDIUM,
            tyre_age_laps=current_lap - 1,
            current_stint_laps_completed=current_lap - 1,
            completed_pit_stops=0,
            compounds_used=(DryCompound.MEDIUM,),
            previous_position=1,
        ),
        target_compound=DryCompound.HARD,
        pit_loss=PitLossAssumption(
            seconds=20.0,
            source=PitLossSource.EXPLICIT_ASSUMPTION,
            evidence="Phase 9 audit unit-test assumption",
        ),
    )
    return OptimizerAuditCandidate(
        request=request,
        context=_context(),
        observed_action=PitDecisionAction.PIT_NOW,
        observed_pit_lap=current_lap,
    )


def _errors() -> tuple[ReplayLapErrorObservation, ...]:
    return (
        ReplayLapErrorObservation(2022, "a", 1, 1.0),
        ReplayLapErrorObservation(2022, "a", 2, 3.0),
        ReplayLapErrorObservation(2024, "b", 1, -3.0),
        ReplayLapErrorObservation(2024, "b", 2, -1.0),
    )


def _calibration() -> UncertaintyCalibration:
    return UncertaintyCalibration(
        calibration_id="audit-unit-calibration",
        method_id=UNCERTAINTY_CALIBRATION_METHOD_ID,
        training_seasons=(2022, 2023, 2024),
        shared_pace_scale_seconds=2.0,
        pit_loss_scale_seconds=4.0,
        lap_time_residual_scale_seconds=1.0,
        replay_count=2,
        lap_count=4,
        pit_loss_profile_count=3,
        evidence="synthetic development audit evidence",
    )


def test_cli_defaults_bind_every_upstream_final_audit() -> None:
    arguments = build_parser().parse_args(["audit"])

    assert arguments.run_id == DEFAULT_RUN_ID == "phase-9-final-audit"
    assert DEFAULT_MODEL_ARTIFACT_ID == "phase-6-final-audit-lap-time"
    assert DEFAULT_SIMULATION_RUN_ID == "phase-7-final-audit"
    assert DEFAULT_OPTIMIZER_RUN_ID == "phase-8-final-audit"


def test_replay_error_observations_join_season_and_sort_identity() -> None:
    replays = pd.DataFrame(
        {"replay_id": ["b", "a"], "season": [2024, 2022]}
    )
    trajectories = pd.DataFrame(
        {
            "replay_id": ["b", "a", "b", "a"],
            "lap_number": [2, 2, 1, 1],
            "signed_lap_error_seconds": [-1.0, 3.0, -3.0, 1.0],
        }
    )

    assert build_replay_error_observations(
        replays=replays,
        trajectories=trajectories,
    ) == _errors()


def test_replay_error_observations_reject_identity_mismatch() -> None:
    replays = pd.DataFrame({"replay_id": ["a", "b"], "season": [2022, 2024]})
    trajectories = pd.DataFrame(
        {
            "replay_id": ["a"],
            "lap_number": [1],
            "signed_lap_error_seconds": [1.0],
        }
    )

    with pytest.raises(ConcurrentSimulationAuditError, match="identities"):
        build_replay_error_observations(
            replays=replays,
            trajectories=trajectories,
        )


def test_pit_loss_observations_are_unique_per_season_and_event() -> None:
    catalog = pd.DataFrame(
        {
            "season": [2022, 2022, 2024],
            "event_name": ["A", "A", "B"],
        }
    )

    observations = build_pit_loss_range_observations(catalog)

    assert [(item.season, item.event_name) for item in observations] == [
        (2022, "A"),
        (2024, "B"),
    ]
    assert {
        (
            item.low_seconds,
            item.nominal_seconds,
            item.high_seconds,
        )
        for item in observations
    } == {AUDIT_PIT_LOSS_SECONDS}


def test_pit_loss_observations_reject_protected_season() -> None:
    catalog = pd.DataFrame({"season": [2025], "event_name": ["Protected"]})

    with pytest.raises(ValueError, match="2025"):
        build_pit_loss_range_observations(catalog)


def test_coverage_recomputes_fitted_replay_components() -> None:
    coverage = summarize_development_coverage(
        replay_lap_errors=_errors(),
        calibration=_calibration(),
    )

    assert coverage.normal_quantile == CENTRAL_90_NORMAL_QUANTILE
    assert coverage.replay_mean_count == 2
    assert coverage.replay_mean_covered == 2
    assert coverage.replay_mean_coverage_rate == 1.0
    assert coverage.lap_residual_count == 4
    assert coverage.lap_residual_covered == 4
    assert coverage.lap_residual_coverage_rate == 1.0
    assert coverage.replay_mean_interval_half_width_seconds == pytest.approx(
        CENTRAL_90_NORMAL_QUANTILE * 2
    )
    assert coverage.lap_residual_interval_half_width_seconds == pytest.approx(
        CENTRAL_90_NORMAL_QUANTILE
    )


def test_coverage_summary_rejects_unreconciled_rate() -> None:
    valid = summarize_development_coverage(
        replay_lap_errors=_errors(),
        calibration=_calibration(),
    )

    with pytest.raises(ConcurrentSimulationAuditError, match="does not reconcile"):
        replace(valid, replay_mean_coverage_rate=0.5)


def test_optimizer_population_reconciliation_requires_exact_keys() -> None:
    candidate = _candidate()
    decisions = pd.DataFrame(
        {
            "season": [2024],
            "session_id": ["2024-01-R"],
            "driver": ["AAA"],
            "decision_lap": [20],
            "target_compound": ["HARD"],
        }
    )

    reconcile_optimizer_candidates(
        candidates=(candidate,),
        optimizer_decisions=decisions,
    )

    with pytest.raises(ConcurrentSimulationAuditError, match="differs"):
        reconcile_optimizer_candidates(
            candidates=(candidate,),
            optimizer_decisions=decisions.assign(driver="BBB"),
        )


def test_representative_selection_uses_lower_median_horizon() -> None:
    candidates = (
        _candidate(5, total_laps=30, driver="LONG"),
        _candidate(20, total_laps=30, driver="SHORT"),
        _candidate(15, total_laps=30, driver="MEDIUM"),
        _candidate(10, total_laps=30, driver="LONGER"),
    )

    selected = select_representative_candidate(candidates)

    assert selected.request.state.driver == "MEDIUM"
    assert selected.request.state.total_laps - selected.request.state.current_lap + 1 == 16


def test_coverage_summary_is_frozen_and_hashable() -> None:
    value = DevelopmentCoverageSummary(
        central_probability=0.90,
        normal_quantile=1.0,
        replay_mean_count=1,
        replay_mean_covered=1,
        replay_mean_coverage_rate=1.0,
        replay_mean_interval_half_width_seconds=1.0,
        lap_residual_count=1,
        lap_residual_covered=1,
        lap_residual_coverage_rate=1.0,
        lap_residual_interval_half_width_seconds=1.0,
    )

    assert hash(value)
