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
from app.optimizer.sensitivity import (
    TYRE_AGE_SENSITIVITY_DELTA_LAPS,
    PitDecisionSensitivity,
    PitDecisionSensitivityCase,
    TyreAgeSensitivityScenario,
    analyze_pit_decision_sensitivity,
)
from app.optimizer.stability import (
    DecisionUncertaintyAssumption,
    PitDecisionStability,
    assess_recommendation_stability,
)

__all__ = (
    "DECISION_EQUALITY_ABS_TOLERANCE_SECONDS",
    "MINIMUM_DECISION_HORIZON_LAPS",
    "OPTIMIZER_CONTRACT_VERSION",
    "STAY_OUT_DEFERRAL_LAPS",
    "TYRE_AGE_SENSITIVITY_DELTA_LAPS",
    "ActionEvaluation",
    "DecisionUncertaintyAssumption",
    "OptimizerContractError",
    "PitDecisionAction",
    "PitDecisionComparison",
    "PitDecisionRecommendation",
    "PitDecisionRequest",
    "PitDecisionSensitivity",
    "PitDecisionSensitivityCase",
    "PitDecisionStability",
    "TyreAgeSensitivityScenario",
    "analyze_pit_decision_sensitivity",
    "assess_recommendation_stability",
    "compare_pit_decision",
    "validate_optimizer_contract",
)
