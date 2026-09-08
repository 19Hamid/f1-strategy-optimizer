"""Versioned quality-reason definitions and normalized links."""

from typing import Final

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
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

QUALITY_REASON_TABLE_NAME: Final = "quality_reasons"

QUALITY_REASON_LINK_TABLE_NAMES: Final = (
    "processed_lap_quality_reasons",
    "stint_quality_reasons",
    "pit_event_quality_reasons",
    "decision_quality_reasons",
    "lap_target_quality_reasons",
    "pit_duration_quality_reasons",
)

QUALITY_REASON_SCOPES: Final = (
    "PROCESSED_LAP",
    "RECONSTRUCTED_STINT",
    "RECONSTRUCTED_PIT_EVENT",
    "DECISION",
    "LAP_TARGET",
    "PIT_DURATION_TARGET",
)

QUALITY_REASON_CODES_BY_SCOPE: Final[
    dict[str, tuple[str, ...]]
] = {
    "PROCESSED_LAP": (
        "MISSING_IDENTITY",
        "DUPLICATE_LAP",
        "MISSING_LAP_TIME",
        "NON_POSITIVE_LAP_TIME",
        "INACCURATE_LAP",
        "FIRST_LAP",
        "PIT_IN_LAP",
        "PIT_OUT_LAP",
        "NON_GREEN_TRACK",
        "WET_CONDITION",
        "MISSING_COMPOUND",
        "UNSUPPORTED_COMPOUND",
        "INVALID_TYRE_LIFE",
        "MISSING_SECTOR_TIME",
        "UNKNOWN_TRACK_STATUS",
    ),
    "RECONSTRUCTED_STINT": (
        "TEAM_CONFLICT",
        "MISSING_COMPOUND",
        "MULTIPLE_COMPOUNDS",
        "UNSUPPORTED_COMPOUND",
        "MISSING_TYRE_LIFE",
        "INVALID_TYRE_LIFE",
        "TYRE_LIFE_DECREASE",
        "TYRE_LIFE_STEP_MISMATCH",
        "LAP_NUMBER_GAP",
        "DISJOINT_STINT",
        "NON_SEQUENTIAL_STINT",
        "MISSING_PIT_EVIDENCE_BEFORE",
        "MISSING_PIT_EVIDENCE_AFTER",
    ),
    "RECONSTRUCTED_PIT_EVENT": (
        "TEAM_CONFLICT",
        "ENTRY_ONLY",
        "EXIT_ONLY",
        "NON_ADJACENT_LAPS",
        "NON_POSITIVE_DURATION",
        "NO_STINT_CHANGE",
        "MISSING_COMPOUND_BEFORE",
        "MISSING_COMPOUND_AFTER",
        "UNSUPPORTED_COMPOUND_BEFORE",
        "UNSUPPORTED_COMPOUND_AFTER",
        "NON_GREEN_ENTRY",
        "NON_GREEN_EXIT",
        "INTERRUPTED_DURATION",
    ),
    "DECISION": (
        "NON_CONSECUTIVE_PREVIOUS_LAP",
        "WEATHER_NOT_AVAILABLE_BY_DECISION",
        "PREVIOUS_LAP_PIT_COMMITMENT",
        "STATE_RECONSTRUCTION_CONFLICT",
        "UNSUPPORTED_CURRENT_COMPOUND",
        "INVALID_CURRENT_TYRE_AGE",
        "MISSING_CURRENT_STINT",
        "WET_AT_DECISION",
        "PREVIOUS_LAP_NOT_GREEN",
        "INSUFFICIENT_ELIGIBLE_HISTORY",
        "MISSING_PREVIOUS_POSITION",
    ),
    "LAP_TARGET": (
        "MISSING_IDENTITY",
        "DUPLICATE_LAP",
        "MISSING_LAP_TIME",
        "NON_POSITIVE_LAP_TIME",
        "INACCURATE_LAP",
        "FIRST_LAP",
        "PIT_IN_LAP",
        "PIT_OUT_LAP",
        "NON_GREEN_TRACK",
        "WET_CONDITION",
        "MISSING_COMPOUND",
        "UNSUPPORTED_COMPOUND",
        "INVALID_TYRE_LIFE",
        "UNKNOWN_TRACK_STATUS",
    ),
    "PIT_DURATION_TARGET": (
        "INCOMPLETE_EVENT",
        "NO_STINT_CHANGE",
        "NON_GREEN_FLAG_PAIR",
        "UNSUPPORTED_DRY_COMPOUND_PAIR",
        "NON_DRY_WEATHER_PAIR",
        "INTERRUPTED_DURATION",
    ),
}

QUALITY_REASON_EXCLUSION_CODES_BY_SCOPE: Final[
    dict[str, frozenset[str]]
] = {
    "PROCESSED_LAP": frozenset(
        code
        for code in QUALITY_REASON_CODES_BY_SCOPE[
            "PROCESSED_LAP"
        ]
        if code != "MISSING_SECTOR_TIME"
    ),
    "RECONSTRUCTED_STINT": frozenset(),
    "RECONSTRUCTED_PIT_EVENT": frozenset(),
    "DECISION": frozenset(
        QUALITY_REASON_CODES_BY_SCOPE[
            "DECISION"
        ]
    ),
    "LAP_TARGET": frozenset(
        QUALITY_REASON_CODES_BY_SCOPE[
            "LAP_TARGET"
        ]
    ),
    "PIT_DURATION_TARGET": frozenset(
        QUALITY_REASON_CODES_BY_SCOPE[
            "PIT_DURATION_TARGET"
        ]
    ),
}


def _qualified_table(table_name: str) -> str:
    """Return one schema-qualified table name."""
    return (
        f"{DATABASE_SCHEMA_NAME}."
        f"{table_name}"
    )


def _reason_definition_foreign_key() -> ForeignKeyConstraint:
    """Build one scoped reason-definition foreign key."""
    return ForeignKeyConstraint(
        [
            "dataset_contract_version",
            "scope",
            "reason_code",
        ],
        [
            (
                f"{_qualified_table(
                    'quality_reasons'
                )}.dataset_contract_version"
            ),
            (
                f"{_qualified_table(
                    'quality_reasons'
                )}.scope"
            ),
            (
                f"{_qualified_table(
                    'quality_reasons'
                )}.reason_code"
            ),
        ],
        ondelete="RESTRICT",
    )


def _scope_constraint(scope: str) -> CheckConstraint:
    """Build one exact-scope check for a link table."""
    return CheckConstraint(
        f"scope = '{scope}'",
        name="scope_exact",
    )


def _ordinal_constraint() -> CheckConstraint:
    """Build one non-negative link-ordinal check."""
    return CheckConstraint(
        "reason_ordinal >= 0",
        name="reason_ordinal_non_negative",
    )


class QualityReason(Base):
    """Define one canonical reason within a versioned scope."""

    __tablename__ = QUALITY_REASON_TABLE_NAME
    __table_args__ = (
        UniqueConstraint(
            "dataset_contract_version",
            "scope",
            "canonical_ordinal",
        ),
        CheckConstraint(
            (
                "scope IN ("
                "'PROCESSED_LAP', "
                "'RECONSTRUCTED_STINT', "
                "'RECONSTRUCTED_PIT_EVENT', "
                "'DECISION', "
                "'LAP_TARGET', "
                "'PIT_DURATION_TARGET'"
                ")"
            ),
            name="scope_allowed",
        ),
        CheckConstraint(
            (
                "reason_code ~ "
                "'^[A-Z][A-Z0-9_]*$'"
            ),
            name="reason_code_normalized",
        ),
        CheckConstraint(
            "canonical_ordinal >= 0",
            name="canonical_ordinal_non_negative",
        ),
    )

    dataset_contract_version: Mapped[str] = (
        mapped_column(
            String(32),
            ForeignKey(
                (
                    f"{_qualified_table('dataset_versions')}"
                    ".dataset_contract_version"
                ),
                ondelete="RESTRICT",
            ),
            primary_key=True,
        )
    )
    scope: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
    )
    reason_code: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )
    canonical_ordinal: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    is_exclusion: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )


class ProcessedLapQualityReason(Base):
    """Link one processed-lap quality flag in source order."""

    __tablename__ = "processed_lap_quality_reasons"
    __table_args__ = (
        _reason_definition_foreign_key(),
        ForeignKeyConstraint(
            [
                "processed_partition_id",
                "source_row_number",
            ],
            [
                (
                    f"{_qualified_table(
                        'processed_laps'
                    )}.processed_partition_id"
                ),
                (
                    f"{_qualified_table(
                        'processed_laps'
                    )}.source_row_number"
                ),
            ],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "dataset_contract_version",
            "processed_partition_id",
            "source_row_number",
            "reason_code",
        ),
        _scope_constraint("PROCESSED_LAP"),
        _ordinal_constraint(),
        Index(
            (
                "ix_processed_lap_quality_reasons_"
                "reason_code"
            ),
            "dataset_contract_version",
            "reason_code",
        ),
    )

    dataset_contract_version: Mapped[str] = (
        mapped_column(
            String(32),
            primary_key=True,
        )
    )
    processed_partition_id: Mapped[int] = (
        mapped_column(
            BigInteger,
            primary_key=True,
        )
    )
    source_row_number: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
    )
    reason_ordinal: Mapped[int] = mapped_column(
        SmallInteger,
        primary_key=True,
    )
    scope: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    reason_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
class StintQualityReason(Base):
    """Link one reconstructed-stint warning in source order."""

    __tablename__ = "stint_quality_reasons"
    __table_args__ = (
        _reason_definition_foreign_key(),
        ForeignKeyConstraint(
            [
                "processed_partition_id",
                "driver_id",
                "stint_number",
            ],
            [
                (
                    f"{_qualified_table(
                        'reconstructed_stints'
                    )}.processed_partition_id"
                ),
                (
                    f"{_qualified_table(
                        'reconstructed_stints'
                    )}.driver_id"
                ),
                (
                    f"{_qualified_table(
                        'reconstructed_stints'
                    )}.stint_number"
                ),
            ],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "dataset_contract_version",
            "processed_partition_id",
            "driver_id",
            "stint_number",
            "reason_code",
        ),
        _scope_constraint("RECONSTRUCTED_STINT"),
        _ordinal_constraint(),
        Index(
            "ix_stint_quality_reasons_reason_code",
            "dataset_contract_version",
            "reason_code",
        ),
    )

    dataset_contract_version: Mapped[str] = (
        mapped_column(
            String(32),
            primary_key=True,
        )
    )
    processed_partition_id: Mapped[int] = (
        mapped_column(
            BigInteger,
            primary_key=True,
        )
    )
    driver_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
    )
    stint_number: Mapped[int] = mapped_column(
        SmallInteger,
        primary_key=True,
    )
    reason_ordinal: Mapped[int] = mapped_column(
        SmallInteger,
        primary_key=True,
    )
    scope: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    reason_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )


class PitEventQualityReason(Base):
    """Link one reconstructed pit-event warning in source order."""

    __tablename__ = "pit_event_quality_reasons"
    __table_args__ = (
        _reason_definition_foreign_key(),
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
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "dataset_contract_version",
            "processed_partition_id",
            "pit_event_id",
            "reason_code",
        ),
        _scope_constraint("RECONSTRUCTED_PIT_EVENT"),
        _ordinal_constraint(),
        Index(
            "ix_pit_event_quality_reasons_reason_code",
            "dataset_contract_version",
            "reason_code",
        ),
    )

    dataset_contract_version: Mapped[str] = (
        mapped_column(
            String(32),
            primary_key=True,
        )
    )
    processed_partition_id: Mapped[int] = (
        mapped_column(
            BigInteger,
            primary_key=True,
        )
    )
    pit_event_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )
    reason_ordinal: Mapped[int] = mapped_column(
        SmallInteger,
        primary_key=True,
    )
    scope: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    reason_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )


class DecisionQualityReason(Base):
    """Link one decision-state exclusion in source order."""

    __tablename__ = "decision_quality_reasons"
    __table_args__ = (
        _reason_definition_foreign_key(),
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
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "dataset_contract_version",
            "decision_id",
            "reason_code",
        ),
        _scope_constraint("DECISION"),
        _ordinal_constraint(),
        Index(
            "ix_decision_quality_reasons_reason_code",
            "dataset_contract_version",
            "reason_code",
        ),
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
    reason_ordinal: Mapped[int] = mapped_column(
        SmallInteger,
        primary_key=True,
    )
    scope: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    reason_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )


class LapTargetQualityReason(Base):
    """Link one lap-target exclusion in source order."""

    __tablename__ = "lap_target_quality_reasons"
    __table_args__ = (
        _reason_definition_foreign_key(),
        ForeignKeyConstraint(
            [
                "dataset_contract_version",
                "decision_id",
            ],
            [
                (
                    f"{_qualified_table(
                        'decision_labels'
                    )}.dataset_contract_version"
                ),
                (
                    f"{_qualified_table(
                        'decision_labels'
                    )}.decision_id"
                ),
            ],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "dataset_contract_version",
            "decision_id",
            "reason_code",
        ),
        _scope_constraint("LAP_TARGET"),
        _ordinal_constraint(),
        Index(
            "ix_lap_target_quality_reasons_reason_code",
            "dataset_contract_version",
            "reason_code",
        ),
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
    reason_ordinal: Mapped[int] = mapped_column(
        SmallInteger,
        primary_key=True,
    )
    scope: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    reason_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )


class PitDurationQualityReason(Base):
    """Link one pit-duration target exclusion in source order."""

    __tablename__ = "pit_duration_quality_reasons"
    __table_args__ = (
        _reason_definition_foreign_key(),
        ForeignKeyConstraint(
            [
                "dataset_contract_version",
                "pit_event_id",
            ],
            [
                (
                    f"{_qualified_table(
                        'pit_duration_observations'
                    )}.dataset_contract_version"
                ),
                (
                    f"{_qualified_table(
                        'pit_duration_observations'
                    )}.pit_event_id"
                ),
            ],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "dataset_contract_version",
            "pit_event_id",
            "reason_code",
        ),
        _scope_constraint("PIT_DURATION_TARGET"),
        _ordinal_constraint(),
        Index(
            (
                "ix_pit_duration_quality_reasons_"
                "reason_code"
            ),
            "dataset_contract_version",
            "reason_code",
        ),
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
    reason_ordinal: Mapped[int] = mapped_column(
        SmallInteger,
        primary_key=True,
    )
    scope: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    reason_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
