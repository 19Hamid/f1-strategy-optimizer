"""Frozen contracts for Phase 5 baseline evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

BASELINE_CONTRACT_VERSION: Final = "1.0"
BASELINE_RANDOM_SEED: Final = 42
DEVELOPMENT_EVALUATION_FOLDS: Final = (
    "development_fold_1",
    "development_fold_2",
)


class BaselineContractError(ValueError):
    """Raised when a baseline contradicts the frozen Phase 5 contract."""


class BaselineTask(StrEnum):
    """Supported prediction targets."""

    LAP_TIME = "LAP_TIME"
    PIT_DURATION = "PIT_DURATION"


class BaselineId(StrEnum):
    """Stable machine-readable baseline identities."""

    PREVIOUS_VALID_LAP = "previous_valid_lap"
    ROLLING_MEDIAN_3 = "rolling_median_3"
    STINT_LINEAR_TREND = "stint_linear_trend"
    CIRCUIT_COMPOUND_MEDIAN = "circuit_compound_median"
    PIT_GLOBAL_MEDIAN = "pit_global_median"
    PIT_CIRCUIT_MEDIAN = "pit_circuit_median"
    PIT_CIRCUIT_TRANSITION_MEDIAN = "pit_circuit_transition_median"


@dataclass(frozen=True, slots=True)
class BaselineSpec:
    """Declare one deterministic baseline and its fallback chain."""

    baseline_id: BaselineId
    task: BaselineTask
    description: str
    required_columns: tuple[str, ...]
    fit_required: bool
    fallback_ids: tuple[BaselineId, ...] = ()

    def __post_init__(self) -> None:
        """Reject ambiguous or cross-task specifications."""
        if not self.description.strip():
            raise BaselineContractError("description must not be blank")
        if not self.required_columns:
            raise BaselineContractError(
                f"{self.baseline_id} must require source columns"
            )
        if len(set(self.required_columns)) != len(self.required_columns):
            raise BaselineContractError(
                f"{self.baseline_id} repeats required columns"
            )
        if self.baseline_id in self.fallback_ids:
            raise BaselineContractError(
                f"{self.baseline_id} cannot fall back to itself"
            )


LAP_TIME_BASELINES: Final = (
    BaselineSpec(
        baseline_id=BaselineId.PREVIOUS_VALID_LAP,
        task=BaselineTask.LAP_TIME,
        description="Use the most recent eligible completed lap.",
        required_columns=(
            "previous_lap_was_target_eligible",
            "previous_lap_time_seconds",
        ),
        fit_required=False,
    ),
    BaselineSpec(
        baseline_id=BaselineId.ROLLING_MEDIAN_3,
        task=BaselineTask.LAP_TIME,
        description="Use the median of up to three eligible completed laps.",
        required_columns=(
            "rolling_lap_time_median_3",
            "previous_lap_was_target_eligible",
            "previous_lap_time_seconds",
        ),
        fit_required=False,
        fallback_ids=(BaselineId.PREVIOUS_VALID_LAP,),
    ),
    BaselineSpec(
        baseline_id=BaselineId.STINT_LINEAR_TREND,
        task=BaselineTask.LAP_TIME,
        description=(
            "Advance the previous eligible lap by the past-only five-lap "
            "linear trend."
        ),
        required_columns=(
            "previous_lap_was_target_eligible",
            "previous_lap_time_seconds",
            "rolling_lap_time_trend_5",
        ),
        fit_required=False,
        fallback_ids=(
            BaselineId.ROLLING_MEDIAN_3,
            BaselineId.PREVIOUS_VALID_LAP,
        ),
    ),
    BaselineSpec(
        baseline_id=BaselineId.CIRCUIT_COMPOUND_MEDIAN,
        task=BaselineTask.LAP_TIME,
        description=(
            "Use training-only event-compound median lap time, then "
            "compound and global training medians."
        ),
        required_columns=(
            "event_name",
            "current_compound",
            "lap_time_target_seconds",
        ),
        fit_required=True,
    ),
)

PIT_DURATION_BASELINES: Final = (
    BaselineSpec(
        baseline_id=BaselineId.PIT_GLOBAL_MEDIAN,
        task=BaselineTask.PIT_DURATION,
        description="Use the global training-event median pit-lane duration.",
        required_columns=("pit_duration_target_seconds",),
        fit_required=True,
    ),
    BaselineSpec(
        baseline_id=BaselineId.PIT_CIRCUIT_MEDIAN,
        task=BaselineTask.PIT_DURATION,
        description=(
            "Use the training-only event median with global-median fallback."
        ),
        required_columns=(
            "event_name",
            "pit_duration_target_seconds",
        ),
        fit_required=True,
        fallback_ids=(BaselineId.PIT_GLOBAL_MEDIAN,),
    ),
    BaselineSpec(
        baseline_id=BaselineId.PIT_CIRCUIT_TRANSITION_MEDIAN,
        task=BaselineTask.PIT_DURATION,
        description=(
            "Use the training-only event and compound-transition median, "
            "then event, transition and global medians."
        ),
        required_columns=(
            "event_name",
            "compound_before",
            "compound_after",
            "pit_duration_target_seconds",
        ),
        fit_required=True,
        fallback_ids=(
            BaselineId.PIT_CIRCUIT_MEDIAN,
            BaselineId.PIT_GLOBAL_MEDIAN,
        ),
    ),
)

BASELINE_SPECS: Final = LAP_TIME_BASELINES + PIT_DURATION_BASELINES
BASELINE_SPEC_BY_ID: Final = {
    specification.baseline_id: specification
    for specification in BASELINE_SPECS
}

PRIMARY_METRIC: Final = "mean_absolute_error_seconds"
SECONDARY_METRICS: Final = (
    "root_mean_squared_error_seconds",
    "median_absolute_error_seconds",
    "p90_absolute_error_seconds",
    "mean_signed_error_seconds",
)
REQUIRED_SLICE_DIMENSIONS: Final = (
    "session_id",
    "event_name",
    "current_compound",
    "tyre_age_band",
    "driver",
    "team",
    "race_progress_band",
)
PIT_REQUIRED_SLICE_DIMENSIONS: Final = (
    "session_id",
    "event_name",
    "season",
    "compound_transition",
)
REQUIRED_EXPERIMENT_PROVENANCE: Final = (
    "baseline_contract_version",
    "dataset_contract_version",
    "dataset_build_identifier",
    "fold_id",
    "training_sessions",
    "validation_sessions",
    "target_name",
    "target_eligibility_rule",
    "baseline_id",
    "parameters",
    "fallback_counts",
    "random_seed",
    "dependency_versions",
    "execution_time_seconds",
)


def baseline_spec(baseline_id: BaselineId | str) -> BaselineSpec:
    """Return one specification by stable identity."""
    try:
        normalized = BaselineId(baseline_id)
    except (TypeError, ValueError) as error:
        raise BaselineContractError(
            f"unknown baseline_id: {baseline_id!r}"
        ) from error
    return BASELINE_SPEC_BY_ID[normalized]


def validate_baseline_contract() -> None:
    """Validate uniqueness, task-local fallbacks and complete definitions."""
    identities = tuple(spec.baseline_id for spec in BASELINE_SPECS)
    if len(identities) != len(set(identities)):
        raise BaselineContractError("baseline identities must be unique")

    for spec in BASELINE_SPECS:
        for fallback_id in spec.fallback_ids:
            fallback = BASELINE_SPEC_BY_ID.get(fallback_id)
            if fallback is None:
                raise BaselineContractError(
                    f"{spec.baseline_id} has an unknown fallback"
                )
            if fallback.task != spec.task:
                raise BaselineContractError(
                    f"{spec.baseline_id} has a cross-task fallback"
                )


validate_baseline_contract()
