"""Normalized, reproducible Phase 9 scenario and benchmark reporting."""

from __future__ import annotations

import json
import math
import os
import platform
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from statistics import median
from typing import Final

import numpy as np
import pandas as pd
from app.concurrent_simulation.aggregation import (
    MINIMUM_STABILITY_SCENARIO_COUNT,
    SEQUENTIAL_AGGREGATOR_ID,
    ScenarioDistribution,
    ScenarioPreference,
    SequentialScenarioEvaluation,
    summarize_scenario_distribution,
)
from app.concurrent_simulation.benchmark import (
    MAXIMUM_BENCHMARK_REPETITIONS,
    PERFORMANCE_BENCHMARK_ID,
    BenchmarkExecutionMode,
    ScenarioScalingBenchmark,
)
from app.concurrent_simulation.calibration import (
    UNCERTAINTY_CALIBRATION_METHOD_ID,
)
from app.concurrent_simulation.executor import (
    CONCURRENT_EXECUTOR_ID,
    MAXIMUM_CONCURRENT_WORKERS,
)

from app.concurrent_simulation.contracts import (
    CONCURRENT_SIMULATION_CONTRACT_VERSION,
    MAXIMUM_SCENARIO_COUNT,
    SCENARIO_GENERATOR_ID,
)
from app.datasets.contracts import DATASET_CONTRACT_VERSION, DEVELOPMENT_SEASONS
from app.ml import MODEL_CONTRACT_VERSION
from app.optimizer.contracts import (
    DECISION_EQUALITY_ABS_TOLERANCE_SECONDS,
    OPTIMIZER_CONTRACT_VERSION,
    PitDecisionRecommendation,
)
from app.simulation import SIMULATION_CONTRACT_VERSION

CONCURRENT_SCENARIO_COLUMNS: Final = (
    "decision_id",
    "scenario_index",
    "scenario_seed",
    "shared_pace_z",
    "pit_loss_z",
    "lap_time_residual_z_json",
    "pit_now_remaining_time_seconds",
    "stay_out_remaining_time_seconds",
    "pit_now_advantage_seconds",
    "preference",
)
CONCURRENT_DECISION_COLUMNS: Final = (
    "decision_id",
    "season",
    "session_id",
    "event_name",
    "driver",
    "team",
    "decision_lap",
    "total_laps",
    "remaining_laps",
    "current_compound",
    "current_tyre_age_laps",
    "current_stint_laps_completed",
    "completed_pit_stops",
    "compounds_used_json",
    "target_compound",
    "pit_loss_seconds",
    "pit_loss_source",
    "pit_loss_evidence",
    "root_seed",
    "scenario_count",
    "generator_id",
    "aggregator_id",
    "calibration_id",
    "calibration_method_id",
    "calibration_training_seasons_json",
    "shared_pace_scale_seconds",
    "pit_loss_scale_seconds",
    "lap_time_residual_scale_seconds",
    "calibration_replay_count",
    "calibration_lap_count",
    "calibration_pit_loss_profile_count",
    "calibration_evidence",
    "pit_now_mean_seconds",
    "pit_now_standard_deviation_seconds",
    "pit_now_minimum_seconds",
    "pit_now_p05_seconds",
    "pit_now_median_seconds",
    "pit_now_p95_seconds",
    "pit_now_maximum_seconds",
    "stay_out_mean_seconds",
    "stay_out_standard_deviation_seconds",
    "stay_out_minimum_seconds",
    "stay_out_p05_seconds",
    "stay_out_median_seconds",
    "stay_out_p95_seconds",
    "stay_out_maximum_seconds",
    "advantage_mean_seconds",
    "advantage_standard_deviation_seconds",
    "advantage_minimum_seconds",
    "advantage_p05_seconds",
    "advantage_median_seconds",
    "advantage_p95_seconds",
    "advantage_maximum_seconds",
    "pit_now_scenario_share",
    "stay_out_scenario_share",
    "tie_scenario_share",
    "recommendation",
    "recommendation_is_stable",
)
CONCURRENT_BENCHMARK_COLUMNS: Final = (
    "decision_id",
    "benchmark_id",
    "scenario_count",
    "execution_mode",
    "max_workers",
    "repetitions",
    "durations_seconds_json",
    "median_duration_seconds",
    "scenarios_per_second",
    "speedup_vs_sequential",
    "worker_efficiency",
)
_REQUIRED_DEPENDENCIES: Final = frozenset(
    {"numpy", "pandas", "pyarrow", "python"}
)


class ConcurrentSimulationReportingError(ValueError):
    """Raised when Phase 9 evidence cannot form an honest report."""


@dataclass(frozen=True, slots=True)
class ConcurrentSimulationReportProvenance:
    """Data, model, calibration, benchmark and machine identity."""

    concurrent_simulation_contract_version: str
    optimizer_contract_version: str
    simulation_contract_version: str
    model_contract_version: str
    model_artifact_id: str
    dataset_contract_version: str
    dataset_build_identifier: str
    calibration_id: str
    calibration_method_id: str
    scenario_generator_id: str
    sequential_aggregator_id: str
    concurrent_executor_id: str
    benchmark_id: str
    development_sessions: int
    protected_evaluation_rows: int
    root_seed: int
    scenario_counts: tuple[int, ...]
    worker_counts: tuple[int, ...]
    repetitions: int
    dependency_versions: tuple[tuple[str, str], ...]
    runtime_platform: str
    runtime_machine: str
    runtime_processor: str
    logical_cpu_count: int
    execution_duration_seconds: float

    def __post_init__(self) -> None:
        expected_versions = (
            (
                "concurrent_simulation_contract_version",
                self.concurrent_simulation_contract_version,
                CONCURRENT_SIMULATION_CONTRACT_VERSION,
            ),
            (
                "optimizer_contract_version",
                self.optimizer_contract_version,
                OPTIMIZER_CONTRACT_VERSION,
            ),
            (
                "simulation_contract_version",
                self.simulation_contract_version,
                SIMULATION_CONTRACT_VERSION,
            ),
            (
                "model_contract_version",
                self.model_contract_version,
                MODEL_CONTRACT_VERSION,
            ),
            (
                "dataset_contract_version",
                self.dataset_contract_version,
                DATASET_CONTRACT_VERSION,
            ),
            (
                "calibration_method_id",
                self.calibration_method_id,
                UNCERTAINTY_CALIBRATION_METHOD_ID,
            ),
            (
                "scenario_generator_id",
                self.scenario_generator_id,
                SCENARIO_GENERATOR_ID,
            ),
            (
                "sequential_aggregator_id",
                self.sequential_aggregator_id,
                SEQUENTIAL_AGGREGATOR_ID,
            ),
            (
                "concurrent_executor_id",
                self.concurrent_executor_id,
                CONCURRENT_EXECUTOR_ID,
            ),
            ("benchmark_id", self.benchmark_id, PERFORMANCE_BENCHMARK_ID),
        )
        for name, actual, expected in expected_versions:
            if actual != expected:
                raise ConcurrentSimulationReportingError(f"unexpected {name}")
        for name in (
            "model_artifact_id",
            "dataset_build_identifier",
            "calibration_id",
            "runtime_platform",
            "runtime_machine",
            "runtime_processor",
        ):
            _text(getattr(self, name), name)
        _positive_integer(self.development_sessions, "development_sessions")
        if self.protected_evaluation_rows != 0:
            raise ConcurrentSimulationReportingError(
                "protected evaluation rows entered Phase 9"
            )
        _integer_at_least(self.root_seed, "root_seed", 0)
        _increasing_positive_tuple(self.scenario_counts, "scenario_counts")
        _increasing_positive_tuple(self.worker_counts, "worker_counts")
        if self.scenario_counts[-1] > MAXIMUM_SCENARIO_COUNT:
            raise ConcurrentSimulationReportingError(
                "scenario_counts exceed the contract maximum"
            )
        if self.worker_counts[-1] > MAXIMUM_CONCURRENT_WORKERS:
            raise ConcurrentSimulationReportingError(
                "worker_counts exceed the contract maximum"
            )
        repetitions = _positive_integer(self.repetitions, "repetitions")
        if repetitions > MAXIMUM_BENCHMARK_REPETITIONS:
            raise ConcurrentSimulationReportingError(
                "repetitions exceed the benchmark maximum"
            )
        if tuple(sorted(self.dependency_versions)) != self.dependency_versions:
            raise ConcurrentSimulationReportingError(
                "dependency versions must be canonical"
            )
        names = {name for name, _ in self.dependency_versions}
        if names != _REQUIRED_DEPENDENCIES:
            raise ConcurrentSimulationReportingError(
                "dependency version evidence is incomplete"
            )
        if any(not name or not value for name, value in self.dependency_versions):
            raise ConcurrentSimulationReportingError(
                "dependency versions must not be blank"
            )
        _positive_integer(self.logical_cpu_count, "logical_cpu_count")
        _finite_non_negative(
            self.execution_duration_seconds,
            "execution_duration_seconds",
        )


@dataclass(frozen=True, slots=True)
class ConcurrentSimulationReportTables:
    """Normalized Phase 9 evidence ready for immutable storage."""

    scenarios: pd.DataFrame
    decision: pd.DataFrame
    benchmarks: pd.DataFrame
    provenance: ConcurrentSimulationReportProvenance

    def __post_init__(self) -> None:
        for name in ("scenarios", "decision", "benchmarks"):
            if not isinstance(getattr(self, name), pd.DataFrame):
                raise TypeError(f"{name} must be a pandas DataFrame")
        if not isinstance(
            self.provenance,
            ConcurrentSimulationReportProvenance,
        ):
            raise TypeError(
                "provenance must be a ConcurrentSimulationReportProvenance"
            )


def runtime_concurrent_dependency_versions() -> tuple[tuple[str, str], ...]:
    """Capture dependencies capable of changing stored numeric evidence."""
    dependencies = {"python": platform.python_version()}
    for package in ("numpy", "pandas", "pyarrow"):
        try:
            dependencies[package] = version(package)
        except PackageNotFoundError as error:
            raise ConcurrentSimulationReportingError(
                f"required dependency is not installed: {package}"
            ) from error
    return tuple(sorted(dependencies.items()))


def runtime_concurrent_machine_identity() -> tuple[str, str, str, int]:
    """Return stable machine fields required beside performance evidence."""
    return (
        platform.platform() or "unknown",
        platform.machine() or "unknown",
        platform.processor() or "unknown",
        os.cpu_count() or 1,
    )


def build_concurrent_simulation_report(
    *,
    evaluation: SequentialScenarioEvaluation,
    benchmark: ScenarioScalingBenchmark,
    provenance: ConcurrentSimulationReportProvenance,
) -> ConcurrentSimulationReportTables:
    """Normalize one decision's largest scenario batch and scaling evidence."""
    if not isinstance(evaluation, SequentialScenarioEvaluation):
        raise TypeError("evaluation must be a SequentialScenarioEvaluation")
    if not isinstance(benchmark, ScenarioScalingBenchmark):
        raise TypeError("benchmark must be a ScenarioScalingBenchmark")
    if not isinstance(provenance, ConcurrentSimulationReportProvenance):
        raise TypeError(
            "provenance must be a ConcurrentSimulationReportProvenance"
        )
    request = evaluation.batch.request
    if request.scenario_count != benchmark.scenario_counts[-1]:
        raise ConcurrentSimulationReportingError(
            "stored scenario population must be the largest benchmark population"
        )
    for result in benchmark.results:
        if result.request.decision_request != request.decision_request:
            raise ConcurrentSimulationReportingError(
                "benchmark and scenario decision requests differ"
            )
        if result.request.root_seed != request.root_seed:
            raise ConcurrentSimulationReportingError(
                "benchmark and scenario root seeds differ"
            )
    worker_counts = tuple(
        measurement.max_workers
        for measurement in benchmark.results[0].concurrent_measurements
    )
    expected_provenance = (
        (provenance.calibration_id, evaluation.calibration.calibration_id),
        (provenance.root_seed, request.root_seed),
        (provenance.scenario_counts, benchmark.scenario_counts),
        (provenance.worker_counts, worker_counts),
        (provenance.repetitions, benchmark.results[0].repetitions),
    )
    if any(actual != expected for actual, expected in expected_provenance):
        raise ConcurrentSimulationReportingError(
            "report provenance differs from scenario or benchmark evidence"
        )

    decision_id = _decision_id(evaluation)
    scenario_records = []
    for scenario, outcome in zip(
        evaluation.batch.scenarios,
        evaluation.outcomes,
        strict=True,
    ):
        scenario_records.append(
            {
                "decision_id": decision_id,
                "scenario_index": scenario.scenario_index,
                "scenario_seed": scenario.scenario_seed,
                "shared_pace_z": scenario.shared_pace_z,
                "pit_loss_z": scenario.pit_loss_z,
                "lap_time_residual_z_json": _json(
                    scenario.lap_time_residual_z
                ),
                "pit_now_remaining_time_seconds": (
                    outcome.pit_now_remaining_time_seconds
                ),
                "stay_out_remaining_time_seconds": (
                    outcome.stay_out_remaining_time_seconds
                ),
                "pit_now_advantage_seconds": (
                    outcome.pit_now_advantage_seconds
                ),
                "preference": outcome.preference.value,
            }
        )
    scenarios = pd.DataFrame.from_records(
        scenario_records,
        columns=CONCURRENT_SCENARIO_COLUMNS,
    )
    decision = pd.DataFrame.from_records(
        [_decision_record(evaluation, decision_id=decision_id)],
        columns=CONCURRENT_DECISION_COLUMNS,
    )
    benchmark_records = []
    for result in benchmark.results:
        for measurement in result.measurements:
            benchmark_records.append(
                {
                    "decision_id": decision_id,
                    "benchmark_id": benchmark.benchmark_id,
                    "scenario_count": measurement.scenario_count,
                    "execution_mode": measurement.execution_mode.value,
                    "max_workers": measurement.max_workers,
                    "repetitions": result.repetitions,
                    "durations_seconds_json": _json(
                        measurement.durations_seconds
                    ),
                    "median_duration_seconds": (
                        measurement.median_duration_seconds
                    ),
                    "scenarios_per_second": measurement.scenarios_per_second,
                    "speedup_vs_sequential": (
                        measurement.speedup_vs_sequential
                    ),
                    "worker_efficiency": measurement.worker_efficiency,
                }
            )
    benchmarks = pd.DataFrame.from_records(
        benchmark_records,
        columns=CONCURRENT_BENCHMARK_COLUMNS,
    )
    tables = ConcurrentSimulationReportTables(
        scenarios=scenarios,
        decision=decision,
        benchmarks=benchmarks,
        provenance=provenance,
    )
    validate_concurrent_simulation_report_tables(tables)
    return tables


def validate_concurrent_simulation_report_tables(
    tables: ConcurrentSimulationReportTables,
) -> None:
    """Recompute scenario summaries and benchmark arithmetic before storage."""
    if not isinstance(tables, ConcurrentSimulationReportTables):
        raise TypeError("tables must be a ConcurrentSimulationReportTables")
    _exact_columns(tables.scenarios, CONCURRENT_SCENARIO_COLUMNS, "scenarios")
    _exact_columns(tables.decision, CONCURRENT_DECISION_COLUMNS, "decision")
    _exact_columns(tables.benchmarks, CONCURRENT_BENCHMARK_COLUMNS, "benchmarks")
    if len(tables.decision) != 1:
        raise ConcurrentSimulationReportingError(
            "decision table must contain exactly one row"
        )
    decision = tables.decision.iloc[0]
    if str(decision["decision_id"]).strip() == "":
        raise ConcurrentSimulationReportingError("decision_id must not be blank")
    season = _integer_value(decision["season"], "season")
    if season not in DEVELOPMENT_SEASONS:
        raise ConcurrentSimulationReportingError(
            "stored decision must use a development season"
        )
    scenario_count = _integer_value(decision["scenario_count"], "scenario_count")
    if len(tables.scenarios) != scenario_count:
        raise ConcurrentSimulationReportingError(
            "scenario row count differs from the decision summary"
        )
    expected_indices = tuple(range(scenario_count))
    actual_indices = tuple(
        _integer_value(value, "scenario_index")
        for value in tables.scenarios["scenario_index"]
    )
    if actual_indices != expected_indices:
        raise ConcurrentSimulationReportingError(
            "stored scenario indices are not canonical"
        )
    seeds = tuple(
        _integer_value(value, "scenario_seed")
        for value in tables.scenarios["scenario_seed"]
    )
    if len(seeds) != len(set(seeds)):
        raise ConcurrentSimulationReportingError(
            "stored scenario seeds are not unique"
        )
    _require_finite(
        tables.scenarios,
        (
            "shared_pace_z",
            "pit_loss_z",
            "pit_now_remaining_time_seconds",
            "stay_out_remaining_time_seconds",
            "pit_now_advantage_seconds",
        ),
    )
    pit_now = tuple(
        float(value)
        for value in tables.scenarios["pit_now_remaining_time_seconds"]
    )
    stay_out = tuple(
        float(value)
        for value in tables.scenarios["stay_out_remaining_time_seconds"]
    )
    advantages = tuple(
        float(value)
        for value in tables.scenarios["pit_now_advantage_seconds"]
    )
    for index, (pit_value, stay_value, advantage, preference) in enumerate(
        zip(
            pit_now,
            stay_out,
            advantages,
            tables.scenarios["preference"],
            strict=True,
        )
    ):
        if pit_value <= 0 or stay_value <= 0:
            raise ConcurrentSimulationReportingError(
                "stored complete action times must be positive"
            )
        _close(advantage, stay_value - pit_value, "scenario advantage")
        if str(preference) != _preference(advantage):
            raise ConcurrentSimulationReportingError(
                f"stored preference differs at scenario {index}"
            )
    _validate_residual_coordinates(tables.scenarios, decision)
    _validate_decision_summary(
        decision,
        pit_now=pit_now,
        stay_out=stay_out,
        advantages=advantages,
        preferences=tuple(str(value) for value in tables.scenarios["preference"]),
    )
    _validate_benchmark_table(tables.benchmarks, tables.provenance)
    decision_ids = {
        str(decision["decision_id"]),
        *tables.scenarios["decision_id"].astype(str),
        *tables.benchmarks["decision_id"].astype(str),
    }
    if len(decision_ids) != 1:
        raise ConcurrentSimulationReportingError(
            "report tables do not share one decision identity"
        )
    root_seed = _integer_value(decision["root_seed"], "root_seed")
    if root_seed != tables.provenance.root_seed:
        raise ConcurrentSimulationReportingError(
            "decision root seed differs from provenance"
        )
    if str(decision["calibration_id"]) != tables.provenance.calibration_id:
        raise ConcurrentSimulationReportingError(
            "decision calibration differs from provenance"
        )
    if scenario_count != tables.provenance.scenario_counts[-1]:
        raise ConcurrentSimulationReportingError(
            "decision population differs from provenance"
        )
    expected_identities = (
        ("generator_id", SCENARIO_GENERATOR_ID),
        ("aggregator_id", SEQUENTIAL_AGGREGATOR_ID),
        ("calibration_method_id", UNCERTAINTY_CALIBRATION_METHOD_ID),
    )
    for field_name, expected in expected_identities:
        if str(decision[field_name]) != expected:
            raise ConcurrentSimulationReportingError(
                f"stored {field_name} differs from the contract"
            )
    training_seasons = tuple(
        _integer_value(value, "calibration training season")
        for value in _json_list(
            decision["calibration_training_seasons_json"],
            "calibration_training_seasons_json",
        )
    )
    if training_seasons != DEVELOPMENT_SEASONS:
        raise ConcurrentSimulationReportingError(
            "stored calibration seasons differ from development seasons"
        )


def concurrent_simulation_provenance_document(
    tables: ConcurrentSimulationReportTables,
) -> dict[str, object]:
    """Serialize provenance with exact normalized table counts."""
    validate_concurrent_simulation_report_tables(tables)
    return {
        **asdict(tables.provenance),
        "scenario_rows": len(tables.scenarios),
        "decision_rows": len(tables.decision),
        "benchmark_rows": len(tables.benchmarks),
    }


def _decision_record(
    evaluation: SequentialScenarioEvaluation,
    *,
    decision_id: str,
) -> dict[str, object]:
    request = evaluation.batch.request
    decision_request = request.decision_request
    state = decision_request.state
    calibration = evaluation.calibration
    record: dict[str, object] = {
        "decision_id": decision_id,
        "season": state.season,
        "session_id": state.session_id,
        "event_name": state.event_name,
        "driver": state.driver,
        "team": state.team,
        "decision_lap": state.current_lap,
        "total_laps": state.total_laps,
        "remaining_laps": state.total_laps - state.current_lap + 1,
        "current_compound": state.current_compound.value,
        "current_tyre_age_laps": state.tyre_age_laps,
        "current_stint_laps_completed": state.current_stint_laps_completed,
        "completed_pit_stops": state.completed_pit_stops,
        "compounds_used_json": _json(
            tuple(compound.value for compound in state.compounds_used)
        ),
        "target_compound": decision_request.target_compound.value,
        "pit_loss_seconds": decision_request.pit_loss.seconds,
        "pit_loss_source": decision_request.pit_loss.source.value,
        "pit_loss_evidence": decision_request.pit_loss.evidence,
        "root_seed": request.root_seed,
        "scenario_count": request.scenario_count,
        "generator_id": evaluation.batch.generator_id,
        "aggregator_id": evaluation.aggregator_id,
        "calibration_id": calibration.calibration_id,
        "calibration_method_id": calibration.method_id,
        "calibration_training_seasons_json": _json(
            calibration.training_seasons
        ),
        "shared_pace_scale_seconds": calibration.shared_pace_scale_seconds,
        "pit_loss_scale_seconds": calibration.pit_loss_scale_seconds,
        "lap_time_residual_scale_seconds": (
            calibration.lap_time_residual_scale_seconds
        ),
        "calibration_replay_count": calibration.replay_count,
        "calibration_lap_count": calibration.lap_count,
        "calibration_pit_loss_profile_count": (
            calibration.pit_loss_profile_count
        ),
        "calibration_evidence": calibration.evidence,
        "pit_now_scenario_share": evaluation.pit_now_scenario_share,
        "stay_out_scenario_share": evaluation.stay_out_scenario_share,
        "tie_scenario_share": evaluation.tie_scenario_share,
        "recommendation": evaluation.recommendation.value,
        "recommendation_is_stable": evaluation.recommendation_is_stable,
    }
    record.update(
        _distribution_record("pit_now", evaluation.pit_now_distribution)
    )
    record.update(
        _distribution_record("stay_out", evaluation.stay_out_distribution)
    )
    record.update(
        _distribution_record("advantage", evaluation.advantage_distribution)
    )
    return record


def _distribution_record(
    prefix: str,
    distribution: ScenarioDistribution,
) -> dict[str, float]:
    return {
        f"{prefix}_mean_seconds": distribution.mean,
        f"{prefix}_standard_deviation_seconds": distribution.standard_deviation,
        f"{prefix}_minimum_seconds": distribution.minimum,
        f"{prefix}_p05_seconds": distribution.p05,
        f"{prefix}_median_seconds": distribution.median,
        f"{prefix}_p95_seconds": distribution.p95,
        f"{prefix}_maximum_seconds": distribution.maximum,
    }


def _validate_decision_summary(
    decision: pd.Series,
    *,
    pit_now: tuple[float, ...],
    stay_out: tuple[float, ...],
    advantages: tuple[float, ...],
    preferences: tuple[str, ...],
) -> None:
    for prefix, values in (
        ("pit_now", pit_now),
        ("stay_out", stay_out),
        ("advantage", advantages),
    ):
        distribution = summarize_scenario_distribution(values)
        for suffix, expected in (
            ("mean", distribution.mean),
            ("standard_deviation", distribution.standard_deviation),
            ("minimum", distribution.minimum),
            ("p05", distribution.p05),
            ("median", distribution.median),
            ("p95", distribution.p95),
            ("maximum", distribution.maximum),
        ):
            _close(
                decision[f"{prefix}_{suffix}_seconds"],
                expected,
                f"{prefix} {suffix}",
            )
    count = len(preferences)
    shares = {
        "pit_now_scenario_share": preferences.count(ScenarioPreference.PIT_NOW.value)
        / count,
        "stay_out_scenario_share": preferences.count(
            ScenarioPreference.STAY_OUT.value
        )
        / count,
        "tie_scenario_share": preferences.count(ScenarioPreference.TIE.value)
        / count,
    }
    for field_name, expected in shares.items():
        _close(decision[field_name], expected, field_name)
    expected_recommendation = PitDecisionRecommendation.NO_CLEAR_ADVANTAGE
    advantage = summarize_scenario_distribution(advantages)
    if count >= MINIMUM_STABILITY_SCENARIO_COUNT:
        if advantage.p05 > DECISION_EQUALITY_ABS_TOLERANCE_SECONDS:
            expected_recommendation = PitDecisionRecommendation.PIT_NOW
        elif advantage.p95 < -DECISION_EQUALITY_ABS_TOLERANCE_SECONDS:
            expected_recommendation = PitDecisionRecommendation.STAY_OUT
    if str(decision["recommendation"]) != expected_recommendation.value:
        raise ConcurrentSimulationReportingError(
            "stored recommendation differs from scenario evidence"
        )
    expected_stable = (
        expected_recommendation
        is not PitDecisionRecommendation.NO_CLEAR_ADVANTAGE
    )
    if _strict_bool(decision["recommendation_is_stable"]) != expected_stable:
        raise ConcurrentSimulationReportingError(
            "stored recommendation stability differs from scenario evidence"
        )


def _validate_residual_coordinates(
    scenarios: pd.DataFrame,
    decision: pd.Series,
) -> None:
    first_lap = _integer_value(decision["decision_lap"], "decision_lap")
    total_laps = _integer_value(decision["total_laps"], "total_laps")
    expected_laps = list(range(first_lap, total_laps + 1))
    for index, encoded in enumerate(scenarios["lap_time_residual_z_json"]):
        values = _json_list(encoded, "lap_time_residual_z_json")
        laps: list[int] = []
        for item in values:
            if not isinstance(item, list) or len(item) != 2:
                raise ConcurrentSimulationReportingError(
                    "stored residual coordinate must contain [lap, z] pairs"
                )
            laps.append(_integer_value(item[0], "residual lap"))
            _finite(item[1], "residual z")
        if laps != expected_laps:
            raise ConcurrentSimulationReportingError(
                f"stored residual laps differ at scenario {index}"
            )


def _validate_benchmark_table(
    benchmarks: pd.DataFrame,
    provenance: ConcurrentSimulationReportProvenance,
) -> None:
    expected_rows = len(provenance.scenario_counts) * (
        1 + len(provenance.worker_counts)
    )
    if len(benchmarks) != expected_rows:
        raise ConcurrentSimulationReportingError(
            "benchmark row count differs from the declared scaling grid"
        )
    if set(benchmarks["benchmark_id"].astype(str)) != {provenance.benchmark_id}:
        raise ConcurrentSimulationReportingError(
            "benchmark identity differs from provenance"
        )
    for scenario_count in provenance.scenario_counts:
        group = benchmarks.loc[
            pd.to_numeric(benchmarks["scenario_count"]).eq(scenario_count)
        ]
        sequential = group.loc[
            group["execution_mode"].eq(BenchmarkExecutionMode.SEQUENTIAL.value)
        ]
        if len(sequential) != 1:
            raise ConcurrentSimulationReportingError(
                "benchmark population must contain one sequential baseline"
            )
        baseline_duration = _validate_benchmark_row(
            sequential.iloc[0],
            scenario_count=scenario_count,
            repetitions=provenance.repetitions,
            baseline_duration=None,
        )
        concurrent = group.loc[
            group["execution_mode"].eq(BenchmarkExecutionMode.CONCURRENT.value)
        ].sort_values("max_workers")
        workers = tuple(
            _integer_value(value, "max_workers")
            for value in concurrent["max_workers"]
        )
        if workers != provenance.worker_counts:
            raise ConcurrentSimulationReportingError(
                "benchmark worker grid differs from provenance"
            )
        for _, row in concurrent.iterrows():
            _validate_benchmark_row(
                row,
                scenario_count=scenario_count,
                repetitions=provenance.repetitions,
                baseline_duration=baseline_duration,
            )


def _validate_benchmark_row(
    row: pd.Series,
    *,
    scenario_count: int,
    repetitions: int,
    baseline_duration: float | None,
) -> float:
    durations = tuple(
        _finite_positive(value, "benchmark duration")
        for value in _json_list(
            row["durations_seconds_json"],
            "durations_seconds_json",
        )
    )
    if len(durations) != repetitions:
        raise ConcurrentSimulationReportingError(
            "benchmark duration count differs from repetitions"
        )
    if _integer_value(row["repetitions"], "repetitions") != repetitions:
        raise ConcurrentSimulationReportingError(
            "benchmark repetitions differ from provenance"
        )
    measured_median = median(durations)
    _close(row["median_duration_seconds"], measured_median, "benchmark median")
    _close(
        row["scenarios_per_second"],
        scenario_count / measured_median,
        "benchmark throughput",
    )
    if baseline_duration is None:
        if not pd.isna(row["max_workers"]):
            raise ConcurrentSimulationReportingError(
                "sequential benchmark cannot declare workers"
            )
        _close(row["speedup_vs_sequential"], 1.0, "sequential speedup")
        if not pd.isna(row["worker_efficiency"]):
            raise ConcurrentSimulationReportingError(
                "sequential benchmark cannot declare worker efficiency"
            )
        return measured_median
    workers = _integer_value(row["max_workers"], "max_workers")
    speedup = baseline_duration / measured_median
    _close(row["speedup_vs_sequential"], speedup, "benchmark speedup")
    _close(row["worker_efficiency"], speedup / workers, "worker efficiency")
    return measured_median


def _decision_id(evaluation: SequentialScenarioEvaluation) -> str:
    state = evaluation.batch.request.decision_request.state
    target = evaluation.batch.request.decision_request.target_compound.value
    return (
        f"{state.season}-{state.session_id}-{state.driver}-"
        f"{state.current_lap}-{target}"
    ).lower()


def _preference(advantage: float) -> str:
    if advantage > DECISION_EQUALITY_ABS_TOLERANCE_SECONDS:
        return ScenarioPreference.PIT_NOW.value
    if advantage < -DECISION_EQUALITY_ABS_TOLERANCE_SECONDS:
        return ScenarioPreference.STAY_OUT.value
    return ScenarioPreference.TIE.value


def _exact_columns(
    frame: pd.DataFrame,
    expected: tuple[str, ...],
    name: str,
) -> None:
    if tuple(frame.columns) != expected:
        raise ConcurrentSimulationReportingError(
            f"{name} columns differ from the report contract"
        )


def _json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True)


def _json_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, str):
        raise ConcurrentSimulationReportingError(f"{field_name} must be JSON text")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as error:
        raise ConcurrentSimulationReportingError(
            f"{field_name} must contain valid JSON"
        ) from error
    if not isinstance(decoded, list):
        raise ConcurrentSimulationReportingError(
            f"{field_name} must contain a JSON array"
        )
    return decoded


def _require_finite(frame: pd.DataFrame, columns: tuple[str, ...]) -> None:
    for column in columns:
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.isna().any() or not values.map(math.isfinite).all():
            raise ConcurrentSimulationReportingError(
                f"{column} must contain finite numeric values"
            )


def _close(actual: object, expected: float, field_name: str) -> None:
    value = _finite(actual, field_name)
    if not math.isclose(value, expected, rel_tol=1e-12, abs_tol=1e-9):
        raise ConcurrentSimulationReportingError(
            f"{field_name} does not reconcile"
        )


def _finite(value: object, field_name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value,
        (int, float, np.integer, np.floating),
    ):
        raise ConcurrentSimulationReportingError(f"{field_name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ConcurrentSimulationReportingError(f"{field_name} must be finite")
    return normalized


def _finite_positive(value: object, field_name: str) -> float:
    normalized = _finite(value, field_name)
    if normalized <= 0:
        raise ConcurrentSimulationReportingError(f"{field_name} must be positive")
    return normalized


def _finite_non_negative(value: object, field_name: str) -> float:
    normalized = _finite(value, field_name)
    if normalized < 0:
        raise ConcurrentSimulationReportingError(
            f"{field_name} must be non-negative"
        )
    return normalized


def _integer_value(value: object, field_name: str) -> int:
    if isinstance(value, (bool, np.bool_)):
        raise ConcurrentSimulationReportingError(f"{field_name} must be an integer")
    if isinstance(value, (int, np.integer)):
        return int(value)
    normalized = _finite(value, field_name)
    integer = int(normalized)
    if normalized != integer:
        raise ConcurrentSimulationReportingError(f"{field_name} must be an integer")
    return integer


def _integer_at_least(value: object, field_name: str, minimum: int) -> int:
    integer = _integer_value(value, field_name)
    if integer < minimum:
        raise ConcurrentSimulationReportingError(
            f"{field_name} must be at least {minimum}"
        )
    return integer


def _positive_integer(value: object, field_name: str) -> int:
    return _integer_at_least(value, field_name, 1)


def _increasing_positive_tuple(value: object, field_name: str) -> None:
    if not isinstance(value, tuple) or not value:
        raise ConcurrentSimulationReportingError(
            f"{field_name} must be a non-empty tuple"
        )
    normalized = tuple(_positive_integer(item, field_name) for item in value)
    if normalized != tuple(sorted(set(normalized))):
        raise ConcurrentSimulationReportingError(
            f"{field_name} must be unique and increasing"
        )


def _strict_bool(value: object) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise ConcurrentSimulationReportingError(
            "recommendation_is_stable must be boolean"
        )
    return bool(value)


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConcurrentSimulationReportingError(
            f"{field_name} must not be blank"
        )
    return value.strip()
