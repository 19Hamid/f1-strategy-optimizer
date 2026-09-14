"""Database model for labels separated from decision features."""

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
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    DATABASE_SCHEMA_NAME,
    Base,
)

DECISION_LABEL_TABLE_NAME: Final = "decision_labels"

DECISION_LABEL_SOURCE_COLUMN_MAP: Final[
    dict[str, str]
] = {
    "decision_id": "decision_id",
    "session_id": "session_id",
    "season": "season",
    "round_number": "round_number",
    "session_type": "session_type",
    "driver": "driver",
    "decision_lap": "decision_lap",
    "historical_action": "historical_action",
    "did_pit": "did_pit",
    "pit_event_id": "pit_event_id",
    "is_lap_time_target_eligible": (
        "is_lap_time_target_eligible"
    ),
    "lap_time_target_seconds": "lap_time_target_seconds",
    "lap_target_exclusion_count": (
        "lap_target_exclusion_count"
    ),
    "lap_target_exclusion_reasons": (
        "lap_target_exclusion_reasons"
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


class DecisionLabel(Base):
    """Preserve post-decision labels outside feature storage."""

    __tablename__ = DECISION_LABEL_TABLE_NAME
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "dataset_contract_version",
                "decision_id",
            ],
            [
                (
                    f"{_qualified_table(
                        'decision_rows'
                    )}.dataset_contract_version"
                ),
                (
                    f"{_qualified_table(
                        'decision_rows'
                    )}.decision_id"
                ),
            ],
            ondelete="RESTRICT",
        ),
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
        UniqueConstraint(
            "processed_partition_id",
            "pit_event_id",
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
                "decision_id = "
                "session_id || '-' || "
                "driver || '-' || "
                "lpad("
                "decision_lap::text, "
                "3, '0'"
                ")"
            ),
            name="canonical_decision_identity",
        ),
        CheckConstraint(
            "decision_lap >= 2",
            name="decision_lap_has_previous",
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
                "historical_action IN ("
                "'PIT_NOW', "
                "'STAY_OUT'"
                ")"
            ),
            name="historical_action_allowed",
        ),
        CheckConstraint(
            (
                "("
                "historical_action = 'PIT_NOW' "
                "AND did_pit"
                ") OR ("
                "historical_action = 'STAY_OUT' "
                "AND NOT did_pit"
                ")"
            ),
            name="historical_action_balance",
        ),
        CheckConstraint(
            (
                "("
                "did_pit "
                "AND pit_event_id IS NOT NULL "
                "AND char_length("
                "btrim(pit_event_id)"
                ") > 0"
                ") OR ("
                "NOT did_pit "
                "AND pit_event_id IS NULL"
                ")"
            ),
            name="pit_event_presence",
        ),
        CheckConstraint(
            (
                "("
                "is_lap_time_target_eligible "
                "AND lap_time_target_seconds IS NOT NULL "
                "AND lap_time_target_seconds > 0"
                ") OR ("
                "NOT is_lap_time_target_eligible "
                "AND lap_time_target_seconds IS NULL"
                ")"
            ),
            name="lap_target_availability",
        ),
        CheckConstraint(
            "lap_target_exclusion_count >= 0",
            name="exclusion_count_non_negative",
        ),
        CheckConstraint(
            (
                "("
                "is_lap_time_target_eligible "
                "AND lap_target_exclusion_count = 0 "
                "AND lap_target_exclusion_reasons = ''"
                ") OR ("
                "NOT is_lap_time_target_eligible "
                "AND lap_target_exclusion_count > 0 "
                "AND char_length("
                "lap_target_exclusion_reasons"
                ") > 0"
                ")"
            ),
            name="target_exclusion_balance",
        ),
        Index(
            (
                "ix_decision_labels_"
                "session_driver_lap"
            ),
            "session_id",
            "driver",
            "decision_lap",
        ),
        Index(
            "ix_decision_labels_action",
            "dataset_contract_version",
            "historical_action",
            "session_id",
        ),
        Index(
            (
                "ix_decision_labels_"
                "lap_target_eligible"
            ),
            "dataset_contract_version",
            "session_id",
            "decision_lap",
            postgresql_where=text(
                "is_lap_time_target_eligible"
            ),
        ),
    )

    processed_partition_id: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    dataset_contract_version: Mapped[str] = (
        mapped_column(
            String(32),
            primary_key=True,
        )
    )
    decision_id: Mapped[str] = mapped_column(
        String(96),
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
    decision_lap: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    historical_action: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    did_pit: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    pit_event_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    is_lap_time_target_eligible: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    lap_time_target_seconds: Mapped[
        float | None
    ] = mapped_column(
        Double,
        nullable=True,
    )
    lap_target_exclusion_count: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    lap_target_exclusion_reasons: Mapped[str] = (
        mapped_column(
            Text,
            nullable=False,
        )
    )
