"""Executable contracts for Phase 4 modelling datasets."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

DATASET_CONTRACT_VERSION = "1.0"
SOURCE_CLEANING_RULE_VERSION = "1.0"
SOURCE_PROCESSED_CONTRACT_VERSION = "1.0"

DEVELOPMENT_SEASONS = (
    2022,
    2023,
    2024,
)

PROTECTED_EVALUATION_SEASON = 2025

DRY_COMPOUNDS = frozenset(
    {
        "HARD",
        "MEDIUM",
        "SOFT",
    }
)

DATASET_DIRECTORY_NAME = "f1_strategy"
DATASET_VERSION_DIRECTORY = (
    f"dataset_contract_version="
    f"{DATASET_CONTRACT_VERSION}"
)


class DatasetContractError(ValueError):
    """Raised when data contradicts the dataset contract."""


class ColumnRole(StrEnum):
    """Semantic role of a stored column."""

    IDENTITY = "IDENTITY"
    PROVENANCE = "PROVENANCE"
    CONTEXT = "CONTEXT"
    FEATURE = "FEATURE"
    AUDIT = "AUDIT"
    LABEL = "LABEL"
    TARGET = "TARGET"
    QUALITY = "QUALITY"


class HistoricalAction(StrEnum):
    """Observed action taken during the decision lap."""

    PIT_NOW = "PIT_NOW"
    STAY_OUT = "STAY_OUT"


class SplitRole(StrEnum):
    """Role assigned to a session within a temporal fold."""

    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    EXCLUDED = "EXCLUDED"


class DecisionExclusionReason(StrEnum):
    """Ordered reasons for rejecting a candidate decision."""

    NON_CONSECUTIVE_PREVIOUS_LAP = (
        "NON_CONSECUTIVE_PREVIOUS_LAP"
    )
    WEATHER_NOT_AVAILABLE_BY_DECISION = (
        "WEATHER_NOT_AVAILABLE_BY_DECISION"
    )
    PREVIOUS_LAP_PIT_COMMITMENT = (
        "PREVIOUS_LAP_PIT_COMMITMENT"
    )
    STATE_RECONSTRUCTION_CONFLICT = (
        "STATE_RECONSTRUCTION_CONFLICT"
    )
    UNSUPPORTED_CURRENT_COMPOUND = (
        "UNSUPPORTED_CURRENT_COMPOUND"
    )
    INVALID_CURRENT_TYRE_AGE = (
        "INVALID_CURRENT_TYRE_AGE"
    )
    MISSING_CURRENT_STINT = "MISSING_CURRENT_STINT"
    WET_AT_DECISION = "WET_AT_DECISION"
    PREVIOUS_LAP_NOT_GREEN = "PREVIOUS_LAP_NOT_GREEN"
    INSUFFICIENT_ELIGIBLE_HISTORY = (
        "INSUFFICIENT_ELIGIBLE_HISTORY"
    )
    MISSING_PREVIOUS_POSITION = (
        "MISSING_PREVIOUS_POSITION"
    )


DECISION_EXCLUSION_REASON_ORDER = tuple(
    DecisionExclusionReason
)


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """One column declared by a stored table contract."""

    name: str
    pandas_dtype: str
    nullable: bool
    role: ColumnRole

    def __post_init__(self) -> None:
        """Reject malformed declarative column entries."""
        if not self.name:
            raise DatasetContractError(
                "column name must not be empty"
            )

        if not self.pandas_dtype:
            raise DatasetContractError(
                f"{self.name} must declare a pandas dtype"
            )


@dataclass(frozen=True, slots=True)
class TableContract:
    """Ordered schema contract for one Parquet table."""

    name: str
    file_name: str
    columns: tuple[ColumnSpec, ...]

    def __post_init__(self) -> None:
        """Verify contract identity and column uniqueness."""
        if not self.name:
            raise DatasetContractError(
                "table name must not be empty"
            )

        if not self.file_name.endswith(".parquet"):
            raise DatasetContractError(
                f"{self.name} file must end with .parquet"
            )

        if not self.columns:
            raise DatasetContractError(
                f"{self.name} must contain columns"
            )

        names = self.column_names

        if len(names) != len(set(names)):
            raise DatasetContractError(
                f"{self.name} contains duplicate columns"
            )

    @property
    def column_names(self) -> tuple[str, ...]:
        """Return ordered stored column names."""
        return tuple(
            column.name
            for column in self.columns
        )

    def column(self, name: str) -> ColumnSpec:
        """Return one declared column by name."""
        for column in self.columns:
            if column.name == name:
                return column

        raise DatasetContractError(
            f"{self.name} has no column {name!r}"
        )

    def validate_column_order(
        self,
        actual_columns: Iterable[str],
    ) -> None:
        """Require an exact ordered-column match."""
        actual = tuple(actual_columns)
        expected = self.column_names

        if actual == expected:
            return

        missing = tuple(
            column
            for column in expected
            if column not in actual
        )
        unexpected = tuple(
            column
            for column in actual
            if column not in expected
        )

        raise DatasetContractError(
            f"{self.name} columns do not match contract; "
            f"missing={missing}, "
            f"unexpected={unexpected}, "
            f"order_matches={set(actual) == set(expected)}"
        )


@dataclass(frozen=True, slots=True)
class TemporalFold:
    """Whole-season assignments for one development fold."""

    fold_id: str
    train_seasons: tuple[int, ...]
    validation_seasons: tuple[int, ...]
    excluded_seasons: tuple[int, ...]

    def __post_init__(self) -> None:
        """Require disjoint and complete development coverage."""
        groups = (
            set(self.train_seasons),
            set(self.validation_seasons),
            set(self.excluded_seasons),
        )

        if groups[0] & groups[1]:
            raise DatasetContractError(
                f"{self.fold_id} train and validation overlap"
            )

        if groups[0] & groups[2]:
            raise DatasetContractError(
                f"{self.fold_id} train and excluded overlap"
            )

        if groups[1] & groups[2]:
            raise DatasetContractError(
                f"{self.fold_id} validation and excluded overlap"
            )

        covered = set().union(*groups)

        if covered != set(DEVELOPMENT_SEASONS):
            raise DatasetContractError(
                f"{self.fold_id} must cover development seasons"
            )

        if PROTECTED_EVALUATION_SEASON in covered:
            raise DatasetContractError(
                f"{self.fold_id} must not contain "
                f"{PROTECTED_EVALUATION_SEASON}"
            )

    def role_for_season(
        self,
        season: int,
    ) -> SplitRole:
        """Return the frozen role for one development season."""
        if season in self.train_seasons:
            return SplitRole.TRAIN

        if season in self.validation_seasons:
            return SplitRole.VALIDATION

        if season in self.excluded_seasons:
            return SplitRole.EXCLUDED

        raise DatasetContractError(
            f"season {season} is outside {self.fold_id}"
        )


@dataclass(frozen=True, slots=True)
class DevelopmentDatasetTotals:
    """Frozen real-data totals expected from contract version 1.0."""

    sessions: int
    source_laps: int
    omitted_first_laps: int
    candidate_decisions: int
    eligible_decisions: int
    ineligible_decisions: int
    eligible_pit_now: int
    eligible_stay_out: int
    eligible_lap_targets: int
    ineligible_lap_targets: int
    pit_duration_observations: int
    eligible_pit_duration_targets: int
    state_reconstruction_conflicts: int
    split_rows: int


@dataclass(frozen=True, slots=True)
class DevelopmentSeasonTotals:
    """Frozen eligible-decision totals for one season."""

    season: int
    sessions: int
    eligible_decisions: int
    eligible_pit_now: int


DECISION_ROW_COLUMNS = (
    ColumnSpec(
        "decision_id",
        "string",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "session_id",
        "string",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "season",
        "int64",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "round_number",
        "int64",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "session_type",
        "string",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "event_name",
        "string",
        False,
        ColumnRole.CONTEXT,
    ),
    ColumnSpec(
        "driver",
        "string",
        False,
        ColumnRole.CONTEXT,
    ),
    ColumnSpec(
        "driver_number",
        "string",
        False,
        ColumnRole.CONTEXT,
    ),
    ColumnSpec(
        "team",
        "string",
        False,
        ColumnRole.CONTEXT,
    ),
    ColumnSpec(
        "decision_lap",
        "int64",
        False,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "decision_time_seconds",
        "float64",
        False,
        ColumnRole.PROVENANCE,
    ),
    ColumnSpec(
        "source_row_number",
        "int64",
        False,
        ColumnRole.PROVENANCE,
    ),
    ColumnSpec(
        "dataset_contract_version",
        "string",
        False,
        ColumnRole.PROVENANCE,
    ),
    ColumnSpec(
        "cleaning_rule_version",
        "string",
        False,
        ColumnRole.PROVENANCE,
    ),
    ColumnSpec(
        "processed_contract_version",
        "string",
        False,
        ColumnRole.PROVENANCE,
    ),
    ColumnSpec(
        "current_compound",
        "string",
        True,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "tyre_age_laps",
        "Int64",
        True,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "current_stint_number",
        "Int64",
        True,
        ColumnRole.CONTEXT,
    ),
    ColumnSpec(
        "current_stint_laps_completed",
        "Int64",
        True,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "completed_pit_stops",
        "int64",
        False,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "previous_position",
        "Int64",
        True,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "previous_lap_was_target_eligible",
        "bool",
        False,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "previous_lap_time_seconds",
        "float64",
        True,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "previous_sector1_time_seconds",
        "float64",
        True,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "previous_sector2_time_seconds",
        "float64",
        True,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "previous_sector3_time_seconds",
        "float64",
        True,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "eligible_laps_completed",
        "int64",
        False,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "rolling_lap_time_median_3",
        "float64",
        True,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "rolling_lap_time_median_5",
        "float64",
        True,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "rolling_lap_time_std_5",
        "float64",
        True,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "rolling_lap_time_trend_5",
        "float64",
        True,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "previous_track_status",
        "string",
        True,
        ColumnRole.CONTEXT,
    ),
    ColumnSpec(
        "weather_observation_time_seconds",
        "float64",
        False,
        ColumnRole.PROVENANCE,
    ),
    ColumnSpec(
        "weather_age_seconds",
        "float64",
        False,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "air_temperature_celsius",
        "float64",
        False,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "humidity_percent",
        "float64",
        False,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "pressure_mbar",
        "float64",
        False,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "track_temperature_celsius",
        "float64",
        False,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "wind_direction_degrees",
        "int64",
        False,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "wind_speed_mps",
        "float64",
        False,
        ColumnRole.FEATURE,
    ),
    ColumnSpec(
        "rainfall",
        "bool",
        False,
        ColumnRole.CONTEXT,
    ),
    ColumnSpec(
        "has_consecutive_previous_lap",
        "bool",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "weather_available_by_decision",
        "bool",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "previous_lap_not_pit_commitment",
        "bool",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "state_reconstruction_consistent",
        "bool",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "supported_dry_compound",
        "bool",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "valid_current_tyre_age",
        "bool",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "current_stint_identified",
        "bool",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "dry_at_decision",
        "bool",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "previous_lap_green",
        "bool",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "minimum_history_available",
        "bool",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "previous_position_available",
        "bool",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "is_decision_eligible",
        "bool",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "decision_exclusion_count",
        "int64",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "decision_exclusion_reasons",
        "string",
        False,
        ColumnRole.AUDIT,
    ),
)

DECISION_LABEL_COLUMNS = (
    ColumnSpec(
        "decision_id",
        "string",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "session_id",
        "string",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "season",
        "int64",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "round_number",
        "int64",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "session_type",
        "string",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "driver",
        "string",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "decision_lap",
        "int64",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "historical_action",
        "string",
        False,
        ColumnRole.LABEL,
    ),
    ColumnSpec(
        "did_pit",
        "bool",
        False,
        ColumnRole.LABEL,
    ),
    ColumnSpec(
        "pit_event_id",
        "string",
        True,
        ColumnRole.LABEL,
    ),
    ColumnSpec(
        "is_lap_time_target_eligible",
        "bool",
        False,
        ColumnRole.QUALITY,
    ),
    ColumnSpec(
        "lap_time_target_seconds",
        "float64",
        True,
        ColumnRole.TARGET,
    ),
    ColumnSpec(
        "lap_target_exclusion_count",
        "int64",
        False,
        ColumnRole.QUALITY,
    ),
    ColumnSpec(
        "lap_target_exclusion_reasons",
        "string",
        False,
        ColumnRole.QUALITY,
    ),
    ColumnSpec(
        "dataset_contract_version",
        "string",
        False,
        ColumnRole.PROVENANCE,
    ),
)

PIT_DURATION_OBSERVATION_COLUMNS = (
    ColumnSpec(
        "pit_event_id",
        "string",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "session_id",
        "string",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "season",
        "int64",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "round_number",
        "int64",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "session_type",
        "string",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "event_name",
        "string",
        False,
        ColumnRole.CONTEXT,
    ),
    ColumnSpec(
        "driver",
        "string",
        False,
        ColumnRole.CONTEXT,
    ),
    ColumnSpec(
        "team",
        "string",
        False,
        ColumnRole.CONTEXT,
    ),
    ColumnSpec(
        "event_type",
        "string",
        False,
        ColumnRole.CONTEXT,
    ),
    ColumnSpec(
        "pit_in_lap",
        "Int64",
        True,
        ColumnRole.CONTEXT,
    ),
    ColumnSpec(
        "pit_out_lap",
        "Int64",
        True,
        ColumnRole.CONTEXT,
    ),
    ColumnSpec(
        "stint_before",
        "Int64",
        True,
        ColumnRole.CONTEXT,
    ),
    ColumnSpec(
        "stint_after",
        "Int64",
        True,
        ColumnRole.CONTEXT,
    ),
    ColumnSpec(
        "compound_before",
        "string",
        True,
        ColumnRole.CONTEXT,
    ),
    ColumnSpec(
        "compound_after",
        "string",
        True,
        ColumnRole.CONTEXT,
    ),
    ColumnSpec(
        "tyre_life_before",
        "float64",
        True,
        ColumnRole.CONTEXT,
    ),
    ColumnSpec(
        "tyre_life_after",
        "float64",
        True,
        ColumnRole.CONTEXT,
    ),
    ColumnSpec(
        "is_stint_change",
        "boolean",
        True,
        ColumnRole.QUALITY,
    ),
    ColumnSpec(
        "is_compound_change",
        "boolean",
        True,
        ColumnRole.QUALITY,
    ),
    ColumnSpec(
        "is_complete",
        "bool",
        False,
        ColumnRole.QUALITY,
    ),
    ColumnSpec(
        "is_green_flag_pair",
        "bool",
        False,
        ColumnRole.QUALITY,
    ),
    ColumnSpec(
        "is_dry_weather_pair",
        "bool",
        False,
        ColumnRole.QUALITY,
    ),
    ColumnSpec(
        "is_interrupted_duration",
        "bool",
        False,
        ColumnRole.QUALITY,
    ),
    ColumnSpec(
        "is_pit_duration_target_eligible",
        "bool",
        False,
        ColumnRole.QUALITY,
    ),
    ColumnSpec(
        "pit_duration_target_seconds",
        "float64",
        True,
        ColumnRole.TARGET,
    ),
    ColumnSpec(
        "pit_duration_exclusion_count",
        "int64",
        False,
        ColumnRole.QUALITY,
    ),
    ColumnSpec(
        "pit_duration_exclusion_reasons",
        "string",
        False,
        ColumnRole.QUALITY,
    ),
    ColumnSpec(
        "dataset_contract_version",
        "string",
        False,
        ColumnRole.PROVENANCE,
    ),
)

SPLIT_COLUMNS = (
    ColumnSpec(
        "fold_id",
        "string",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "session_id",
        "string",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "season",
        "int64",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "round_number",
        "int64",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "session_type",
        "string",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "role",
        "string",
        False,
        ColumnRole.CONTEXT,
    ),
)

CATALOG_COLUMNS = (
    ColumnSpec(
        "session_id",
        "string",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "season",
        "int64",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "round_number",
        "int64",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "session_type",
        "string",
        False,
        ColumnRole.IDENTITY,
    ),
    ColumnSpec(
        "event_name",
        "string",
        False,
        ColumnRole.CONTEXT,
    ),
    ColumnSpec(
        "dataset_contract_version",
        "string",
        False,
        ColumnRole.PROVENANCE,
    ),
    ColumnSpec(
        "cleaning_rule_version",
        "string",
        False,
        ColumnRole.PROVENANCE,
    ),
    ColumnSpec(
        "processed_contract_version",
        "string",
        False,
        ColumnRole.PROVENANCE,
    ),
    ColumnSpec(
        "created_at_utc",
        "string",
        False,
        ColumnRole.PROVENANCE,
    ),
    ColumnSpec(
        "decision_rows",
        "int64",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "eligible_decisions",
        "int64",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "ineligible_decisions",
        "int64",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "decision_label_rows",
        "int64",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "lap_time_target_eligible_rows",
        "int64",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "pit_now_rows",
        "int64",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "stay_out_rows",
        "int64",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "pit_duration_rows",
        "int64",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "pit_duration_target_eligible_rows",
        "int64",
        False,
        ColumnRole.AUDIT,
    ),
    ColumnSpec(
        "total_size_bytes",
        "int64",
        False,
        ColumnRole.PROVENANCE,
    ),
    ColumnSpec(
        "session_directory",
        "string",
        False,
        ColumnRole.PROVENANCE,
    ),
)

DECISION_ROWS_CONTRACT = TableContract(
    name="decision_rows",
    file_name="decision_rows.parquet",
    columns=DECISION_ROW_COLUMNS,
)

DECISION_LABELS_CONTRACT = TableContract(
    name="decision_labels",
    file_name="decision_labels.parquet",
    columns=DECISION_LABEL_COLUMNS,
)

PIT_DURATION_OBSERVATIONS_CONTRACT = TableContract(
    name="pit_duration_observations",
    file_name="pit_duration_observations.parquet",
    columns=PIT_DURATION_OBSERVATION_COLUMNS,
)

SPLITS_CONTRACT = TableContract(
    name="splits",
    file_name="splits.parquet",
    columns=SPLIT_COLUMNS,
)

CATALOG_CONTRACT = TableContract(
    name="catalog",
    file_name="catalog.parquet",
    columns=CATALOG_COLUMNS,
)

SESSION_TABLE_CONTRACTS = (
    DECISION_ROWS_CONTRACT,
    DECISION_LABELS_CONTRACT,
    PIT_DURATION_OBSERVATIONS_CONTRACT,
)

GLOBAL_TABLE_CONTRACTS = (
    SPLITS_CONTRACT,
    CATALOG_CONTRACT,
)

TABLE_CONTRACTS = (
    *SESSION_TABLE_CONTRACTS,
    *GLOBAL_TABLE_CONTRACTS,
)

DECISION_MODEL_FEATURE_COLUMNS = (
    "event_name",
    "driver",
    "team",
    "decision_lap",
    "current_compound",
    "tyre_age_laps",
    "current_stint_laps_completed",
    "completed_pit_stops",
    "previous_position",
    "previous_lap_was_target_eligible",
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

PIT_EVENT_NULLABLE_INTEGER_COLUMNS = (
    "pit_in_lap",
    "pit_out_lap",
    "stint_before",
    "stint_after",
)

PIT_EVENT_NULLABLE_BOOLEAN_COLUMNS = (
    "is_stint_change",
    "is_compound_change",
)

TEMPORAL_FOLDS = (
    TemporalFold(
        fold_id="development_fold_1",
        train_seasons=(2022,),
        validation_seasons=(2023,),
        excluded_seasons=(2024,),
    ),
    TemporalFold(
        fold_id="development_fold_2",
        train_seasons=(
            2022,
            2023,
        ),
        validation_seasons=(2024,),
        excluded_seasons=(),
    ),
    TemporalFold(
        fold_id="final_development_fit",
        train_seasons=DEVELOPMENT_SEASONS,
        validation_seasons=(),
        excluded_seasons=(),
    ),
)

EXPECTED_DEVELOPMENT_TOTALS = (
    DevelopmentDatasetTotals(
        sessions=68,
        source_laps=74601,
        omitted_first_laps=1350,
        candidate_decisions=73251,
        eligible_decisions=55943,
        ineligible_decisions=17308,
        eligible_pit_now=1776,
        eligible_stay_out=54167,
        eligible_lap_targets=52483,
        ineligible_lap_targets=3460,
        pit_duration_observations=2693,
        eligible_pit_duration_targets=1465,
        state_reconstruction_conflicts=6,
        split_rows=204,
    )
)

EXPECTED_SEASON_TOTALS = (
    DevelopmentSeasonTotals(
        season=2022,
        sessions=22,
        eligible_decisions=16216,
        eligible_pit_now=560,
    ),
    DevelopmentSeasonTotals(
        season=2023,
        sessions=22,
        eligible_decisions=19239,
        eligible_pit_now=620,
    ),
    DevelopmentSeasonTotals(
        season=2024,
        sessions=24,
        eligible_decisions=20488,
        eligible_pit_now=596,
    ),
)


def temporal_fold(
    fold_id: str,
) -> TemporalFold:
    """Return one declared temporal fold."""
    for fold in TEMPORAL_FOLDS:
        if fold.fold_id == fold_id:
            return fold

    raise DatasetContractError(
        f"unknown temporal fold {fold_id!r}"
    )