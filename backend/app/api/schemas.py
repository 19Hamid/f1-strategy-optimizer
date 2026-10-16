"""Pydantic response schemas for the versioned public API."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.api.analysis import StrategyAnalysisResult
from app.api.contracts import (
    API_ANALYSIS_SCOPE,
    API_CONTRACT_VERSION,
    API_OPTIMIZATION_OBJECTIVE,
    API_STRATEGY_COMPARISON,
    DEVELOPMENT_SEASONS,
    PROTECTED_EVALUATION_SEASON,
    SUPPORTED_EXECUTION_MODES,
    validate_api_contract,
)
from app.api.evidence import (
    DevelopmentEvidenceBundle,
    EvidenceArtifactKind,
)
from app.api.jobs import (
    DEFAULT_INTERACTIVE_SCENARIOS,
    MAXIMUM_INTERACTIVE_SCENARIOS,
    MAXIMUM_INTERACTIVE_WORKERS,
    MINIMUM_INTERACTIVE_SCENARIOS,
    JobSnapshot,
    JobStatus,
)
from app.api.reporting import ConcurrentSimulationSummary
from app.concurrent_simulation.aggregation import (
    MINIMUM_STABILITY_SCENARIO_COUNT,
)
from app.concurrent_simulation.contracts import (
    DEFAULT_SCENARIO_COUNT,
    MAXIMUM_SCENARIO_COUNT,
)
from app.optimizer.contracts import (
    PitDecisionAction,
    PitDecisionRecommendation,
)
from app.simulation import SIMULATION_RANDOM_SEED, DryCompound


class HealthResponse(BaseModel):
    """Minimal liveness response retained for deployment checks."""

    model_config = ConfigDict(frozen=True)

    status: Literal["healthy"] = "healthy"


class ApiErrorResponse(BaseModel):
    """Stable fail-closed API error payload."""

    model_config = ConfigDict(frozen=True)

    code: str
    message: str


class ScenarioLimitsResponse(BaseModel):
    """Public scenario-count limits inherited from Phase 9."""

    model_config = ConfigDict(frozen=True)

    minimum_for_stability: int
    default: int
    maximum: int


class ApiCapabilitiesResponse(BaseModel):
    """Machine-readable statement of supported V1 behavior and limits."""

    model_config = ConfigDict(frozen=True)

    api_contract_version: str
    analysis_scope: str
    strategy_comparison: str
    optimization_objective: str
    development_seasons: tuple[int, ...]
    protected_evaluation_season: int
    protected_evaluation_used_for_development: bool
    decision_actions: tuple[str, ...]
    recommendation_values: tuple[str, ...]
    execution_modes: tuple[str, ...]
    scenario_limits: ScenarioLimitsResponse
    interactive_scenario_limits: ScenarioLimitsResponse
    interactive_max_workers: int
    scenario_shares_are_correctness_probabilities: bool
    counterfactual_strategy_accuracy_is_proven: bool


class VerifiedEvidenceArtifactResponse(BaseModel):
    """Public identity of one independently verified artifact."""

    model_config = ConfigDict(frozen=True)

    kind: EvidenceArtifactKind
    identifier: str
    artifact_count: int
    verification_rows: int | None


class DevelopmentEvidenceResponse(BaseModel):
    """Complete Phase 6-9 integrity result for dashboard startup."""

    model_config = ConfigDict(frozen=True)

    status: Literal["valid"]
    artifacts: tuple[VerifiedEvidenceArtifactResponse, ...]
    protected_evaluation_rows: Literal[0]


class ConcurrentBenchmarkResponse(BaseModel):
    """Fastest measured concurrent path for the stored population."""

    model_config = ConfigDict(frozen=True)

    scenario_count: int
    workers: int
    median_duration_seconds: float
    scenarios_per_second: float
    speedup_vs_sequential: float
    worker_efficiency: float


class ConcurrentSimulationSummaryResponse(BaseModel):
    """Verified Phase 9 decision evidence safe for dashboard rendering."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    decision_id: str
    season: int
    session_id: str
    event_name: str
    driver: str
    team: str
    decision_lap: int
    total_laps: int
    remaining_laps: int
    current_compound: str
    target_compound: str
    pit_loss_seconds: float
    scenario_count: int
    root_seed: int
    shared_pace_scale_seconds: float
    pit_loss_scale_seconds: float
    lap_time_residual_scale_seconds: float
    pit_now_mean_seconds: float
    stay_out_mean_seconds: float
    advantage_mean_seconds: float
    advantage_p05_seconds: float
    advantage_median_seconds: float
    advantage_p95_seconds: float
    pit_now_scenario_share: float
    stay_out_scenario_share: float
    tie_scenario_share: float
    recommendation: PitDecisionRecommendation
    recommendation_is_stable: bool
    protected_evaluation_rows: Literal[0]
    fastest_concurrent_benchmark: ConcurrentBenchmarkResponse
    scenario_shares_are_correctness_probabilities: Literal[False]


class HistoricalDecisionRequest(BaseModel):
    """Select one recorded Phase 8 development decision without raw features."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    season: Literal[2022, 2023, 2024]
    session_id: str = Field(pattern=r"^20\d{2}-\d{2}-R$")
    driver: str = Field(pattern=r"^[A-Z]{3}$")
    decision_lap: int = Field(ge=1)
    target_compound: DryCompound


class HistoricalDecisionOptionResponse(HistoricalDecisionRequest):
    """One verified browseable Phase 8 decision and its race labels."""

    event_name: str
    driver_name: str
    team: str
    total_laps: int
    current_compound: DryCompound


class HistoricalDecisionCatalogResponse(BaseModel):
    """Browseable development decisions backed by verified report rows."""

    model_config = ConfigDict(frozen=True)

    decisions: tuple[HistoricalDecisionOptionResponse, ...]


class PairedJobRequestBody(HistoricalDecisionRequest):
    """Resource-bounded paired scenario request over a recorded decision."""

    scenario_count: StrictInt = Field(
        default=DEFAULT_INTERACTIVE_SCENARIOS,
        ge=MINIMUM_INTERACTIVE_SCENARIOS,
        le=MAXIMUM_INTERACTIVE_SCENARIOS,
    )
    root_seed: StrictInt = Field(
        default=SIMULATION_RANDOM_SEED, ge=0, le=2**32 - 1
    )
    max_workers: StrictInt = Field(
        default=MAXIMUM_INTERACTIVE_WORKERS,
        ge=1,
        le=MAXIMUM_INTERACTIVE_WORKERS,
    )


class PairedAnalysisResponse(BaseModel):
    """Complete paired evidence with honest simulated-world labels."""

    model_config = ConfigDict(frozen=True)

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
    recommendation: PitDecisionRecommendation
    recommendation_is_stable: bool
    scenario_shares_are_correctness_probabilities: Literal[False]
    counterfactual_strategy_accuracy_is_proven: Literal[False]


class PairedJobResponse(BaseModel):
    """Progress and terminal output for one bounded in-process job."""

    model_config = ConfigDict(frozen=True)

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
    result: PairedAnalysisResponse | None
    error_code: str | None


class AnalysisLapResponse(BaseModel):
    """One predicted lap and explicit pit loss along an action trajectory."""

    model_config = ConfigDict(frozen=True)

    lap_number: int
    compound: DryCompound
    tyre_age_laps: int
    predicted_lap_time_seconds: float
    pit_loss_seconds: float
    total_lap_time_seconds: float
    elapsed_time_after_lap_seconds: float
    pitted_after_lap: bool


class AnalysisActionResponse(BaseModel):
    """A complete action cost with every contributing future lap."""

    model_config = ConfigDict(frozen=True)

    action: PitDecisionAction
    expected_remaining_time_seconds: float
    racing_time_seconds: float
    pit_loss_seconds: float
    laps: tuple[AnalysisLapResponse, ...]


class DeterministicAnalysisResponse(BaseModel):
    """Point comparison without scenario stability or confidence claims."""

    model_config = ConfigDict(frozen=True)

    mode: Literal["DETERMINISTIC"]
    season: int
    session_id: str
    event_name: str
    driver: str
    team: str
    decision_lap: int
    total_laps: int
    current_compound: DryCompound
    target_compound: DryCompound
    assumed_pit_loss_seconds: float
    pit_now: AnalysisActionResponse
    stay_out: AnalysisActionResponse
    pit_now_advantage_seconds: float
    recommendation: PitDecisionRecommendation
    recommendation_basis: Literal["POINT_ESTIMATE_ONLY"]
    recommendation_is_stable: Literal[False]
    uncertainty_evaluated: Literal[False]
    counterfactual_strategy_accuracy_is_proven: Literal[False]


def build_api_capabilities_response() -> ApiCapabilitiesResponse:
    """Build capabilities only after validating every published boundary."""
    validate_api_contract()
    return ApiCapabilitiesResponse(
        api_contract_version=API_CONTRACT_VERSION,
        analysis_scope=API_ANALYSIS_SCOPE,
        strategy_comparison=API_STRATEGY_COMPARISON,
        optimization_objective=API_OPTIMIZATION_OBJECTIVE,
        development_seasons=DEVELOPMENT_SEASONS,
        protected_evaluation_season=PROTECTED_EVALUATION_SEASON,
        protected_evaluation_used_for_development=False,
        decision_actions=tuple(action.value for action in PitDecisionAction),
        recommendation_values=tuple(
            recommendation.value
            for recommendation in PitDecisionRecommendation
        ),
        execution_modes=SUPPORTED_EXECUTION_MODES,
        scenario_limits=ScenarioLimitsResponse(
            minimum_for_stability=MINIMUM_STABILITY_SCENARIO_COUNT,
            default=DEFAULT_SCENARIO_COUNT,
            maximum=MAXIMUM_SCENARIO_COUNT,
        ),
        interactive_scenario_limits=ScenarioLimitsResponse(
            minimum_for_stability=MINIMUM_INTERACTIVE_SCENARIOS,
            default=DEFAULT_INTERACTIVE_SCENARIOS,
            maximum=MAXIMUM_INTERACTIVE_SCENARIOS,
        ),
        interactive_max_workers=MAXIMUM_INTERACTIVE_WORKERS,
        scenario_shares_are_correctness_probabilities=False,
        counterfactual_strategy_accuracy_is_proven=False,
    )


def build_deterministic_analysis_response(
    result: StrategyAnalysisResult,
) -> DeterministicAnalysisResponse:
    """Expose two complete trajectories without implying uncertainty evidence."""
    if result.scenarios is not None:
        raise ValueError("deterministic response cannot contain scenario evidence")
    request = result.comparison.request
    state = request.state

    def action_response(action: PitDecisionAction) -> AnalysisActionResponse:
        evaluation = (
            result.comparison.pit_now
            if action is PitDecisionAction.PIT_NOW
            else result.comparison.stay_out
        )
        simulation = evaluation.simulation
        return AnalysisActionResponse(
            action=action,
            expected_remaining_time_seconds=simulation.remaining_time_seconds,
            racing_time_seconds=simulation.racing_time_seconds,
            pit_loss_seconds=simulation.pit_loss_seconds,
            laps=tuple(
                AnalysisLapResponse(
                    lap_number=lap.transition.lap_number,
                    compound=lap.transition.start_compound,
                    tyre_age_laps=lap.transition.start_tyre_age_laps,
                    predicted_lap_time_seconds=(
                        lap.transition.predicted_lap_time_seconds
                    ),
                    pit_loss_seconds=lap.transition.pit_loss_seconds,
                    total_lap_time_seconds=lap.transition.total_lap_time_seconds,
                    elapsed_time_after_lap_seconds=(
                        lap.transition.elapsed_time_after_lap_seconds
                    ),
                    pitted_after_lap=lap.transition.pitted,
                )
                for lap in simulation.laps
            ),
        )

    return DeterministicAnalysisResponse(
        mode="DETERMINISTIC",
        season=state.season,
        session_id=state.session_id,
        event_name=state.event_name,
        driver=state.driver,
        team=state.team,
        decision_lap=state.current_lap,
        total_laps=state.total_laps,
        current_compound=state.current_compound,
        target_compound=request.target_compound,
        assumed_pit_loss_seconds=request.pit_loss.seconds,
        pit_now=action_response(PitDecisionAction.PIT_NOW),
        stay_out=action_response(PitDecisionAction.STAY_OUT),
        pit_now_advantage_seconds=result.comparison.pit_now_advantage_seconds,
        recommendation=result.recommendation,
        recommendation_basis="POINT_ESTIMATE_ONLY",
        recommendation_is_stable=False,
        uncertainty_evaluated=False,
        counterfactual_strategy_accuracy_is_proven=False,
    )


def build_paired_job_response(snapshot: JobSnapshot) -> PairedJobResponse:
    """Serialize only completed job evidence, never partial scenario results."""
    result = (
        PairedAnalysisResponse(
            **asdict(snapshot.result),
            scenario_shares_are_correctness_probabilities=False,
            counterfactual_strategy_accuracy_is_proven=False,
        )
        if snapshot.result is not None and snapshot.status is JobStatus.COMPLETED
        else None
    )
    return PairedJobResponse(
        job_id=snapshot.job_id,
        status=snapshot.status,
        season=snapshot.season,
        session_id=snapshot.session_id,
        driver=snapshot.driver,
        decision_lap=snapshot.decision_lap,
        target_compound=snapshot.target_compound,
        scenario_count=snapshot.scenario_count,
        root_seed=snapshot.root_seed,
        max_workers=snapshot.max_workers,
        completed_scenarios=snapshot.completed_scenarios,
        result=result,
        error_code=snapshot.error_code,
    )


def build_development_evidence_response(
    bundle: DevelopmentEvidenceBundle,
) -> DevelopmentEvidenceResponse:
    """Serialize verified artifact identities without exposing local paths."""
    return DevelopmentEvidenceResponse(
        status="valid",
        artifacts=tuple(
            VerifiedEvidenceArtifactResponse(
                kind=artifact.kind,
                identifier=artifact.identifier,
                artifact_count=artifact.artifact_count,
                verification_rows=artifact.verification_rows,
            )
            for artifact in bundle.artifacts
        ),
        protected_evaluation_rows=0,
    )


def build_concurrent_simulation_summary_response(
    summary: ConcurrentSimulationSummary,
) -> ConcurrentSimulationSummaryResponse:
    """Serialize the verified Phase 9 summary with honest evidence labels."""
    benchmark = summary.fastest_concurrent_benchmark
    return ConcurrentSimulationSummaryResponse(
        run_id=summary.run_id,
        decision_id=summary.decision_id,
        season=summary.season,
        session_id=summary.session_id,
        event_name=summary.event_name,
        driver=summary.driver,
        team=summary.team,
        decision_lap=summary.decision_lap,
        total_laps=summary.total_laps,
        remaining_laps=summary.remaining_laps,
        current_compound=summary.current_compound,
        target_compound=summary.target_compound,
        pit_loss_seconds=summary.pit_loss_seconds,
        scenario_count=summary.scenario_count,
        root_seed=summary.root_seed,
        shared_pace_scale_seconds=summary.shared_pace_scale_seconds,
        pit_loss_scale_seconds=summary.pit_loss_scale_seconds,
        lap_time_residual_scale_seconds=(
            summary.lap_time_residual_scale_seconds
        ),
        pit_now_mean_seconds=summary.pit_now_mean_seconds,
        stay_out_mean_seconds=summary.stay_out_mean_seconds,
        advantage_mean_seconds=summary.advantage_mean_seconds,
        advantage_p05_seconds=summary.advantage_p05_seconds,
        advantage_median_seconds=summary.advantage_median_seconds,
        advantage_p95_seconds=summary.advantage_p95_seconds,
        pit_now_scenario_share=summary.pit_now_scenario_share,
        stay_out_scenario_share=summary.stay_out_scenario_share,
        tie_scenario_share=summary.tie_scenario_share,
        recommendation=summary.recommendation,
        recommendation_is_stable=summary.recommendation_is_stable,
        protected_evaluation_rows=summary.protected_evaluation_rows,
        fastest_concurrent_benchmark=ConcurrentBenchmarkResponse(
            scenario_count=benchmark.scenario_count,
            workers=benchmark.workers,
            median_duration_seconds=benchmark.median_duration_seconds,
            scenarios_per_second=benchmark.scenarios_per_second,
            speedup_vs_sequential=benchmark.speedup_vs_sequential,
            worker_efficiency=benchmark.worker_efficiency,
        ),
        scenario_shares_are_correctness_probabilities=False,
    )
