"""Run the complete Phase 9 audit on verified development evidence."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import fmean
from time import perf_counter
from typing import Final

import pandas as pd

from app.cleaning.integrity import verify_processed_partition
from app.cleaning.paths import ProcessedDataPaths
from app.concurrent_simulation.aggregation import (
    SequentialScenarioEvaluation,
    evaluate_scenario_batch_sequentially,
)
from app.concurrent_simulation.benchmark import (
    DEFAULT_BENCHMARK_REPETITIONS,
    DEFAULT_BENCHMARK_SCENARIO_COUNTS,
    DEFAULT_BENCHMARK_WORKER_COUNTS,
    ScenarioScalingBenchmark,
    benchmark_scenario_scaling,
)
from app.concurrent_simulation.calibration import (
    UNCERTAINTY_CALIBRATION_METHOD_ID,
    PitLossRangeObservation,
    ReplayLapErrorObservation,
    UncertaintyCalibration,
    calibrate_uncertainty,
)
from app.concurrent_simulation.contracts import (
    CONCURRENT_SIMULATION_CONTRACT_VERSION,
    SCENARIO_GENERATOR_ID,
    ScenarioBatchRequest,
)
from app.concurrent_simulation.executor import CONCURRENT_EXECUTOR_ID
from app.concurrent_simulation.reporting import (
    ConcurrentSimulationReportProvenance,
    build_concurrent_simulation_report,
    runtime_concurrent_dependency_versions,
    runtime_concurrent_machine_identity,
)
from app.concurrent_simulation.scenarios import generate_scenario_batch
from app.concurrent_simulation.storage import (
    ConcurrentSimulationReportPaths,
    ConcurrentSimulationReportVerification,
    verify_concurrent_simulation_report,
    write_concurrent_simulation_report,
)
from app.datasets.contracts import (
    DATASET_CONTRACT_VERSION,
    DEVELOPMENT_SEASONS,
    EXPECTED_DEVELOPMENT_TOTALS,
    PROTECTED_EVALUATION_SEASON,
)
from app.datasets.integrity import verify_complete_dataset
from app.datasets.paths import DatasetPaths
from app.ml import MODEL_CONTRACT_VERSION, ModelArtifactPaths
from app.optimizer import OPTIMIZER_CONTRACT_VERSION
from app.optimizer.audit import (
    OptimizerAuditCandidate,
    build_session_optimizer_audit_candidates,
)
from app.optimizer.storage import OptimizerReportPaths, verify_optimizer_report
from app.pipeline import SessionKey
from app.pipeline.serialization import (
    read_json_document,
    read_parquet_table,
    sha256_file,
)
from app.simulation import (
    AUDIT_PIT_LOSS_SECONDS,
    SIMULATION_CONTRACT_VERSION,
    SIMULATION_RANDOM_SEED,
    CircuitPitLossProfile,
    Phase6ModelAdapter,
    PitLossRegistry,
    PitLossSource,
    SimulationReportPaths,
    verify_simulation_report,
)

ProgressCallback = Callable[[str], None]
CENTRAL_90_NORMAL_QUANTILE: Final = 1.6448536269514722
PHASE_9_AUDIT_CALIBRATION_ID: Final = "phase-9-final-audit-uncertainty"
_PIT_LOSS_EVIDENCE: Final = (
    "controlled Phase 9 development uncertainty assumption inherited from "
    "the Phase 7 and Phase 8 audits; not an observed net pit-loss label"
)


class ConcurrentSimulationAuditError(RuntimeError):
    """Raised when the real Phase 9 development audit cannot pass safely."""


@dataclass(frozen=True, slots=True)
class DevelopmentCoverageSummary:
    """In-sample development coverage for calibrated replay perturbations."""

    central_probability: float
    normal_quantile: float
    replay_mean_count: int
    replay_mean_covered: int
    replay_mean_coverage_rate: float
    replay_mean_interval_half_width_seconds: float
    lap_residual_count: int
    lap_residual_covered: int
    lap_residual_coverage_rate: float
    lap_residual_interval_half_width_seconds: float

    def __post_init__(self) -> None:
        if not math.isclose(self.central_probability, 0.90):
            raise ConcurrentSimulationAuditError(
                "development coverage must describe a central 90% interval"
            )
        _positive(self.normal_quantile, "normal_quantile")
        for prefix in ("replay_mean", "lap_residual"):
            count = _positive_integer(
                getattr(self, f"{prefix}_count"),
                f"{prefix}_count",
            )
            covered = _integer_between(
                getattr(self, f"{prefix}_covered"),
                f"{prefix}_covered",
                minimum=0,
                maximum=count,
            )
            rate = _finite_non_negative(
                getattr(self, f"{prefix}_coverage_rate"),
                f"{prefix}_coverage_rate",
            )
            if rate > 1 or not math.isclose(
                rate,
                covered / count,
                abs_tol=1e-12,
            ):
                raise ConcurrentSimulationAuditError(
                    f"{prefix}_coverage_rate does not reconcile"
                )
            _positive(
                getattr(self, f"{prefix}_interval_half_width_seconds"),
                f"{prefix}_interval_half_width_seconds",
            )


@dataclass(frozen=True, slots=True)
class ConcurrentSimulationAuditResult:
    """Verified Phase 9 calibration, benchmark and immutable evidence."""

    report_paths: ConcurrentSimulationReportPaths
    report_verification: ConcurrentSimulationReportVerification
    calibration: UncertaintyCalibration
    coverage: DevelopmentCoverageSummary
    benchmark: ScenarioScalingBenchmark
    evaluation: SequentialScenarioEvaluation
    audited_development_sessions: int
    candidate_development_sessions: int
    reconciled_historical_decisions: int
    representative_decision_key: tuple[int, str, str, int, str]
    representative_remaining_laps: int
    protected_evaluation_rows: int


def run_development_concurrent_simulation_audit(
    *,
    datasets_root: Path,
    processed_root: Path,
    artifacts_root: Path,
    run_id: str,
    model_artifact_id: str,
    simulation_run_id: str,
    optimizer_run_id: str,
    progress: ProgressCallback | None = None,
) -> ConcurrentSimulationAuditResult:
    """Calibrate, benchmark and store Phase 9 development-only evidence."""
    dataset_paths = DatasetPaths(Path(datasets_root))
    processed_paths = ProcessedDataPaths(Path(processed_root))
    artifacts_root = Path(artifacts_root)
    report_paths = ConcurrentSimulationReportPaths(artifacts_root, run_id)
    if report_paths.root.exists():
        raise ConcurrentSimulationAuditError(
            f"concurrent simulation report already exists: {report_paths.root}"
        )

    _announce(progress, "Verifying the 68-race dataset catalog and partitions")
    dataset_catalog = _load_catalog(
        dataset_paths.catalog,
        protected_root=(
            dataset_paths.version_root
            / f"season={PROTECTED_EVALUATION_SEASON}"
        ),
        source="dataset",
    )
    session_keys = _session_keys(dataset_catalog)
    dataset_integrity = verify_complete_dataset(dataset_paths, session_keys)
    if not dataset_integrity.is_valid:
        detail = "; ".join(
            issue.message for issue in dataset_integrity.issues[:5]
        )
        raise ConcurrentSimulationAuditError(
            f"dataset integrity failed: {detail}"
        )

    _announce(progress, "Verifying the matching processed-race catalog")
    processed_catalog = _load_catalog(
        processed_paths.catalog,
        protected_root=(
            processed_paths.version_root
            / f"season={PROTECTED_EVALUATION_SEASON}"
        ),
        source="processed",
    )
    _reconcile_catalogs(dataset_catalog, processed_catalog)
    protected_rows = _protected_row_count(
        (dataset_catalog, "season"),
        (processed_catalog, "season"),
    )
    if protected_rows:
        raise ConcurrentSimulationAuditError("protected 2025 rows entered Phase 9")

    dataset_build_identifier = sha256_file(dataset_paths.catalog)
    model_paths = ModelArtifactPaths(artifacts_root, model_artifact_id)
    _announce(progress, "Loading the verified final Phase 6 model artifact")
    adapter = Phase6ModelAdapter.from_paths(model_paths)
    model_provenance = adapter.artifact.provenance
    if model_provenance.dataset_contract_version != DATASET_CONTRACT_VERSION:
        raise ConcurrentSimulationAuditError(
            "model and concurrent simulation dataset contracts differ"
        )
    if model_provenance.dataset_build_identifier != dataset_build_identifier:
        raise ConcurrentSimulationAuditError(
            "model artifact was not fitted from the verified dataset catalog"
        )

    _announce(progress, "Loading verified Phase 7 replay evidence")
    simulation_paths = SimulationReportPaths(artifacts_root, simulation_run_id)
    simulation_verification = verify_simulation_report(simulation_paths)
    if not simulation_verification.valid:
        detail = "; ".join(simulation_verification.issues[:5])
        raise ConcurrentSimulationAuditError(
            f"Phase 7 simulation report integrity failed: {detail}"
        )
    _verify_upstream_provenance(
        read_json_document(simulation_paths.root / "provenance.json"),
        source="Phase 7",
        model_artifact_id=model_artifact_id,
        dataset_build_identifier=dataset_build_identifier,
    )
    replay_errors = build_replay_error_observations(
        replays=read_parquet_table(simulation_paths.root / "replays.parquet"),
        trajectories=read_parquet_table(
            simulation_paths.root / "trajectories.parquet"
        ),
    )
    pit_loss_ranges = build_pit_loss_range_observations(processed_catalog)
    calibration = calibrate_uncertainty(
        calibration_id=PHASE_9_AUDIT_CALIBRATION_ID,
        replay_lap_errors=replay_errors,
        pit_loss_ranges=pit_loss_ranges,
        evidence=(
            "Phase 7 immutable development replay signed lap errors decomposed "
            "into replay-level and within-replay scales; declared development "
            "circuit pit-loss ranges provide the pit-loss scale. These are "
            "perturbation scales, not probabilities of strategy correctness."
        ),
    )
    if calibration.training_seasons != DEVELOPMENT_SEASONS:
        raise ConcurrentSimulationAuditError(
            "uncertainty calibration does not cover every development season"
        )
    coverage = summarize_development_coverage(
        replay_lap_errors=replay_errors,
        calibration=calibration,
    )

    _announce(progress, "Loading verified Phase 8 optimizer evidence")
    optimizer_paths = OptimizerReportPaths(artifacts_root, optimizer_run_id)
    optimizer_verification = verify_optimizer_report(optimizer_paths)
    if not optimizer_verification.valid:
        detail = "; ".join(optimizer_verification.issues[:5])
        raise ConcurrentSimulationAuditError(
            f"Phase 8 optimizer report integrity failed: {detail}"
        )
    _verify_upstream_provenance(
        read_json_document(optimizer_paths.root / "provenance.json"),
        source="Phase 8",
        model_artifact_id=model_artifact_id,
        dataset_build_identifier=dataset_build_identifier,
    )
    optimizer_decisions = read_parquet_table(
        optimizer_paths.root / "decisions.parquet"
    )

    _announce(
        progress,
        "Reconstructing the Phase 8 historical decision population",
    )
    registry = _pit_loss_registry(processed_catalog)
    candidates: list[OptimizerAuditCandidate] = []
    for index, session_key in enumerate(session_keys, start=1):
        integrity = verify_processed_partition(processed_paths, session_key)
        if not integrity.is_valid:
            detail = "; ".join(issue.message for issue in integrity.issues[:5])
            raise ConcurrentSimulationAuditError(
                f"processed integrity failed for {session_key.identifier}: {detail}"
            )
        decision_rows = read_parquet_table(
            dataset_paths.for_session(session_key).decision_rows
        )
        processed_laps = read_parquet_table(
            processed_paths.for_session(session_key).laps
        )
        protected_rows += _protected_row_count(
            (decision_rows, "season"),
            (processed_laps, "Season"),
        )
        candidates.extend(
            build_session_optimizer_audit_candidates(
                session_key=session_key,
                decision_rows=decision_rows,
                processed_laps=processed_laps,
                pit_loss_registry=registry,
            )
        )
        if index % 10 == 0 or index == len(session_keys):
            _announce(
                progress,
                f"Scanned {index}/{len(session_keys)} development races",
            )
    if protected_rows:
        raise ConcurrentSimulationAuditError("protected 2025 rows entered Phase 9")

    candidate_tuple = tuple(candidates)
    reconcile_optimizer_candidates(
        candidates=candidate_tuple,
        optimizer_decisions=optimizer_decisions,
    )
    representative = select_representative_candidate(candidate_tuple)
    state = representative.request.state
    candidate_sessions = len(
        {
            (candidate.request.state.season, candidate.request.state.session_id)
            for candidate in candidate_tuple
        }
    )

    _announce(
        progress,
        "Benchmarking the deterministic median-horizon Phase 8 decision",
    )
    request = ScenarioBatchRequest(
        decision_request=representative.request,
        scenario_count=DEFAULT_BENCHMARK_SCENARIO_COUNTS[-1],
        root_seed=SIMULATION_RANDOM_SEED,
    )
    started = perf_counter()
    benchmark = benchmark_scenario_scaling(
        request,
        calibration=calibration,
        context=representative.context,
        adapter=adapter,
        scenario_counts=DEFAULT_BENCHMARK_SCENARIO_COUNTS,
        worker_counts=DEFAULT_BENCHMARK_WORKER_COUNTS,
        repetitions=DEFAULT_BENCHMARK_REPETITIONS,
        progress=progress,
    )
    _announce(
        progress,
        "Evaluating the largest scenario population for immutable storage",
    )
    largest_batch = generate_scenario_batch(
        replace(request, scenario_count=benchmark.scenario_counts[-1])
    )
    evaluation = evaluate_scenario_batch_sequentially(
        largest_batch,
        calibration=calibration,
        context=representative.context,
        adapter=adapter,
    )
    execution_duration = perf_counter() - started
    runtime_platform, runtime_machine, runtime_processor, cpu_count = (
        runtime_concurrent_machine_identity()
    )
    worker_counts = tuple(
        measurement.max_workers
        for measurement in benchmark.results[0].concurrent_measurements
    )
    if any(worker is None for worker in worker_counts):
        raise ConcurrentSimulationAuditError(
            "concurrent benchmark worker identity is incomplete"
        )
    provenance = ConcurrentSimulationReportProvenance(
        concurrent_simulation_contract_version=(
            CONCURRENT_SIMULATION_CONTRACT_VERSION
        ),
        optimizer_contract_version=OPTIMIZER_CONTRACT_VERSION,
        simulation_contract_version=SIMULATION_CONTRACT_VERSION,
        model_contract_version=MODEL_CONTRACT_VERSION,
        model_artifact_id=model_artifact_id,
        dataset_contract_version=DATASET_CONTRACT_VERSION,
        dataset_build_identifier=dataset_build_identifier,
        calibration_id=calibration.calibration_id,
        calibration_method_id=UNCERTAINTY_CALIBRATION_METHOD_ID,
        scenario_generator_id=SCENARIO_GENERATOR_ID,
        sequential_aggregator_id=evaluation.aggregator_id,
        concurrent_executor_id=CONCURRENT_EXECUTOR_ID,
        benchmark_id=benchmark.benchmark_id,
        development_sessions=len(session_keys),
        protected_evaluation_rows=protected_rows,
        root_seed=request.root_seed,
        scenario_counts=benchmark.scenario_counts,
        worker_counts=tuple(int(worker) for worker in worker_counts),
        repetitions=benchmark.results[0].repetitions,
        dependency_versions=runtime_concurrent_dependency_versions(),
        runtime_platform=runtime_platform,
        runtime_machine=runtime_machine,
        runtime_processor=runtime_processor,
        logical_cpu_count=cpu_count,
        execution_duration_seconds=execution_duration,
    )
    _announce(progress, "Writing and reloading immutable Phase 9 evidence")
    tables = build_concurrent_simulation_report(
        evaluation=evaluation,
        benchmark=benchmark,
        provenance=provenance,
    )
    write_concurrent_simulation_report(paths=report_paths, tables=tables)
    report_verification = verify_concurrent_simulation_report(report_paths)
    report_verification.raise_for_errors()

    return ConcurrentSimulationAuditResult(
        report_paths=report_paths,
        report_verification=report_verification,
        calibration=calibration,
        coverage=coverage,
        benchmark=benchmark,
        evaluation=evaluation,
        audited_development_sessions=len(session_keys),
        candidate_development_sessions=candidate_sessions,
        reconciled_historical_decisions=len(candidate_tuple),
        representative_decision_key=representative.decision_key,
        representative_remaining_laps=(
            state.total_laps - state.current_lap + 1
        ),
        protected_evaluation_rows=protected_rows,
    )


def build_replay_error_observations(
    *,
    replays: pd.DataFrame,
    trajectories: pd.DataFrame,
) -> tuple[ReplayLapErrorObservation, ...]:
    """Reconstruct unique signed lap errors from verified Phase 7 tables."""
    _require_columns(
        replays,
        {"replay_id", "season"},
        source="Phase 7 replays",
    )
    _require_columns(
        trajectories,
        {"replay_id", "lap_number", "signed_lap_error_seconds"},
        source="Phase 7 trajectories",
    )
    replay_rows = replays.loc[:, ["replay_id", "season"]].copy()
    replay_rows["replay_id"] = replay_rows["replay_id"].astype(str)
    if replay_rows["replay_id"].eq("").any():
        raise ConcurrentSimulationAuditError("Phase 7 replay_id must not be blank")
    if replay_rows["replay_id"].duplicated().any():
        raise ConcurrentSimulationAuditError("Phase 7 replay IDs must be unique")
    replay_rows["season"] = _integer_series(replay_rows["season"], "season")
    season_by_replay = dict(
        zip(replay_rows["replay_id"], replay_rows["season"], strict=True)
    )
    trajectory_replays = trajectories["replay_id"].astype(str)
    if set(trajectory_replays) != set(season_by_replay):
        raise ConcurrentSimulationAuditError(
            "Phase 7 replay and trajectory identities differ"
        )
    lap_numbers = _integer_series(trajectories["lap_number"], "lap_number")
    errors = pd.to_numeric(
        trajectories["signed_lap_error_seconds"],
        errors="coerce",
    )
    if errors.isna().any() or not errors.map(math.isfinite).all():
        raise ConcurrentSimulationAuditError(
            "Phase 7 signed lap errors must be finite"
        )
    identities = tuple(zip(trajectory_replays, lap_numbers, strict=True))
    if len(identities) != len(set(identities)):
        raise ConcurrentSimulationAuditError(
            "Phase 7 replay-lap identities must be unique"
        )
    observations = tuple(
        ReplayLapErrorObservation(
            season=int(season_by_replay[replay_id]),
            replay_id=replay_id,
            lap_number=int(lap_number),
            signed_error_seconds=float(error),
        )
        for replay_id, lap_number, error in sorted(
            zip(trajectory_replays, lap_numbers, errors, strict=True),
            key=lambda item: (item[0], item[1]),
        )
    )
    if not observations:
        raise ConcurrentSimulationAuditError(
            "Phase 7 replay error population must not be empty"
        )
    return observations


def build_pit_loss_range_observations(
    catalog: pd.DataFrame,
) -> tuple[PitLossRangeObservation, ...]:
    """Create one declared development pit-loss range per season and event."""
    _require_columns(
        catalog,
        {"season", "event_name"},
        source="processed catalog",
    )
    low, nominal, high = AUDIT_PIT_LOSS_SECONDS
    identities = {
        (int(season), str(event_name).strip())
        for season, event_name in zip(
            _integer_series(catalog["season"], "season"),
            catalog["event_name"],
            strict=True,
        )
    }
    if not identities or any(not event_name for _, event_name in identities):
        raise ConcurrentSimulationAuditError(
            "processed catalog contains invalid pit-loss identities"
        )
    return tuple(
        PitLossRangeObservation(
            season=season,
            event_name=event_name,
            low_seconds=low,
            nominal_seconds=nominal,
            high_seconds=high,
        )
        for season, event_name in sorted(identities)
    )


def summarize_development_coverage(
    *,
    replay_lap_errors: tuple[ReplayLapErrorObservation, ...],
    calibration: UncertaintyCalibration,
) -> DevelopmentCoverageSummary:
    """Measure in-sample central-90% coverage of the fitted replay scales."""
    if not isinstance(replay_lap_errors, tuple) or not replay_lap_errors:
        raise ConcurrentSimulationAuditError(
            "replay_lap_errors must be a non-empty tuple"
        )
    if any(
        not isinstance(item, ReplayLapErrorObservation)
        for item in replay_lap_errors
    ):
        raise TypeError(
            "replay_lap_errors must contain ReplayLapErrorObservation values"
        )
    if not isinstance(calibration, UncertaintyCalibration):
        raise TypeError("calibration must be an UncertaintyCalibration")
    grouped: dict[str, list[float]] = defaultdict(list)
    for item in replay_lap_errors:
        grouped[item.replay_id].append(float(item.signed_error_seconds))
    replay_means = tuple(fmean(values) for values in grouped.values())
    lap_residuals = tuple(
        error - fmean(errors)
        for errors in grouped.values()
        for error in errors
    )
    replay_half_width = (
        CENTRAL_90_NORMAL_QUANTILE * calibration.shared_pace_scale_seconds
    )
    residual_half_width = (
        CENTRAL_90_NORMAL_QUANTILE
        * calibration.lap_time_residual_scale_seconds
    )
    replay_covered = sum(
        abs(value) <= replay_half_width for value in replay_means
    )
    residual_covered = sum(
        abs(value) <= residual_half_width for value in lap_residuals
    )
    return DevelopmentCoverageSummary(
        central_probability=0.90,
        normal_quantile=CENTRAL_90_NORMAL_QUANTILE,
        replay_mean_count=len(replay_means),
        replay_mean_covered=replay_covered,
        replay_mean_coverage_rate=replay_covered / len(replay_means),
        replay_mean_interval_half_width_seconds=replay_half_width,
        lap_residual_count=len(lap_residuals),
        lap_residual_covered=residual_covered,
        lap_residual_coverage_rate=residual_covered / len(lap_residuals),
        lap_residual_interval_half_width_seconds=residual_half_width,
    )


def reconcile_optimizer_candidates(
    *,
    candidates: tuple[OptimizerAuditCandidate, ...],
    optimizer_decisions: pd.DataFrame,
) -> None:
    """Prove Phase 9 uses exactly the immutable Phase 8 decision population."""
    if not isinstance(candidates, tuple) or not candidates:
        raise ConcurrentSimulationAuditError(
            "optimizer candidates must be a non-empty tuple"
        )
    if any(not isinstance(item, OptimizerAuditCandidate) for item in candidates):
        raise TypeError("candidates must contain OptimizerAuditCandidate values")
    _require_columns(
        optimizer_decisions,
        {
            "season",
            "session_id",
            "driver",
            "decision_lap",
            "target_compound",
        },
        source="Phase 8 decisions",
    )
    expected = {candidate.decision_key for candidate in candidates}
    observed = {
        (
            int(season),
            str(session_id),
            str(driver),
            int(decision_lap),
            str(target_compound),
        )
        for season, session_id, driver, decision_lap, target_compound in zip(
            _integer_series(optimizer_decisions["season"], "season"),
            optimizer_decisions["session_id"],
            optimizer_decisions["driver"],
            _integer_series(
                optimizer_decisions["decision_lap"],
                "decision_lap",
            ),
            optimizer_decisions["target_compound"],
            strict=True,
        )
    }
    if len(expected) != len(candidates):
        raise ConcurrentSimulationAuditError(
            "reconstructed Phase 8 candidate identities are not unique"
        )
    if len(observed) != len(optimizer_decisions):
        raise ConcurrentSimulationAuditError(
            "stored Phase 8 decision identities are not unique"
        )
    if expected != observed:
        raise ConcurrentSimulationAuditError(
            "Phase 9 decision population differs from immutable Phase 8 evidence"
        )


def select_representative_candidate(
    candidates: tuple[OptimizerAuditCandidate, ...],
) -> OptimizerAuditCandidate:
    """Select the deterministic lower median by horizon, then decision key."""
    if not isinstance(candidates, tuple) or not candidates:
        raise ConcurrentSimulationAuditError(
            "representative selection requires candidates"
        )
    if any(not isinstance(item, OptimizerAuditCandidate) for item in candidates):
        raise TypeError("candidates must contain OptimizerAuditCandidate values")
    ranked = sorted(
        candidates,
        key=lambda item: (
            item.request.state.total_laps
            - item.request.state.current_lap
            + 1,
            item.decision_key,
        ),
    )
    return ranked[(len(ranked) - 1) // 2]


def _verify_upstream_provenance(
    provenance: object,
    *,
    source: str,
    model_artifact_id: str,
    dataset_build_identifier: str,
) -> None:
    if not isinstance(provenance, dict):
        raise ConcurrentSimulationAuditError(
            f"{source} provenance must be a JSON object"
        )
    expected = {
        "model_artifact_id": model_artifact_id,
        "dataset_contract_version": DATASET_CONTRACT_VERSION,
        "dataset_build_identifier": dataset_build_identifier,
        "protected_evaluation_rows": 0,
    }
    mismatches = [
        name for name, value in expected.items() if provenance.get(name) != value
    ]
    if mismatches:
        raise ConcurrentSimulationAuditError(
            f"{source} evidence differs from Phase 9 inputs: "
            + ", ".join(mismatches)
        )


def _pit_loss_registry(catalog: pd.DataFrame) -> PitLossRegistry:
    _require_columns(catalog, {"event_name"}, source="processed catalog")
    events = tuple(sorted(set(catalog["event_name"].astype(str))))
    if not events or any(not event.strip() for event in events):
        raise ConcurrentSimulationAuditError(
            "processed catalog contains invalid events"
        )
    low, nominal, high = AUDIT_PIT_LOSS_SECONDS
    return PitLossRegistry(
        tuple(
            CircuitPitLossProfile(
                event_name=event,
                low_seconds=low,
                nominal_seconds=nominal,
                high_seconds=high,
                source=PitLossSource.EXPLICIT_ASSUMPTION,
                evidence=_PIT_LOSS_EVIDENCE,
            )
            for event in events
        )
    )


def _load_catalog(
    path: Path,
    *,
    protected_root: Path,
    source: str,
) -> pd.DataFrame:
    if protected_root.exists():
        raise ConcurrentSimulationAuditError(
            f"protected evaluation directory exists: {protected_root}"
        )
    if not path.is_file():
        raise ConcurrentSimulationAuditError(
            f"{source} catalog does not exist: {path}"
        )
    catalog = read_parquet_table(path)
    _require_columns(
        catalog,
        {"season", "round_number", "session_type", "event_name"},
        source=f"{source} catalog",
    )
    return catalog


def _session_keys(catalog: pd.DataFrame) -> tuple[SessionKey, ...]:
    keys = tuple(
        sorted(
            (
                SessionKey(
                    season=int(row.season),
                    round_number=int(row.round_number),
                    session_type=str(row.session_type),
                )
                for row in catalog.itertuples(index=False)
            ),
            key=lambda key: (key.season, key.round_number, key.session_type),
        )
    )
    expected = EXPECTED_DEVELOPMENT_TOTALS.sessions
    if len(keys) != expected:
        raise ConcurrentSimulationAuditError(
            f"Phase 9 audit requires exactly {expected} sessions"
        )
    if len(set(keys)) != len(keys):
        raise ConcurrentSimulationAuditError(
            "dataset catalog contains duplicate sessions"
        )
    if any(key.season == PROTECTED_EVALUATION_SEASON for key in keys):
        raise ConcurrentSimulationAuditError(
            "dataset catalog contains protected 2025"
        )
    return keys


def _reconcile_catalogs(dataset: pd.DataFrame, processed: pd.DataFrame) -> None:
    columns = ["season", "round_number", "session_type", "event_name"]
    left = dataset.loc[:, columns].copy()
    right = processed.loc[:, columns].copy()
    for frame in (left, right):
        frame["season"] = pd.to_numeric(
            frame["season"],
            errors="raise",
        ).astype(int)
        frame["round_number"] = pd.to_numeric(
            frame["round_number"],
            errors="raise",
        ).astype(int)
        frame["session_type"] = frame["session_type"].astype(str)
        frame["event_name"] = frame["event_name"].astype(str)
        frame.sort_values(columns[:3], kind="stable", inplace=True)
        frame.reset_index(drop=True, inplace=True)
    try:
        pd.testing.assert_frame_equal(left, right)
    except AssertionError as error:
        raise ConcurrentSimulationAuditError(
            "dataset and processed catalogs describe different races"
        ) from error


def _protected_row_count(*frames: tuple[pd.DataFrame, str]) -> int:
    count = 0
    for frame, column in frames:
        if column not in frame.columns:
            raise ConcurrentSimulationAuditError(
                f"audit source is missing {column}"
            )
        seasons = pd.to_numeric(frame[column], errors="coerce")
        if seasons.isna().any():
            raise ConcurrentSimulationAuditError(
                "audit source contains invalid seasons"
            )
        count += int(seasons.eq(PROTECTED_EVALUATION_SEASON).sum())
    return count


def _require_columns(
    frame: pd.DataFrame,
    required: set[str],
    *,
    source: str,
) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"{source} must be a pandas DataFrame")
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ConcurrentSimulationAuditError(
            f"{source} is missing columns: {', '.join(missing)}"
        )


def _integer_series(values: pd.Series, field_name: str) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.isna().any() or not numeric.map(math.isfinite).all():
        raise ConcurrentSimulationAuditError(
            f"{field_name} must contain finite integers"
        )
    if not numeric.mod(1).eq(0).all():
        raise ConcurrentSimulationAuditError(
            f"{field_name} must contain finite integers"
        )
    return numeric.astype("int64")


def _positive(value: object, field_name: str) -> float:
    normalized = _finite_non_negative(value, field_name)
    if normalized <= 0:
        raise ConcurrentSimulationAuditError(f"{field_name} must be positive")
    return normalized


def _finite_non_negative(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConcurrentSimulationAuditError(f"{field_name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ConcurrentSimulationAuditError(
            f"{field_name} must be finite and non-negative"
        )
    return normalized


def _positive_integer(value: object, field_name: str) -> int:
    return _integer_between(value, field_name, minimum=1, maximum=2**63 - 1)


def _integer_between(
    value: object,
    field_name: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        raise ConcurrentSimulationAuditError(
            f"{field_name} must be an integer between {minimum} and {maximum}"
        )
    return value


def _announce(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)
