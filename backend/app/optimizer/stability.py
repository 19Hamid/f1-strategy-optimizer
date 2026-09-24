"""Fail-closed Phase 8 recommendation stability assessment."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.optimizer.contracts import (
    DECISION_EQUALITY_ABS_TOLERANCE_SECONDS,
    OptimizerContractError,
    PitDecisionRecommendation,
)
from app.optimizer.sensitivity import PitDecisionSensitivity


@dataclass(frozen=True, slots=True)
class DecisionUncertaintyAssumption:
    """Explicit symmetric time margin for each simulated action estimate."""

    action_time_margin_seconds: float
    evidence: str

    def __post_init__(self) -> None:
        """Require a finite declared margin and non-empty provenance."""
        margin = _finite_non_negative(
            self.action_time_margin_seconds,
            "action_time_margin_seconds",
        )
        if not isinstance(self.evidence, str) or not self.evidence.strip():
            raise OptimizerContractError(
                "decision uncertainty evidence must not be blank"
            )
        object.__setattr__(self, "action_time_margin_seconds", margin)
        object.__setattr__(self, "evidence", self.evidence.strip())

    @property
    def advantage_margin_seconds(self) -> float:
        """Return the worst-case difference margin for two action estimates."""
        return 2.0 * self.action_time_margin_seconds


@dataclass(frozen=True, slots=True)
class PitDecisionStability:
    """Sensitivity envelope widened by an explicit action-time margin."""

    sensitivity: PitDecisionSensitivity
    uncertainty: DecisionUncertaintyAssumption

    def __post_init__(self) -> None:
        """Require verified sensitivity evidence and declared uncertainty."""
        if not isinstance(self.sensitivity, PitDecisionSensitivity):
            raise TypeError("sensitivity must be a PitDecisionSensitivity")
        if not isinstance(self.uncertainty, DecisionUncertaintyAssumption):
            raise TypeError(
                "uncertainty must be a DecisionUncertaintyAssumption"
            )

    @property
    def conservative_advantage_interval_seconds(self) -> tuple[float, float]:
        """Return the full pit-now advantage interval under both mechanisms."""
        lower, upper = self.sensitivity.pit_now_advantage_range_seconds
        margin = self.uncertainty.advantage_margin_seconds
        return lower - margin, upper + margin

    @property
    def recommendation(self) -> PitDecisionRecommendation:
        """Recommend an action only when the complete interval excludes zero."""
        lower, upper = self.conservative_advantage_interval_seconds
        tolerance = DECISION_EQUALITY_ABS_TOLERANCE_SECONDS
        if lower > tolerance:
            return PitDecisionRecommendation.PIT_NOW
        if upper < -tolerance:
            return PitDecisionRecommendation.STAY_OUT
        return PitDecisionRecommendation.NO_CLEAR_ADVANTAGE

    @property
    def is_stable(self) -> bool:
        """Return whether one action wins across the full declared interval."""
        return self.recommendation is not (
            PitDecisionRecommendation.NO_CLEAR_ADVANTAGE
        )

    @property
    def nominal_recommendation(self) -> PitDecisionRecommendation:
        """Expose the centre-cell point estimate beside the stable outcome."""
        return self.sensitivity.nominal.recommendation


def assess_recommendation_stability(
    sensitivity: PitDecisionSensitivity,
    *,
    uncertainty: DecisionUncertaintyAssumption,
) -> PitDecisionStability:
    """Widen a complete sensitivity envelope and classify it conservatively."""
    if not isinstance(sensitivity, PitDecisionSensitivity):
        raise TypeError("sensitivity must be a PitDecisionSensitivity")
    if not isinstance(uncertainty, DecisionUncertaintyAssumption):
        raise TypeError("uncertainty must be a DecisionUncertaintyAssumption")
    return PitDecisionStability(
        sensitivity=sensitivity,
        uncertainty=uncertainty,
    )


def _finite_non_negative(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OptimizerContractError(f"{field_name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise OptimizerContractError(
            f"{field_name} must be finite and non-negative"
        )
    return normalized
