"""Development-only Phase 8 historical decision diagnostics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from statistics import median

from app.optimizer.contracts import (
    OptimizerContractError,
    PitDecisionAction,
    PitDecisionRecommendation,
    PitDecisionRequest,
)
from app.optimizer.stability import PitDecisionStability


class HistoricalDiagnosticScope(StrEnum):
    """Supported population groupings for decision diagnostics."""

    OVERALL = "OVERALL"
    EVENT = "EVENT"


@dataclass(frozen=True, slots=True)
class HistoricalDecisionDiagnostic:
    """One historical decision paired with simulator-conditioned evidence."""

    stability: PitDecisionStability
    observed_action: PitDecisionAction | None = None

    def __post_init__(self) -> None:
        """Normalize the optional action without treating it as ground truth."""
        if not isinstance(self.stability, PitDecisionStability):
            raise TypeError("stability must be a PitDecisionStability")
        if self.observed_action is None:
            return
        try:
            observed_action = PitDecisionAction(self.observed_action)
        except (TypeError, ValueError) as error:
            raise OptimizerContractError(
                f"unsupported observed historical action: "
                f"{self.observed_action!r}"
            ) from error
        object.__setattr__(self, "observed_action", observed_action)

    @property
    def request(self) -> PitDecisionRequest:
        """Return the base optimizer request defining this decision identity."""
        return self.stability.sensitivity.base_request

    @property
    def decision_key(self) -> tuple[int, str, str, int, str]:
        """Return the canonical historical decision identity."""
        state = self.request.state
        return (
            state.season,
            state.session_id,
            state.driver,
            state.current_lap,
            self.request.target_compound.value,
        )

    @property
    def observed_action_alignment(self) -> bool | None:
        """Compare actions only when both observed and stable values exist."""
        if self.observed_action is None or not self.stability.is_stable:
            return None
        recommended_action = PitDecisionAction(
            self.stability.recommendation.value
        )
        return self.observed_action is recommended_action


@dataclass(frozen=True, slots=True)
class HistoricalDecisionSummary:
    """Aggregate diagnostic counts and model-conditioned distributions."""

    scope: HistoricalDiagnosticScope
    value: str
    decisions: int
    stable_pit_now: int
    stable_stay_out: int
    no_clear_advantage: int
    observed_action_rows: int
    observed_pit_now: int
    observed_stay_out: int
    comparable_observed_action_rows: int
    aligned_observed_actions: int
    different_observed_actions: int
    mean_nominal_advantage_seconds: float
    median_nominal_advantage_seconds: float
    mean_conservative_interval_width_seconds: float

    def __post_init__(self) -> None:
        """Require internally reconciled non-probabilistic summary evidence."""
        try:
            scope = HistoricalDiagnosticScope(self.scope)
        except (TypeError, ValueError) as error:
            raise OptimizerContractError(
                f"unsupported historical diagnostic scope: {self.scope!r}"
            ) from error
        if not isinstance(self.value, str) or not self.value.strip():
            raise OptimizerContractError("diagnostic summary value must not be blank")
        counts = (
            self.decisions,
            self.stable_pit_now,
            self.stable_stay_out,
            self.no_clear_advantage,
            self.observed_action_rows,
            self.observed_pit_now,
            self.observed_stay_out,
            self.comparable_observed_action_rows,
            self.aligned_observed_actions,
            self.different_observed_actions,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in counts):
            raise OptimizerContractError("diagnostic summary counts must be integers")
        if self.decisions <= 0 or any(value < 0 for value in counts[1:]):
            raise OptimizerContractError(
                "diagnostic summary counts must be non-negative with decisions"
            )
        if (
            self.stable_pit_now
            + self.stable_stay_out
            + self.no_clear_advantage
            != self.decisions
        ):
            raise OptimizerContractError(
                "recommendation counts do not reconcile with decisions"
            )
        if self.observed_pit_now + self.observed_stay_out != self.observed_action_rows:
            raise OptimizerContractError(
                "observed action counts do not reconcile"
            )
        if (
            self.aligned_observed_actions + self.different_observed_actions
            != self.comparable_observed_action_rows
        ):
            raise OptimizerContractError(
                "observed alignment counts do not reconcile"
            )
        if self.comparable_observed_action_rows > self.observed_action_rows:
            raise OptimizerContractError(
                "comparable observed rows exceed observed action rows"
            )
        for value in (
            self.mean_nominal_advantage_seconds,
            self.median_nominal_advantage_seconds,
            self.mean_conservative_interval_width_seconds,
        ):
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise OptimizerContractError(
                    "diagnostic summary values must be finite"
                )
        if self.mean_conservative_interval_width_seconds < 0:
            raise OptimizerContractError(
                "mean conservative interval width must be non-negative"
            )
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "value", self.value.strip())

    @property
    def observed_action_alignment_rate(self) -> float | None:
        """Return descriptive alignment, never decision accuracy."""
        if self.comparable_observed_action_rows == 0:
            return None
        return (
            self.aligned_observed_actions
            / self.comparable_observed_action_rows
        )


@dataclass(frozen=True, slots=True)
class HistoricalDecisionDiagnostics:
    """Complete overall and event-level development decision population."""

    decisions: tuple[HistoricalDecisionDiagnostic, ...]

    def __post_init__(self) -> None:
        """Reject empty, mutable, invalid or duplicate decision evidence."""
        if not isinstance(self.decisions, tuple):
            raise OptimizerContractError("historical decisions must be a tuple")
        if not self.decisions:
            raise OptimizerContractError("historical decisions must not be empty")
        if any(
            not isinstance(decision, HistoricalDecisionDiagnostic)
            for decision in self.decisions
        ):
            raise OptimizerContractError(
                "every historical decision must be a HistoricalDecisionDiagnostic"
            )
        keys = tuple(decision.decision_key for decision in self.decisions)
        if len(keys) != len(set(keys)):
            raise OptimizerContractError(
                "historical decision identities must be unique"
            )

    @property
    def overall(self) -> HistoricalDecisionSummary:
        """Summarize the complete development diagnostic population."""
        return _summarize(
            self.decisions,
            scope=HistoricalDiagnosticScope.OVERALL,
            value="ALL",
        )

    @property
    def by_event(self) -> tuple[HistoricalDecisionSummary, ...]:
        """Return deterministic event-level diagnostic slices."""
        event_names = sorted(
            {decision.request.state.event_name for decision in self.decisions},
            key=str.casefold,
        )
        return tuple(
            _summarize(
                tuple(
                    decision
                    for decision in self.decisions
                    if decision.request.state.event_name == event_name
                ),
                scope=HistoricalDiagnosticScope.EVENT,
                value=event_name,
            )
            for event_name in event_names
        )


def build_historical_decision_diagnostics(
    decisions: tuple[HistoricalDecisionDiagnostic, ...],
) -> HistoricalDecisionDiagnostics:
    """Build reconciled development diagnostics without an optimality claim."""
    return HistoricalDecisionDiagnostics(decisions=decisions)


def _summarize(
    decisions: tuple[HistoricalDecisionDiagnostic, ...],
    *,
    scope: HistoricalDiagnosticScope,
    value: str,
) -> HistoricalDecisionSummary:
    recommendations = tuple(
        decision.stability.recommendation for decision in decisions
    )
    observed = tuple(
        decision.observed_action
        for decision in decisions
        if decision.observed_action is not None
    )
    alignments = tuple(
        alignment
        for decision in decisions
        if (alignment := decision.observed_action_alignment) is not None
    )
    advantages = tuple(
        decision.stability.sensitivity.nominal.pit_now_advantage_seconds
        for decision in decisions
    )
    widths = tuple(
        upper - lower
        for lower, upper in (
            decision.stability.conservative_advantage_interval_seconds
            for decision in decisions
        )
    )
    return HistoricalDecisionSummary(
        scope=scope,
        value=value,
        decisions=len(decisions),
        stable_pit_now=recommendations.count(PitDecisionRecommendation.PIT_NOW),
        stable_stay_out=recommendations.count(
            PitDecisionRecommendation.STAY_OUT
        ),
        no_clear_advantage=recommendations.count(
            PitDecisionRecommendation.NO_CLEAR_ADVANTAGE
        ),
        observed_action_rows=len(observed),
        observed_pit_now=observed.count(PitDecisionAction.PIT_NOW),
        observed_stay_out=observed.count(PitDecisionAction.STAY_OUT),
        comparable_observed_action_rows=len(alignments),
        aligned_observed_actions=alignments.count(True),
        different_observed_actions=alignments.count(False),
        mean_nominal_advantage_seconds=math.fsum(advantages) / len(advantages),
        median_nominal_advantage_seconds=float(median(advantages)),
        mean_conservative_interval_width_seconds=(
            math.fsum(widths) / len(widths)
        ),
    )
