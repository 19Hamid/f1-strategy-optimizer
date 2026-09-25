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
