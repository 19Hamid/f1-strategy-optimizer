"""Frozen Phase 6 model, feature and evaluation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from app.datasets.contracts import DECISION_MODEL_FEATURE_COLUMNS

MODEL_CONTRACT_VERSION: Final = "1.1"
MODEL_RANDOM_SEED: Final = 42
PROTECTED_EVALUATION_SEASON: Final = 2025

PRIMARY_TARGET_COLUMN: Final = "lap_time_target_seconds"
AUXILIARY_TARGET_COLUMN: Final = "lap_time_delta_seconds"
PRIMARY_BASELINE_ID: Final = "previous_valid_lap"
PRIMARY_BASELINE_MAE_SECONDS: Final = 0.410049
MINIMUM_PRIMARY_COVERAGE: Final = 0.970376

CATEGORICAL_FEATURE_COLUMNS: Final = (
    "event_name",
    "driver",
    "team",
    "current_compound",
)
BOOLEAN_FEATURE_COLUMNS: Final = ("previous_lap_was_target_eligible",)
NUMERIC_FEATURE_COLUMNS: Final = (
    "decision_lap",
    "tyre_age_laps",
    "current_stint_laps_completed",
    "completed_pit_stops",
    "previous_position",
    "previous_lap_time_seconds",
    "previous_sector1_time_seconds",
    "previous_sector2_time_seconds",
    "previous_sector3_time_seconds",
    "eligible_laps_completed",
    "rolling_lap_time_median_3",
    "rolling_lap_time_median_5",
    "rolling_lap_time_std_5",
    "rolling_lap_time_trend_5",
    "weather_age_seconds",
    "air_temperature_celsius",
    "humidity_percent",
    "pressure_mbar",
    "track_temperature_celsius",
    "wind_direction_degrees",
    "wind_speed_mps",
)
APPROVED_FEATURE_COLUMNS: Final = DECISION_MODEL_FEATURE_COLUMNS
IDENTITY_DEPENDENCE_COLUMNS: Final = ("driver", "team")
IDENTITY_ABLATION_FEATURE_COLUMNS: Final = tuple(
    column
    for column in APPROVED_FEATURE_COLUMNS
    if column not in IDENTITY_DEPENDENCE_COLUMNS
)
FORBIDDEN_MODEL_COLUMNS: Final = frozenset(
    {
        "decision_id",
        "session_id",
        "season",
        "round_number",
        "session_type",
        "decision_time_seconds",
        "source_row_number",
        "dataset_contract_version",
        "cleaning_rule_version",
        "processed_contract_version",
        "historical_action",
        "did_pit",
        "pit_event_id",
        "is_decision_eligible",
        "decision_exclusion_count",
        "decision_exclusion_reasons",
        "is_lap_time_target_eligible",
        "lap_target_exclusion_count",
        "lap_target_exclusion_reasons",
        PRIMARY_TARGET_COLUMN,
        AUXILIARY_TARGET_COLUMN,
    }
)

DEVELOPMENT_FOLDS: Final = (
    "development_fold_1",
    "development_fold_2",
)


class ModelContractError(ValueError):
    """Raised when Phase 6 configuration could leak or misstate results."""


class ModelTarget(StrEnum):
    """Frozen Phase 6 supervised targets."""

    LAP_TIME = "LAP_TIME"
    LAP_TIME_DELTA = "LAP_TIME_DELTA"


class PredictionFormulation(StrEnum):
    """Approved ways to produce an absolute next-lap prediction."""

    DIRECT_ABSOLUTE = "DIRECT_ABSOLUTE"
    RESIDUAL_HYBRID = "RESIDUAL_HYBRID"


class ModelFamily(StrEnum):
    """Approved scikit-learn regression families."""

    RIDGE = "ridge"
    RANDOM_FOREST = "random_forest"
    HIST_GRADIENT_BOOSTING = "hist_gradient_boosting"


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Declare one model family and its bounded search grid."""

    family: ModelFamily
    description: str
    parameter_grid: tuple[dict[str, object], ...]

    def __post_init__(self) -> None:
        """Reject empty or duplicate configurations."""
        if not self.description.strip():
            raise ModelContractError("model description must not be blank")
        if not self.parameter_grid:
            raise ModelContractError(
                f"{self.family.value} parameter grid must not be empty"
            )
        normalized = tuple(
            tuple(sorted(parameters.items())) for parameters in self.parameter_grid
        )
        if len(normalized) != len(set(normalized)):
            raise ModelContractError(
                f"{self.family.value} parameter grid contains duplicates"
            )


MODEL_SPECS: Final = (
    ModelSpec(
        family=ModelFamily.RIDGE,
        description=(
            "Regularized linear reference with scaled numeric and one-hot "
            "categorical features."
        ),
        parameter_grid=(
            {"alpha": 0.1},
            {"alpha": 1.0},
            {"alpha": 10.0},
        ),
    ),
    ModelSpec(
        family=ModelFamily.RANDOM_FOREST,
        description=(
            "Bagged nonlinear trees for interactions and robust tabular comparisons."
        ),
        parameter_grid=tuple(
            {
                "n_estimators": 300,
                "max_depth": max_depth,
                "min_samples_leaf": minimum_leaf,
                "max_features": 0.7,
            }
            for max_depth in (12, None)
            for minimum_leaf in (1, 5)
        ),
    ),
    ModelSpec(
        family=ModelFamily.HIST_GRADIENT_BOOSTING,
        description=(
            "Boosted histogram trees for strong nonlinear tabular prediction."
        ),
        parameter_grid=tuple(
            {
                "learning_rate": learning_rate,
                "max_iter": 300,
                "max_leaf_nodes": leaves,
                "l2_regularization": regularization,
            }
            for learning_rate in (0.05, 0.1)
            for leaves in (15, 31)
            for regularization in (0.1, 1.0)
        ),
    ),
)
MODEL_SPEC_BY_FAMILY: Final = {
    specification.family: specification for specification in MODEL_SPECS
}


def model_spec(family: ModelFamily | str) -> ModelSpec:
    """Return one approved specification by stable family identity."""
    try:
        normalized = ModelFamily(family)
    except (TypeError, ValueError) as error:
        raise ModelContractError(f"unknown model family: {family!r}") from error
    return MODEL_SPEC_BY_FAMILY[normalized]


def validate_model_contract() -> None:
    """Prove exact feature partitioning and protected-data boundaries."""
    feature_set = set(APPROVED_FEATURE_COLUMNS)
    if len(APPROVED_FEATURE_COLUMNS) != len(feature_set):
        raise ModelContractError("approved model features must be unique")
    if feature_set != set(DECISION_MODEL_FEATURE_COLUMNS):
        raise ModelContractError(
            "Phase 6 features differ from the Phase 4 leakage-safe contract"
        )
    partitions = (
        set(CATEGORICAL_FEATURE_COLUMNS),
        set(BOOLEAN_FEATURE_COLUMNS),
        set(NUMERIC_FEATURE_COLUMNS),
    )
    if any(
        left & right
        for index, left in enumerate(partitions)
        for right in partitions[index + 1 :]
    ):
        raise ModelContractError("feature-type partitions overlap")
    if set().union(*partitions) != feature_set:
        raise ModelContractError("feature-type partitions are incomplete")
    if feature_set & FORBIDDEN_MODEL_COLUMNS:
        raise ModelContractError("forbidden columns entered model features")
    if not set(IDENTITY_DEPENDENCE_COLUMNS) < feature_set:
        raise ModelContractError("identity diagnostic columns are incomplete")
    families = tuple(specification.family for specification in MODEL_SPECS)
    if len(families) != len(set(families)):
        raise ModelContractError("model families must be unique")
    if PROTECTED_EVALUATION_SEASON in {2022, 2023, 2024}:
        raise ModelContractError("protected season entered development")


validate_model_contract()
