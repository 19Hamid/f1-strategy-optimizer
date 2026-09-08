"""Database model for separated pit-duration targets."""

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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    DATABASE_SCHEMA_NAME,
    Base,
)

PIT_DURATION_OBSERVATION_TABLE_NAME: Final = (
    "pit_duration_observations"
)

PIT_DURATION_OBSERVATION_SOURCE_COLUMN_MAP: Final[
    dict[str, str]
] = {
    "pit_event_id": "pit_event_id",
    "session_id": "session_id",
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
    "is_stint_change": "is_stint_change",
    "is_compound_change": "is_compound_change",
    "is_complete": "is_complete",
    "is_green_flag_pair": "is_green_flag_pair",
    "is_dry_weather_pair": "is_dry_weather_pair",
    "is_interrupted_duration": (
        "is_interrupted_duration"
    ),
    "is_pit_duration_target_eligible": (
        "is_pit_duration_target_eligible"
    ),
    "pit_duration_target_seconds": (
        "pit_duration_target_seconds"
    ),
    "pit_duration_exclusion_count": (
        "pit_duration_exclusion_count"
    ),
    "pit_duration_exclusion_reasons": (
        "pit_duration_exclusion_reasons"
    ),
    "dataset_contract_version": (
        "dataset_contract_version"
    ),
}


def _qualified_table(table_name: str) -> str:
    """Return one schema-qualified table name."""
    return (
        f"{DATABASE_SCHEMA_NAME}."
        f"{table_name}"
    )


class PitDurationObservation(Base):
    """Preserve one pit event and its separated target."""

    __tablename__ = PIT_DURATION_OBSERVATION_TABLE_NAME
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "dataset_contract_version",
                "session_id",
            ],
            [
                (
                    f"{_qualified_table(
                        'dataset_sessions'
                    )}.dataset_contract_version"
                ),
                (
                    f"{_qualified_table(
                        'dataset_sessions'
                    )}.session_id"
                ),
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "dataset_contract_version",
                "processed_partition_id",
            ],
            [
                (
                    f"{_qualified_table(
                        'dataset_sessions'
                    )}.dataset_contract_version"
                ),
                (
                    f"{_qualified_table(
                        'dataset_sessions'
                    )}.processed_partition_id"
                ),
            ],
            ondelete="RESTRICT",
        ),
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
                "processed_partition_id",
                "pit_event_id",
            ],
            [
                (
                    f"{_qualified_table(
                        'reconstructed_pit_events'
                    )}.processed_partition_id"
                ),
                (
                    f"{_qualified_table(
                        'reconstructed_pit_events'
                    )}.pit_event_id"
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
                "tyre_life_before IS NULL "
                "OR tyre_life_before >= 0"
            ),
            name="tyre_life_before_non_negative",
        ),
        CheckConstraint(
            (
                "tyre_life_after IS NULL "
                "OR tyre_life_after >= 0"
            ),
            name="tyre_life_after_non_negative",
        ),
        CheckConstraint(
            (
                "NOT is_complete OR ("
                "event_type = 'MATCHED' "
                "AND pit_in_lap IS NOT NULL "
                "AND pit_out_lap = pit_in_lap + 1"
                ")"
            ),
            name="complete_event_requirements",
        ),
        CheckConstraint(
            (
                "is_pit_duration_target_eligible = ("
                "is_complete "
                "AND is_stint_change IS TRUE "
                "AND is_green_flag_pair "
                "AND compound_before IS NOT NULL "
                "AND compound_before IN ("
                "'HARD', 'MEDIUM', 'SOFT'"
                ") "
                "AND compound_after IS NOT NULL "
                "AND compound_after IN ("
                "'HARD', 'MEDIUM', 'SOFT'"
                ") "
                "AND is_dry_weather_pair "
                "AND NOT is_interrupted_duration"
                ")"
            ),
            name="exact_target_eligibility",
        ),
        CheckConstraint(
            (
                "("
                "is_pit_duration_target_eligible "
                "AND pit_duration_target_seconds IS NOT NULL "
                "AND pit_duration_target_seconds > 0"
                ") OR ("
                "NOT is_pit_duration_target_eligible "
                "AND pit_duration_target_seconds IS NULL"
                ")"
            ),
            name="target_availability",
        ),
        CheckConstraint(
            "pit_duration_exclusion_count >= 0",
            name="exclusion_count_non_negative",
        ),
        CheckConstraint(
            (
                "("
                "is_pit_duration_target_eligible "
                "AND pit_duration_exclusion_count = 0 "
                "AND pit_duration_exclusion_reasons = ''"
                ") OR ("
                "NOT is_pit_duration_target_eligible "
                "AND pit_duration_exclusion_count > 0 "
                "AND char_length("
                "pit_duration_exclusion_reasons"
                ") > 0"
                ")"
            ),
            name="target_exclusion_balance",
        ),
        Index(
            (
                "ix_pit_duration_observations_"
                "session_driver_pit_lap"
            ),
            "session_id",
            "driver_id",
            "pit_in_lap",
            "pit_out_lap",
        ),
        Index(
            (
                "ix_pit_duration_observations_"
                "source_event"
            ),
            "processed_partition_id",
            "pit_event_id",
        ),
        Index(
            (
                "ix_pit_duration_observations_"
                "target_eligible"
            ),
            "dataset_contract_version",
            "session_id",
            "pit_in_lap",
            postgresql_where=text(
                "is_pit_duration_target_eligible"
            ),
        ),
    )

    processed_partition_id: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    driver_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    dataset_contract_version: Mapped[str] = (
        mapped_column(
            String(32),
            primary_key=True,
        )
    )
    pit_event_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(16),
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
    is_complete: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    is_green_flag_pair: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    is_dry_weather_pair: Mapped[bool] = (
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
    is_pit_duration_target_eligible: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    pit_duration_target_seconds: Mapped[
        float | None
    ] = mapped_column(
        Double,
        nullable=True,
    )
    pit_duration_exclusion_count: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    pit_duration_exclusion_reasons: Mapped[str] = (
        mapped_column(
            Text,
            nullable=False,
        )
    )
