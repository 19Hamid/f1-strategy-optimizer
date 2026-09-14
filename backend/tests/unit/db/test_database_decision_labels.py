"""Tests for separated decision-label database persistence."""

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
    DECISION_LABEL_SOURCE_COLUMN_MAP,
    DECISION_LABEL_TABLE_NAME,
    Base,
    DecisionLabel,
)

EXPECTED_SOURCE_COLUMNS = (
    "decision_id",
    "session_id",
    "season",
    "round_number",
    "session_type",
    "driver",
    "decision_lap",
    "historical_action",
    "did_pit",
    "pit_event_id",
    "is_lap_time_target_eligible",
    "lap_time_target_seconds",
    "lap_target_exclusion_count",
    "lap_target_exclusion_reasons",
    "dataset_contract_version",
)


def _table():
    """Return the registered decision-label table."""
    return Base.metadata.tables[
        (
            f"{DATABASE_SCHEMA_NAME}."
            f"{DECISION_LABEL_TABLE_NAME}"
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


def test_decision_label_table_is_registered() -> None:
    """The model maps to the frozen table name."""
    assert DecisionLabel.__tablename__ == "decision_labels"
    assert DECISION_LABEL_TABLE_NAME == "decision_labels"
    assert _table().name == "decision_labels"


def test_source_column_map_is_complete() -> None:
    """All 15 supplied label fields map once."""
    assert tuple(
        DECISION_LABEL_SOURCE_COLUMN_MAP
    ) == EXPECTED_SOURCE_COLUMNS
    assert len(DECISION_LABEL_SOURCE_COLUMN_MAP) == 15
    assert set(
        DECISION_LABEL_SOURCE_COLUMN_MAP
    ) == set(
        DECISION_LABEL_SOURCE_COLUMN_MAP.values()
    )


def test_database_preserves_all_16_fields() -> None:
    """Fifteen source fields plus one lineage key are stored."""
    database_columns = set(_table().columns.keys())

    assert set(
        DECISION_LABEL_SOURCE_COLUMN_MAP.values()
    ) <= database_columns
    assert database_columns - set(
        DECISION_LABEL_SOURCE_COLUMN_MAP.values()
    ) == {
        "processed_partition_id",
    }
    assert len(database_columns) == 16


def test_decision_label_primary_key_is_exact() -> None:
    """Dataset version and decision identity form the key."""
    assert tuple(
        column.name
        for column in _table().primary_key.columns
    ) == (
        "dataset_contract_version",
        "decision_id",
    )


def test_one_label_owns_each_reconstructed_pit_event() -> None:
    """A represented pit event cannot label two decisions."""
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
            "processed_partition_id",
            "pit_event_id",
        ),
    }


def test_decision_label_foreign_keys_are_exact() -> None:
    """Labels reference decisions, datasets and pit events."""
    targets = {
        foreign_key.target_fullname
        for foreign_key in _table().foreign_keys
    }

    assert targets == {
        (
            "f1_strategy.decision_rows."
            "dataset_contract_version"
        ),
        "f1_strategy.decision_rows.decision_id",
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
            "decision_id",
        ),
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
    }


def test_label_nullability_matches_contract() -> None:
    """Only the optional pit link and target are nullable."""
    nullable_columns = {
        column.name
        for column in _table().columns
        if column.nullable
    }

    assert nullable_columns == {
        "pit_event_id",
        "lap_time_target_seconds",
    }


def test_label_physical_types_preserve_meaning() -> None:
    """Counts, ordinals, targets and reasons stay distinct."""
    for column_name in (
        "processed_partition_id",
        "lap_target_exclusion_count",
    ):
        assert isinstance(
            _table().c[column_name].type,
            BigInteger,
        )

    for column_name in (
        "season",
        "round_number",
        "decision_lap",
    ):
        assert isinstance(
            _table().c[column_name].type,
            SmallInteger,
        )

    assert isinstance(
        _table().c.lap_time_target_seconds.type,
        Double,
    )
    assert isinstance(
        _table().c.lap_target_exclusion_reasons.type,
        Text,
    )


def test_identity_and_action_checks_exist() -> None:
    """Canonical identity and historical action agree."""
    required = {
        "ck_decision_labels_canonical_session_identity",
        "ck_decision_labels_canonical_decision_identity",
        "ck_decision_labels_decision_lap_has_previous",
        "ck_decision_labels_historical_action_allowed",
        "ck_decision_labels_historical_action_balance",
        "ck_decision_labels_pit_event_presence",
    }

    assert required <= _check_names()
    action_sql = _check_sql(
        "historical_action_balance"
    )

    assert "PIT_NOW" in action_sql
    assert "STAY_OUT" in action_sql
    assert "did_pit" in action_sql
    assert "pit_event_id IS NOT NULL" in _check_sql(
        "pit_event_presence"
    )


def test_target_and_exclusion_checks_exist() -> None:
    """Target availability and quality reasons stay balanced."""
    required = {
        "ck_decision_labels_lap_target_availability",
        "ck_decision_labels_exclusion_count_non_negative",
        "ck_decision_labels_target_exclusion_balance",
    }

    assert required <= _check_names()
    target_sql = _check_sql(
        "lap_target_availability"
    )

    assert "lap_time_target_seconds IS NOT NULL" in target_sql
    assert "lap_time_target_seconds > 0" in target_sql
    assert "lap_time_target_seconds IS NULL" in target_sql


def test_decision_label_indexes_cover_access_paths() -> None:
    """Decision, action and target queries are indexed."""
    indexes = {
        str(index.name): index
        for index in _table().indexes
        if isinstance(index, Index)
    }

    assert set(indexes) == {
        "ix_decision_labels_session_driver_lap",
        "ix_decision_labels_action",
        "ix_decision_labels_lap_target_eligible",
    }
    assert tuple(
        column.name
        for column in indexes[
            "ix_decision_labels_session_driver_lap"
        ].columns
    ) == (
        "session_id",
        "driver",
        "decision_lap",
    )
    assert str(
        indexes[
            "ix_decision_labels_lap_target_eligible"
        ].dialect_options[
            "postgresql"
        ]["where"]
    ) == "is_lap_time_target_eligible"


def test_decision_label_compiles_for_postgresql() -> None:
    """The complete label table produces PostgreSQL DDL."""
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
        == "ix_decision_labels_lap_target_eligible"
    )
    index_ddl = str(
        CreateIndex(
            target_index
        ).compile(
            dialect=dialect
        )
    )

    assert "CREATE TABLE" in ddl
    assert "f1_strategy.decision_labels" in ddl
    assert "REFERENCES f1_strategy.decision_rows" in ddl
    assert (
        "REFERENCES "
        "f1_strategy.reconstructed_pit_events"
        in ddl
    )
    assert "WHERE is_lap_time_target_eligible" in index_ddl
