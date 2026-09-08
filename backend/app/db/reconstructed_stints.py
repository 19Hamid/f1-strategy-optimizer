"""Database model for reconstructed tyre stints."""

from typing import Final

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    DATABASE_SCHEMA_NAME,
    Base,
)

RECONSTRUCTED_STINT_TABLE_NAME: Final = (
    "reconstructed_stints"
)

RECONSTRUCTED_STINT_SOURCE_COLUMN_MAP: Final[
    dict[str, str]
] = {
    "season": "season",
    "round_number": "round_number",
    "session_type": "session_type",
    "event_name": "event_name",
    "driver": "driver",
    "team": "team",
    "stint_number": "stint_number",
    "compound": "compound",
    "start_lap": "start_lap",
    "end_lap": "end_lap",
    "recorded_laps": "recorded_laps",
    "start_tyre_life": "start_tyre_life",
    "end_tyre_life": "end_tyre_life",
    "is_first_stint": "is_first_stint",
    "is_last_stint": "is_last_stint",
    "boundary_before_verified": (
        "boundary_before_verified"
    ),
    "boundary_after_verified": (
        "boundary_after_verified"
    ),
    "is_complete": "is_complete",
    "warning_count": "warning_count",
    "warnings": "warnings",
}


def _qualified_table(table_name: str) -> str:
    """Return one schema-qualified table name."""
    return (
        f"{DATABASE_SCHEMA_NAME}."
        f"{table_name}"
    )


class ReconstructedStint(Base):
    """Preserve one Phase 3 reconstructed tyre stint."""

    __tablename__ = RECONSTRUCTED_STINT_TABLE_NAME
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "processed_partition_id",
                "session_id",
            ],
            [
                (
                    f"{_qualified_table(
                        'processed_session_partitions'
                    )}.processed_partition_id"
                ),
                (
                    f"{_qualified_table(
                        'processed_session_partitions'
                    )}.session_id"
                ),
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "session_id",
                "driver_id",
            ],
            [
                (
                    f"{_qualified_table(
                        'session_participants'
                    )}.session_id"
                ),
                (
                    f"{_qualified_table(
                        'session_participants'
                    )}.driver_id"
                ),
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "stint_number >= 1",
            name="stint_number_positive",
        ),
        CheckConstraint(
            "start_lap >= 1",
            name="start_lap_positive",
        ),
        CheckConstraint(
            "end_lap >= 1",
            name="end_lap_positive",
        ),
        CheckConstraint(
            "end_lap >= start_lap",
            name="lap_range_ordered",
        ),
        CheckConstraint(
            "recorded_laps >= 1",
            name="recorded_laps_positive",
        ),
        CheckConstraint(
            "warning_count >= 0",
            name="warning_count_non_negative",
        ),
        CheckConstraint(
            (
                "("
                "is_complete "
                "AND warning_count = 0 "
                "AND warnings = ''"
                ") OR ("
                "NOT is_complete "
                "AND warning_count > 0 "
                "AND char_length(warnings) > 0"
                ")"
            ),
            name="completeness_warning_balance",
        ),
        CheckConstraint(
            (
                "round_number "
                "BETWEEN 1 AND 30"
            ),
            name="round_number_range",
        ),
        CheckConstraint(
            "session_type = 'R'",
            name="race_session_only",
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
            name="canonical_session_identity",
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
                "driver = "
                "upper(btrim(driver))"
            ),
            name="driver_normalized",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(team)"
                ") > 0"
            ),
            name="team_not_blank",
        ),
        CheckConstraint(
            (
                "compound IS NULL "
                "OR char_length("
                "btrim(compound)"
                ") > 0"
            ),
            name="compound_not_blank",
        ),
        Index(
            (
                "ix_reconstructed_stints_"
                "session_driver"
            ),
            "session_id",
            "driver_id",
            "stint_number",
        ),
    )

    processed_partition_id: Mapped[int] = (
        mapped_column(
            BigInteger,
            primary_key=True,
        )
    )
    session_id: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    driver_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
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
    event_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    driver: Mapped[str] = mapped_column(
        String(16),
        ForeignKey(
            (
                f"{_qualified_table('drivers')}"
                ".driver_code"
            ),
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    team: Mapped[str] = mapped_column(
        String(200),
        ForeignKey(
            (
                f"{_qualified_table('teams')}"
                ".team_name"
            ),
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    stint_number: Mapped[int] = mapped_column(
        SmallInteger,
        primary_key=True,
    )
    compound: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    start_lap: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    end_lap: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    recorded_laps: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    start_tyre_life: Mapped[float | None] = (
        mapped_column(
            Double,
            nullable=True,
        )
    )
    end_tyre_life: Mapped[float | None] = (
        mapped_column(
            Double,
            nullable=True,
        )
    )
    is_first_stint: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    is_last_stint: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    boundary_before_verified: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    boundary_after_verified: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    is_complete: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    warning_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    warnings: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
