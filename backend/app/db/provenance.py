"""Version and artifact provenance database models."""

from datetime import datetime
from typing import Final

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    DATABASE_SCHEMA_NAME,
    Base,
)

PROVENANCE_TABLE_NAMES: Final = (
    "processed_session_partitions",
    "dataset_versions",
    "dataset_builds",
    "dataset_sessions",
)


def _qualified_table(table_name: str) -> str:
    """Return one schema-qualified table name."""
    return (
        f"{DATABASE_SCHEMA_NAME}."
        f"{table_name}"
    )


class ProcessedSessionPartition(Base):
    """Record one verified processed session partition."""

    __tablename__ = "processed_session_partitions"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "source_contract_version",
            "processed_contract_version",
            "cleaning_rule_version",
        ),
        UniqueConstraint(
            "processed_partition_id",
            "session_id",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(source_contract_version)"
                ") > 0"
            ),
            name="source_version_not_blank",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(processed_contract_version)"
                ") > 0"
            ),
            name="processed_version_not_blank",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(cleaning_rule_version)"
                ") > 0"
            ),
            name="cleaning_version_not_blank",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(session_directory)"
                ") > 0"
            ),
            name="directory_not_blank",
        ),
        CheckConstraint(
            (
                "source_manifest_sha256 "
                "IS NULL OR "
                "source_manifest_sha256 ~ "
                "'^[0-9a-f]{64}$'"
            ),
            name="source_manifest_hash",
        ),
        CheckConstraint(
            (
                "processed_manifest_sha256 ~ "
                "'^[0-9a-f]{64}$'"
            ),
            name="processed_manifest_hash",
        ),
        CheckConstraint(
            (
                "laps_sha256 ~ "
                "'^[0-9a-f]{64}$'"
            ),
            name="laps_hash",
        ),
        CheckConstraint(
            (
                "stints_sha256 ~ "
                "'^[0-9a-f]{64}$'"
            ),
            name="stints_hash",
        ),
        CheckConstraint(
            (
                "pit_events_sha256 ~ "
                "'^[0-9a-f]{64}$'"
            ),
            name="pit_events_hash",
        ),
        CheckConstraint(
            (
                "quality_report_sha256 ~ "
                "'^[0-9a-f]{64}$'"
            ),
            name="quality_report_hash",
        ),
        CheckConstraint(
            "laps_rows >= 0",
            name="laps_rows_non_negative",
        ),
        CheckConstraint(
            "stints_rows >= 0",
            name="stints_rows_non_negative",
        ),
        CheckConstraint(
            "pit_events_rows >= 0",
            name="pit_events_rows_non_negative",
        ),
        CheckConstraint(
            "total_size_bytes >= 0",
            name="size_non_negative",
        ),
        Index(
            (
                "ix_processed_session_"
                "partitions_session_id"
            ),
            "session_id",
        ),
        Index(
            (
                "ix_processed_session_"
                "partitions_versions"
            ),
            "processed_contract_version",
            "cleaning_rule_version",
        ),
    )

    processed_partition_id: Mapped[int] = (
        mapped_column(
            BigInteger,
            Identity(),
            primary_key=True,
        )
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
        nullable=False,
    )
    source_contract_version: Mapped[str] = (
        mapped_column(
            String(32),
            nullable=False,
        )
    )
    processed_contract_version: Mapped[str] = (
        mapped_column(
            String(32),
            nullable=False,
        )
    )
    cleaning_rule_version: Mapped[str] = (
        mapped_column(
            String(32),
            nullable=False,
        )
    )
    created_at_utc: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=False,
        )
    )
    session_directory: Mapped[str] = (
        mapped_column(
            Text,
            nullable=False,
        )
    )
    source_manifest_sha256: Mapped[
        str | None
    ] = mapped_column(
        CHAR(64),
        nullable=True,
    )
    processed_manifest_sha256: Mapped[str] = (
        mapped_column(
            CHAR(64),
            nullable=False,
        )
    )
    laps_sha256: Mapped[str] = mapped_column(
        CHAR(64),
        nullable=False,
    )
    stints_sha256: Mapped[str] = mapped_column(
        CHAR(64),
        nullable=False,
    )
    pit_events_sha256: Mapped[str] = (
        mapped_column(
            CHAR(64),
            nullable=False,
        )
    )
    quality_report_sha256: Mapped[str] = (
        mapped_column(
            CHAR(64),
            nullable=False,
        )
    )
    laps_rows: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    stints_rows: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    pit_events_rows: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    total_size_bytes: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )


class DatasetVersion(Base):
    """Define one immutable analytical dataset version."""

    __tablename__ = "dataset_versions"
    __table_args__ = (
        CheckConstraint(
            (
                "char_length("
                "btrim(dataset_contract_version)"
                ") > 0"
            ),
            name="dataset_version_not_blank",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(database_schema_version)"
                ") > 0"
            ),
            name="database_version_not_blank",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(source_contract_version)"
                ") > 0"
            ),
            name="source_version_not_blank",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(processed_contract_version)"
                ") > 0"
            ),
            name="processed_version_not_blank",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(cleaning_rule_version)"
                ") > 0"
            ),
            name="cleaning_version_not_blank",
        ),
        Index(
            (
                "ix_dataset_versions_"
                "source_versions"
            ),
            "source_contract_version",
            "processed_contract_version",
            "cleaning_rule_version",
        ),
    )

    dataset_contract_version: Mapped[str] = (
        mapped_column(
            String(32),
            primary_key=True,
        )
    )
    database_schema_version: Mapped[str] = (
        mapped_column(
            String(32),
            nullable=False,
        )
    )
    source_contract_version: Mapped[str] = (
        mapped_column(
            String(32),
            nullable=False,
        )
    )
    processed_contract_version: Mapped[str] = (
        mapped_column(
            String(32),
            nullable=False,
        )
    )
    cleaning_rule_version: Mapped[str] = (
        mapped_column(
            String(32),
            nullable=False,
        )
    )
    created_at_utc: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=False,
        )
    )


class DatasetBuild(Base):
    """Record one dataset batch execution."""

    __tablename__ = "dataset_builds"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "dataset_contract_version",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(run_id)"
                ") > 0"
            ),
            name="run_id_not_blank",
        ),
        CheckConstraint(
            (
                "status IN ("
                "'RUNNING', "
                "'SUCCEEDED', "
                "'FAILED'"
                ")"
            ),
            name="status_allowed",
        ),
        CheckConstraint(
            "requested_sessions >= 0",
            name="requested_non_negative",
        ),
        CheckConstraint(
            "written_sessions >= 0",
            name="written_non_negative",
        ),
        CheckConstraint(
            "skipped_sessions >= 0",
            name="skipped_non_negative",
        ),
        CheckConstraint(
            "failed_sessions >= 0",
            name="failed_non_negative",
        ),
        CheckConstraint(
            (
                "status = 'RUNNING' OR "
                "written_sessions "
                "+ skipped_sessions "
                "+ failed_sessions "
                "= requested_sessions"
            ),
            name="terminal_count_balance",
        ),
        CheckConstraint(
            (
                "("
                "status = 'RUNNING' "
                "AND completed_at_utc IS NULL"
                ") OR ("
                "status IN ('SUCCEEDED', 'FAILED') "
                "AND completed_at_utc IS NOT NULL "
                "AND completed_at_utc "
                ">= started_at_utc"
                ")"
            ),
            name="completion_state",
        ),
        CheckConstraint(
            (
                "status <> 'SUCCEEDED' "
                "OR failed_sessions = 0"
            ),
            name="successful_without_failures",
        ),
        CheckConstraint(
            (
                "status <> 'SUCCEEDED' OR ("
                "catalog_sha256 IS NOT NULL "
                "AND splits_sha256 IS NOT NULL"
                ")"
            ),
            name="successful_artifacts_present",
        ),
        CheckConstraint(
            (
                "catalog_sha256 IS NULL OR "
                "catalog_sha256 ~ "
                "'^[0-9a-f]{64}$'"
            ),
            name="catalog_hash",
        ),
        CheckConstraint(
            (
                "splits_sha256 IS NULL OR "
                "splits_sha256 ~ "
                "'^[0-9a-f]{64}$'"
            ),
            name="splits_hash",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(run_record_path)"
                ") > 0"
            ),
            name="run_record_path_not_blank",
        ),
        Index(
            (
                "ix_dataset_builds_"
                "version_started_at"
            ),
            "dataset_contract_version",
            "started_at_utc",
        ),
    )

    run_id: Mapped[str] = mapped_column(
        String(80),
        primary_key=True,
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
            nullable=False,
        )
    )
    started_at_utc: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=False,
        )
    )
    completed_at_utc: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    requested_sessions: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    written_sessions: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    skipped_sessions: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    failed_sessions: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    catalog_sha256: Mapped[str | None] = (
        mapped_column(
            CHAR(64),
            nullable=True,
        )
    )
    splits_sha256: Mapped[str | None] = (
        mapped_column(
            CHAR(64),
            nullable=True,
        )
    )
    run_record_path: Mapped[str] = (
        mapped_column(
            Text,
            nullable=False,
        )
    )


class DatasetSession(Base):
    """Record one authoritative dataset session partition."""

    __tablename__ = "dataset_sessions"
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
                "created_by_run_id",
                "dataset_contract_version",
            ],
            [
                (
                    f"{_qualified_table('dataset_builds')}"
                    ".run_id"
                ),
                (
                    f"{_qualified_table('dataset_builds')}"
                    ".dataset_contract_version"
                ),
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "dataset_contract_version",
            "processed_partition_id",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(session_directory)"
                ") > 0"
            ),
            name="directory_not_blank",
        ),
        CheckConstraint(
            (
                "dataset_manifest_sha256 ~ "
                "'^[0-9a-f]{64}$'"
            ),
            name="manifest_hash",
        ),
        CheckConstraint(
            (
                "decision_rows_sha256 ~ "
                "'^[0-9a-f]{64}$'"
            ),
            name="decision_rows_hash",
        ),
        CheckConstraint(
            (
                "decision_labels_sha256 ~ "
                "'^[0-9a-f]{64}$'"
            ),
            name="decision_labels_hash",
        ),
        CheckConstraint(
            (
                "pit_duration_observations_sha256 ~ "
                "'^[0-9a-f]{64}$'"
            ),
            name="pit_duration_hash",
        ),
        CheckConstraint(
            (
                "quality_report_sha256 ~ "
                "'^[0-9a-f]{64}$'"
            ),
            name="quality_report_hash",
        ),
        CheckConstraint(
            (
                "decision_rows >= 0 "
                "AND eligible_decisions >= 0 "
                "AND ineligible_decisions >= 0 "
                "AND decision_label_rows >= 0"
            ),
            name="decision_counts_non_negative",
        ),
        CheckConstraint(
            (
                "lap_time_target_eligible_rows >= 0 "
                "AND pit_now_rows >= 0 "
                "AND stay_out_rows >= 0"
            ),
            name="label_counts_non_negative",
        ),
        CheckConstraint(
            (
                "pit_duration_rows >= 0 "
                "AND "
                "pit_duration_target_eligible_rows "
                ">= 0"
            ),
            name="pit_counts_non_negative",
        ),
        CheckConstraint(
            "total_size_bytes >= 0",
            name="size_non_negative",
        ),
        CheckConstraint(
            (
                "decision_rows = "
                "eligible_decisions "
                "+ ineligible_decisions"
            ),
            name="decision_count_balance",
        ),
        CheckConstraint(
            (
                "decision_label_rows "
                "= decision_rows"
            ),
            name="label_count_balance",
        ),
        CheckConstraint(
            (
                "pit_now_rows "
                "+ stay_out_rows "
                "= eligible_decisions"
            ),
            name="action_count_balance",
        ),
        CheckConstraint(
            (
                "lap_time_target_eligible_rows "
                "<= eligible_decisions"
            ),
            name="lap_target_within_eligible",
        ),
        CheckConstraint(
            (
                "pit_duration_target_eligible_rows "
                "<= pit_duration_rows"
            ),
            name="pit_target_within_observations",
        ),
        Index(
            (
                "ix_dataset_sessions_"
                "session_id"
            ),
            "session_id",
        ),
        Index(
            (
                "ix_dataset_sessions_"
                "processed_partition_id"
            ),
            "processed_partition_id",
        ),
        Index(
            (
                "ix_dataset_sessions_"
                "created_by_run_id"
            ),
            "created_by_run_id",
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
    processed_partition_id: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    created_by_run_id: Mapped[str] = (
        mapped_column(
            String(80),
            nullable=False,
        )
    )
    created_at_utc: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=False,
        )
    )
    session_directory: Mapped[str] = (
        mapped_column(
            Text,
            nullable=False,
        )
    )
    dataset_manifest_sha256: Mapped[str] = (
        mapped_column(
            CHAR(64),
            nullable=False,
        )
    )
    decision_rows_sha256: Mapped[str] = (
        mapped_column(
            CHAR(64),
            nullable=False,
        )
    )
    decision_labels_sha256: Mapped[str] = (
        mapped_column(
            CHAR(64),
            nullable=False,
        )
    )
    pit_duration_observations_sha256: Mapped[
        str
    ] = mapped_column(
        CHAR(64),
        nullable=False,
    )
    quality_report_sha256: Mapped[str] = (
        mapped_column(
            CHAR(64),
            nullable=False,
        )
    )
    decision_rows: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    eligible_decisions: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    ineligible_decisions: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    decision_label_rows: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    lap_time_target_eligible_rows: Mapped[
        int
    ] = mapped_column(
        BigInteger,
        nullable=False,
    )
    pit_now_rows: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    stay_out_rows: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    pit_duration_rows: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    pit_duration_target_eligible_rows: Mapped[
        int
    ] = mapped_column(
        BigInteger,
        nullable=False,
    )
    total_size_bytes: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )