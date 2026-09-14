"""Exercise database guarantees against a real PostgreSQL service."""

from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError

from app.db import (
    DATABASE_SCHEMA_NAME,
    Base,
    Circuit,
    Event,
    ImmutableRepository,
    ImmutableRowConflictError,
    Season,
    create_database_session_factory,
    database_transaction,
)

INITIAL_REVISION = "20260914_0001"

pytestmark = pytest.mark.postgresql


def _application_table_names() -> set[str]:
    """Return the exact ORM-owned table-name population."""
    return {table.name for table in Base.metadata.tables.values()}


def _include_application_schema(
    name: str | None,
    type_: str,
    _parent_names: dict[str, str | None],
) -> bool:
    """Avoid duplicate reflection through PostgreSQL's implicit user schema."""
    return type_ != "schema" or name == DATABASE_SCHEMA_NAME


def _constraint_name(error: IntegrityError) -> str | None:
    """Read the PostgreSQL constraint reported by psycopg."""
    diagnostic = getattr(error.orig, "diag", None)
    return getattr(diagnostic, "constraint_name", None)


def test_migration_upgrades_downgrades_and_reupgrades_empty_database(
    postgresql_engine: Engine,
    alembic_config: Config,
) -> None:
    """Prove the complete initial migration lifecycle on PostgreSQL."""
    command.upgrade(alembic_config, "head")

    inspector = sa.inspect(postgresql_engine)
    assert DATABASE_SCHEMA_NAME in inspector.get_schema_names()
    assert (
        set(inspector.get_table_names(schema=DATABASE_SCHEMA_NAME))
        == _application_table_names()
    )
    with postgresql_engine.connect() as connection:
        assert (
            connection.scalar(sa.text("SELECT version_num FROM public.alembic_version"))
            == INITIAL_REVISION
        )

    command.downgrade(alembic_config, "base")

    inspector = sa.inspect(postgresql_engine)
    assert DATABASE_SCHEMA_NAME not in inspector.get_schema_names()
    with postgresql_engine.connect() as connection:
        assert (
            connection.scalar(sa.text("SELECT count(*) FROM public.alembic_version"))
            == 0
        )

    command.upgrade(alembic_config, "head")

    assert (
        set(sa.inspect(postgresql_engine).get_table_names(schema=DATABASE_SCHEMA_NAME))
        == _application_table_names()
    )


def test_live_postgresql_schema_has_no_orm_migration_drift(
    migrated_postgresql_engine: Engine,
) -> None:
    """Compare migrated PostgreSQL objects with the ORM metadata."""
    with migrated_postgresql_engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "include_schemas": True,
                "include_name": _include_application_schema,
                "compare_type": True,
                "compare_server_default": True,
            },
        )
        differences = compare_metadata(context, Base.metadata)

    assert differences == []


def test_postgresql_rejects_check_unique_and_foreign_key_violations(
    migrated_postgresql_engine: Engine,
) -> None:
    """Exercise each core relational constraint family physically."""
    with (
        pytest.raises(IntegrityError) as check_error,
        migrated_postgresql_engine.begin() as connection,
    ):
        connection.execute(sa.insert(Season).values(season=99))
    assert _constraint_name(check_error.value) == "ck_seasons_four_digit"

    with migrated_postgresql_engine.begin() as connection:
        connection.execute(
            sa.insert(Circuit).values(
                country="Bahrain",
                location="Sakhir",
                circuit_name=None,
            )
        )
    with (
        pytest.raises(IntegrityError) as unique_error,
        migrated_postgresql_engine.begin() as connection,
    ):
        connection.execute(
            sa.insert(Circuit).values(
                country="Bahrain",
                location="Sakhir",
                circuit_name=None,
            )
        )
    assert _constraint_name(unique_error.value) == ("uq_circuits_country_location")

    with migrated_postgresql_engine.begin() as connection:
        connection.execute(sa.insert(Season).values(season=2024))
    with (
        pytest.raises(IntegrityError) as foreign_key_error,
        migrated_postgresql_engine.begin() as connection,
    ):
        connection.execute(
            sa.insert(Event).values(
                season=2024,
                round_number=1,
                circuit_id=999_999,
                event_name="Bahrain Grand Prix",
                official_event_name="Formula 1 Bahrain Grand Prix",
                event_date=date(2024, 3, 2),
                event_format="conventional",
            )
        )
    assert _constraint_name(foreign_key_error.value) == (
        "fk_events_circuit_id_circuits"
    )


def test_database_transaction_rolls_back_real_postgresql_write(
    migrated_postgresql_engine: Engine,
) -> None:
    """Leave no partial rows when an application transaction fails."""
    session_factory = create_database_session_factory(migrated_postgresql_engine)

    with (
        pytest.raises(RuntimeError, match="abort integration transaction"),
        database_transaction(session_factory) as session,
    ):
        session.execute(sa.insert(Season).values(season=2024))
        raise RuntimeError("abort integration transaction")

    with migrated_postgresql_engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(Season)) == 0


def test_immutable_repository_inserts_verifies_and_rejects_drift(
    migrated_postgresql_engine: Engine,
) -> None:
    """Prove idempotent immutable writes against PostgreSQL conflicts."""
    session_factory = create_database_session_factory(migrated_postgresql_engine)
    repository = ImmutableRepository(
        Circuit.__table__,
        ("country", "location"),
    )
    source = {
        "country": "Bahrain",
        "location": "Sakhir",
        "circuit_name": None,
    }

    with database_transaction(session_factory) as session:
        inserted = repository.insert_or_verify(session, source)
    with database_transaction(session_factory) as session:
        verified = repository.insert_or_verify(session, source)

    assert inserted.status == "inserted"
    assert verified.status == "verified"
    assert inserted.row == verified.row

    with (
        pytest.raises(ImmutableRowConflictError),
        database_transaction(session_factory) as session,
    ):
        repository.insert_or_verify(
            session,
            {**source, "circuit_name": "Invented Name"},
        )

    with migrated_postgresql_engine.connect() as connection:
        stored = connection.execute(sa.select(Circuit.__table__)).mappings().one()
    assert stored["circuit_name"] is None
