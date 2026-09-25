"""Pydantic response schemas for the versioned public API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

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
        scenario_shares_are_correctness_probabilities=False,
        counterfactual_strategy_accuracy_is_proven=False,
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
