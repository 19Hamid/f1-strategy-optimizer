"""Shared SQLAlchemy metadata for PostgreSQL persistence."""

from typing import Final

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

DATABASE_SCHEMA_NAME: Final = "f1_strategy"
DATABASE_SCHEMA_VERSION: Final = "1.0"

NAMING_CONVENTION: Final[dict[str, str]] = {
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


class Base(DeclarativeBase):
    """Base class for every database model."""

    metadata = MetaData(
        schema=DATABASE_SCHEMA_NAME,
        naming_convention=NAMING_CONVENTION,
    )