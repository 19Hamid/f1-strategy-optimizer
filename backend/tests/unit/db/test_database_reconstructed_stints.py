"""Tests for reconstructed-stint database persistence."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.db import (
    DATABASE_SCHEMA_NAME,
    RECONSTRUCTED_STINT_SOURCE_COLUMN_MAP,
    RECONSTRUCTED_STINT_TABLE_NAME,
    Base,
    ReconstructedStint,
)

EXPECTED_SOURCE_COLUMNS = (
    "season",
    "round_number",
    "session_type",
    "event_name",
    "driver",
    "team",
    "stint_number",
    "compound",
    "start_lap",
    "end_lap",
    "recorded_laps",
    "start_tyre_life",
    "end_tyre_life",
    "is_first_stint",
    "is_last_stint",
    "boundary_before_verified",
    "boundary_after_verified",
    "is_complete",
    "warning_count",
    "warnings",
)


def _table():
    """Return the registered reconstructed-stint table."""
    return Base.metadata.tables[
        (
            f"{DATABASE_SCHEMA_NAME}."
            f"{RECONSTRUCTED_STINT_TABLE_NAME}"
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


def test_reconstructed_stint_table_is_registered() -> None:
    """The model maps to the frozen table name."""
    assert (
        ReconstructedStint.__tablename__
        == "reconstructed_stints"
    )
    assert (
        RECONSTRUCTED_STINT_TABLE_NAME
        == "reconstructed_stints"
    )
    assert _table().name == "reconstructed_stints"


def test_source_column_map_is_complete() -> None:
    """All 20 reconstructed fields map exactly once."""
    assert tuple(
        RECONSTRUCTED_STINT_SOURCE_COLUMN_MAP
    ) == EXPECTED_SOURCE_COLUMNS
    assert (
        len(
            RECONSTRUCTED_STINT_SOURCE_COLUMN_MAP
        )
        == 20
    )
    assert (
        set(
            RECONSTRUCTED_STINT_SOURCE_COLUMN_MAP
        )
        == set(
            RECONSTRUCTED_STINT_SOURCE_COLUMN_MAP.values()
        )
    )


def test_every_source_mapping_targets_a_column() -> None:
    """No source field maps to an imaginary column."""
    database_columns = set(
        _table().columns.keys()
    )

    assert set(
        RECONSTRUCTED_STINT_SOURCE_COLUMN_MAP.values()
    ) <= database_columns
    assert len(database_columns) == 23


def test_reconstructed_stint_primary_key_is_exact() -> None:
    """Partition, driver and stint form the key."""
    assert tuple(
        column.name
        for column in _table().primary_key.columns
    ) == (
        "processed_partition_id",
        "driver_id",
        "stint_number",
    )


def test_reconstructed_stint_foreign_keys_are_exact() -> None:
    """Stints reference provenance and participation."""
    targets = {
        foreign_key.target_fullname
        for foreign_key in _table().foreign_keys
    }

    assert targets == {
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
            "f1_strategy."
            "session_participants."
            "driver_id"
        ),
        (
            "f1_strategy."
            "session_participants."
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
    }

    assert (
        "processed_partition_id",
        "session_id",
    ) in composite_foreign_keys
    assert (
        "session_id",
        "driver_id",
    ) in composite_foreign_keys


def test_reconstructed_stint_checks_are_exact() -> None:
    """Stint and warning integrity fails closed."""
    required = {
        (
            "ck_reconstructed_stints_"
            "stint_number_positive"
        ),
        (
            "ck_reconstructed_stints_"
            "start_lap_positive"
        ),
        (
            "ck_reconstructed_stints_"
            "end_lap_positive"
        ),
        (
            "ck_reconstructed_stints_"
            "lap_range_ordered"
        ),
        (
            "ck_reconstructed_stints_"
            "recorded_laps_positive"
        ),
        (
            "ck_reconstructed_stints_"
            "warning_count_non_negative"
        ),
        (
            "ck_reconstructed_stints_"
            "completeness_warning_balance"
        ),
        (
            "ck_reconstructed_stints_"
            "canonical_session_identity"
        ),
    }

    assert required <= _check_names()


def test_reconstructed_stint_types_preserve_source() -> None:
    """Counts and optional measurements retain meaning."""
    assert isinstance(
        _table().c.processed_partition_id.type,
        BigInteger,
    )
    assert isinstance(
        _table().c.recorded_laps.type,
        BigInteger,
    )
    assert _table().c.compound.nullable is True
    assert _table().c.start_tyre_life.nullable is True
    assert _table().c.end_tyre_life.nullable is True


def test_reconstructed_stint_index_covers_access_path() -> None:
    """Session-driver stint queries use an explicit index."""
    index_names = {
        str(index.name)
        for index in _table().indexes
        if isinstance(index, Index)
    }

    assert index_names == {
        (
            "ix_reconstructed_stints_"
            "session_driver"
        ),
    }


def test_reconstructed_stint_compiles_for_postgresql() -> None:
    """The complete stint table produces PostgreSQL DDL."""
    ddl = str(
        CreateTable(
            _table()
        ).compile(
            dialect=postgresql.dialect()
        )
    )

    assert "CREATE TABLE" in ddl
    assert (
        "f1_strategy.reconstructed_stints"
        in ddl
    )
    assert "end_lap >= start_lap" in ddl
    assert (
        "REFERENCES "
        "f1_strategy."
        "processed_session_partitions"
        in ddl
    )
