"""Reference entities for Formula 1 database persistence."""

from datetime import date
from typing import Final

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    DATABASE_SCHEMA_NAME,
    Base,
)

REFERENCE_TABLE_NAMES: Final = (
    "seasons",
    "circuits",
    "events",
    "race_sessions",
    "drivers",
    "teams",
    "session_participants",
)


def _qualified_table(table_name: str) -> str:
    """Return one schema-qualified table name."""
    return (
        f"{DATABASE_SCHEMA_NAME}."
        f"{table_name}"
    )


class Season(Base):
    """Represent one Formula 1 season."""

    __tablename__ = "seasons"
    __table_args__ = (
        CheckConstraint(
            "season BETWEEN 1000 AND 9999",
            name="four_digit",
        ),
    )

    season: Mapped[int] = mapped_column(
        SmallInteger,
        primary_key=True,
        autoincrement=False,
    )


class Circuit(Base):
    """Represent one source-observed circuit location."""

    __tablename__ = "circuits"
    __table_args__ = (
        UniqueConstraint(
            "country",
            "location",
        ),
        CheckConstraint(
            "char_length(btrim(country)) > 0",
            name="country_not_blank",
        ),
        CheckConstraint(
            "char_length(btrim(location)) > 0",
            name="location_not_blank",
        ),
        CheckConstraint(
            (
                "circuit_name IS NULL "
                "OR char_length("
                "btrim(circuit_name)"
                ") > 0"
            ),
            name="name_not_blank",
        ),
    )

    circuit_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    country: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    location: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    circuit_name: Mapped[str | None] = (
        mapped_column(
            String(200),
            nullable=True,
        )
    )


class Event(Base):
    """Represent one scheduled race event."""

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint(
            "season",
            "round_number",
        ),
        UniqueConstraint(
            "event_id",
            "season",
            "round_number",
        ),
        CheckConstraint(
            (
                "round_number "
                "BETWEEN 1 AND 30"
            ),
            name="round_number_range",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(event_name)"
                ") > 0"
            ),
            name="event_name_not_blank",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(official_event_name)"
                ") > 0"
            ),
            name="official_name_not_blank",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(event_format)"
                ") > 0"
            ),
            name="event_format_not_blank",
        ),
        Index(
            "ix_events_season_event_date",
            "season",
            "event_date",
        ),
        Index(
            "ix_events_circuit_id_season",
            "circuit_id",
            "season",
        ),
    )

    event_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    season: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            (
                f"{_qualified_table('seasons')}"
                ".season"
            ),
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    round_number: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    circuit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            (
                f"{_qualified_table('circuits')}"
                ".circuit_id"
            ),
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    event_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    official_event_name: Mapped[str] = (
        mapped_column(
            String(300),
            nullable=False,
        )
    )
    event_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    event_format: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )


class RaceSession(Base):
    """Represent one canonical Formula 1 race session."""

    __tablename__ = "race_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "event_id",
                "season",
                "round_number",
            ],
            [
                (
                    f"{_qualified_table('events')}"
                    ".event_id"
                ),
                (
                    f"{_qualified_table('events')}"
                    ".season"
                ),
                (
                    f"{_qualified_table('events')}"
                    ".round_number"
                ),
                       ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "event_id",
            "session_type",
        ),
        UniqueConstraint(
            "season",
            "round_number",
            "session_type",
        ),
        CheckConstraint(
            "session_type = 'R'",
            name="race_session_only",
        ),
        CheckConstraint(
            (
                "session_id ~ "
                "'^[0-9]{4}-"
                "[0-9]{2}-R$'"
            ),
            name="identifier_format",
        ),
        CheckConstraint(
            (
                "session_id = "
                "season::text || '-' || "
                "lpad("
                "round_number::text, "
                "2, '0'"
                ") || '-' || "
                "session_type"
            ),
            name="canonical_identifier",
        ),
        Index(
            (
                "ix_race_sessions_"
                "season_round_number"
            ),
            "season",
            "round_number",
        ),
        Index(
            "ix_race_sessions_event_id",
            "event_id",
        ),
    )

    session_id: Mapped[str] = mapped_column(
        String(16),
        primary_key=True,
    )
    event_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    season: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    round_number: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    session_type: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
    )


class Driver(Base):
    """Represent one normalized FastF1 driver code."""

    __tablename__ = "drivers"
    __table_args__ = (
        UniqueConstraint(
            "driver_code",
        ),
        CheckConstraint(
            (
                "driver_code = "
                "upper(btrim(driver_code))"
            ),
            name="code_normalized",
        ),
        CheckConstraint(
            (
                "char_length("
                "driver_code"
                ") BETWEEN 1 AND 16"
            ),
            name="code_length",
        ),
        CheckConstraint(
            (
                "driver_name IS NULL "
                "OR char_length("
                "btrim(driver_name)"
                ") > 0"
            ),
            name="name_not_blank",
        ),
    )

    driver_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    driver_code: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    driver_name: Mapped[str | None] = (
        mapped_column(
            String(200),
            nullable=True,
        )
    )


class Team(Base):
    """Represent one exact source-observed team name."""

    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint(
            "team_name",
        ),
        CheckConstraint(
            (
                "team_name = "
                "btrim(team_name)"
            ),
            name="name_trimmed",
        ),
        CheckConstraint(
            (
                "char_length("
                "team_name"
                ") > 0"
            ),
            name="name_not_blank",
        ),
    )

    team_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    team_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )


class SessionParticipant(Base):
    """Represent one driver and team within one race."""

    __tablename__ = "session_participants"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "driver_number",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(driver_number)"
                ") > 0"
            ),
            name="driver_number_not_blank",
        ),
        Index(
            (
                "ix_session_participants_"
                "driver_id"
            ),
            "driver_id",
        ),
        Index(
            (
                "ix_session_participants_"
                "team_id_session_id"
            ),
            "team_id",
            "session_id",
        ),
    )

    session_id: Mapped[str] = mapped_column(
        String(16),
        ForeignKey(
            (
                f"{_qualified_table('race_sessions')}"
                ".session_id"
            ),
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    driver_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            (
                f"{_qualified_table('drivers')}"
                ".driver_id"
            ),
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    team_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            (
                f"{_qualified_table('teams')}"
                ".team_id"
            ),
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    driver_number: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
    )