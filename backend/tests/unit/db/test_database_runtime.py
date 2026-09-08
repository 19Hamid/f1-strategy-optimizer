"""Tests for PostgreSQL runtime configuration and transactions."""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import URL, Engine

import app.db.runtime as database_runtime
from app.db import (
    DATABASE_URL_ENVIRONMENT_VARIABLE,
    SUPPORTED_DATABASE_DRIVER,
    DatabaseConfigurationError,
    DatabaseSettings,
    create_database_engine,
    create_database_session_factory,
    database_transaction,
)

DATABASE_URL = (
    "postgresql+psycopg://strategy:secret@db/strategy"
)


def test_database_settings_require_psycopg_postgresql() -> None:
    """Only the project's explicit PostgreSQL driver is accepted."""
    settings = DatabaseSettings(database_url=DATABASE_URL)

    assert settings.url.drivername == SUPPORTED_DATABASE_DRIVER
    assert settings.url.database == "strategy"

    with pytest.raises(
        DatabaseConfigurationError,
        match="postgresql\\+psycopg",
    ):
        DatabaseSettings(database_url="sqlite:///strategy.db")

    with pytest.raises(
        DatabaseConfigurationError,
        match="must name",
    ):
        DatabaseSettings(
            database_url="postgresql+psycopg://db"
        )


def test_database_settings_hide_credentials() -> None:
    """Diagnostics never render the configured database password."""
    settings = DatabaseSettings(database_url=DATABASE_URL)

    assert "secret" not in repr(settings)
    assert "secret" not in settings.safe_url
    assert "***" in settings.safe_url


def test_database_settings_load_from_explicit_environment() -> None:
    """The runtime reads one namespaced required variable."""
    settings = DatabaseSettings.from_environment(
        {DATABASE_URL_ENVIRONMENT_VARIABLE: DATABASE_URL}
    )

    assert settings.database_url == DATABASE_URL

    with pytest.raises(
        DatabaseConfigurationError,
        match=DATABASE_URL_ENVIRONMENT_VARIABLE,
    ):
        DatabaseSettings.from_environment({})


def test_engine_and_session_factory_are_safely_configured() -> None:
    """Connections are lazy and sessions preserve loaded identities."""
    settings = DatabaseSettings(database_url=DATABASE_URL)
    engine = create_database_engine(settings)

    try:
        assert isinstance(engine, Engine)

        session_factory = create_database_session_factory(
            engine
        )

        assert session_factory.kw["autoflush"] is False
        assert (
            session_factory.kw["expire_on_commit"]
            is False
        )
        assert session_factory.kw["bind"] is engine
    finally:
        engine.dispose()


def test_engine_uses_validated_connection_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Engine creation preserves the pool health-check policy."""
    captured: dict[str, object] = {}
    expected_engine = object()

    def fake_create_engine(
        url: URL,
        **options: object,
    ) -> object:
        captured["url"] = url
        captured.update(options)
        return expected_engine

    monkeypatch.setattr(
        database_runtime,
        "create_engine",
        fake_create_engine,
    )
    settings = DatabaseSettings(
        database_url=DATABASE_URL,
        echo_sql=True,
    )

    engine = create_database_engine(settings)

    assert engine is expected_engine
    assert captured == {
        "url": settings.url,
        "echo": True,
        "pool_pre_ping": True,
    }


class _RecordingSessionFactory:
    """Record simulated transaction outcomes for unit tests."""

    def __init__(self) -> None:
        self.session = object()
        self.commits = 0
        self.rollbacks = 0

    @contextmanager
    def begin(self) -> Iterator[object]:
        """Simulate sessionmaker.begin transaction semantics."""
        try:
            yield self.session
        except BaseException:
            self.rollbacks += 1
            raise
        else:
            self.commits += 1


def test_database_transaction_commits_success() -> None:
    """A successful unit of work commits exactly once."""
    session_factory = _RecordingSessionFactory()

    with database_transaction(  # type: ignore[arg-type]
        session_factory
    ) as session:
        assert session is session_factory.session

    assert session_factory.commits == 1
    assert session_factory.rollbacks == 0


def test_database_transaction_rolls_back_failure() -> None:
    """Any exception leaves the transaction uncommitted."""
    session_factory = _RecordingSessionFactory()

    with (
        pytest.raises(RuntimeError, match="fail closed"),
        database_transaction(  # type: ignore[arg-type]
            session_factory
        ),
    ):
        raise RuntimeError("fail closed")

    assert session_factory.commits == 0
    assert session_factory.rollbacks == 1
