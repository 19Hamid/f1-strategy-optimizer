"""Frozen public API boundaries for the Phase 10 dashboard."""

from __future__ import annotations

from typing import Final

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

API_CONTRACT_VERSION: Final = "1.0"
API_PREFIX: Final = "/api/v1"
API_ANALYSIS_SCOPE: Final = "CONTROLLED_DRY_GREEN_FLAG"
API_STRATEGY_COMPARISON: Final = "PIT_NOW_VS_ONE_LAP_STAY_OUT"
API_OPTIMIZATION_OBJECTIVE: Final = "EXPECTED_REMAINING_RACE_TIME"
DEVELOPMENT_SEASONS: Final = (2022, 2023, 2024)
PROTECTED_EVALUATION_SEASON: Final = 2025
SUPPORTED_EXECUTION_MODES: Final = (
    "DETERMINISTIC",
    "PAIRED_SCENARIO",
)


class ApiContractError(ValueError):
    """Raised when a public API boundary drifts from the frozen V1 scope."""


def validate_api_contract() -> None:
    """Assert identities and limits published to dashboard clients."""
    if API_CONTRACT_VERSION != "1.0":
        raise ApiContractError("API contract version changed")
    if API_PREFIX != "/api/v1":
        raise ApiContractError("API prefix changed")
    if API_ANALYSIS_SCOPE != "CONTROLLED_DRY_GREEN_FLAG":
        raise ApiContractError("analysis scope changed")
    if API_STRATEGY_COMPARISON != "PIT_NOW_VS_ONE_LAP_STAY_OUT":
        raise ApiContractError("strategy comparison changed")
    if API_OPTIMIZATION_OBJECTIVE != "EXPECTED_REMAINING_RACE_TIME":
        raise ApiContractError("optimization objective changed")
    if DEVELOPMENT_SEASONS != (2022, 2023, 2024):
        raise ApiContractError("development-season boundary changed")
    if PROTECTED_EVALUATION_SEASON != 2025:
        raise ApiContractError("protected evaluation season changed")
    if PROTECTED_EVALUATION_SEASON in DEVELOPMENT_SEASONS:
        raise ApiContractError("protected season entered development scope")
    if set(PitDecisionAction) != {
        PitDecisionAction.PIT_NOW,
        PitDecisionAction.STAY_OUT,
    }:
        raise ApiContractError("public decision action set changed")
    if set(PitDecisionRecommendation) != {
        PitDecisionRecommendation.PIT_NOW,
        PitDecisionRecommendation.STAY_OUT,
        PitDecisionRecommendation.NO_CLEAR_ADVANTAGE,
    }:
        raise ApiContractError("public recommendation set changed")
    if MINIMUM_STABILITY_SCENARIO_COUNT != 100:
        raise ApiContractError("minimum stability population changed")
    if DEFAULT_SCENARIO_COUNT != 10_000:
        raise ApiContractError("default scenario population changed")
    if MAXIMUM_SCENARIO_COUNT != 100_000:
        raise ApiContractError("maximum scenario population changed")
