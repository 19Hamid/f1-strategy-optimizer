"""Tests for separated pit-duration target persistence."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Double,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    Text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db import (
    DATABASE_SCHEMA_NAME,
    PIT_DURATION_OBSERVATION_SOURCE_COLUMN_MAP,
    PIT_DURATION_OBSERVATION_TABLE_NAME,
    Base,
    PitDurationObservation,
)

EXPECTED_SOURCE_COLUMNS = (
    "pit_event_id",
    "session_id",
    "season",
    "round_number",
    "session_type",
    "event_name",
    "driver",
    "team",
    "event_type",
    "pit_in_lap",
    "pit_out_lap",
    "stint_before",
    "stint_after",
    "compound_before",
    "compound_after",
    "tyre_life_before",
    "tyre_life_after",
    "is_stint_change",
    "is_compound_change",
    "is_complete",
    "is_green_flag_pair",
    "is_dry_weather_pair",
    "is_interrupted_duration",
    "is_pit_duration_target_eligible",
    "pit_duration_target_seconds",
    "pit_duration_exclusion_count",
    "pit_duration_exclusion_reasons",
    "dataset_contract_version",
)


def _table():
    """Return the registered pit-duration observation table."""
    return Base.metadata.tables[
        (
            f"{DATABASE_SCHEMA_NAME}."
            f"{PIT_DURATION_OBSERVATION_TABLE_NAME}"
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
    """Return SQL for the check ending in one suffix."""
    constraint = next(
        constraint
        for constraint in _table().constraints
        if isinstance(
            constraint,
            CheckConstraint,
        )
        and str(constraint.name).endswith(
            suffix
        )
    )
    return str(constraint.sqltext)


def test_pit_duration_observation_table_is_registered() -> None:
    """The model maps to the frozen table name."""
    assert (
        PitDurationObservation.__tablename__
        == "pit_duration_observations"
    )
    assert (
        PIT_DURATION_OBSERVATION_TABLE_NAME
        == "pit_duration_observations"
    )
    assert _table().name == "pit_duration_observations"


def test_source_column_map_is_complete() -> None:
    """All 28 pit-duration artifact fields map once."""
    assert tuple(
        PIT_DURATION_OBSERVATION_SOURCE_COLUMN_MAP
    ) == EXPECTED_SOURCE_COLUMNS
    assert len(
        PIT_DURATION_OBSERVATION_SOURCE_COLUMN_MAP
    ) == 28
    assert set(
        PIT_DURATION_OBSERVATION_SOURCE_COLUMN_MAP
    ) == set(
        PIT_DURATION_OBSERVATION_SOURCE_COLUMN_MAP.values()
    )


def test_database_preserves_all_30_fields() -> None:
    """Twenty-eight source fields plus two keys are stored."""
    database_columns = set(_table().columns.keys())

    assert set(
        PIT_DURATION_OBSERVATION_SOURCE_COLUMN_MAP.values()
    ) <= database_columns
    assert database_columns - set(
        PIT_DURATION_OBSERVATION_SOURCE_COLUMN_MAP.values()
    ) == {
        "processed_partition_id",
        "driver_id",
    }
    assert len(database_columns) == 30


def test_pit_duration_primary_key_is_exact() -> None:
    """Dataset version and pit-event identity form the key."""
    assert tuple(
        column.name
        for column in _table().primary_key.columns
    ) == (
        "dataset_contract_version",
        "pit_event_id",
    )


def test_pit_duration_foreign_keys_are_exact() -> None:
    """Targets reference datasets, source events and drivers."""
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
        (
            "f1_strategy.dataset_sessions."
            "processed_partition_id"
        ),
        "f1_strategy.drivers.driver_code",
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
            "f1_strategy.reconstructed_pit_events."
            "processed_partition_id"
        ),
        (
            "f1_strategy.reconstructed_pit_events."
            "pit_event_id"
        ),
        (
            "f1_strategy.session_participants."
            "session_id"
        ),
        (
            "f1_strategy.session_participants."
            "driver_id"
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
            "dataset_contract_version",
            "processed_partition_id",
        ),
        (
            "processed_partition_id",
            "session_id",
        ),
        (
            "processed_partition_id",
            "pit_event_id",
        ),
        (
            "session_id",
            "driver_id",
        ),
    }


def test_pit_duration_nullability_matches_contract() -> None:
    """Only partial-event context and the target are nullable."""
    nullable_columns = {
        column.name
        for column in _table().columns
        if column.nullable
    }

    assert nullable_columns == {
        "pit_in_lap",
        "pit_out_lap",
        "stint_before",
        "stint_after",
        "compound_before",
        "compound_after",
        "tyre_life_before",
        "tyre_life_after",
        "is_stint_change",
        "is_compound_change",
        "pit_duration_target_seconds",
    }


def test_pit_duration_physical_types_preserve_meaning() -> None:
    """Keys, ordinals, targets and reasons stay distinct."""
    for column_name in (
        "processed_partition_id",
        "driver_id",
        "pit_duration_exclusion_count",
    ):
        assert isinstance(
            _table().c[column_name].type,
            BigInteger,
        )

    for column_name in (
        "season",
        "round_number",
        "pit_in_lap",
        "pit_out_lap",
        "stint_before",
        "stint_after",
    ):
        assert isinstance(
            _table().c[column_name].type,
            SmallInteger,
        )

    for column_name in (
        "tyre_life_before",
        "tyre_life_after",
        "pit_duration_target_seconds",
    ):
        assert isinstance(
            _table().c[column_name].type,
            Double,
        )

    assert isinstance(
        _table().c.pit_duration_exclusion_reasons.type,
        Text,
    )


def test_event_shape_checks_preserve_partial_events() -> None:
    """Matched and partial event marker shapes remain distinct."""
    required = {
        (
            "ck_pit_duration_observations_"
            "event_type_allowed"
        ),
        (
            "ck_pit_duration_observations_"
            "event_type_marker_shape"
        ),
        (
            "ck_pit_duration_observations_"
            "complete_event_requirements"
        ),
        (
            "ck_pit_duration_observations_"
            "canonical_session_identity"
        ),
    }

    assert required <= _check_names()
    marker_sql = _check_sql(
        "event_type_marker_shape"
    )

    assert "MATCHED" in marker_sql
    assert "ENTRY_ONLY" in marker_sql
    assert "EXIT_ONLY" in marker_sql


def test_exact_target_eligibility_is_enforced() -> None:
    """Stored eligibility equals every frozen source condition."""
    sql = _check_sql(
        "exact_target_eligibility"
    )

    for fragment in (
        "is_complete",
        "is_stint_change IS TRUE",
        "is_green_flag_pair",
        "compound_before IS NOT NULL",
        "compound_after IS NOT NULL",
        "HARD",
        "MEDIUM",
        "SOFT",
        "is_dry_weather_pair",
        "NOT is_interrupted_duration",
    ):
        assert fragment in sql

    assert (
        "is_pit_duration_target_eligible ="
        in sql
    )


def test_target_and_exclusion_checks_exist() -> None:
    """Eligibility controls target and exclusion availability."""
    required = {
        (
            "ck_pit_duration_observations_"
            "target_availability"
        ),
        (
            "ck_pit_duration_observations_"
            "exclusion_count_non_negative"
        ),
        (
            "ck_pit_duration_observations_"
            "target_exclusion_balance"
        ),
    }

    assert required <= _check_names()
    target_sql = _check_sql(
        "target_availability"
    )

    assert "pit_duration_target_seconds IS NOT NULL" in target_sql
    assert "pit_duration_target_seconds > 0" in target_sql
    assert "pit_duration_target_seconds IS NULL" in target_sql


def test_pit_duration_indexes_cover_access_paths() -> None:
    """Source, session and eligible-target queries are indexed."""
    indexes = {
        str(index.name): index
        for index in _table().indexes
        if isinstance(index, Index)
    }

    assert set(indexes) == {
        (
            "ix_pit_duration_observations_"
            "session_driver_pit_lap"
        ),
        (
            "ix_pit_duration_observations_"
            "source_event"
        ),
        (
            "ix_pit_duration_observations_"
            "target_eligible"
        ),
    }
    assert tuple(
        column.name
        for column in indexes[
            "ix_pit_duration_observations_source_event"
        ].columns
    ) == (
        "processed_partition_id",
        "pit_event_id",
    )
    assert str(
        indexes[
            "ix_pit_duration_observations_target_eligible"
        ].dialect_options[
            "postgresql"
        ]["where"]
    ) == "is_pit_duration_target_eligible"


def test_pit_duration_compiles_for_postgresql() -> None:
    """The complete target table produces PostgreSQL DDL."""
    dialect = postgresql.dialect()
    ddl = str(
        CreateTable(
            _table()
        ).compile(
            dialect=dialect
        )
    )
    target_index = next(
        index
        for index in _table().indexes
        if str(index.name)
        == "ix_pit_duration_observations_target_eligible"
    )
    index_ddl = str(
        CreateIndex(
            target_index
        ).compile(
            dialect=dialect
        )
    )

    assert "CREATE TABLE" in ddl
    assert "f1_strategy.pit_duration_observations" in ddl
    assert (
        "REFERENCES "
        "f1_strategy.reconstructed_pit_events"
        in ddl
    )
    assert "WHERE is_pit_duration_target_eligible" in index_ddl
