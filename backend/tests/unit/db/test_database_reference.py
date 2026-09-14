"""Tests for Formula 1 database reference entities."""

from sqlalchemy import (
    CheckConstraint,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.db import (
    DATABASE_SCHEMA_NAME,
    REFERENCE_TABLE_NAMES,
    Base,
    Circuit,
    Driver,
    Event,
    RaceSession,
    Season,
    SessionParticipant,
    Team,
)


def _table(table_name: str):
    """Return one registered schema-qualified table."""
    return Base.metadata.tables[
        (
            f"{DATABASE_SCHEMA_NAME}."
            f"{table_name}"
        )
    ]


def _primary_key_columns(
    table_name: str,
) -> tuple[str, ...]:
    """Return ordered primary-key column names."""
    return tuple(
        column.name
        for column in _table(
            table_name
        ).primary_key.columns
    )


def _unique_column_sets(
    table_name: str,
) -> set[tuple[str, ...]]:
    """Return every declared uniqueness column set."""
    return {
        tuple(
            column.name
            for column in constraint.columns
        )
        for constraint in _table(
            table_name
        ).constraints
        if isinstance(
            constraint,
            UniqueConstraint,
        )
    }


def _check_names(
    table_name: str,
) -> set[str]:
    """Return deterministic check-constraint names."""
    return {
        str(constraint.name)
        for constraint in _table(
            table_name
        ).constraints
        if isinstance(
            constraint,
            CheckConstraint,
        )
    }


def _index_names(
    table_name: str,
) -> set[str]:
    """Return explicit database index names."""
    return {
        str(index.name)
        for index in _table(
            table_name
        ).indexes
        if isinstance(index, Index)
    }


def test_all_reference_tables_are_registered() -> None:
    """The metadata contains every planned reference entity."""
    registered = {
        table.name
        for table in Base.metadata.tables.values()
    }

    assert set(
        REFERENCE_TABLE_NAMES
    ) <= registered
    assert len(REFERENCE_TABLE_NAMES) == 7


def test_reference_model_table_names_are_exact() -> None:
    """ORM models map to the frozen physical names."""
    models = (
        Season,
        Circuit,
        Event,
        RaceSession,
        Driver,
        Team,
        SessionParticipant,
    )

    assert tuple(
        model.__tablename__
        for model in models
    ) == REFERENCE_TABLE_NAMES


def test_reference_primary_keys_are_exact() -> None:
    """Reference identities cannot drift silently."""
    assert _primary_key_columns(
        "seasons"
    ) == ("season",)
    assert _primary_key_columns(
        "circuits"
    ) == ("circuit_id",)
    assert _primary_key_columns(
        "events"
    ) == ("event_id",)
    assert _primary_key_columns(
        "race_sessions"
    ) == ("session_id",)
    assert _primary_key_columns(
        "drivers"
    ) == ("driver_id",)
    assert _primary_key_columns(
        "teams"
    ) == ("team_id",)
    assert _primary_key_columns(
        "session_participants"
    ) == (
        "session_id",
        "driver_id",
    )


def test_reference_natural_keys_are_unique() -> None:
    """Source-observed identities receive database protection."""
    assert (
        "country",
        "location",
    ) in _unique_column_sets(
        "circuits"
    )
    assert (
        "season",
        "round_number",
    ) in _unique_column_sets(
        "events"
    )
    assert (
        "event_id",
        "season",
        "round_number",
    ) in _unique_column_sets(
        "events"
    )
    assert (
        "event_id",
        "session_type",
    ) in _unique_column_sets(
        "race_sessions"
    )
    assert (
        "season",
        "round_number",
        "session_type",
    ) in _unique_column_sets(
        "race_sessions"
    )
    assert (
        "driver_code",
    ) in _unique_column_sets(
        "drivers"
    )
    assert (
        "team_name",
    ) in _unique_column_sets(
        "teams"
    )
    assert (
        "session_id",
        "driver_number",
    ) in _unique_column_sets(
        "session_participants"
    )


def test_reference_foreign_keys_are_exact() -> None:
    """Every dimension relationship targets its parent."""
    targets = {
        foreign_key.target_fullname
        for table_name in (
            "events",
            "race_sessions",
            "session_participants",
        )
        for foreign_key in _table(
            table_name
        ).foreign_keys
    }

    assert targets == {
        (
            "f1_strategy.circuits."
            "circuit_id"
        ),
        (
            "f1_strategy.drivers."
            "driver_id"
        ),
        (
            "f1_strategy.events."
            "event_id"
        ),
        (
            "f1_strategy.events."
            "round_number"
        ),
        (
            "f1_strategy.events."
            "season"
        ),
        (
            "f1_strategy.race_sessions."
            "session_id"
        ),
        (
            "f1_strategy.seasons."
            "season"
        ),
        (
            "f1_strategy.teams."
            "team_id"
        ),
    }


def test_race_session_checks_are_present() -> None:
    """Race identities and session types fail closed."""
    assert _check_names(
        "race_sessions"
    ) == {
        (
            "ck_race_sessions_"
            "canonical_identifier"
        ),
        (
            "ck_race_sessions_"
            "identifier_format"
        ),
        (
            "ck_race_sessions_"
            "race_session_only"
        ),
    }


def test_nullable_reference_fields_are_explicit() -> None:
    """Unavailable names remain null instead of being invented."""
    assert (
        _table(
            "circuits"
        ).c.circuit_name.nullable
        is True
    )
    assert (
        _table(
            "drivers"
        ).c.driver_name.nullable
        is True
    )

    assert (
        _table(
            "circuits"
        ).c.country.nullable
        is False
    )
    assert (
        _table(
            "events"
        ).c.official_event_name.nullable
        is False
    )


def test_reference_indexes_cover_access_paths() -> None:
    """Expected event, session and participation indexes exist."""
    assert _index_names(
        "events"
    ) == {
        (
            "ix_events_"
            "circuit_id_season"
        ),
        (
            "ix_events_"
            "season_event_date"
        ),
    }
    assert _index_names(
        "race_sessions"
    ) == {
        "ix_race_sessions_event_id",
        (
            "ix_race_sessions_"
            "season_round_number"
        ),
    }
    assert _index_names(
        "session_participants"
    ) == {
        (
            "ix_session_participants_"
            "driver_id"
        ),
        (
            "ix_session_participants_"
            "team_id_session_id"
        ),
    }


def test_reference_tables_compile_for_postgresql() -> None:
    """Every reference table produces PostgreSQL DDL."""
    dialect = postgresql.dialect()

    compiled = {
        table_name: str(
            CreateTable(
                _table(table_name)
            ).compile(
                dialect=dialect
            )
        )
        for table_name in REFERENCE_TABLE_NAMES
    }

    assert all(compiled.values())
    assert (
        "GENERATED BY DEFAULT AS IDENTITY"
        in compiled["circuits"]
    )
    assert (
        "GENERATED BY DEFAULT AS IDENTITY"
        in compiled["events"]
    )
    assert (
        "GENERATED BY DEFAULT AS IDENTITY"
        in compiled["drivers"]
    )
    assert (
        "GENERATED BY DEFAULT AS IDENTITY"
        in compiled["teams"]
    )
    assert (
        "CHECK (session_type = 'R')"
        in compiled["race_sessions"]
    )
    assert (
        'REFERENCES f1_strategy.events'
        in compiled["race_sessions"]
    )