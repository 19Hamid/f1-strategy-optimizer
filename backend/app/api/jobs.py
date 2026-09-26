"""Bounded cancellable in-process jobs for paired Phase 9 analysis."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import StrEnum
from threading import Event, Lock
from typing import Final
from uuid import uuid4

from app.api.analysis import AnalysisMode, StrategyAnalysisResult
from app.api.evidence import ApiEvidenceError
from app.api.historical import (
    AnalysisSelectionError,
    HistoricalDecisionKey,
    load_verified_historical_analysis,
)
from app.concurrent_simulation.aggregation import (
    SEQUENTIAL_AGGREGATOR_ID,
    ScenarioOutcome,
    SequentialScenarioEvaluation,
    evaluate_scenario_outcome,
)
from app.concurrent_simulation.calibration import UncertaintyCalibration
from app.concurrent_simulation.contracts import ScenarioBatch, ScenarioBatchRequest
from app.concurrent_simulation.scenarios import generate_scenario_batch
from app.optimizer.comparison import compare_pit_decision
from app.simulation import (
    SIMULATION_RANDOM_SEED,
    Phase6ModelAdapter,
    SimulationFeatureContext,
)

MINIMUM_INTERACTIVE_SCENARIOS: Final = 100
DEFAULT_INTERACTIVE_SCENARIOS: Final = 100
MAXIMUM_INTERACTIVE_SCENARIOS: Final = 1_000
MAXIMUM_INTERACTIVE_WORKERS: Final = 4
MAXIMUM_ACTIVE_JOBS: Final = 2
MAXIMUM_RETAINED_JOBS: Final = 16


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class JobQueueFullError(RuntimeError):
    """Both bounded worker slots are already occupied."""


class JobNotFoundError(LookupError):
    """The job id is unknown or its completed record was evicted."""


class JobCancelledError(RuntimeError):
    """The request was cancelled before a complete result was published."""


@dataclass(frozen=True, slots=True)
class PairedJobRequest:
    key: HistoricalDecisionKey
    scenario_count: int = DEFAULT_INTERACTIVE_SCENARIOS
    root_seed: int = SIMULATION_RANDOM_SEED
    max_workers: int = MAXIMUM_INTERACTIVE_WORKERS

    def __post_init__(self) -> None:
        if not isinstance(self.key, HistoricalDecisionKey):
            raise TypeError("key must be a HistoricalDecisionKey")
        for name, lower, upper in (
            (
                "scenario_count",
                MINIMUM_INTERACTIVE_SCENARIOS,
                MAXIMUM_INTERACTIVE_SCENARIOS,
            ),
            ("root_seed", 0, 2**32 - 1),
            ("max_workers", 1, MAXIMUM_INTERACTIVE_WORKERS),
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not lower <= value <= upper
            ):
                raise ValueError(f"{name} must be between {lower} and {upper}")


@dataclass(frozen=True, slots=True)
class PairedAnalysisSummary:
    """A compact complete result; per-scenario working data is not retained."""

    season: int
    session_id: str
    driver: str
    decision_lap: int
    target_compound: str
    scenario_count: int
    root_seed: int
    calibration_id: str
    point_advantage_seconds: float
    pit_now_mean_seconds: float
    stay_out_mean_seconds: float
    advantage_mean_seconds: float
    advantage_p05_seconds: float
    advantage_median_seconds: float
    advantage_p95_seconds: float
    pit_now_scenario_share: float
    stay_out_scenario_share: float
    tie_scenario_share: float
    recommendation: str
    recommendation_is_stable: bool

    @classmethod
    def from_analysis(cls, result: StrategyAnalysisResult) -> PairedAnalysisSummary:
        scenarios = result.scenarios
        if scenarios is None:
            raise ValueError("paired job requires complete scenario evidence")
        decision = result.comparison.request
        state = decision.state
        advantage = scenarios.advantage_distribution
        return cls(
            season=state.season,
            session_id=state.session_id,
            driver=state.driver,
            decision_lap=state.current_lap,
            target_compound=decision.target_compound.value,
            scenario_count=scenarios.scenario_count,
            root_seed=scenarios.batch.request.root_seed,
            calibration_id=scenarios.calibration.calibration_id,
            point_advantage_seconds=(
                result.comparison.pit_now_advantage_seconds
            ),
            pit_now_mean_seconds=scenarios.pit_now_distribution.mean,
            stay_out_mean_seconds=scenarios.stay_out_distribution.mean,
            advantage_mean_seconds=advantage.mean,
            advantage_p05_seconds=advantage.p05,
            advantage_median_seconds=advantage.median,
            advantage_p95_seconds=advantage.p95,
            pit_now_scenario_share=scenarios.pit_now_scenario_share,
            stay_out_scenario_share=scenarios.stay_out_scenario_share,
            tie_scenario_share=scenarios.tie_scenario_share,
            recommendation=result.recommendation.value,
            recommendation_is_stable=result.recommendation_is_stable,
        )


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    job_id: str
    status: JobStatus
    season: int
    session_id: str
    driver: str
    decision_lap: int
    target_compound: str
    scenario_count: int
    root_seed: int
    max_workers: int
    completed_scenarios: int
    result: PairedAnalysisSummary | None
    error_code: str | None


@dataclass(slots=True)
class _JobRecord:
    job_id: str
    request: PairedJobRequest
    status: JobStatus = JobStatus.QUEUED
    completed_scenarios: int = 0
    result: PairedAnalysisSummary | None = None
    error_code: str | None = None
    cancel: Event = field(default_factory=Event)
    future: Future[None] | None = None

    def snapshot(self) -> JobSnapshot:
        return JobSnapshot(
            job_id=self.job_id,
            status=self.status,
            season=self.request.key.season,
            session_id=self.request.key.session_id,
            driver=self.request.key.driver,
            decision_lap=self.request.key.decision_lap,
            target_compound=self.request.key.target_compound.value,
            scenario_count=self.request.scenario_count,
            root_seed=self.request.root_seed,
            max_workers=self.request.max_workers,
            completed_scenarios=self.completed_scenarios,
            result=self.result if self.status is JobStatus.COMPLETED else None,
            error_code=self.error_code if self.status is JobStatus.FAILED else None,
        )


class AnalysisJobManager:
    """Single active analysis worker with one waiting slot and bounded history."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._worker = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="phase10-analysis"
        )
        self._jobs: dict[str, _JobRecord] = {}
        self._closed = False

    def submit(self, request: PairedJobRequest) -> JobSnapshot:
        if not isinstance(request, PairedJobRequest):
            raise TypeError("request must be a PairedJobRequest")
        with self._lock:
            if self._closed:
                raise JobQueueFullError("analysis worker is shutting down")
            active = sum(
                item.status in {
                    JobStatus.QUEUED,
                    JobStatus.RUNNING,
                    JobStatus.CANCEL_REQUESTED,
                }
                for item in self._jobs.values()
            )
            if active >= MAXIMUM_ACTIVE_JOBS:
                raise JobQueueFullError("analysis queue is full")
            record = _JobRecord(job_id=uuid4().hex, request=request)
            self._jobs[record.job_id] = record
            record.future = self._worker.submit(self._run, record)
            self._trim_terminal_records()
            return record.snapshot()

    def status(self, job_id: str) -> JobSnapshot:
        with self._lock:
            return self._record(job_id).snapshot()

    def cancel(self, job_id: str) -> JobSnapshot:
        with self._lock:
            record = self._record(job_id)
            if record.status is JobStatus.QUEUED:
                record.cancel.set()
                if record.future is not None and record.future.cancel():
                    record.status = JobStatus.CANCELLED
                else:
                    record.status = JobStatus.CANCEL_REQUESTED
            elif record.status is JobStatus.RUNNING:
                record.cancel.set()
                record.status = JobStatus.CANCEL_REQUESTED
            return record.snapshot()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            for record in self._jobs.values():
                if record.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                    record.cancel.set()
                    if (
                        record.status is JobStatus.QUEUED
                        and record.future is not None
                        and record.future.cancel()
                    ):
                        record.status = JobStatus.CANCELLED
                    else:
                        record.status = JobStatus.CANCEL_REQUESTED
        self._worker.shutdown(wait=True, cancel_futures=True)

    def _record(self, job_id: str) -> _JobRecord:
        try:
            return self._jobs[job_id]
        except KeyError as error:
            raise JobNotFoundError("analysis job was not found") from error

    def _trim_terminal_records(self) -> None:
        for job_id, record in tuple(self._jobs.items()):
            if len(self._jobs) <= MAXIMUM_RETAINED_JOBS:
                break
            if record.status in {
                JobStatus.CANCELLED,
                JobStatus.COMPLETED,
                JobStatus.FAILED,
            }:
                del self._jobs[job_id]

    def _progress(self, record: _JobRecord, completed: int) -> None:
        with self._lock:
            record.completed_scenarios = completed

    def _run(self, record: _JobRecord) -> None:
        with self._lock:
            if record.cancel.is_set():
                record.status = JobStatus.CANCELLED
                return
            record.status = JobStatus.RUNNING
        try:
            inputs = load_verified_historical_analysis(record.request.key)
            if record.cancel.is_set():
                raise JobCancelledError("cancelled while verifying evidence")
            comparison = compare_pit_decision(
                inputs.decision,
                context=inputs.context,
                adapter=inputs.adapter,
            )
            batch = generate_scenario_batch(
                ScenarioBatchRequest(
                    inputs.decision,
                    scenario_count=record.request.scenario_count,
                    root_seed=record.request.root_seed,
                )
            )
            evaluation = _evaluate_cancellable_batch(
                batch,
                calibration=inputs.calibration,
                context=inputs.context,
                adapter=inputs.adapter,
                max_workers=record.request.max_workers,
                cancel=record.cancel,
                progress=lambda completed: self._progress(record, completed),
            )
            summary = PairedAnalysisSummary.from_analysis(
                StrategyAnalysisResult(
                    AnalysisMode.PAIRED_SCENARIO,
                    comparison,
                    evaluation,
                )
            )
            with self._lock:
                if record.cancel.is_set():
                    record.status = JobStatus.CANCELLED
                else:
                    record.result = summary
                    record.status = JobStatus.COMPLETED
        except JobCancelledError:
            with self._lock:
                record.status = JobStatus.CANCELLED
        except (AnalysisSelectionError, ApiEvidenceError) as error:
            with self._lock:
                if record.cancel.is_set():
                    record.status = JobStatus.CANCELLED
                else:
                    record.error_code = (
                        "DECISION_NOT_AVAILABLE"
                        if isinstance(error, AnalysisSelectionError)
                        else "EVIDENCE_UNAVAILABLE"
                    )
                    record.status = JobStatus.FAILED
        except Exception:
            with self._lock:
                if record.cancel.is_set():
                    record.status = JobStatus.CANCELLED
                else:
                    record.error_code = "ANALYSIS_FAILED"
                    record.status = JobStatus.FAILED


def _evaluate_cancellable_batch(
    batch: ScenarioBatch,
    *,
    calibration: UncertaintyCalibration,
    context: SimulationFeatureContext,
    adapter: Phase6ModelAdapter,
    max_workers: int,
    cancel: Event,
    progress: Callable[[int], None],
) -> SequentialScenarioEvaluation:
    """Evaluate ordered paired outcomes in small cancellable work chunks."""
    size = batch.request.scenario_count
    ordered: list[ScenarioOutcome | None] = [None] * size
    chunk_size = max_workers * 2
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for start in range(0, size, chunk_size):
            if cancel.is_set():
                raise JobCancelledError("scenario job cancelled")
            end = min(start + chunk_size, size)
            futures = {
                pool.submit(
                    evaluate_scenario_outcome,
                    batch,
                    scenario_index=index,
                    calibration=calibration,
                    context=context,
                    adapter=adapter,
                ): index
                for index in range(start, end)
            }
            for future in as_completed(futures):
                if cancel.is_set():
                    for pending in futures:
                        pending.cancel()
                    raise JobCancelledError("scenario job cancelled")
                index = futures[future]
                outcome = future.result()
                if outcome.scenario_index != index:
                    raise RuntimeError("scenario worker returned the wrong index")
                ordered[index] = outcome
            progress(end)
    if cancel.is_set():
        raise JobCancelledError("scenario job cancelled")
    return SequentialScenarioEvaluation(
        batch=batch,
        calibration=calibration,
        aggregator_id=SEQUENTIAL_AGGREGATOR_ID,
        outcomes=tuple(item for item in ordered if item is not None),
    )


_manager_lock = Lock()
_manager: AnalysisJobManager | None = None


def get_job_manager() -> AnalysisJobManager:
    """Return one per-process manager; deployment must use one API worker."""
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = AnalysisJobManager()
        return _manager


def shutdown_job_manager() -> None:
    """Cancel active work and allow a later app lifespan to start fresh."""
    global _manager
    with _manager_lock:
        manager, _manager = _manager, None
    if manager is not None:
        manager.close()
