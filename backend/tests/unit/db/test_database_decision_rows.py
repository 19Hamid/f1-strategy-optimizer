"""Tests for decision-row database persistence."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Double,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db import (
    DATABASE_SCHEMA_NAME,
    DECISION_ROW_SOURCE_COLUMN_MAP,
    DECISION_ROW_TABLE_NAME,
    Base,
    DecisionRow,
)

EXPECTED_SOURCE_COLUMNS = (
    "decision_id",
    "session_id",
    "season",
    "round_number",
    "session_type",
    "event_name",
    "driver",
    "driver_number",
    "team",
    "decision_lap",
    "decision_time_seconds",
    "source_row_number",
    "dataset_contract_version",
    "cleaning_rule_version",
    "processed_contract_version",
    "current_compound",
    "tyre_age_laps",
    "current_stint_number",
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
    "previous_track_status",
    "weather_observation_time_seconds",
    "weather_age_seconds",
    "air_temperature_celsius",
    "humidity_percent",
    "pressure_mbar",
    "track_temperature_celsius",
    "wind_direction_degrees",
    "wind_speed_mps",
    "rainfall",
    "has_consecutive_previous_lap",
    "weather_available_by_decision",
    "previous_lap_not_pit_commitment",
    "state_reconstruction_consistent",
    "supported_dry_compound",
    "valid_current_tyre_age",
    "current_stint_identified",
    "dry_at_decision",
    "previous_lap_green",
    "minimum_history_available",
    "previous_position_available",
    "is_decision_eligible",
    "decision_exclusion_count",
    "decision_exclusion_reasons",
)


def _table():
    """Return the registered decision-row table."""
    return Base.metadata.tables[
        (
            f"{DATABASE_SCHEMA_NAME}."
            f"{DECISION_ROW_TABLE_NAME}"
        )
    ]


def _check_names() -> set[str]:
    """Return deterministic check names."""
    return {
        str(constraint.name)
        for constraint in _table().constraints
        if isinstance(
            constraint,
            CheckConstraint,
        )
    }


def _check_sql(suffix: str) -> str:
    """Return SQL text for one named check."""
    constraint = next(
        constraint
        for constraint in _table().constraints
        if isinstance(
            constraint,
            CheckConstraint,
        )
        and str(constraint.name).endswith(suffix)
    )

    return str(constraint.sqltext)


def test_decision_row_table_is_registered() -> None:
    """The model maps to the frozen table name."""
    assert DecisionRow.__tablename__ == "decision_rows"
    assert DECISION_ROW_TABLE_NAME == "decision_rows"
    assert _table().name == "decision_rows"


def test_source_column_map_is_complete() -> None:
    """All 55 supplied decision fields map once."""
    assert tuple(
        DECISION_ROW_SOURCE_COLUMN_MAP
    ) == EXPECTED_SOURCE_COLUMNS
    assert len(DECISION_ROW_SOURCE_COLUMN_MAP) == 55
    assert set(
        DECISION_ROW_SOURCE_COLUMN_MAP
    ) == set(
        DECISION_ROW_SOURCE_COLUMN_MAP.values()
    )


def test_database_preserves_all_57_fields() -> None:
    """Fifty-five source fields plus two keys are stored."""
    database_columns = set(_table().columns.keys())

    assert set(
        DECISION_ROW_SOURCE_COLUMN_MAP.values()
    ) <= database_columns
    assert database_columns - set(
        DECISION_ROW_SOURCE_COLUMN_MAP.values()
    ) == {
        "processed_partition_id",
        "driver_id",
    }
    assert len(database_columns) == 57


def test_decision_row_primary_key_is_exact() -> None:
    """Dataset version and canonical decision form the key."""
    assert tuple(
        column.name
        for column in _table().primary_key.columns
    ) == (
        "dataset_contract_version",
        "decision_id",
    )


def test_decision_row_natural_identity_is_unique() -> None:
    """A driver-lap decision cannot repeat in a version."""
    unique_columns = {
        tuple(
            column.name
            for column in constraint.columns
        )
        for constraint in _table().constraints
        if isinstance(
            constraint,
            UniqueConstraint,
        )
    }

    assert unique_columns == {
        (
            "dataset_contract_version",
            "session_id",
            "driver_id",
            "decision_lap",
        ),
    }


def test_decision_row_foreign_keys_are_exact() -> None:
    """Rows preserve dataset and processed-lap lineage."""
    targets = {
        foreign_key.target_fullname
        for foreign_key in _table().foreign_keys
    }

    assert targets == {
        (
            "f1_strategy.dataset_sessions."
            "dataset_contract_version"
        ),
        "f1_strategy.dataset_sessions.session_id",
        "f1_strategy.drivers.driver_code",
        (
            "f1_strategy.processed_laps."
            "processed_partition_id"
        ),
        "f1_strategy.processed_laps.source_row_number",
        (
            "f1_strategy."
            "processed_session_partitions."
            "processed_partition_id"
        ),
        (
            "f1_strategy."
            "processed_session_partitions."
            "session_id"
        ),
        (
            "f1_strategy.session_participants."
            "driver_id"
        ),
        (
            "f1_strategy.session_participants."
            "session_id"
        ),
        "f1_strategy.teams.team_name",
    }

    composite_foreign_keys = {
        tuple(
            element.parent.name
            for element in constraint.elements
        )
        for constraint in _table().constraints
        if isinstance(
            constraint,
            ForeignKeyConstraint,
        )
        and len(constraint.elements) > 1
    }

    assert composite_foreign_keys == {
        (
            "dataset_contract_version",
            "session_id",
        ),
        (
            "processed_partition_id",
            "session_id",
        ),
        (
            "session_id",
            "driver_id",
        ),
        (
            "processed_partition_id",
            "source_row_number",
        ),
    }


def test_decision_row_nullability_matches_contract() -> None:
    """Only explicitly unavailable past state is nullable."""
    nullable_columns = {
        column.name
        for column in _table().columns
        if column.nullable
    }

    assert nullable_columns == {
        "current_compound",
        "tyre_age_laps",
        "current_stint_number",
        "current_stint_laps_completed",
        "previous_position",
        "previous_lap_time_seconds",
        "previous_sector1_time_seconds",
        "previous_sector2_time_seconds",
        "previous_sector3_time_seconds",
        "rolling_lap_time_median_3",
        "rolling_lap_time_median_5",
        "rolling_lap_time_std_5",
        "rolling_lap_time_trend_5",
        "previous_track_status",
    }


def test_decision_row_physical_types_preserve_meaning() -> None:
    """Counts, ordinals, measurements and reasons stay distinct."""
    for column_name in (
        "processed_partition_id",
        "driver_id",
        "source_row_number",
        "current_stint_laps_completed",
        "completed_pit_stops",
        "eligible_laps_completed",
        "decision_exclusion_count",
    ):
        assert isinstance(
            _table().c[column_name].type,
            BigInteger,
        )

    for column_name in (
        "season",
        "round_number",
        "decision_lap",
        "tyre_age_laps",
        "current_stint_number",
        "previous_position",
        "wind_direction_degrees",
    ):
        assert isinstance(
            _table().c[column_name].type,
            SmallInteger,
        )

    for column_name in (
        "decision_time_seconds",
        "weather_observation_time_seconds",
        "weather_age_seconds",
        "rolling_lap_time_trend_5",
    ):
        assert isinstance(
            _table().c[column_name].type,
            Double,
        )

    assert isinstance(
        _table().c.decision_exclusion_reasons.type,
        Text,
    )


def test_identity_and_measurement_checks_exist() -> None:
    """Identifiers and bounded measurements are protected."""
    required = {
        "ck_decision_rows_canonical_session_identity",
        "ck_decision_rows_canonical_decision_identity",
        "ck_decision_rows_decision_lap_positive",
        "ck_decision_rows_decision_time_non_negative",
        "ck_decision_rows_source_row_non_negative",
        "ck_decision_rows_humidity_range",
        "ck_decision_rows_pressure_positive",
        "ck_decision_rows_wind_direction_range",
        "ck_decision_rows_wind_speed_non_negative",
    }

    assert required <= _check_names()
    assert ">= 2" in _check_sql(
        "decision_lap_positive"
    )


def test_past_state_availability_checks_exist() -> None:
    """Availability flags agree with stored past state."""
    required = {
        "ck_decision_rows_tyre_age_validity",
        "ck_decision_rows_current_stint_availability",
        "ck_decision_rows_previous_position_availability",
        "ck_decision_rows_minimum_history_balance",
        "ck_decision_rows_rolling_history_availability",
        "ck_decision_rows_previous_target_availability",
        "ck_decision_rows_weather_availability_boundary",
        "ck_decision_rows_dry_decision_balance",
        "ck_decision_rows_previous_green_balance",
        "ck_decision_rows_dry_compound_balance",
    }

    assert required <= _check_names()
    assert "IS NOT NULL" in _check_sql(
        "rolling_history_availability"
    )
    assert "IS NOT NULL" in _check_sql(
        "previous_target_availability"
    )


def test_eligibility_and_exclusions_stay_balanced() -> None:
    """Eligibility cannot disagree with its audit evidence."""
    required = {
        "ck_decision_rows_eligibility_conditions",
        "ck_decision_rows_exclusion_count_non_negative",
        "ck_decision_rows_eligibility_exclusion_balance",
    }

    assert required <= _check_names()
    eligibility_sql = _check_sql(
        "eligibility_conditions"
    )

    for condition in (
        "has_consecutive_previous_lap",
        "weather_available_by_decision",
        "previous_lap_not_pit_commitment",
        "state_reconstruction_consistent",
        "supported_dry_compound",
        "valid_current_tyre_age",
        "current_stint_identified",
        "dry_at_decision",
        "previous_lap_green",
        "minimum_history_available",
        "previous_position_available",
    ):
        assert condition in eligibility_sql


def test_decision_row_indexes_cover_access_paths() -> None:
    """Driver-lap and eligible-feature queries are indexed."""
    indexes = {
        str(index.name): index
        for index in _table().indexes
        if isinstance(index, Index)
    }

    assert set(indexes) == {
        "ix_decision_rows_session_driver_lap",
        "ix_decision_rows_eligible",
    }
    assert tuple(
        column.name
        for column in indexes[
            "ix_decision_rows_session_driver_lap"
        ].columns
    ) == (
        "session_id",
        "driver_id",
        "decision_lap",
    )
    assert str(
        indexes[
            "ix_decision_rows_eligible"
        ].dialect_options[
            "postgresql"
        ]["where"]
    ) == "is_decision_eligible"


def test_decision_row_compiles_for_postgresql() -> None:
    """The complete decision table produces PostgreSQL DDL."""
    dialect = postgresql.dialect()
    ddl = str(
        CreateTable(
            _table()
        ).compile(
            dialect=dialect
        )
    )
    eligible_index = next(
        index
        for index in _table().indexes
        if str(index.name)
        == "ix_decision_rows_eligible"
    )
    index_ddl = str(
        CreateIndex(
            eligible_index
        ).compile(
            dialect=dialect
        )
    )

    assert "CREATE TABLE" in ddl
    assert "f1_strategy.decision_rows" in ddl
    assert (
        "REFERENCES f1_strategy.processed_laps"
        in ddl
    )
    assert "is_decision_eligible" in ddl
    assert "WHERE is_decision_eligible" in index_ddl
