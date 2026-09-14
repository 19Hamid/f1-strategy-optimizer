"""Isolated PostgreSQL fixtures for database integration tests."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

from app.db import (
    DATABASE_SCHEMA_NAME,
    DATABASE_URL_ENVIRONMENT_VARIABLE,
    DatabaseSettings,
    create_database_engine,
)

TEST_DATABASE_URL_ENVIRONMENT_VARIABLE = "F1_STRATEGY_TEST_DATABASE_URL"
EXPECTED_TEST_DATABASE_NAME = "f1_strategy_test"
BACKEND_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def postgresql_settings() -> DatabaseSettings:
    """Require an explicitly named disposable test database."""
    database_url = os.environ.get(TEST_DATABASE_URL_ENVIRONMENT_VARIABLE)
    if database_url is None:
        pytest.skip(
            "PostgreSQL integration database is not configured; "
            "run scripts/run_postgresql_tests.sh"
        )

    settings = DatabaseSettings(database_url=database_url)
    if settings.url.database != EXPECTED_TEST_DATABASE_NAME:
        pytest.fail(
            f"{TEST_DATABASE_URL_ENVIRONMENT_VARIABLE} must name "
            f"the disposable {EXPECTED_TEST_DATABASE_NAME!r} database"
        )

    return settings


@pytest.fixture(scope="session")
def postgresql_engine(
    postgresql_settings: DatabaseSettings,
) -> Iterator[Engine]:
    """Share one connection pool for the isolated test database."""
    engine = create_database_engine(postgresql_settings)
    try:
        yield engine
    finally:
        engine.dispose()


def _reset_database(engine: Engine) -> None:
    """Remove only objects owned by the disposable test database."""
    with engine.begin() as connection:
        connection.execute(
            sa.schema.DropSchema(
                DATABASE_SCHEMA_NAME,
                if_exists=True,
                cascade=True,
            )
        )
        connection.execute(sa.text("DROP TABLE IF EXISTS public.alembic_version"))


@pytest.fixture(autouse=True)
def isolated_database(
    postgresql_engine: Engine,
    postgresql_settings: DatabaseSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Start and finish every test with no application objects."""
    monkeypatch.setenv(
        DATABASE_URL_ENVIRONMENT_VARIABLE,
        postgresql_settings.database_url,
    )
    _reset_database(postgresql_engine)
    try:
        yield
    finally:
        _reset_database(postgresql_engine)


@pytest.fixture
def alembic_config() -> Config:
    """Resolve migrations independently of the caller's directory."""
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(BACKEND_ROOT / "migrations"),
    )
    return config


@pytest.fixture
def migrated_postgresql_engine(
    postgresql_engine: Engine,
    alembic_config: Config,
) -> Engine:
    """Upgrade the isolated database to the current migration head."""
    command.upgrade(alembic_config, "head")
    return postgresql_engine
