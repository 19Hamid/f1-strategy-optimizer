"""Tests for reproducible Phase 9 reporting and immutable storage."""

from __future__ import annotations

import json
from dataclasses import replace

import pandas as pd
import pytest

from app.concurrent_simulation import (
    CONCURRENT_EXECUTOR_ID,
    CONCURRENT_SIMULATION_CONTRACT_VERSION,
    PERFORMANCE_BENCHMARK_ID,
    SCENARIO_GENERATOR_ID,
    SEQUENTIAL_AGGREGATOR_ID,
    UNCERTAINTY_CALIBRATION_METHOD_ID,
    BenchmarkExecutionMode,
    ConcurrentSimulationReportPaths,
    ConcurrentSimulationReportProvenance,
    ConcurrentSimulationReportTables,
    ConcurrentSimulationStorageError,
    ScenarioBatchRequest,
    ScenarioBenchmarkMeasurement,
    ScenarioOutcome,
    ScenarioPerformanceBenchmark,
    ScenarioPreference,
    ScenarioScalingBenchmark,
    SequentialScenarioEvaluation,
    UncertaintyCalibration,
    build_concurrent_simulation_report,
    concurrent_simulation_provenance_document,
    generate_scenario_batch,
    validate_concurrent_simulation_report_tables,
    verify_concurrent_simulation_report,
    write_concurrent_simulation_report,
)
from app.datasets.contracts import DATASET_CONTRACT_VERSION, DEVELOPMENT_SEASONS
from app.ml import MODEL_CONTRACT_VERSION
from app.optimizer import OPTIMIZER_CONTRACT_VERSION, PitDecisionRequest
from app.simulation import (
    SIMULATION_CONTRACT_VERSION,
    DryCompound,
    PitLossAssumption,
    PitLossSource,
    RaceState,
)


def _decision_request() -> PitDecisionRequest:
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
            evidence="Phase 9 reporting unit-test assumption",
        ),
    )


def _calibration() -> UncertaintyCalibration:
    return UncertaintyCalibration(
        calibration_id="reporting-unit-calibration",
        method_id=UNCERTAINTY_CALIBRATION_METHOD_ID,
        training_seasons=DEVELOPMENT_SEASONS,
        shared_pace_scale_seconds=0.2,
        pit_loss_scale_seconds=0.3,
        lap_time_residual_scale_seconds=0.4,
        replay_count=10,
        lap_count=100,
        pit_loss_profile_count=3,
        evidence="verified development replay and circuit-range evidence",
    )


def _evaluation(scenario_count: int = 4) -> SequentialScenarioEvaluation:
    batch = generate_scenario_batch(
        ScenarioBatchRequest(
            _decision_request(),
            scenario_count=scenario_count,
            root_seed=789,
        )
    )
    advantages = (1.0, -1.0, 0.0, 2.0)
    outcomes = []
    for scenario in batch.scenarios:
        advantage = advantages[scenario.scenario_index % len(advantages)]
        pit_now = 100.0 + scenario.scenario_index
        preference = ScenarioPreference.TIE
        if advantage > 0:
            preference = ScenarioPreference.PIT_NOW
        elif advantage < 0:
            preference = ScenarioPreference.STAY_OUT
        outcomes.append(
            ScenarioOutcome(
                scenario_index=scenario.scenario_index,
                scenario_seed=scenario.scenario_seed,
                pit_now_remaining_time_seconds=pit_now,
                stay_out_remaining_time_seconds=pit_now + advantage,
                pit_now_advantage_seconds=advantage,
                preference=preference,
            )
        )
    return SequentialScenarioEvaluation(
        batch=batch,
        calibration=_calibration(),
        aggregator_id=SEQUENTIAL_AGGREGATOR_ID,
        outcomes=tuple(outcomes),
    )


def _measurement(
    *,
    scenario_count: int,
    mode: BenchmarkExecutionMode,
    duration: float,
    baseline_duration: float,
    workers: int | None,
) -> ScenarioBenchmarkMeasurement:
    speedup = baseline_duration / duration
    return ScenarioBenchmarkMeasurement(
        execution_mode=mode,
        scenario_count=scenario_count,
        max_workers=workers,
        durations_seconds=(duration,),
        median_duration_seconds=duration,
        scenarios_per_second=scenario_count / duration,
        speedup_vs_sequential=speedup,
        worker_efficiency=None if workers is None else speedup / workers,
    )


def _benchmark_result(scenario_count: int) -> ScenarioPerformanceBenchmark:
    baseline = float(scenario_count)
    request = ScenarioBatchRequest(
        _decision_request(),
        scenario_count=scenario_count,
        root_seed=789,
    )
    return ScenarioPerformanceBenchmark(
        benchmark_id=PERFORMANCE_BENCHMARK_ID,
        request=request,
        repetitions=1,
        measurements=(
            _measurement(
                scenario_count=scenario_count,
                mode=BenchmarkExecutionMode.SEQUENTIAL,
                duration=baseline,
                baseline_duration=baseline,
                workers=None,
            ),
            _measurement(
                scenario_count=scenario_count,
                mode=BenchmarkExecutionMode.CONCURRENT,
                duration=baseline / 2,
                baseline_duration=baseline,
                workers=1,
            ),
            _measurement(
                scenario_count=scenario_count,
                mode=BenchmarkExecutionMode.CONCURRENT,
                duration=baseline / 4,
                baseline_duration=baseline,
                workers=2,
            ),
        ),
    )


def _benchmark() -> ScenarioScalingBenchmark:
    return ScenarioScalingBenchmark(
        benchmark_id=PERFORMANCE_BENCHMARK_ID,
        results=(_benchmark_result(2), _benchmark_result(4)),
    )


def _provenance() -> ConcurrentSimulationReportProvenance:
    return ConcurrentSimulationReportProvenance(
        concurrent_simulation_contract_version=(
            CONCURRENT_SIMULATION_CONTRACT_VERSION
        ),
        optimizer_contract_version=OPTIMIZER_CONTRACT_VERSION,
        simulation_contract_version=SIMULATION_CONTRACT_VERSION,
        model_contract_version=MODEL_CONTRACT_VERSION,
        model_artifact_id="phase-6-final-audit-lap-time",
        dataset_contract_version=DATASET_CONTRACT_VERSION,
        dataset_build_identifier="development-build",
        calibration_id="reporting-unit-calibration",
        calibration_method_id=UNCERTAINTY_CALIBRATION_METHOD_ID,
        scenario_generator_id=SCENARIO_GENERATOR_ID,
        sequential_aggregator_id=SEQUENTIAL_AGGREGATOR_ID,
        concurrent_executor_id=CONCURRENT_EXECUTOR_ID,
        benchmark_id=PERFORMANCE_BENCHMARK_ID,
        development_sessions=68,
        protected_evaluation_rows=0,
        root_seed=789,
        scenario_counts=(2, 4),
        worker_counts=(1, 2),
        repetitions=1,
        dependency_versions=(
            ("numpy", "2"),
            ("pandas", "2"),
            ("pyarrow", "25"),
            ("python", "3.14"),
        ),
        runtime_platform="Linux-test",
        runtime_machine="x86_64",
        runtime_processor="test-cpu",
        logical_cpu_count=20,
        execution_duration_seconds=7.5,
    )


def _tables() -> ConcurrentSimulationReportTables:
    return build_concurrent_simulation_report(
        evaluation=_evaluation(),
        benchmark=_benchmark(),
        provenance=_provenance(),
    )


def test_reporting_preserves_scenarios_decision_and_benchmarks() -> None:
    tables = _tables()

    assert len(tables.scenarios) == 4
    assert len(tables.decision) == 1
    assert len(tables.benchmarks) == 6
    assert tuple(tables.scenarios["scenario_index"]) == (0, 1, 2, 3)
    assert tables.scenarios["scenario_seed"].is_unique
    assert set(tables.scenarios["preference"]) == {
        ScenarioPreference.PIT_NOW.value,
        ScenarioPreference.STAY_OUT.value,
        ScenarioPreference.TIE.value,
    }
    decision = tables.decision.iloc[0]
    assert decision["pit_now_scenario_share"] == 0.5
    assert decision["stay_out_scenario_share"] == 0.25
    assert decision["tie_scenario_share"] == 0.25
    assert decision["recommendation"] == "NO_CLEAR_ADVANTAGE"
    assert not decision["recommendation_is_stable"]
    residuals = json.loads(
        tables.scenarios.iloc[0]["lap_time_residual_z_json"]
    )
    assert [item[0] for item in residuals] == [20, 21, 22]


def test_reporting_is_deterministic_and_reconciles_all_arithmetic() -> None:
    first = _tables()
    second = _tables()

    pd.testing.assert_frame_equal(first.scenarios, second.scenarios)
    pd.testing.assert_frame_equal(first.decision, second.decision)
    pd.testing.assert_frame_equal(first.benchmarks, second.benchmarks)
    validate_concurrent_simulation_report_tables(first)


def test_reporting_requires_largest_benchmark_population() -> None:
    with pytest.raises(
        ValueError,
        match="largest benchmark population",
    ):
        build_concurrent_simulation_report(
            evaluation=_evaluation(2),
            benchmark=_benchmark(),
            provenance=_provenance(),
        )


def test_reporting_rejects_tampered_scenario_advantage() -> None:
    tables = _tables()
    altered = tables.scenarios.copy()
    altered.loc[0, "pit_now_advantage_seconds"] = 999.0

    with pytest.raises(ValueError, match="scenario advantage"):
        validate_concurrent_simulation_report_tables(
            replace(tables, scenarios=altered)
        )


def test_reporting_rejects_tampered_benchmark_speedup() -> None:
    tables = _tables()
    altered = tables.benchmarks.copy()
    concurrent = altered["execution_mode"].eq("CONCURRENT")
    altered.loc[concurrent, "speedup_vs_sequential"] = 99.0

    with pytest.raises(ValueError, match="benchmark speedup"):
        validate_concurrent_simulation_report_tables(
            replace(tables, benchmarks=altered)
        )


def test_reporting_rejects_protected_decision_season() -> None:
    tables = _tables()
    altered = tables.decision.copy()
    altered.loc[0, "season"] = 2025

    with pytest.raises(ValueError, match="development season"):
        validate_concurrent_simulation_report_tables(
            replace(tables, decision=altered)
        )


def test_provenance_document_records_exact_table_counts() -> None:
    document = concurrent_simulation_provenance_document(_tables())

    assert document["scenario_rows"] == 4
    assert document["decision_rows"] == 1
    assert document["benchmark_rows"] == 6
    assert document["protected_evaluation_rows"] == 0
    assert document["logical_cpu_count"] == 20


def test_provenance_rejects_protected_rows_and_wrong_executor() -> None:
    with pytest.raises(ValueError, match="protected"):
        replace(_provenance(), protected_evaluation_rows=1)
    with pytest.raises(ValueError, match="concurrent_executor_id"):
        replace(_provenance(), concurrent_executor_id="fast-looking-v0")


@pytest.mark.parametrize("run_id", ("", ".", "..", "../escape", "a/b", "a\\b"))
def test_paths_reject_unsafe_run_identity(tmp_path, run_id: str) -> None:
    with pytest.raises(ConcurrentSimulationStorageError, match="safe path segment"):
        ConcurrentSimulationReportPaths(tmp_path, run_id)


def test_storage_writes_and_verifies_immutable_report(tmp_path) -> None:
    paths = ConcurrentSimulationReportPaths(tmp_path, "phase-9-test")

    manifest = write_concurrent_simulation_report(paths=paths, tables=_tables())
    verification = verify_concurrent_simulation_report(paths)

    assert manifest["run_id"] == "phase-9-test"
    assert set(manifest["artifacts"]) == {
        "scenarios.parquet",
        "decision.parquet",
        "benchmarks.parquet",
        "provenance.json",
    }
    assert verification.valid
    assert verification.artifact_count == 4
    assert verification.issues == ()
    with pytest.raises(ConcurrentSimulationStorageError, match="already exists"):
        write_concurrent_simulation_report(paths=paths, tables=_tables())


def test_verification_detects_corrupted_artifact(tmp_path) -> None:
    paths = ConcurrentSimulationReportPaths(tmp_path, "phase-9-test")
    write_concurrent_simulation_report(paths=paths, tables=_tables())
    with (paths.root / "scenarios.parquet").open("ab") as stream:
        stream.write(b"corruption")

    verification = verify_concurrent_simulation_report(paths)

    assert not verification.valid
    assert any("scenarios.parquet" in issue for issue in verification.issues)
    with pytest.raises(ConcurrentSimulationStorageError, match="verification failed"):
        verification.raise_for_errors()
