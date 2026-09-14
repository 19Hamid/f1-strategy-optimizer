"""Tests for the shared SQLAlchemy metadata."""

from sqlalchemy import MetaData

import app.db as database_package
from app.db import (
    DATABASE_SCHEMA_NAME,
    DATABASE_SCHEMA_VERSION,
    NAMING_CONVENTION,
    Base,
)


def test_database_schema_constants_are_frozen() -> None:
    """The initial PostgreSQL namespace and version are stable."""
    assert DATABASE_SCHEMA_NAME == "f1_strategy"
    assert DATABASE_SCHEMA_VERSION == "1.0"


def test_base_uses_shared_schema_metadata() -> None:
    """Every model inherits one schema-aware metadata object."""
    assert isinstance(Base.metadata, MetaData)
    assert (
        Base.metadata.schema
        == DATABASE_SCHEMA_NAME
    )


def test_constraint_naming_convention_is_deterministic() -> None:
    """Alembic receives stable names for every constraint type."""
    expected = {
        "ix": (
            "ix_%(table_name)s_"
            "%(column_0_N_name)s"
        ),
        "uq": (
            "uq_%(table_name)s_"
            "%(column_0_N_name)s"
        ),
        "ck": (
            "ck_%(table_name)s_"
            "%(constraint_name)s"
        ),
        "fk": (
            "fk_%(table_name)s_"
            "%(column_0_N_name)s_"
            "%(referred_table_name)s"
        ),
        "pk": "pk_%(table_name)s",
    }

    assert NAMING_CONVENTION == expected

    for key, value in expected.items():
        assert (
            Base.metadata.naming_convention[key]
            == value
        )


def test_database_foundation_is_public() -> None:
    """Database consumers can import the shared foundation."""
    required_exports = {
        "DATABASE_SCHEMA_NAME",
        "DATABASE_SCHEMA_VERSION",
        "NAMING_CONVENTION",
        "Base",
    }

    assert required_exports <= set(
        database_package.__all__
    )