"""Database model for reconstructed pit events."""

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

RECONSTRUCTED_PIT_EVENT_TABLE_NAME: Final = (
    "reconstructed_pit_events"
)

RECONSTRUCTED_PIT_EVENT_SOURCE_COLUMN_MAP: Final[
    dict[str, str]
] = {
    "pit_event_id": "pit_event_id",
    "season": "season",
    "round_number": "round_number",
    "session_type": "session_type",
    "event_name": "event_name",
    "driver": "driver",
    "team": "team",
    "event_type": "event_type",
    "pit_in_lap": "pit_in_lap",
    "pit_out_lap": "pit_out_lap",
    "stint_before": "stint_before",
    "stint_after": "stint_after",
    "compound_before": "compound_before",
    "compound_after": "compound_after",
    "tyre_life_before": "tyre_life_before",
    "tyre_life_after": "tyre_life_after",
    "pit_in_time_seconds": "pit_in_time_seconds",
    "pit_out_time_seconds": "pit_out_time_seconds",
    "observed_pit_lane_duration_seconds": (
        "observed_pit_lane_duration_seconds"
    ),
    "entry_track_status": "entry_track_status",
    "exit_track_status": "exit_track_status",
    "is_stint_change": "is_stint_change",
    "is_compound_change": "is_compound_change",
    "is_green_flag_pair": "is_green_flag_pair",
    "is_dry_compound_pair": "is_dry_compound_pair",
    "is_interrupted_duration": (
        "is_interrupted_duration"
    ),
    "is_complete": "is_complete",
    "is_duration_analysis_candidate": (
        "is_duration_analysis_candidate"
    ),
    "warning_count": "warning_count",
    "warnings": "warnings",
}


def _qualified_table(table_name: str) -> str:
    """Return one schema-qualified table name."""
    return (
        f"{DATABASE_SCHEMA_NAME}."
        f"{table_name}"
    )


class ReconstructedPitEvent(Base):
    """Preserve one Phase 3 reconstructed pit event."""

    __tablename__ = RECONSTRUCTED_PIT_EVENT_TABLE_NAME
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
            (
                "event_type IN ("
                "'MATCHED', "
                "'ENTRY_ONLY', "
                "'EXIT_ONLY'"
                ")"
            ),
            name="event_type_allowed",
        ),
        CheckConstraint(
            (
                "("
                "event_type = 'MATCHED' "
                "AND pit_in_lap IS NOT NULL "
                "AND pit_out_lap IS NOT NULL"
                ") OR ("
                "event_type = 'ENTRY_ONLY' "
                "AND pit_in_lap IS NOT NULL "
                "AND pit_out_lap IS NULL"
                ") OR ("
                "event_type = 'EXIT_ONLY' "
                "AND pit_in_lap IS NULL "
                "AND pit_out_lap IS NOT NULL"
                ")"
            ),
            name="event_type_marker_shape",
        ),
        CheckConstraint(
            (
                "pit_in_lap IS NULL "
                "OR pit_in_lap >= 1"
            ),
            name="pit_in_lap_positive",
        ),
        CheckConstraint(
            (
                "pit_out_lap IS NULL "
                "OR pit_out_lap >= 1"
            ),
            name="pit_out_lap_positive",
        ),
        CheckConstraint(
            (
                "stint_before IS NULL "
                "OR stint_before >= 1"
            ),
            name="stint_before_positive",
        ),
        CheckConstraint(
            (
                "stint_after IS NULL "
                "OR stint_after >= 1"
            ),
            name="stint_after_positive",
        ),
        CheckConstraint(
            (
                "NOT is_complete OR ("
                "event_type = 'MATCHED' "
                "AND pit_out_lap = pit_in_lap + 1 "
                "AND observed_pit_lane_duration_seconds "
                "IS NOT NULL "
                "AND observed_pit_lane_duration_seconds > 0"
                ")"
            ),
            name="complete_event_requirements",
        ),
        CheckConstraint(
            (
                "NOT is_duration_analysis_candidate OR ("
                "is_complete "
                "AND is_stint_change IS TRUE "
                "AND is_green_flag_pair "
                "AND is_dry_compound_pair "
                "AND NOT is_interrupted_duration"
                ")"
            ),
            name="duration_candidate_requirements",
        ),
        CheckConstraint(
            "warning_count >= 0",
            name="warning_count_non_negative",
        ),
        CheckConstraint(
            (
                "("
                "warning_count = 0 "
                "AND warnings = ''"
                ") OR ("
                "warning_count > 0 "
                "AND char_length(warnings) > 0"
                ")"
            ),
            name="warning_encoding_balance",
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
                "btrim(pit_event_id)"
                ") > 0"
            ),
            name="pit_event_id_not_blank",
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
        Index(
            (
                "ix_reconstructed_pit_events_"
                "session_driver_pit_lap"
            ),
            "session_id",
            "driver_id",
            "pit_in_lap",
            "pit_out_lap",
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
        nullable=False,
    )
    pit_event_id: Mapped[str] = mapped_column(
        String(64),
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
    event_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    pit_in_lap: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
    )
    pit_out_lap: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
    )
    stint_before: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
    )
    stint_after: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
    )
    compound_before: Mapped[str | None] = (
        mapped_column(
            String(32),
            nullable=True,
        )
    )
    compound_after: Mapped[str | None] = (
        mapped_column(
            String(32),
            nullable=True,
        )
    )
    tyre_life_before: Mapped[float | None] = (
        mapped_column(
            Double,
            nullable=True,
        )
    )
    tyre_life_after: Mapped[float | None] = (
        mapped_column(
            Double,
            nullable=True,
        )
    )
    pit_in_time_seconds: Mapped[float | None] = (
        mapped_column(
            Double,
            nullable=True,
        )
    )
    pit_out_time_seconds: Mapped[float | None] = (
        mapped_column(
            Double,
            nullable=True,
        )
    )
    observed_pit_lane_duration_seconds: Mapped[
        float | None
    ] = mapped_column(
        Double,
        nullable=True,
    )
    entry_track_status: Mapped[str | None] = (
        mapped_column(
            String(32),
            nullable=True,
        )
    )
    exit_track_status: Mapped[str | None] = (
        mapped_column(
            String(32),
            nullable=True,
        )
    )
    is_stint_change: Mapped[bool | None] = (
        mapped_column(
            Boolean,
            nullable=True,
        )
    )
    is_compound_change: Mapped[bool | None] = (
        mapped_column(
            Boolean,
            nullable=True,
        )
    )
    is_green_flag_pair: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    is_dry_compound_pair: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    is_interrupted_duration: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    is_complete: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    is_duration_analysis_candidate: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    warning_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    warnings: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
