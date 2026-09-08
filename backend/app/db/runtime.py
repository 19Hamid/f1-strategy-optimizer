"""Configure PostgreSQL engines and transactional ORM sessions."""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Final

from sqlalchemy import Engine, URL, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL_ENVIRONMENT_VARIABLE: Final = (
    "F1_STRATEGY_DATABASE_URL"
)
SUPPORTED_DATABASE_DRIVER: Final = "postgresql+psycopg"


class DatabaseConfigurationError(ValueError):
    """Raised when database configuration is absent or unsafe."""


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """Validated runtime settings for PostgreSQL persistence."""

    database_url: str = field(repr=False)
    echo_sql: bool = False
    pool_pre_ping: bool = True

    def __post_init__(self) -> None:
        """Reject malformed or non-PostgreSQL database URLs."""
        if not isinstance(self.database_url, str):
            raise TypeError("database_url must be a string")

        if not isinstance(self.echo_sql, bool):
            raise TypeError("echo_sql must be a boolean")

        if not isinstance(self.pool_pre_ping, bool):
            raise TypeError("pool_pre_ping must be a boolean")

        raw_url = self.database_url.strip()

        if not raw_url:
            raise DatabaseConfigurationError(
                "database_url must not be empty"
            )

        try:
            parsed_url = make_url(raw_url)
        except ArgumentError:
            raise DatabaseConfigurationError(
                "database_url is not a valid SQLAlchemy URL"
            ) from None

        if parsed_url.drivername != SUPPORTED_DATABASE_DRIVER:
            raise DatabaseConfigurationError(
                "database_url must use the "
                f"{SUPPORTED_DATABASE_DRIVER!r} driver"
            )

        if not parsed_url.database:
            raise DatabaseConfigurationError(
                "database_url must name a PostgreSQL database"
            )

        object.__setattr__(self, "database_url", raw_url)

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> DatabaseSettings:
        """Read the required URL from an explicit environment source."""
        source = os.environ if environment is None else environment
        database_url = source.get(
            DATABASE_URL_ENVIRONMENT_VARIABLE
        )

        if database_url is None:
            raise DatabaseConfigurationError(
                "missing required environment variable "
                f"{DATABASE_URL_ENVIRONMENT_VARIABLE}"
            )

        return cls(database_url=database_url)

    @property
    def url(self) -> URL:
        """Return the parsed URL without opening a connection."""
        return make_url(self.database_url)

    @property
    def safe_url(self) -> str:
        """Render the URL with any password hidden."""
        return self.url.render_as_string(
            hide_password=True
        )


def create_database_engine(
    settings: DatabaseSettings,
) -> Engine:
    """Create a lazy PostgreSQL engine from validated settings."""
    if not isinstance(settings, DatabaseSettings):
        raise TypeError(
            "settings must be DatabaseSettings"
        )

    return create_engine(
        settings.url,
        echo=settings.echo_sql,
        pool_pre_ping=settings.pool_pre_ping,
    )


def create_database_session_factory(
    engine: Engine,
) -> sessionmaker[Session]:
    """Create sessions with explicit flush and expiry behaviour."""
    if not isinstance(engine, Engine):
        raise TypeError("engine must be an Engine")

    return sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )


@contextmanager
def database_transaction(
    session_factory: sessionmaker[Session],
) -> Iterator[Session]:
    """Commit one unit of work or roll it back on any exception."""
    with session_factory.begin() as session:
        yield session
