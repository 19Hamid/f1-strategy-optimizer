"""Database models for frozen whole-session temporal folds."""

from typing import Final

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    DATABASE_SCHEMA_NAME,
    Base,
)

TEMPORAL_FOLD_TABLE_NAME: Final = "temporal_folds"
SESSION_SPLIT_ASSIGNMENT_TABLE_NAME: Final = (
    "session_split_assignments"
)

SESSION_SPLIT_ASSIGNMENT_SOURCE_COLUMN_MAP: Final[
    dict[str, str]
] = {
    "fold_id": "fold_id",
    "session_id": "session_id",
    "season": "season",
    "round_number": "round_number",
    "session_type": "session_type",
    "role": "role",
}


def _qualified_table(table_name: str) -> str:
    """Return one schema-qualified table name."""
    return (
        f"{DATABASE_SCHEMA_NAME}."
        f"{table_name}"
    )


class TemporalFold(Base):
    """Persist one versioned whole-season fold definition."""

    __tablename__ = TEMPORAL_FOLD_TABLE_NAME
    __table_args__ = (
        CheckConstraint(
            (
                "char_length("
                "btrim(fold_id)"
                ") > 0"
            ),
            name="fold_id_not_blank",
        ),
        CheckConstraint(
            (
                "cardinality(train_seasons) > 0"
            ),
            name="training_seasons_present",
        ),
        CheckConstraint(
            (
                "array_position("
                "train_seasons, NULL"
                ") IS NULL "
                "AND array_position("
                "validation_seasons, NULL"
                ") IS NULL "
                "AND array_position("
                "excluded_seasons, NULL"
                ") IS NULL"
            ),
            name="season_arrays_without_nulls",
        ),
        CheckConstraint(
            (
                "NOT ("
                "train_seasons && validation_seasons"
                ") AND NOT ("
                "train_seasons && excluded_seasons"
                ") AND NOT ("
                "validation_seasons && excluded_seasons"
                ")"
            ),
            name="season_groups_disjoint",
        ),
        CheckConstraint(
            (
                "("
                "train_seasons || "
                "validation_seasons || "
                "excluded_seasons"
                ") @> ARRAY[2022, 2023, 2024]::smallint[] "
                "AND ("
                "train_seasons || "
                "validation_seasons || "
                "excluded_seasons"
                ") <@ ARRAY[2022, 2023, 2024]::smallint[] "
                "AND cardinality("
                "train_seasons || "
                "validation_seasons || "
                "excluded_seasons"
                ") = 3"
            ),
            name="development_seasons_exact",
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
    fold_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )
    train_seasons: Mapped[list[int]] = mapped_column(
        ARRAY(SmallInteger),
        nullable=False,
    )
    validation_seasons: Mapped[list[int]] = (
        mapped_column(
            ARRAY(SmallInteger),
            nullable=False,
        )
    )
    excluded_seasons: Mapped[list[int]] = (
        mapped_column(
            ARRAY(SmallInteger),
            nullable=False,
        )
    )


class SessionSplitAssignment(Base):
    """Assign one complete race session to one fold role."""

    __tablename__ = SESSION_SPLIT_ASSIGNMENT_TABLE_NAME
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "dataset_contract_version",
                "fold_id",
            ],
            [
                (
                    f"{_qualified_table(
                        'temporal_folds'
                    )}.dataset_contract_version"
                ),
                (
                    f"{_qualified_table(
                        'temporal_folds'
                    )}.fold_id"
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
        CheckConstraint(
            (
                "char_length("
                "btrim(fold_id)"
                ") > 0"
            ),
            name="fold_id_not_blank",
        ),
        CheckConstraint(
            "season IN (2022, 2023, 2024)",
            name="development_season_only",
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
                "role IN ("
                "'TRAIN', "
                "'VALIDATION', "
                "'EXCLUDED'"
                ")"
            ),
            name="role_allowed",
        ),
        Index(
            (
                "ix_session_split_assignments_"
                "fold_role"
            ),
            "dataset_contract_version",
            "fold_id",
            "role",
            "session_id",
        ),
        Index(
            (
                "ix_session_split_assignments_"
                "session"
            ),
            "dataset_contract_version",
            "session_id",
        ),
    )

    dataset_contract_version: Mapped[str] = (
        mapped_column(
            String(32),
            primary_key=True,
        )
    )
    fold_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(16),
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
    role: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
