"""Tests for reconstructed pit-event database persistence."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Double,
    ForeignKeyConstraint,
    Index,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.db import (
    DATABASE_SCHEMA_NAME,
    RECONSTRUCTED_PIT_EVENT_SOURCE_COLUMN_MAP,
    RECONSTRUCTED_PIT_EVENT_TABLE_NAME,
    Base,
    ReconstructedPitEvent,
)

EXPECTED_SOURCE_COLUMNS = (
    "pit_event_id",
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
    "pit_in_time_seconds",
    "pit_out_time_seconds",
    "observed_pit_lane_duration_seconds",
    "entry_track_status",
    "exit_track_status",
    "is_stint_change",
    "is_compound_change",
    "is_green_flag_pair",
    "is_dry_compound_pair",
    "is_interrupted_duration",
    "is_complete",
    "is_duration_analysis_candidate",
    "warning_count",
    "warnings",
)


def _table():
    """Return the registered reconstructed pit-event table."""
    return Base.metadata.tables[
        (
            f"{DATABASE_SCHEMA_NAME}."
            f"{RECONSTRUCTED_PIT_EVENT_TABLE_NAME}"
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


def test_reconstructed_pit_event_table_is_registered() -> None:
    """The model maps to the frozen table name."""
    assert (
        ReconstructedPitEvent.__tablename__
        == "reconstructed_pit_events"
    )
    assert (
        RECONSTRUCTED_PIT_EVENT_TABLE_NAME
        == "reconstructed_pit_events"
    )
    assert _table().name == "reconstructed_pit_events"


def test_source_column_map_is_complete() -> None:
    """All 30 reconstructed source fields map once."""
    assert tuple(
        RECONSTRUCTED_PIT_EVENT_SOURCE_COLUMN_MAP
    ) == EXPECTED_SOURCE_COLUMNS
    assert (
        len(
            RECONSTRUCTED_PIT_EVENT_SOURCE_COLUMN_MAP
        )
        == 30
    )
    assert (
        set(
            RECONSTRUCTED_PIT_EVENT_SOURCE_COLUMN_MAP
        )
        == set(
            RECONSTRUCTED_PIT_EVENT_SOURCE_COLUMN_MAP.values()
        )
    )


def test_database_preserves_all_33_fields() -> None:
    """Thirty source fields plus three keys are stored."""
    database_columns = set(
        _table().columns.keys()
    )

    assert set(
        RECONSTRUCTED_PIT_EVENT_SOURCE_COLUMN_MAP.values()
    ) <= database_columns
    assert database_columns - set(
        RECONSTRUCTED_PIT_EVENT_SOURCE_COLUMN_MAP.values()
    ) == {
        "processed_partition_id",
        "session_id",
        "driver_id",
    }
    assert len(database_columns) == 33


def test_reconstructed_pit_event_primary_key_is_exact() -> None:
    """Partition and stable event identity form the key."""
    assert tuple(
        column.name
        for column in _table().primary_key.columns
    ) == (
        "processed_partition_id",
        "pit_event_id",
    )


def test_reconstructed_pit_event_foreign_keys_are_exact() -> None:
    """Pit events reference provenance and participation."""
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


def test_event_shape_and_candidate_checks_exist() -> None:
    """Partial events and eligible durations stay distinct."""
    required = {
        (
            "ck_reconstructed_pit_events_"
            "event_type_allowed"
        ),
        (
            "ck_reconstructed_pit_events_"
            "event_type_marker_shape"
        ),
        (
            "ck_reconstructed_pit_events_"
            "pit_in_lap_positive"
        ),
        (
            "ck_reconstructed_pit_events_"
            "pit_out_lap_positive"
        ),
        (
            "ck_reconstructed_pit_events_"
            "complete_event_requirements"
        ),
        (
            "ck_reconstructed_pit_events_"
            "duration_candidate_requirements"
        ),
        (
            "ck_reconstructed_pit_events_"
            "warning_encoding_balance"
        ),
        (
            "ck_reconstructed_pit_events_"
            "canonical_session_identity"
        ),
    }

    assert required <= _check_names()

    complete_check = next(
        constraint
        for constraint in _table().constraints
        if isinstance(
            constraint,
            CheckConstraint,
        )
        and str(constraint.name).endswith(
            "complete_event_requirements"
        )
    )

    assert (
        "observed_pit_lane_duration_seconds IS NOT NULL"
        in str(complete_check.sqltext)
    )


def test_partial_event_fields_are_nullable() -> None:
    """Entry-only and exit-only rows remain representable."""
    nullable_columns = (
        "pit_in_lap",
        "pit_out_lap",
        "stint_before",
        "stint_after",
        "compound_before",
        "compound_after",
        "tyre_life_before",
        "tyre_life_after",
        "pit_in_time_seconds",
        "pit_out_time_seconds",
        "observed_pit_lane_duration_seconds",
        "entry_track_status",
        "exit_track_status",
        "is_stint_change",
        "is_compound_change",
    )

    assert all(
        _table().c[column_name].nullable
        for column_name in nullable_columns
    )


def test_pit_duration_preserves_observed_measurement() -> None:
    """Observed pit-lane duration remains a nullable double."""
    column = _table().c[
        "observed_pit_lane_duration_seconds"
    ]

    assert isinstance(column.type, Double)
    assert column.nullable is True
    assert isinstance(
        _table().c.warning_count.type,
        BigInteger,
    )


def test_reconstructed_pit_event_index_covers_access_path() -> None:
    """Session-driver pit-lap queries are indexed."""
    index_names = {
        str(index.name)
        for index in _table().indexes
        if isinstance(index, Index)
    }

    assert index_names == {
        (
            "ix_reconstructed_pit_events_"
            "session_driver_pit_lap"
        ),
    }


def test_reconstructed_pit_event_compiles_for_postgresql() -> None:
    """The complete pit-event table produces PostgreSQL DDL."""
    ddl = str(
        CreateTable(
            _table()
        ).compile(
            dialect=postgresql.dialect()
        )
    )

    assert "CREATE TABLE" in ddl
    assert (
        "f1_strategy.reconstructed_pit_events"
        in ddl
    )
    assert "ENTRY_ONLY" in ddl
    assert "EXIT_ONLY" in ddl
    assert "observed_pit_lane_duration_seconds" in ddl
    assert (
        "REFERENCES "
        "f1_strategy."
        "processed_session_partitions"
        in ddl
    )
