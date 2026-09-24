"""Pit-now versus stay-out decision comparison."""

from app.optimizer.comparison import (
    ActionEvaluation,
    PitDecisionComparison,
    compare_pit_decision,
)
from app.optimizer.contracts import (
    DECISION_EQUALITY_ABS_TOLERANCE_SECONDS,
    MINIMUM_DECISION_HORIZON_LAPS,
    OPTIMIZER_CONTRACT_VERSION,
    STAY_OUT_DEFERRAL_LAPS,
    OptimizerContractError,
    PitDecisionAction,
    PitDecisionRecommendation,
    PitDecisionRequest,
    validate_optimizer_contract,
)

__all__ = (
    "DECISION_EQUALITY_ABS_TOLERANCE_SECONDS",
    "MINIMUM_DECISION_HORIZON_LAPS",
    "OPTIMIZER_CONTRACT_VERSION",
    "STAY_OUT_DEFERRAL_LAPS",
    "ActionEvaluation",
    "OptimizerContractError",
    "PitDecisionAction",
    "PitDecisionComparison",
    "PitDecisionRecommendation",
    "PitDecisionRequest",
    "compare_pit_decision",
    "validate_optimizer_contract",
)
