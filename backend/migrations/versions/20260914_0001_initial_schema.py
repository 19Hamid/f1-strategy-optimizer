"""Create the immutable initial PostgreSQL application schema.

Revision ID: 20260914_0001
Revises:
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260914_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create schema V1 from an empty PostgreSQL database."""
    op.execute(sa.schema.CreateSchema("f1_strategy"))
    op.create_table(
        "circuits",
        sa.Column(
            "circuit_id", sa.BigInteger(), sa.Identity(always=False), nullable=False
        ),
        sa.Column("country", sa.String(length=100), nullable=False),
        sa.Column("location", sa.String(length=100), nullable=False),
        sa.Column("circuit_name", sa.String(length=200), nullable=True),
        sa.CheckConstraint(
            "char_length(btrim(country)) > 0",
            name=op.f("ck_circuits_country_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(location)) > 0",
            name=op.f("ck_circuits_location_not_blank"),
        ),
        sa.CheckConstraint(
            "circuit_name IS NULL OR char_length(btrim(circuit_name)) > 0",
            name=op.f("ck_circuits_name_not_blank"),
        ),
        sa.PrimaryKeyConstraint("circuit_id", name=op.f("pk_circuits")),
        sa.UniqueConstraint(
            "country", "location", name=op.f("uq_circuits_country_location")
        ),
        schema="f1_strategy",
    )
    op.create_table(
        "dataset_versions",
        sa.Column("dataset_contract_version", sa.String(length=32), nullable=False),
        sa.Column("database_schema_version", sa.String(length=32), nullable=False),
        sa.Column("source_contract_version", sa.String(length=32), nullable=False),
        sa.Column("processed_contract_version", sa.String(length=32), nullable=False),
        sa.Column("cleaning_rule_version", sa.String(length=32), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(btrim(cleaning_rule_version)) > 0",
            name=op.f("ck_dataset_versions_cleaning_version_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(database_schema_version)) > 0",
            name=op.f("ck_dataset_versions_database_version_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(dataset_contract_version)) > 0",
            name=op.f("ck_dataset_versions_dataset_version_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(processed_contract_version)) > 0",
            name=op.f("ck_dataset_versions_processed_version_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(source_contract_version)) > 0",
            name=op.f("ck_dataset_versions_source_version_not_blank"),
        ),
        sa.PrimaryKeyConstraint(
            "dataset_contract_version", name=op.f("pk_dataset_versions")
        ),
        schema="f1_strategy",
    )
    op.create_index(
        "ix_dataset_versions_source_versions",
        "dataset_versions",
        [
            "source_contract_version",
            "processed_contract_version",
            "cleaning_rule_version",
        ],
        unique=False,
        schema="f1_strategy",
    )
    op.create_table(
        "drivers",
        sa.Column(
            "driver_id", sa.BigInteger(), sa.Identity(always=False), nullable=False
        ),
        sa.Column("driver_code", sa.String(length=16), nullable=False),
        sa.Column("driver_name", sa.String(length=200), nullable=True),
        sa.CheckConstraint(
            "char_length(driver_code) BETWEEN 1 AND 16",
            name=op.f("ck_drivers_code_length"),
        ),
        sa.CheckConstraint(
            "driver_code = upper(btrim(driver_code))",
            name=op.f("ck_drivers_code_normalized"),
        ),
        sa.CheckConstraint(
            "driver_name IS NULL OR char_length(btrim(driver_name)) > 0",
            name=op.f("ck_drivers_name_not_blank"),
        ),
        sa.PrimaryKeyConstraint("driver_id", name=op.f("pk_drivers")),
        sa.UniqueConstraint("driver_code", name=op.f("uq_drivers_driver_code")),
        schema="f1_strategy",
    )
    op.create_table(
        "seasons",
        sa.Column("season", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.CheckConstraint(
            "season BETWEEN 1000 AND 9999", name=op.f("ck_seasons_four_digit")
        ),
        sa.PrimaryKeyConstraint("season", name=op.f("pk_seasons")),
        schema="f1_strategy",
    )
    op.create_table(
        "teams",
        sa.Column(
            "team_id", sa.BigInteger(), sa.Identity(always=False), nullable=False
        ),
        sa.Column("team_name", sa.String(length=200), nullable=False),
        sa.CheckConstraint(
            "char_length(team_name) > 0", name=op.f("ck_teams_name_not_blank")
        ),
        sa.CheckConstraint(
            "team_name = btrim(team_name)", name=op.f("ck_teams_name_trimmed")
        ),
        sa.PrimaryKeyConstraint("team_id", name=op.f("pk_teams")),
        sa.UniqueConstraint("team_name", name=op.f("uq_teams_team_name")),
        schema="f1_strategy",
    )
    op.create_table(
        "dataset_builds",
        sa.Column("run_id", sa.String(length=80), nullable=False),
        sa.Column("dataset_contract_version", sa.String(length=32), nullable=False),
        sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_sessions", sa.BigInteger(), nullable=False),
        sa.Column("written_sessions", sa.BigInteger(), nullable=False),
        sa.Column("skipped_sessions", sa.BigInteger(), nullable=False),
        sa.Column("failed_sessions", sa.BigInteger(), nullable=False),
        sa.Column("catalog_sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("splits_sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("run_record_path", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "(status = 'RUNNING' AND completed_at_utc IS NULL) OR (status IN ('SUCCEEDED', 'FAILED') AND completed_at_utc IS NOT NULL AND completed_at_utc >= started_at_utc)",
            name=op.f("ck_dataset_builds_completion_state"),
        ),
        sa.CheckConstraint(
            "catalog_sha256 IS NULL OR catalog_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_dataset_builds_catalog_hash"),
        ),
        sa.CheckConstraint(
            "splits_sha256 IS NULL OR splits_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_dataset_builds_splits_hash"),
        ),
        sa.CheckConstraint(
            "status <> 'SUCCEEDED' OR (catalog_sha256 IS NOT NULL AND splits_sha256 IS NOT NULL)",
            name=op.f("ck_dataset_builds_successful_artifacts_present"),
        ),
        sa.CheckConstraint(
            "status <> 'SUCCEEDED' OR failed_sessions = 0",
            name=op.f("ck_dataset_builds_successful_without_failures"),
        ),
        sa.CheckConstraint(
            "status = 'RUNNING' OR written_sessions + skipped_sessions + failed_sessions = requested_sessions",
            name=op.f("ck_dataset_builds_terminal_count_balance"),
        ),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'FAILED')",
            name=op.f("ck_dataset_builds_status_allowed"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(run_id)) > 0",
            name=op.f("ck_dataset_builds_run_id_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(run_record_path)) > 0",
            name=op.f("ck_dataset_builds_run_record_path_not_blank"),
        ),
        sa.CheckConstraint(
            "failed_sessions >= 0", name=op.f("ck_dataset_builds_failed_non_negative")
        ),
        sa.CheckConstraint(
            "requested_sessions >= 0",
            name=op.f("ck_dataset_builds_requested_non_negative"),
        ),
        sa.CheckConstraint(
            "skipped_sessions >= 0", name=op.f("ck_dataset_builds_skipped_non_negative")
        ),
        sa.CheckConstraint(
            "written_sessions >= 0", name=op.f("ck_dataset_builds_written_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["dataset_contract_version"],
            ["f1_strategy.dataset_versions.dataset_contract_version"],
            name=op.f("fk_dataset_builds_dataset_contract_version_dataset_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_dataset_builds")),
        sa.UniqueConstraint(
            "run_id",
            "dataset_contract_version",
            name=op.f("uq_dataset_builds_run_id_dataset_contract_version"),
        ),
        schema="f1_strategy",
    )
    op.create_index(
        "ix_dataset_builds_version_started_at",
        "dataset_builds",
        ["dataset_contract_version", "started_at_utc"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_table(
        "events",
        sa.Column(
            "event_id", sa.BigInteger(), sa.Identity(always=False), nullable=False
        ),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("round_number", sa.SmallInteger(), nullable=False),
        sa.Column("circuit_id", sa.BigInteger(), nullable=False),
        sa.Column("event_name", sa.String(length=200), nullable=False),
        sa.Column("official_event_name", sa.String(length=300), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_format", sa.String(length=50), nullable=False),
        sa.CheckConstraint(
            "char_length(btrim(event_format)) > 0",
            name=op.f("ck_events_event_format_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(event_name)) > 0",
            name=op.f("ck_events_event_name_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(official_event_name)) > 0",
            name=op.f("ck_events_official_name_not_blank"),
        ),
        sa.CheckConstraint(
            "round_number BETWEEN 1 AND 30", name=op.f("ck_events_round_number_range")
        ),
        sa.ForeignKeyConstraint(
            ["circuit_id"],
            ["f1_strategy.circuits.circuit_id"],
            name=op.f("fk_events_circuit_id_circuits"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["season"],
            ["f1_strategy.seasons.season"],
            name=op.f("fk_events_season_seasons"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_events")),
        sa.UniqueConstraint(
            "event_id",
            "season",
            "round_number",
            name=op.f("uq_events_event_id_season_round_number"),
        ),
        sa.UniqueConstraint(
            "season", "round_number", name=op.f("uq_events_season_round_number")
        ),
        schema="f1_strategy",
    )
    op.create_index(
        "ix_events_circuit_id_season",
        "events",
        ["circuit_id", "season"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_index(
        "ix_events_season_event_date",
        "events",
        ["season", "event_date"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_table(
        "quality_reasons",
        sa.Column("dataset_contract_version", sa.String(length=32), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("canonical_ordinal", sa.SmallInteger(), nullable=False),
        sa.Column("is_exclusion", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "reason_code ~ '^[A-Z][A-Z0-9_]*$'",
            name=op.f("ck_quality_reasons_reason_code_normalized"),
        ),
        sa.CheckConstraint(
            "scope IN ('PROCESSED_LAP', 'RECONSTRUCTED_STINT', 'RECONSTRUCTED_PIT_EVENT', 'DECISION', 'LAP_TARGET', 'PIT_DURATION_TARGET')",
            name=op.f("ck_quality_reasons_scope_allowed"),
        ),
        sa.CheckConstraint(
            "canonical_ordinal >= 0",
            name=op.f("ck_quality_reasons_canonical_ordinal_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_contract_version"],
            ["f1_strategy.dataset_versions.dataset_contract_version"],
            name=op.f("fk_quality_reasons_dataset_contract_version_dataset_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_contract_version",
            "scope",
            "reason_code",
            name=op.f("pk_quality_reasons"),
        ),
        sa.UniqueConstraint(
            "dataset_contract_version",
            "scope",
            "canonical_ordinal",
            name=op.f(
                "uq_quality_reasons_dataset_contract_version_scope_canonical_ordinal"
            ),
        ),
        schema="f1_strategy",
    )
    op.create_table(
        "temporal_folds",
        sa.Column("dataset_contract_version", sa.String(length=32), nullable=False),
        sa.Column("fold_id", sa.String(length=64), nullable=False),
        sa.Column(
            "train_seasons",
            postgresql.ARRAY(sa.SmallInteger()),
            nullable=False,
        ),
        sa.Column(
            "validation_seasons",
            postgresql.ARRAY(sa.SmallInteger()),
            nullable=False,
        ),
        sa.Column(
            "excluded_seasons",
            postgresql.ARRAY(sa.SmallInteger()),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(train_seasons || validation_seasons || excluded_seasons) @> ARRAY[2022, 2023, 2024]::smallint[] AND (train_seasons || validation_seasons || excluded_seasons) <@ ARRAY[2022, 2023, 2024]::smallint[] AND cardinality(train_seasons || validation_seasons || excluded_seasons) = 3",
            name=op.f("ck_temporal_folds_development_seasons_exact"),
        ),
        sa.CheckConstraint(
            "NOT (train_seasons && validation_seasons) AND NOT (train_seasons && excluded_seasons) AND NOT (validation_seasons && excluded_seasons)",
            name=op.f("ck_temporal_folds_season_groups_disjoint"),
        ),
        sa.CheckConstraint(
            "array_position(train_seasons, NULL) IS NULL AND array_position(validation_seasons, NULL) IS NULL AND array_position(excluded_seasons, NULL) IS NULL",
            name=op.f("ck_temporal_folds_season_arrays_without_nulls"),
        ),
        sa.CheckConstraint(
            "cardinality(train_seasons) > 0",
            name=op.f("ck_temporal_folds_training_seasons_present"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(fold_id)) > 0",
            name=op.f("ck_temporal_folds_fold_id_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_contract_version"],
            ["f1_strategy.dataset_versions.dataset_contract_version"],
            name=op.f("fk_temporal_folds_dataset_contract_version_dataset_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_contract_version", "fold_id", name=op.f("pk_temporal_folds")
        ),
        schema="f1_strategy",
    )
    op.create_table(
        "race_sessions",
        sa.Column("session_id", sa.String(length=16), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("round_number", sa.SmallInteger(), nullable=False),
        sa.Column("session_type", sa.String(length=8), nullable=False),
        sa.CheckConstraint(
            "session_id = season::text || '-' || lpad(round_number::text, 2, '0') || '-' || session_type",
            name=op.f("ck_race_sessions_canonical_identifier"),
        ),
        sa.CheckConstraint(
            "session_id ~ '^[0-9]{4}-[0-9]{2}-R$'",
            name=op.f("ck_race_sessions_identifier_format"),
        ),
        sa.CheckConstraint(
            "session_type = 'R'", name=op.f("ck_race_sessions_race_session_only")
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "season", "round_number"],
            [
                "f1_strategy.events.event_id",
                "f1_strategy.events.season",
                "f1_strategy.events.round_number",
            ],
            name=op.f("fk_race_sessions_event_id_season_round_number_events"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_race_sessions")),
        sa.UniqueConstraint(
            "event_id",
            "session_type",
            name=op.f("uq_race_sessions_event_id_session_type"),
        ),
        sa.UniqueConstraint(
            "season",
            "round_number",
            "session_type",
            name=op.f("uq_race_sessions_season_round_number_session_type"),
        ),
        schema="f1_strategy",
    )
    op.create_index(
        "ix_race_sessions_event_id",
        "race_sessions",
        ["event_id"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_index(
        "ix_race_sessions_season_round_number",
        "race_sessions",
        ["season", "round_number"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_table(
        "processed_session_partitions",
        sa.Column(
            "processed_partition_id",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column("session_id", sa.String(length=16), nullable=False),
        sa.Column("source_contract_version", sa.String(length=32), nullable=False),
        sa.Column("processed_contract_version", sa.String(length=32), nullable=False),
        sa.Column("cleaning_rule_version", sa.String(length=32), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_directory", sa.Text(), nullable=False),
        sa.Column("source_manifest_sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("processed_manifest_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("laps_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("stints_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("pit_events_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("quality_report_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("laps_rows", sa.BigInteger(), nullable=False),
        sa.Column("stints_rows", sa.BigInteger(), nullable=False),
        sa.Column("pit_events_rows", sa.BigInteger(), nullable=False),
        sa.Column("total_size_bytes", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "laps_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_processed_session_partitions_laps_hash"),
        ),
        sa.CheckConstraint(
            "pit_events_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_processed_session_partitions_pit_events_hash"),
        ),
        sa.CheckConstraint(
            "processed_manifest_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_processed_session_partitions_processed_manifest_hash"),
        ),
        sa.CheckConstraint(
            "quality_report_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_processed_session_partitions_quality_report_hash"),
        ),
        sa.CheckConstraint(
            "source_manifest_sha256 IS NULL OR source_manifest_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_processed_session_partitions_source_manifest_hash"),
        ),
        sa.CheckConstraint(
            "stints_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_processed_session_partitions_stints_hash"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(cleaning_rule_version)) > 0",
            name=op.f("ck_processed_session_partitions_cleaning_version_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(processed_contract_version)) > 0",
            name=op.f("ck_processed_session_partitions_processed_version_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(session_directory)) > 0",
            name=op.f("ck_processed_session_partitions_directory_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(source_contract_version)) > 0",
            name=op.f("ck_processed_session_partitions_source_version_not_blank"),
        ),
        sa.CheckConstraint(
            "laps_rows >= 0",
            name=op.f("ck_processed_session_partitions_laps_rows_non_negative"),
        ),
        sa.CheckConstraint(
            "pit_events_rows >= 0",
            name=op.f("ck_processed_session_partitions_pit_events_rows_non_negative"),
        ),
        sa.CheckConstraint(
            "stints_rows >= 0",
            name=op.f("ck_processed_session_partitions_stints_rows_non_negative"),
        ),
        sa.CheckConstraint(
            "total_size_bytes >= 0",
            name=op.f("ck_processed_session_partitions_size_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["f1_strategy.race_sessions.session_id"],
            name=op.f("fk_processed_session_partitions_session_id_race_sessions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "processed_partition_id", name=op.f("pk_processed_session_partitions")
        ),
        sa.UniqueConstraint(
            "processed_partition_id",
            "session_id",
            name=op.f(
                "uq_processed_session_partitions_processed_partition_id_session_id"
            ),
        ),
        sa.UniqueConstraint(
            "session_id",
            "source_contract_version",
            "processed_contract_version",
            "cleaning_rule_version",
            name=op.f(
                "uq_processed_session_partitions_session_id_source_contract_version_processed_contract_version_cleaning_rule_version"
            ),
        ),
        schema="f1_strategy",
    )
    op.create_index(
        "ix_processed_session_partitions_session_id",
        "processed_session_partitions",
        ["session_id"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_index(
        "ix_processed_session_partitions_versions",
        "processed_session_partitions",
        ["processed_contract_version", "cleaning_rule_version"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_table(
        "session_participants",
        sa.Column("session_id", sa.String(length=16), nullable=False),
        sa.Column("driver_id", sa.BigInteger(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("driver_number", sa.String(length=8), nullable=False),
        sa.CheckConstraint(
            "char_length(btrim(driver_number)) > 0",
            name=op.f("ck_session_participants_driver_number_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["f1_strategy.drivers.driver_id"],
            name=op.f("fk_session_participants_driver_id_drivers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["f1_strategy.race_sessions.session_id"],
            name=op.f("fk_session_participants_session_id_race_sessions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["f1_strategy.teams.team_id"],
            name=op.f("fk_session_participants_team_id_teams"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "session_id", "driver_id", name=op.f("pk_session_participants")
        ),
        sa.UniqueConstraint(
            "session_id",
            "driver_number",
            name=op.f("uq_session_participants_session_id_driver_number"),
        ),
        schema="f1_strategy",
    )
    op.create_index(
        "ix_session_participants_driver_id",
        "session_participants",
        ["driver_id"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_index(
        "ix_session_participants_team_id_session_id",
        "session_participants",
        ["team_id", "session_id"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_table(
        "dataset_sessions",
        sa.Column("dataset_contract_version", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=16), nullable=False),
        sa.Column("processed_partition_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by_run_id", sa.String(length=80), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_directory", sa.Text(), nullable=False),
        sa.Column("dataset_manifest_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("decision_rows_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("decision_labels_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "pit_duration_observations_sha256", sa.CHAR(length=64), nullable=False
        ),
        sa.Column("quality_report_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("decision_rows", sa.BigInteger(), nullable=False),
        sa.Column("eligible_decisions", sa.BigInteger(), nullable=False),
        sa.Column("ineligible_decisions", sa.BigInteger(), nullable=False),
        sa.Column("decision_label_rows", sa.BigInteger(), nullable=False),
        sa.Column("lap_time_target_eligible_rows", sa.BigInteger(), nullable=False),
        sa.Column("pit_now_rows", sa.BigInteger(), nullable=False),
        sa.Column("stay_out_rows", sa.BigInteger(), nullable=False),
        sa.Column("pit_duration_rows", sa.BigInteger(), nullable=False),
        sa.Column("pit_duration_target_eligible_rows", sa.BigInteger(), nullable=False),
        sa.Column("total_size_bytes", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "dataset_manifest_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_dataset_sessions_manifest_hash"),
        ),
        sa.CheckConstraint(
            "decision_labels_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_dataset_sessions_decision_labels_hash"),
        ),
        sa.CheckConstraint(
            "decision_rows_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_dataset_sessions_decision_rows_hash"),
        ),
        sa.CheckConstraint(
            "pit_duration_observations_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_dataset_sessions_pit_duration_hash"),
        ),
        sa.CheckConstraint(
            "quality_report_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_dataset_sessions_quality_report_hash"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(session_directory)) > 0",
            name=op.f("ck_dataset_sessions_directory_not_blank"),
        ),
        sa.CheckConstraint(
            "decision_label_rows = decision_rows",
            name=op.f("ck_dataset_sessions_label_count_balance"),
        ),
        sa.CheckConstraint(
            "decision_rows = eligible_decisions + ineligible_decisions",
            name=op.f("ck_dataset_sessions_decision_count_balance"),
        ),
        sa.CheckConstraint(
            "decision_rows >= 0 AND eligible_decisions >= 0 AND ineligible_decisions >= 0 AND decision_label_rows >= 0",
            name=op.f("ck_dataset_sessions_decision_counts_non_negative"),
        ),
        sa.CheckConstraint(
            "lap_time_target_eligible_rows <= eligible_decisions",
            name=op.f("ck_dataset_sessions_lap_target_within_eligible"),
        ),
        sa.CheckConstraint(
            "lap_time_target_eligible_rows >= 0 AND pit_now_rows >= 0 AND stay_out_rows >= 0",
            name=op.f("ck_dataset_sessions_label_counts_non_negative"),
        ),
        sa.CheckConstraint(
            "pit_duration_rows >= 0 AND pit_duration_target_eligible_rows >= 0",
            name=op.f("ck_dataset_sessions_pit_counts_non_negative"),
        ),
        sa.CheckConstraint(
            "pit_duration_target_eligible_rows <= pit_duration_rows",
            name=op.f("ck_dataset_sessions_pit_target_within_observations"),
        ),
        sa.CheckConstraint(
            "pit_now_rows + stay_out_rows = eligible_decisions",
            name=op.f("ck_dataset_sessions_action_count_balance"),
        ),
        sa.CheckConstraint(
            "total_size_bytes >= 0", name=op.f("ck_dataset_sessions_size_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_run_id", "dataset_contract_version"],
            [
                "f1_strategy.dataset_builds.run_id",
                "f1_strategy.dataset_builds.dataset_contract_version",
            ],
            name=op.f(
                "fk_dataset_sessions_created_by_run_id_dataset_contract_version_dataset_builds"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_contract_version"],
            ["f1_strategy.dataset_versions.dataset_contract_version"],
            name=op.f("fk_dataset_sessions_dataset_contract_version_dataset_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["processed_partition_id", "session_id"],
            [
                "f1_strategy.processed_session_partitions.processed_partition_id",
                "f1_strategy.processed_session_partitions.session_id",
            ],
            name=op.f(
                "fk_dataset_sessions_processed_partition_id_session_id_processed_session_partitions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["f1_strategy.race_sessions.session_id"],
            name=op.f("fk_dataset_sessions_session_id_race_sessions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_contract_version", "session_id", name=op.f("pk_dataset_sessions")
        ),
        sa.UniqueConstraint(
            "dataset_contract_version",
            "processed_partition_id",
            name=op.f(
                "uq_dataset_sessions_dataset_contract_version_processed_partition_id"
            ),
        ),
        schema="f1_strategy",
    )
    op.create_index(
        "ix_dataset_sessions_created_by_run_id",
        "dataset_sessions",
        ["created_by_run_id"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_index(
        "ix_dataset_sessions_processed_partition_id",
        "dataset_sessions",
        ["processed_partition_id"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_index(
        "ix_dataset_sessions_session_id",
        "dataset_sessions",
        ["session_id"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_table(
        "processed_laps",
        sa.Column("processed_partition_id", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.String(length=16), nullable=False),
        sa.Column("driver_id", sa.BigInteger(), nullable=False),
        sa.Column("source_row_number", sa.BigInteger(), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("round_number", sa.SmallInteger(), nullable=False),
        sa.Column("session_type", sa.String(length=8), nullable=False),
        sa.Column("event_name", sa.String(length=200), nullable=False),
        sa.Column("session_time_nanoseconds", sa.BigInteger(), nullable=True),
        sa.Column("driver", sa.String(length=16), nullable=False),
        sa.Column("driver_number", sa.String(length=8), nullable=False),
        sa.Column("lap_time_nanoseconds", sa.BigInteger(), nullable=True),
        sa.Column("lap_number", sa.SmallInteger(), nullable=False),
        sa.Column("stint_number", sa.SmallInteger(), nullable=False),
        sa.Column("pit_out_time_nanoseconds", sa.BigInteger(), nullable=True),
        sa.Column("pit_in_time_nanoseconds", sa.BigInteger(), nullable=True),
        sa.Column("sector1_time_nanoseconds", sa.BigInteger(), nullable=True),
        sa.Column("sector2_time_nanoseconds", sa.BigInteger(), nullable=True),
        sa.Column("sector3_time_nanoseconds", sa.BigInteger(), nullable=True),
        sa.Column("sector1_session_time_nanoseconds", sa.BigInteger(), nullable=True),
        sa.Column("sector2_session_time_nanoseconds", sa.BigInteger(), nullable=True),
        sa.Column("sector3_session_time_nanoseconds", sa.BigInteger(), nullable=True),
        sa.Column("speed_i1", sa.Double(), nullable=True),
        sa.Column("speed_i2", sa.Double(), nullable=True),
        sa.Column("speed_finish_line", sa.Double(), nullable=True),
        sa.Column("speed_trap", sa.Double(), nullable=True),
        sa.Column("is_personal_best", sa.Boolean(), nullable=True),
        sa.Column("compound", sa.String(length=32), nullable=False),
        sa.Column("tyre_life", sa.Double(), nullable=True),
        sa.Column("fresh_tyre", sa.Boolean(), nullable=False),
        sa.Column("team", sa.String(length=200), nullable=False),
        sa.Column("lap_start_time_nanoseconds", sa.BigInteger(), nullable=False),
        sa.Column("lap_start_date_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("track_status", sa.String(length=32), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=True),
        sa.Column("deleted", sa.Boolean(), nullable=True),
        sa.Column("deleted_reason", sa.Text(), nullable=True),
        sa.Column("fastf1_generated", sa.Boolean(), nullable=False),
        sa.Column("is_accurate", sa.Boolean(), nullable=False),
        sa.Column(
            "weather_observation_time_nanoseconds", sa.BigInteger(), nullable=False
        ),
        sa.Column("air_temperature_celsius", sa.Double(), nullable=False),
        sa.Column("humidity_percent", sa.Double(), nullable=False),
        sa.Column("pressure_mbar", sa.Double(), nullable=False),
        sa.Column("rainfall", sa.Boolean(), nullable=False),
        sa.Column("track_temperature_celsius", sa.Double(), nullable=False),
        sa.Column("wind_direction_degrees", sa.SmallInteger(), nullable=False),
        sa.Column("wind_speed_mps", sa.Double(), nullable=False),
        sa.Column("weather_matched", sa.Boolean(), nullable=False),
        sa.Column("weather_age_seconds", sa.Double(), nullable=False),
        sa.Column("lap_time_seconds", sa.Double(), nullable=True),
        sa.Column("sector1_time_seconds", sa.Double(), nullable=True),
        sa.Column("sector2_time_seconds", sa.Double(), nullable=True),
        sa.Column("sector3_time_seconds", sa.Double(), nullable=True),
        sa.Column("quality_flags", sa.Text(), nullable=False),
        sa.Column("exclusion_reasons", sa.Text(), nullable=False),
        sa.Column("quality_flag_count", sa.BigInteger(), nullable=False),
        sa.Column("exclusion_reason_count", sa.BigInteger(), nullable=False),
        sa.Column("is_eligible", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "session_id = season::text || '-' || lpad(round_number::text, 2, '0') || '-' || session_type",
            name=op.f("ck_processed_laps_canonical_session_identity"),
        ),
        sa.CheckConstraint(
            "session_type = 'R'", name=op.f("ck_processed_laps_race_session_only")
        ),
        sa.CheckConstraint(
            "(is_eligible AND exclusion_reason_count = 0) OR (NOT is_eligible AND exclusion_reason_count > 0)",
            name=op.f("ck_processed_laps_eligibility_exclusion_balance"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(compound)) > 0",
            name=op.f("ck_processed_laps_compound_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(driver_number)) > 0",
            name=op.f("ck_processed_laps_driver_number_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(event_name)) > 0",
            name=op.f("ck_processed_laps_event_name_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(team)) > 0",
            name=op.f("ck_processed_laps_team_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(track_status)) > 0",
            name=op.f("ck_processed_laps_track_status_not_blank"),
        ),
        sa.CheckConstraint(
            "driver = upper(btrim(driver))",
            name=op.f("ck_processed_laps_driver_normalized"),
        ),
        sa.CheckConstraint(
            "exclusion_reason_count >= 0",
            name=op.f("ck_processed_laps_exclusion_count_non_negative"),
        ),
        sa.CheckConstraint(
            "humidity_percent BETWEEN 0 AND 100",
            name=op.f("ck_processed_laps_humidity_range"),
        ),
        sa.CheckConstraint(
            "lap_number >= 1", name=op.f("ck_processed_laps_lap_number_positive")
        ),
        sa.CheckConstraint(
            "lap_time_seconds IS NULL OR lap_time_seconds > 0",
            name=op.f("ck_processed_laps_lap_time_positive"),
        ),
        sa.CheckConstraint(
            "position IS NULL OR position >= 1",
            name=op.f("ck_processed_laps_position_positive"),
        ),
        sa.CheckConstraint(
            "pressure_mbar > 0", name=op.f("ck_processed_laps_pressure_positive")
        ),
        sa.CheckConstraint(
            "quality_flag_count >= 0",
            name=op.f("ck_processed_laps_quality_count_non_negative"),
        ),
        sa.CheckConstraint(
            "round_number BETWEEN 1 AND 30",
            name=op.f("ck_processed_laps_round_number_range"),
        ),
        sa.CheckConstraint(
            "sector1_time_seconds IS NULL OR sector1_time_seconds > 0",
            name=op.f("ck_processed_laps_sector1_time_positive"),
        ),
        sa.CheckConstraint(
            "sector2_time_seconds IS NULL OR sector2_time_seconds > 0",
            name=op.f("ck_processed_laps_sector2_time_positive"),
        ),
        sa.CheckConstraint(
            "sector3_time_seconds IS NULL OR sector3_time_seconds > 0",
            name=op.f("ck_processed_laps_sector3_time_positive"),
        ),
        sa.CheckConstraint(
            "source_row_number >= 0",
            name=op.f("ck_processed_laps_source_row_non_negative"),
        ),
        sa.CheckConstraint(
            "speed_finish_line IS NULL OR speed_finish_line >= 0",
            name=op.f("ck_processed_laps_speed_finish_line_non_negative"),
        ),
        sa.CheckConstraint(
            "speed_i1 IS NULL OR speed_i1 >= 0",
            name=op.f("ck_processed_laps_speed_i1_non_negative"),
        ),
        sa.CheckConstraint(
            "speed_i2 IS NULL OR speed_i2 >= 0",
            name=op.f("ck_processed_laps_speed_i2_non_negative"),
        ),
        sa.CheckConstraint(
            "speed_trap IS NULL OR speed_trap >= 0",
            name=op.f("ck_processed_laps_speed_trap_non_negative"),
        ),
        sa.CheckConstraint(
            "stint_number >= 1", name=op.f("ck_processed_laps_stint_number_positive")
        ),
        sa.CheckConstraint(
            "tyre_life IS NULL OR tyre_life >= 0",
            name=op.f("ck_processed_laps_tyre_life_non_negative"),
        ),
        sa.CheckConstraint(
            "weather_age_seconds >= 0",
            name=op.f("ck_processed_laps_weather_age_non_negative"),
        ),
        sa.CheckConstraint(
            "weather_observation_time_nanoseconds <= lap_start_time_nanoseconds",
            name=op.f("ck_processed_laps_weather_not_from_future"),
        ),
        sa.CheckConstraint(
            "wind_direction_degrees BETWEEN 0 AND 360",
            name=op.f("ck_processed_laps_wind_direction_range"),
        ),
        sa.CheckConstraint(
            "wind_speed_mps >= 0",
            name=op.f("ck_processed_laps_wind_speed_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["driver"],
            ["f1_strategy.drivers.driver_code"],
            name=op.f("fk_processed_laps_driver_drivers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["processed_partition_id", "session_id"],
            [
                "f1_strategy.processed_session_partitions.processed_partition_id",
                "f1_strategy.processed_session_partitions.session_id",
            ],
            name=op.f(
                "fk_processed_laps_processed_partition_id_session_id_processed_session_partitions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "driver_id"],
            [
                "f1_strategy.session_participants.session_id",
                "f1_strategy.session_participants.driver_id",
            ],
            name=op.f("fk_processed_laps_session_id_driver_id_session_participants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["team"],
            ["f1_strategy.teams.team_name"],
            name=op.f("fk_processed_laps_team_teams"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "processed_partition_id",
            "source_row_number",
            name=op.f("pk_processed_laps"),
        ),
        sa.UniqueConstraint(
            "processed_partition_id",
            "driver_id",
            "lap_number",
            name=op.f("uq_processed_laps_processed_partition_id_driver_id_lap_number"),
        ),
        schema="f1_strategy",
    )
    op.create_index(
        "ix_processed_laps_eligible",
        "processed_laps",
        ["processed_partition_id", "source_row_number"],
        unique=False,
        schema="f1_strategy",
        postgresql_where=sa.text("is_eligible"),
    )
    op.create_index(
        "ix_processed_laps_session_driver_lap",
        "processed_laps",
        ["session_id", "driver_id", "lap_number"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_index(
        "ix_processed_laps_session_team",
        "processed_laps",
        ["session_id", "team"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_table(
        "reconstructed_pit_events",
        sa.Column("processed_partition_id", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.String(length=16), nullable=False),
        sa.Column("driver_id", sa.BigInteger(), nullable=False),
        sa.Column("pit_event_id", sa.String(length=64), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("round_number", sa.SmallInteger(), nullable=False),
        sa.Column("session_type", sa.String(length=8), nullable=False),
        sa.Column("event_name", sa.String(length=200), nullable=False),
        sa.Column("driver", sa.String(length=16), nullable=False),
        sa.Column("team", sa.String(length=200), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("pit_in_lap", sa.SmallInteger(), nullable=True),
        sa.Column("pit_out_lap", sa.SmallInteger(), nullable=True),
        sa.Column("stint_before", sa.SmallInteger(), nullable=True),
        sa.Column("stint_after", sa.SmallInteger(), nullable=True),
        sa.Column("compound_before", sa.String(length=32), nullable=True),
        sa.Column("compound_after", sa.String(length=32), nullable=True),
        sa.Column("tyre_life_before", sa.Double(), nullable=True),
        sa.Column("tyre_life_after", sa.Double(), nullable=True),
        sa.Column("pit_in_time_seconds", sa.Double(), nullable=True),
        sa.Column("pit_out_time_seconds", sa.Double(), nullable=True),
        sa.Column("observed_pit_lane_duration_seconds", sa.Double(), nullable=True),
        sa.Column("entry_track_status", sa.String(length=32), nullable=True),
        sa.Column("exit_track_status", sa.String(length=32), nullable=True),
        sa.Column("entry_rainfall", sa.Boolean(), nullable=True),
        sa.Column("exit_rainfall", sa.Boolean(), nullable=True),
        sa.Column("is_stint_change", sa.Boolean(), nullable=True),
        sa.Column("is_compound_change", sa.Boolean(), nullable=True),
        sa.Column("is_green_flag_pair", sa.Boolean(), nullable=False),
        sa.Column("is_dry_weather_pair", sa.Boolean(), nullable=False),
        sa.Column("is_dry_compound_pair", sa.Boolean(), nullable=False),
        sa.Column("is_interrupted_duration", sa.Boolean(), nullable=False),
        sa.Column("is_complete", sa.Boolean(), nullable=False),
        sa.Column("is_duration_analysis_candidate", sa.Boolean(), nullable=False),
        sa.Column("warning_count", sa.BigInteger(), nullable=False),
        sa.Column("warnings", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "(event_type = 'MATCHED' AND pit_in_lap IS NOT NULL AND pit_out_lap IS NOT NULL) OR (event_type = 'ENTRY_ONLY' AND pit_in_lap IS NOT NULL AND pit_out_lap IS NULL) OR (event_type = 'EXIT_ONLY' AND pit_in_lap IS NULL AND pit_out_lap IS NOT NULL)",
            name=op.f("ck_reconstructed_pit_events_event_type_marker_shape"),
        ),
        sa.CheckConstraint(
            "(warning_count = 0 AND warnings = '') OR (warning_count > 0 AND char_length(warnings) > 0)",
            name=op.f("ck_reconstructed_pit_events_warning_encoding_balance"),
        ),
        sa.CheckConstraint(
            "NOT is_complete OR (event_type = 'MATCHED' AND pit_out_lap = pit_in_lap + 1 AND observed_pit_lane_duration_seconds IS NOT NULL AND observed_pit_lane_duration_seconds > 0)",
            name=op.f("ck_reconstructed_pit_events_complete_event_requirements"),
        ),
        sa.CheckConstraint(
            "event_type IN ('MATCHED', 'ENTRY_ONLY', 'EXIT_ONLY')",
            name=op.f("ck_reconstructed_pit_events_event_type_allowed"),
        ),
        sa.CheckConstraint(
            "session_id = season::text || '-' || lpad(round_number::text, 2, '0') || '-' || session_type",
            name=op.f("ck_reconstructed_pit_events_canonical_session_identity"),
        ),
        sa.CheckConstraint(
            "session_type = 'R'",
            name=op.f("ck_reconstructed_pit_events_race_session_only"),
        ),
        sa.CheckConstraint(
            "NOT is_duration_analysis_candidate OR (is_complete AND is_stint_change IS TRUE AND is_green_flag_pair AND is_dry_weather_pair AND is_dry_compound_pair AND NOT is_interrupted_duration)",
            name=op.f("ck_reconstructed_pit_events_duration_candidate_requirements"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(event_name)) > 0",
            name=op.f("ck_reconstructed_pit_events_event_name_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(pit_event_id)) > 0",
            name=op.f("ck_reconstructed_pit_events_pit_event_id_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(team)) > 0",
            name=op.f("ck_reconstructed_pit_events_team_not_blank"),
        ),
        sa.CheckConstraint(
            "driver = upper(btrim(driver))",
            name=op.f("ck_reconstructed_pit_events_driver_normalized"),
        ),
        sa.CheckConstraint(
            "pit_in_lap IS NULL OR pit_in_lap >= 1",
            name=op.f("ck_reconstructed_pit_events_pit_in_lap_positive"),
        ),
        sa.CheckConstraint(
            "pit_out_lap IS NULL OR pit_out_lap >= 1",
            name=op.f("ck_reconstructed_pit_events_pit_out_lap_positive"),
        ),
        sa.CheckConstraint(
            "round_number BETWEEN 1 AND 30",
            name=op.f("ck_reconstructed_pit_events_round_number_range"),
        ),
        sa.CheckConstraint(
            "stint_after IS NULL OR stint_after >= 1",
            name=op.f("ck_reconstructed_pit_events_stint_after_positive"),
        ),
        sa.CheckConstraint(
            "stint_before IS NULL OR stint_before >= 1",
            name=op.f("ck_reconstructed_pit_events_stint_before_positive"),
        ),
        sa.CheckConstraint(
            "warning_count >= 0",
            name=op.f("ck_reconstructed_pit_events_warning_count_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["driver"],
            ["f1_strategy.drivers.driver_code"],
            name=op.f("fk_reconstructed_pit_events_driver_drivers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["processed_partition_id", "session_id"],
            [
                "f1_strategy.processed_session_partitions.processed_partition_id",
                "f1_strategy.processed_session_partitions.session_id",
            ],
            name=op.f(
                "fk_reconstructed_pit_events_processed_partition_id_session_id_processed_session_partitions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "driver_id"],
            [
                "f1_strategy.session_participants.session_id",
                "f1_strategy.session_participants.driver_id",
            ],
            name=op.f(
                "fk_reconstructed_pit_events_session_id_driver_id_session_participants"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["team"],
            ["f1_strategy.teams.team_name"],
            name=op.f("fk_reconstructed_pit_events_team_teams"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "processed_partition_id",
            "pit_event_id",
            name=op.f("pk_reconstructed_pit_events"),
        ),
        schema="f1_strategy",
    )
    op.create_index(
        "ix_reconstructed_pit_events_session_driver_pit_lap",
        "reconstructed_pit_events",
        ["session_id", "driver_id", "pit_in_lap", "pit_out_lap"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_table(
        "reconstructed_stints",
        sa.Column("processed_partition_id", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.String(length=16), nullable=False),
        sa.Column("driver_id", sa.BigInteger(), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("round_number", sa.SmallInteger(), nullable=False),
        sa.Column("session_type", sa.String(length=8), nullable=False),
        sa.Column("event_name", sa.String(length=200), nullable=False),
        sa.Column("driver", sa.String(length=16), nullable=False),
        sa.Column("team", sa.String(length=200), nullable=False),
        sa.Column("stint_number", sa.SmallInteger(), nullable=False),
        sa.Column("compound", sa.String(length=128), nullable=True),
        sa.Column("start_lap", sa.SmallInteger(), nullable=False),
        sa.Column("end_lap", sa.SmallInteger(), nullable=False),
        sa.Column("recorded_laps", sa.BigInteger(), nullable=False),
        sa.Column("start_tyre_life", sa.Double(), nullable=True),
        sa.Column("end_tyre_life", sa.Double(), nullable=True),
        sa.Column("is_first_stint", sa.Boolean(), nullable=False),
        sa.Column("is_last_stint", sa.Boolean(), nullable=False),
        sa.Column("boundary_before_verified", sa.Boolean(), nullable=False),
        sa.Column("boundary_after_verified", sa.Boolean(), nullable=False),
        sa.Column("is_complete", sa.Boolean(), nullable=False),
        sa.Column("warning_count", sa.BigInteger(), nullable=False),
        sa.Column("warnings", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "(is_complete AND warning_count = 0 AND warnings = '') OR (NOT is_complete AND warning_count > 0 AND char_length(warnings) > 0)",
            name=op.f("ck_reconstructed_stints_completeness_warning_balance"),
        ),
        sa.CheckConstraint(
            "session_id = season::text || '-' || lpad(round_number::text, 2, '0') || '-' || session_type",
            name=op.f("ck_reconstructed_stints_canonical_session_identity"),
        ),
        sa.CheckConstraint(
            "session_type = 'R'", name=op.f("ck_reconstructed_stints_race_session_only")
        ),
        sa.CheckConstraint(
            "char_length(btrim(event_name)) > 0",
            name=op.f("ck_reconstructed_stints_event_name_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(team)) > 0",
            name=op.f("ck_reconstructed_stints_team_not_blank"),
        ),
        sa.CheckConstraint(
            "compound IS NULL OR char_length(btrim(compound)) > 0",
            name=op.f("ck_reconstructed_stints_compound_not_blank"),
        ),
        sa.CheckConstraint(
            "driver = upper(btrim(driver))",
            name=op.f("ck_reconstructed_stints_driver_normalized"),
        ),
        sa.CheckConstraint(
            "end_lap >= 1", name=op.f("ck_reconstructed_stints_end_lap_positive")
        ),
        sa.CheckConstraint(
            "end_lap >= start_lap",
            name=op.f("ck_reconstructed_stints_lap_range_ordered"),
        ),
        sa.CheckConstraint(
            "recorded_laps >= 1",
            name=op.f("ck_reconstructed_stints_recorded_laps_positive"),
        ),
        sa.CheckConstraint(
            "round_number BETWEEN 1 AND 30",
            name=op.f("ck_reconstructed_stints_round_number_range"),
        ),
        sa.CheckConstraint(
            "start_lap >= 1", name=op.f("ck_reconstructed_stints_start_lap_positive")
        ),
        sa.CheckConstraint(
            "stint_number >= 1",
            name=op.f("ck_reconstructed_stints_stint_number_positive"),
        ),
        sa.CheckConstraint(
            "warning_count >= 0",
            name=op.f("ck_reconstructed_stints_warning_count_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["driver"],
            ["f1_strategy.drivers.driver_code"],
            name=op.f("fk_reconstructed_stints_driver_drivers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["processed_partition_id", "session_id"],
            [
                "f1_strategy.processed_session_partitions.processed_partition_id",
                "f1_strategy.processed_session_partitions.session_id",
            ],
            name=op.f(
                "fk_reconstructed_stints_processed_partition_id_session_id_processed_session_partitions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "driver_id"],
            [
                "f1_strategy.session_participants.session_id",
                "f1_strategy.session_participants.driver_id",
            ],
            name=op.f(
                "fk_reconstructed_stints_session_id_driver_id_session_participants"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["team"],
            ["f1_strategy.teams.team_name"],
            name=op.f("fk_reconstructed_stints_team_teams"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "processed_partition_id",
            "driver_id",
            "stint_number",
            name=op.f("pk_reconstructed_stints"),
        ),
        schema="f1_strategy",
    )
    op.create_index(
        "ix_reconstructed_stints_session_driver",
        "reconstructed_stints",
        ["session_id", "driver_id", "stint_number"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_table(
        "decision_rows",
        sa.Column("processed_partition_id", sa.BigInteger(), nullable=False),
        sa.Column("driver_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset_contract_version", sa.String(length=32), nullable=False),
        sa.Column("decision_id", sa.String(length=96), nullable=False),
        sa.Column("session_id", sa.String(length=16), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("round_number", sa.SmallInteger(), nullable=False),
        sa.Column("session_type", sa.String(length=8), nullable=False),
        sa.Column("event_name", sa.String(length=200), nullable=False),
        sa.Column("driver", sa.String(length=16), nullable=False),
        sa.Column("driver_number", sa.String(length=8), nullable=False),
        sa.Column("team", sa.String(length=200), nullable=False),
        sa.Column("decision_lap", sa.SmallInteger(), nullable=False),
        sa.Column("decision_time_seconds", sa.Double(), nullable=False),
        sa.Column("source_row_number", sa.BigInteger(), nullable=False),
        sa.Column("cleaning_rule_version", sa.String(length=32), nullable=False),
        sa.Column("processed_contract_version", sa.String(length=32), nullable=False),
        sa.Column("current_compound", sa.String(length=32), nullable=True),
        sa.Column("tyre_age_laps", sa.SmallInteger(), nullable=True),
        sa.Column("current_stint_number", sa.SmallInteger(), nullable=True),
        sa.Column("current_stint_laps_completed", sa.BigInteger(), nullable=True),
        sa.Column("completed_pit_stops", sa.BigInteger(), nullable=False),
        sa.Column("previous_position", sa.SmallInteger(), nullable=True),
        sa.Column("previous_lap_was_target_eligible", sa.Boolean(), nullable=False),
        sa.Column("previous_lap_time_seconds", sa.Double(), nullable=True),
        sa.Column("previous_sector1_time_seconds", sa.Double(), nullable=True),
        sa.Column("previous_sector2_time_seconds", sa.Double(), nullable=True),
        sa.Column("previous_sector3_time_seconds", sa.Double(), nullable=True),
        sa.Column("eligible_laps_completed", sa.BigInteger(), nullable=False),
        sa.Column("rolling_lap_time_median_3", sa.Double(), nullable=True),
        sa.Column("rolling_lap_time_median_5", sa.Double(), nullable=True),
        sa.Column("rolling_lap_time_std_5", sa.Double(), nullable=True),
        sa.Column("rolling_lap_time_trend_5", sa.Double(), nullable=True),
        sa.Column("previous_track_status", sa.String(length=32), nullable=True),
        sa.Column("weather_observation_time_seconds", sa.Double(), nullable=False),
        sa.Column("weather_age_seconds", sa.Double(), nullable=False),
        sa.Column("air_temperature_celsius", sa.Double(), nullable=False),
        sa.Column("humidity_percent", sa.Double(), nullable=False),
        sa.Column("pressure_mbar", sa.Double(), nullable=False),
        sa.Column("track_temperature_celsius", sa.Double(), nullable=False),
        sa.Column("wind_direction_degrees", sa.SmallInteger(), nullable=False),
        sa.Column("wind_speed_mps", sa.Double(), nullable=False),
        sa.Column("rainfall", sa.Boolean(), nullable=False),
        sa.Column("has_consecutive_previous_lap", sa.Boolean(), nullable=False),
        sa.Column("weather_available_by_decision", sa.Boolean(), nullable=False),
        sa.Column("previous_lap_not_pit_commitment", sa.Boolean(), nullable=False),
        sa.Column("state_reconstruction_consistent", sa.Boolean(), nullable=False),
        sa.Column("supported_dry_compound", sa.Boolean(), nullable=False),
        sa.Column("valid_current_tyre_age", sa.Boolean(), nullable=False),
        sa.Column("current_stint_identified", sa.Boolean(), nullable=False),
        sa.Column("dry_at_decision", sa.Boolean(), nullable=False),
        sa.Column("previous_lap_green", sa.Boolean(), nullable=False),
        sa.Column("minimum_history_available", sa.Boolean(), nullable=False),
        sa.Column("previous_position_available", sa.Boolean(), nullable=False),
        sa.Column("is_decision_eligible", sa.Boolean(), nullable=False),
        sa.Column("decision_exclusion_count", sa.BigInteger(), nullable=False),
        sa.Column("decision_exclusion_reasons", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "(is_decision_eligible AND decision_exclusion_count = 0 AND decision_exclusion_reasons = '') OR (NOT is_decision_eligible AND decision_exclusion_count > 0 AND char_length(decision_exclusion_reasons) > 0)",
            name=op.f("ck_decision_rows_eligibility_exclusion_balance"),
        ),
        sa.CheckConstraint(
            "(previous_lap_green AND previous_track_status = '1') OR (NOT previous_lap_green AND (previous_track_status IS NULL OR previous_track_status <> '1'))",
            name=op.f("ck_decision_rows_previous_green_balance"),
        ),
        sa.CheckConstraint(
            "(supported_dry_compound AND current_compound IN ('HARD', 'MEDIUM', 'SOFT')) OR (NOT supported_dry_compound AND (current_compound IS NULL OR current_compound NOT IN ('HARD', 'MEDIUM', 'SOFT')))",
            name=op.f("ck_decision_rows_dry_compound_balance"),
        ),
        sa.CheckConstraint(
            "decision_id = session_id || '-' || driver || '-' || lpad(decision_lap::text, 3, '0')",
            name=op.f("ck_decision_rows_canonical_decision_identity"),
        ),
        sa.CheckConstraint(
            "session_id = season::text || '-' || lpad(round_number::text, 2, '0') || '-' || session_type",
            name=op.f("ck_decision_rows_canonical_session_identity"),
        ),
        sa.CheckConstraint(
            "session_type = 'R'", name=op.f("ck_decision_rows_race_session_only")
        ),
        sa.CheckConstraint(
            "(current_stint_identified AND current_stint_number IS NOT NULL AND current_stint_number > 0 AND current_stint_laps_completed IS NOT NULL AND current_stint_laps_completed >= 1) OR (NOT current_stint_identified AND (current_stint_number IS NULL OR current_stint_number <= 0) AND current_stint_laps_completed IS NULL)",
            name=op.f("ck_decision_rows_current_stint_availability"),
        ),
        sa.CheckConstraint(
            "(minimum_history_available AND rolling_lap_time_median_3 IS NOT NULL AND rolling_lap_time_median_3 > 0 AND rolling_lap_time_median_5 IS NOT NULL AND rolling_lap_time_median_5 > 0 AND rolling_lap_time_std_5 IS NOT NULL AND rolling_lap_time_std_5 >= 0 AND rolling_lap_time_trend_5 IS NOT NULL) OR (NOT minimum_history_available AND rolling_lap_time_median_3 IS NULL AND rolling_lap_time_median_5 IS NULL AND rolling_lap_time_std_5 IS NULL AND rolling_lap_time_trend_5 IS NULL)",
            name=op.f("ck_decision_rows_rolling_history_availability"),
        ),
        sa.CheckConstraint(
            "(previous_lap_was_target_eligible AND previous_lap_time_seconds IS NOT NULL AND previous_lap_time_seconds > 0 AND previous_sector1_time_seconds IS NOT NULL AND previous_sector1_time_seconds > 0 AND previous_sector2_time_seconds IS NOT NULL AND previous_sector2_time_seconds > 0 AND previous_sector3_time_seconds IS NOT NULL AND previous_sector3_time_seconds > 0) OR (NOT previous_lap_was_target_eligible AND previous_lap_time_seconds IS NULL AND previous_sector1_time_seconds IS NULL AND previous_sector2_time_seconds IS NULL AND previous_sector3_time_seconds IS NULL)",
            name=op.f("ck_decision_rows_previous_target_availability"),
        ),
        sa.CheckConstraint(
            "(previous_position_available AND previous_position IS NOT NULL) OR (NOT previous_position_available AND previous_position IS NULL)",
            name=op.f("ck_decision_rows_previous_position_availability"),
        ),
        sa.CheckConstraint(
            "(valid_current_tyre_age AND tyre_age_laps IS NOT NULL AND tyre_age_laps > 0) OR (NOT valid_current_tyre_age AND (tyre_age_laps IS NULL OR tyre_age_laps <= 0))",
            name=op.f("ck_decision_rows_tyre_age_validity"),
        ),
        sa.CheckConstraint(
            "NOT weather_available_by_decision OR (weather_observation_time_seconds <= decision_time_seconds AND weather_age_seconds >= 0)",
            name=op.f("ck_decision_rows_weather_availability_boundary"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(cleaning_rule_version)) > 0",
            name=op.f("ck_decision_rows_cleaning_version_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(driver_number)) > 0",
            name=op.f("ck_decision_rows_driver_number_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(event_name)) > 0",
            name=op.f("ck_decision_rows_event_name_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(processed_contract_version)) > 0",
            name=op.f("ck_decision_rows_processed_version_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(team)) > 0", name=op.f("ck_decision_rows_team_not_blank")
        ),
        sa.CheckConstraint(
            "completed_pit_stops >= 0",
            name=op.f("ck_decision_rows_completed_pit_stops_non_negative"),
        ),
        sa.CheckConstraint(
            "current_compound IS NULL OR char_length(btrim(current_compound)) > 0",
            name=op.f("ck_decision_rows_current_compound_not_blank"),
        ),
        sa.CheckConstraint(
            "decision_exclusion_count >= 0",
            name=op.f("ck_decision_rows_exclusion_count_non_negative"),
        ),
        sa.CheckConstraint(
            "decision_lap >= 2", name=op.f("ck_decision_rows_decision_lap_positive")
        ),
        sa.CheckConstraint(
            "decision_time_seconds >= 0",
            name=op.f("ck_decision_rows_decision_time_non_negative"),
        ),
        sa.CheckConstraint(
            "driver = upper(btrim(driver))",
            name=op.f("ck_decision_rows_driver_normalized"),
        ),
        sa.CheckConstraint(
            "dry_at_decision = (NOT rainfall)",
            name=op.f("ck_decision_rows_dry_decision_balance"),
        ),
        sa.CheckConstraint(
            "eligible_laps_completed >= 0",
            name=op.f("ck_decision_rows_eligible_laps_non_negative"),
        ),
        sa.CheckConstraint(
            "humidity_percent BETWEEN 0 AND 100",
            name=op.f("ck_decision_rows_humidity_range"),
        ),
        sa.CheckConstraint(
            "is_decision_eligible = (has_consecutive_previous_lap AND weather_available_by_decision AND previous_lap_not_pit_commitment AND state_reconstruction_consistent AND supported_dry_compound AND valid_current_tyre_age AND current_stint_identified AND dry_at_decision AND previous_lap_green AND minimum_history_available AND previous_position_available)",
            name=op.f("ck_decision_rows_eligibility_conditions"),
        ),
        sa.CheckConstraint(
            "minimum_history_available = (eligible_laps_completed >= 3)",
            name=op.f("ck_decision_rows_minimum_history_balance"),
        ),
        sa.CheckConstraint(
            "pressure_mbar > 0", name=op.f("ck_decision_rows_pressure_positive")
        ),
        sa.CheckConstraint(
            "previous_position IS NULL OR previous_position >= 1",
            name=op.f("ck_decision_rows_previous_position_positive"),
        ),
        sa.CheckConstraint(
            "previous_track_status IS NULL OR char_length(btrim(previous_track_status)) > 0",
            name=op.f("ck_decision_rows_previous_track_status_not_blank"),
        ),
        sa.CheckConstraint(
            "round_number BETWEEN 1 AND 30",
            name=op.f("ck_decision_rows_round_number_range"),
        ),
        sa.CheckConstraint(
            "source_row_number >= 0",
            name=op.f("ck_decision_rows_source_row_non_negative"),
        ),
        sa.CheckConstraint(
            "wind_direction_degrees BETWEEN 0 AND 360",
            name=op.f("ck_decision_rows_wind_direction_range"),
        ),
        sa.CheckConstraint(
            "wind_speed_mps >= 0", name=op.f("ck_decision_rows_wind_speed_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["dataset_contract_version", "session_id"],
            [
                "f1_strategy.dataset_sessions.dataset_contract_version",
                "f1_strategy.dataset_sessions.session_id",
            ],
            name=op.f(
                "fk_decision_rows_dataset_contract_version_session_id_dataset_sessions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["driver"],
            ["f1_strategy.drivers.driver_code"],
            name=op.f("fk_decision_rows_driver_drivers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["processed_partition_id", "session_id"],
            [
                "f1_strategy.processed_session_partitions.processed_partition_id",
                "f1_strategy.processed_session_partitions.session_id",
            ],
            name=op.f(
                "fk_decision_rows_processed_partition_id_session_id_processed_session_partitions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["processed_partition_id", "source_row_number"],
            [
                "f1_strategy.processed_laps.processed_partition_id",
                "f1_strategy.processed_laps.source_row_number",
            ],
            name=op.f(
                "fk_decision_rows_processed_partition_id_source_row_number_processed_laps"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "driver_id"],
            [
                "f1_strategy.session_participants.session_id",
                "f1_strategy.session_participants.driver_id",
            ],
            name=op.f("fk_decision_rows_session_id_driver_id_session_participants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["team"],
            ["f1_strategy.teams.team_name"],
            name=op.f("fk_decision_rows_team_teams"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_contract_version", "decision_id", name=op.f("pk_decision_rows")
        ),
        sa.UniqueConstraint(
            "dataset_contract_version",
            "session_id",
            "driver_id",
            "decision_lap",
            name=op.f(
                "uq_decision_rows_dataset_contract_version_session_id_driver_id_decision_lap"
            ),
        ),
        schema="f1_strategy",
    )
    op.create_index(
        "ix_decision_rows_eligible",
        "decision_rows",
        ["dataset_contract_version", "session_id", "decision_lap"],
        unique=False,
        schema="f1_strategy",
        postgresql_where=sa.text("is_decision_eligible"),
    )
    op.create_index(
        "ix_decision_rows_session_driver_lap",
        "decision_rows",
        ["session_id", "driver_id", "decision_lap"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_table(
        "pit_duration_observations",
        sa.Column("processed_partition_id", sa.BigInteger(), nullable=False),
        sa.Column("driver_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset_contract_version", sa.String(length=32), nullable=False),
        sa.Column("pit_event_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=16), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("round_number", sa.SmallInteger(), nullable=False),
        sa.Column("session_type", sa.String(length=8), nullable=False),
        sa.Column("event_name", sa.String(length=200), nullable=False),
        sa.Column("driver", sa.String(length=16), nullable=False),
        sa.Column("team", sa.String(length=200), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("pit_in_lap", sa.SmallInteger(), nullable=True),
        sa.Column("pit_out_lap", sa.SmallInteger(), nullable=True),
        sa.Column("stint_before", sa.SmallInteger(), nullable=True),
        sa.Column("stint_after", sa.SmallInteger(), nullable=True),
        sa.Column("compound_before", sa.String(length=32), nullable=True),
        sa.Column("compound_after", sa.String(length=32), nullable=True),
        sa.Column("tyre_life_before", sa.Double(), nullable=True),
        sa.Column("tyre_life_after", sa.Double(), nullable=True),
        sa.Column("is_stint_change", sa.Boolean(), nullable=True),
        sa.Column("is_compound_change", sa.Boolean(), nullable=True),
        sa.Column("is_complete", sa.Boolean(), nullable=False),
        sa.Column("is_green_flag_pair", sa.Boolean(), nullable=False),
        sa.Column("is_dry_weather_pair", sa.Boolean(), nullable=False),
        sa.Column("is_interrupted_duration", sa.Boolean(), nullable=False),
        sa.Column("is_pit_duration_target_eligible", sa.Boolean(), nullable=False),
        sa.Column("pit_duration_target_seconds", sa.Double(), nullable=True),
        sa.Column("pit_duration_exclusion_count", sa.BigInteger(), nullable=False),
        sa.Column("pit_duration_exclusion_reasons", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "(event_type = 'MATCHED' AND pit_in_lap IS NOT NULL AND pit_out_lap IS NOT NULL) OR (event_type = 'ENTRY_ONLY' AND pit_in_lap IS NOT NULL AND pit_out_lap IS NULL) OR (event_type = 'EXIT_ONLY' AND pit_in_lap IS NULL AND pit_out_lap IS NOT NULL)",
            name=op.f("ck_pit_duration_observations_event_type_marker_shape"),
        ),
        sa.CheckConstraint(
            "(is_pit_duration_target_eligible AND pit_duration_exclusion_count = 0 AND pit_duration_exclusion_reasons = '') OR (NOT is_pit_duration_target_eligible AND pit_duration_exclusion_count > 0 AND char_length(pit_duration_exclusion_reasons) > 0)",
            name=op.f("ck_pit_duration_observations_target_exclusion_balance"),
        ),
        sa.CheckConstraint(
            "NOT is_complete OR (event_type = 'MATCHED' AND pit_in_lap IS NOT NULL AND pit_out_lap = pit_in_lap + 1)",
            name=op.f("ck_pit_duration_observations_complete_event_requirements"),
        ),
        sa.CheckConstraint(
            "event_type IN ('MATCHED', 'ENTRY_ONLY', 'EXIT_ONLY')",
            name=op.f("ck_pit_duration_observations_event_type_allowed"),
        ),
        sa.CheckConstraint(
            "is_pit_duration_target_eligible = (is_complete AND is_stint_change IS TRUE AND is_green_flag_pair AND compound_before IS NOT NULL AND compound_before IN ('HARD', 'MEDIUM', 'SOFT') AND compound_after IS NOT NULL AND compound_after IN ('HARD', 'MEDIUM', 'SOFT') AND is_dry_weather_pair AND NOT is_interrupted_duration)",
            name=op.f("ck_pit_duration_observations_exact_target_eligibility"),
        ),
        sa.CheckConstraint(
            "session_id = season::text || '-' || lpad(round_number::text, 2, '0') || '-' || session_type",
            name=op.f("ck_pit_duration_observations_canonical_session_identity"),
        ),
        sa.CheckConstraint(
            "session_type = 'R'",
            name=op.f("ck_pit_duration_observations_race_session_only"),
        ),
        sa.CheckConstraint(
            "(is_pit_duration_target_eligible AND pit_duration_target_seconds IS NOT NULL AND pit_duration_target_seconds > 0) OR (NOT is_pit_duration_target_eligible AND pit_duration_target_seconds IS NULL)",
            name=op.f("ck_pit_duration_observations_target_availability"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(event_name)) > 0",
            name=op.f("ck_pit_duration_observations_event_name_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(pit_event_id)) > 0",
            name=op.f("ck_pit_duration_observations_pit_event_id_not_blank"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(team)) > 0",
            name=op.f("ck_pit_duration_observations_team_not_blank"),
        ),
        sa.CheckConstraint(
            "driver = upper(btrim(driver))",
            name=op.f("ck_pit_duration_observations_driver_normalized"),
        ),
        sa.CheckConstraint(
            "pit_duration_exclusion_count >= 0",
            name=op.f("ck_pit_duration_observations_exclusion_count_non_negative"),
        ),
        sa.CheckConstraint(
            "pit_in_lap IS NULL OR pit_in_lap >= 1",
            name=op.f("ck_pit_duration_observations_pit_in_lap_positive"),
        ),
        sa.CheckConstraint(
            "pit_out_lap IS NULL OR pit_out_lap >= 1",
            name=op.f("ck_pit_duration_observations_pit_out_lap_positive"),
        ),
        sa.CheckConstraint(
            "round_number BETWEEN 1 AND 30",
            name=op.f("ck_pit_duration_observations_round_number_range"),
        ),
        sa.CheckConstraint(
            "stint_after IS NULL OR stint_after >= 1",
            name=op.f("ck_pit_duration_observations_stint_after_positive"),
        ),
        sa.CheckConstraint(
            "stint_before IS NULL OR stint_before >= 1",
            name=op.f("ck_pit_duration_observations_stint_before_positive"),
        ),
        sa.CheckConstraint(
            "tyre_life_after IS NULL OR tyre_life_after >= 0",
            name=op.f("ck_pit_duration_observations_tyre_life_after_non_negative"),
        ),
        sa.CheckConstraint(
            "tyre_life_before IS NULL OR tyre_life_before >= 0",
            name=op.f("ck_pit_duration_observations_tyre_life_before_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_contract_version", "processed_partition_id"],
            [
                "f1_strategy.dataset_sessions.dataset_contract_version",
                "f1_strategy.dataset_sessions.processed_partition_id",
            ],
            name=op.f(
                "fk_pit_duration_observations_dataset_contract_version_processed_partition_id_dataset_sessions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_contract_version", "session_id"],
            [
                "f1_strategy.dataset_sessions.dataset_contract_version",
                "f1_strategy.dataset_sessions.session_id",
            ],
            name=op.f(
                "fk_pit_duration_observations_dataset_contract_version_session_id_dataset_sessions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["driver"],
            ["f1_strategy.drivers.driver_code"],
            name=op.f("fk_pit_duration_observations_driver_drivers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["processed_partition_id", "pit_event_id"],
            [
                "f1_strategy.reconstructed_pit_events.processed_partition_id",
                "f1_strategy.reconstructed_pit_events.pit_event_id",
            ],
            name=op.f(
                "fk_pit_duration_observations_processed_partition_id_pit_event_id_reconstructed_pit_events"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["processed_partition_id", "session_id"],
            [
                "f1_strategy.processed_session_partitions.processed_partition_id",
                "f1_strategy.processed_session_partitions.session_id",
            ],
            name=op.f(
                "fk_pit_duration_observations_processed_partition_id_session_id_processed_session_partitions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "driver_id"],
            [
                "f1_strategy.session_participants.session_id",
                "f1_strategy.session_participants.driver_id",
            ],
            name=op.f(
                "fk_pit_duration_observations_session_id_driver_id_session_participants"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["team"],
            ["f1_strategy.teams.team_name"],
            name=op.f("fk_pit_duration_observations_team_teams"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_contract_version",
            "pit_event_id",
            name=op.f("pk_pit_duration_observations"),
        ),
        schema="f1_strategy",
    )
    op.create_index(
        "ix_pit_duration_observations_session_driver_pit_lap",
        "pit_duration_observations",
        ["session_id", "driver_id", "pit_in_lap", "pit_out_lap"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_index(
        "ix_pit_duration_observations_source_event",
        "pit_duration_observations",
        ["processed_partition_id", "pit_event_id"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_index(
        "ix_pit_duration_observations_target_eligible",
        "pit_duration_observations",
        ["dataset_contract_version", "session_id", "pit_in_lap"],
        unique=False,
        schema="f1_strategy",
        postgresql_where=sa.text("is_pit_duration_target_eligible"),
    )
    op.create_table(
        "pit_event_quality_reasons",
        sa.Column("dataset_contract_version", sa.String(length=32), nullable=False),
        sa.Column("processed_partition_id", sa.BigInteger(), nullable=False),
        sa.Column("pit_event_id", sa.String(length=64), nullable=False),
        sa.Column("reason_ordinal", sa.SmallInteger(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "scope = 'RECONSTRUCTED_PIT_EVENT'",
            name=op.f("ck_pit_event_quality_reasons_scope_exact"),
        ),
        sa.CheckConstraint(
            "reason_ordinal >= 0",
            name=op.f("ck_pit_event_quality_reasons_reason_ordinal_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_contract_version", "scope", "reason_code"],
            [
                "f1_strategy.quality_reasons.dataset_contract_version",
                "f1_strategy.quality_reasons.scope",
                "f1_strategy.quality_reasons.reason_code",
            ],
            name=op.f(
                "fk_pit_event_quality_reasons_dataset_contract_version_scope_reason_code_quality_reasons"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["processed_partition_id", "pit_event_id"],
            [
                "f1_strategy.reconstructed_pit_events.processed_partition_id",
                "f1_strategy.reconstructed_pit_events.pit_event_id",
            ],
            name=op.f(
                "fk_pit_event_quality_reasons_processed_partition_id_pit_event_id_reconstructed_pit_events"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_contract_version",
            "processed_partition_id",
            "pit_event_id",
            "reason_ordinal",
            name=op.f("pk_pit_event_quality_reasons"),
        ),
        sa.UniqueConstraint(
            "dataset_contract_version",
            "processed_partition_id",
            "pit_event_id",
            "reason_code",
            name=op.f(
                "uq_pit_event_quality_reasons_dataset_contract_version_processed_partition_id_pit_event_id_reason_code"
            ),
        ),
        schema="f1_strategy",
    )
    op.create_index(
        "ix_pit_event_quality_reasons_reason_code",
        "pit_event_quality_reasons",
        ["dataset_contract_version", "reason_code"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_table(
        "processed_lap_quality_reasons",
        sa.Column("dataset_contract_version", sa.String(length=32), nullable=False),
        sa.Column("processed_partition_id", sa.BigInteger(), nullable=False),
        sa.Column("source_row_number", sa.BigInteger(), nullable=False),
        sa.Column("reason_ordinal", sa.SmallInteger(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "scope = 'PROCESSED_LAP'",
            name=op.f("ck_processed_lap_quality_reasons_scope_exact"),
        ),
        sa.CheckConstraint(
            "reason_ordinal >= 0",
            name=op.f("ck_processed_lap_quality_reasons_reason_ordinal_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_contract_version", "scope", "reason_code"],
            [
                "f1_strategy.quality_reasons.dataset_contract_version",
                "f1_strategy.quality_reasons.scope",
                "f1_strategy.quality_reasons.reason_code",
            ],
            name=op.f(
                "fk_processed_lap_quality_reasons_dataset_contract_version_scope_reason_code_quality_reasons"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["processed_partition_id", "source_row_number"],
            [
                "f1_strategy.processed_laps.processed_partition_id",
                "f1_strategy.processed_laps.source_row_number",
            ],
            name=op.f(
                "fk_processed_lap_quality_reasons_processed_partition_id_source_row_number_processed_laps"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_contract_version",
            "processed_partition_id",
            "source_row_number",
            "reason_ordinal",
            name=op.f("pk_processed_lap_quality_reasons"),
        ),
        sa.UniqueConstraint(
            "dataset_contract_version",
            "processed_partition_id",
            "source_row_number",
            "reason_code",
            name=op.f(
                "uq_processed_lap_quality_reasons_dataset_contract_version_processed_partition_id_source_row_number_reason_code"
            ),
        ),
        schema="f1_strategy",
    )
    op.create_index(
        "ix_processed_lap_quality_reasons_reason_code",
        "processed_lap_quality_reasons",
        ["dataset_contract_version", "reason_code"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_table(
        "session_split_assignments",
        sa.Column("dataset_contract_version", sa.String(length=32), nullable=False),
        sa.Column("fold_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=16), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("round_number", sa.SmallInteger(), nullable=False),
        sa.Column("session_type", sa.String(length=8), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "role IN ('TRAIN', 'VALIDATION', 'EXCLUDED')",
            name=op.f("ck_session_split_assignments_role_allowed"),
        ),
        sa.CheckConstraint(
            "session_id = season::text || '-' || lpad(round_number::text, 2, '0') || '-' || session_type",
            name=op.f("ck_session_split_assignments_canonical_session_identity"),
        ),
        sa.CheckConstraint(
            "session_type = 'R'",
            name=op.f("ck_session_split_assignments_race_session_only"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(fold_id)) > 0",
            name=op.f("ck_session_split_assignments_fold_id_not_blank"),
        ),
        sa.CheckConstraint(
            "round_number BETWEEN 1 AND 30",
            name=op.f("ck_session_split_assignments_round_number_range"),
        ),
        sa.CheckConstraint(
            "season IN (2022, 2023, 2024)",
            name=op.f("ck_session_split_assignments_development_season_only"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_contract_version", "fold_id"],
            [
                "f1_strategy.temporal_folds.dataset_contract_version",
                "f1_strategy.temporal_folds.fold_id",
            ],
            name=op.f(
                "fk_session_split_assignments_dataset_contract_version_fold_id_temporal_folds"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_contract_version", "session_id"],
            [
                "f1_strategy.dataset_sessions.dataset_contract_version",
                "f1_strategy.dataset_sessions.session_id",
            ],
            name=op.f(
                "fk_session_split_assignments_dataset_contract_version_session_id_dataset_sessions"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_contract_version",
            "fold_id",
            "session_id",
            name=op.f("pk_session_split_assignments"),
        ),
        schema="f1_strategy",
    )
    op.create_index(
        "ix_session_split_assignments_fold_role",
        "session_split_assignments",
        ["dataset_contract_version", "fold_id", "role", "session_id"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_index(
        "ix_session_split_assignments_session",
        "session_split_assignments",
        ["dataset_contract_version", "session_id"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_table(
        "stint_quality_reasons",
        sa.Column("dataset_contract_version", sa.String(length=32), nullable=False),
        sa.Column("processed_partition_id", sa.BigInteger(), nullable=False),
        sa.Column("driver_id", sa.BigInteger(), nullable=False),
        sa.Column("stint_number", sa.SmallInteger(), nullable=False),
        sa.Column("reason_ordinal", sa.SmallInteger(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "scope = 'RECONSTRUCTED_STINT'",
            name=op.f("ck_stint_quality_reasons_scope_exact"),
        ),
        sa.CheckConstraint(
            "reason_ordinal >= 0",
            name=op.f("ck_stint_quality_reasons_reason_ordinal_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_contract_version", "scope", "reason_code"],
            [
                "f1_strategy.quality_reasons.dataset_contract_version",
                "f1_strategy.quality_reasons.scope",
                "f1_strategy.quality_reasons.reason_code",
            ],
            name=op.f(
                "fk_stint_quality_reasons_dataset_contract_version_scope_reason_code_quality_reasons"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["processed_partition_id", "driver_id", "stint_number"],
            [
                "f1_strategy.reconstructed_stints.processed_partition_id",
                "f1_strategy.reconstructed_stints.driver_id",
                "f1_strategy.reconstructed_stints.stint_number",
            ],
            name=op.f(
                "fk_stint_quality_reasons_processed_partition_id_driver_id_stint_number_reconstructed_stints"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_contract_version",
            "processed_partition_id",
            "driver_id",
            "stint_number",
            "reason_ordinal",
            name=op.f("pk_stint_quality_reasons"),
        ),
        sa.UniqueConstraint(
            "dataset_contract_version",
            "processed_partition_id",
            "driver_id",
            "stint_number",
            "reason_code",
            name=op.f(
                "uq_stint_quality_reasons_dataset_contract_version_processed_partition_id_driver_id_stint_number_reason_code"
            ),
        ),
        schema="f1_strategy",
    )
    op.create_index(
        "ix_stint_quality_reasons_reason_code",
        "stint_quality_reasons",
        ["dataset_contract_version", "reason_code"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_table(
        "decision_labels",
        sa.Column("processed_partition_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset_contract_version", sa.String(length=32), nullable=False),
        sa.Column("decision_id", sa.String(length=96), nullable=False),
        sa.Column("session_id", sa.String(length=16), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("round_number", sa.SmallInteger(), nullable=False),
        sa.Column("session_type", sa.String(length=8), nullable=False),
        sa.Column("driver", sa.String(length=16), nullable=False),
        sa.Column("decision_lap", sa.SmallInteger(), nullable=False),
        sa.Column("historical_action", sa.String(length=16), nullable=False),
        sa.Column("did_pit", sa.Boolean(), nullable=False),
        sa.Column("pit_event_id", sa.String(length=64), nullable=True),
        sa.Column("is_lap_time_target_eligible", sa.Boolean(), nullable=False),
        sa.Column("lap_time_target_seconds", sa.Double(), nullable=True),
        sa.Column("lap_target_exclusion_count", sa.BigInteger(), nullable=False),
        sa.Column("lap_target_exclusion_reasons", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "(historical_action = 'PIT_NOW' AND did_pit) OR (historical_action = 'STAY_OUT' AND NOT did_pit)",
            name=op.f("ck_decision_labels_historical_action_balance"),
        ),
        sa.CheckConstraint(
            "(is_lap_time_target_eligible AND lap_target_exclusion_count = 0 AND lap_target_exclusion_reasons = '') OR (NOT is_lap_time_target_eligible AND lap_target_exclusion_count > 0 AND char_length(lap_target_exclusion_reasons) > 0)",
            name=op.f("ck_decision_labels_target_exclusion_balance"),
        ),
        sa.CheckConstraint(
            "decision_id = session_id || '-' || driver || '-' || lpad(decision_lap::text, 3, '0')",
            name=op.f("ck_decision_labels_canonical_decision_identity"),
        ),
        sa.CheckConstraint(
            "historical_action IN ('PIT_NOW', 'STAY_OUT')",
            name=op.f("ck_decision_labels_historical_action_allowed"),
        ),
        sa.CheckConstraint(
            "session_id = season::text || '-' || lpad(round_number::text, 2, '0') || '-' || session_type",
            name=op.f("ck_decision_labels_canonical_session_identity"),
        ),
        sa.CheckConstraint(
            "session_type = 'R'", name=op.f("ck_decision_labels_race_session_only")
        ),
        sa.CheckConstraint(
            "(did_pit AND pit_event_id IS NOT NULL AND char_length(btrim(pit_event_id)) > 0) OR (NOT did_pit AND pit_event_id IS NULL)",
            name=op.f("ck_decision_labels_pit_event_presence"),
        ),
        sa.CheckConstraint(
            "(is_lap_time_target_eligible AND lap_time_target_seconds IS NOT NULL AND lap_time_target_seconds > 0) OR (NOT is_lap_time_target_eligible AND lap_time_target_seconds IS NULL)",
            name=op.f("ck_decision_labels_lap_target_availability"),
        ),
        sa.CheckConstraint(
            "decision_lap >= 2",
            name=op.f("ck_decision_labels_decision_lap_has_previous"),
        ),
        sa.CheckConstraint(
            "driver = upper(btrim(driver))",
            name=op.f("ck_decision_labels_driver_normalized"),
        ),
        sa.CheckConstraint(
            "lap_target_exclusion_count >= 0",
            name=op.f("ck_decision_labels_exclusion_count_non_negative"),
        ),
        sa.CheckConstraint(
            "round_number BETWEEN 1 AND 30",
            name=op.f("ck_decision_labels_round_number_range"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_contract_version", "decision_id"],
            [
                "f1_strategy.decision_rows.dataset_contract_version",
                "f1_strategy.decision_rows.decision_id",
            ],
            name=op.f(
                "fk_decision_labels_dataset_contract_version_decision_id_decision_rows"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_contract_version", "processed_partition_id"],
            [
                "f1_strategy.dataset_sessions.dataset_contract_version",
                "f1_strategy.dataset_sessions.processed_partition_id",
            ],
            name=op.f(
                "fk_decision_labels_dataset_contract_version_processed_partition_id_dataset_sessions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_contract_version", "session_id"],
            [
                "f1_strategy.dataset_sessions.dataset_contract_version",
                "f1_strategy.dataset_sessions.session_id",
            ],
            name=op.f(
                "fk_decision_labels_dataset_contract_version_session_id_dataset_sessions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["driver"],
            ["f1_strategy.drivers.driver_code"],
            name=op.f("fk_decision_labels_driver_drivers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["processed_partition_id", "pit_event_id"],
            [
                "f1_strategy.reconstructed_pit_events.processed_partition_id",
                "f1_strategy.reconstructed_pit_events.pit_event_id",
            ],
            name=op.f(
                "fk_decision_labels_processed_partition_id_pit_event_id_reconstructed_pit_events"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["processed_partition_id", "session_id"],
            [
                "f1_strategy.processed_session_partitions.processed_partition_id",
                "f1_strategy.processed_session_partitions.session_id",
            ],
            name=op.f(
                "fk_decision_labels_processed_partition_id_session_id_processed_session_partitions"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_contract_version", "decision_id", name=op.f("pk_decision_labels")
        ),
        sa.UniqueConstraint(
            "processed_partition_id",
            "pit_event_id",
            name=op.f("uq_decision_labels_processed_partition_id_pit_event_id"),
        ),
        schema="f1_strategy",
    )
    op.create_index(
        "ix_decision_labels_action",
        "decision_labels",
        ["dataset_contract_version", "historical_action", "session_id"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_index(
        "ix_decision_labels_lap_target_eligible",
        "decision_labels",
        ["dataset_contract_version", "session_id", "decision_lap"],
        unique=False,
        schema="f1_strategy",
        postgresql_where=sa.text("is_lap_time_target_eligible"),
    )
    op.create_index(
        "ix_decision_labels_session_driver_lap",
        "decision_labels",
        ["session_id", "driver", "decision_lap"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_table(
        "decision_quality_reasons",
        sa.Column("dataset_contract_version", sa.String(length=32), nullable=False),
        sa.Column("decision_id", sa.String(length=96), nullable=False),
        sa.Column("reason_ordinal", sa.SmallInteger(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "scope = 'DECISION'", name=op.f("ck_decision_quality_reasons_scope_exact")
        ),
        sa.CheckConstraint(
            "reason_ordinal >= 0",
            name=op.f("ck_decision_quality_reasons_reason_ordinal_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_contract_version", "decision_id"],
            [
                "f1_strategy.decision_rows.dataset_contract_version",
                "f1_strategy.decision_rows.decision_id",
            ],
            name=op.f(
                "fk_decision_quality_reasons_dataset_contract_version_decision_id_decision_rows"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_contract_version", "scope", "reason_code"],
            [
                "f1_strategy.quality_reasons.dataset_contract_version",
                "f1_strategy.quality_reasons.scope",
                "f1_strategy.quality_reasons.reason_code",
            ],
            name=op.f(
                "fk_decision_quality_reasons_dataset_contract_version_scope_reason_code_quality_reasons"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_contract_version",
            "decision_id",
            "reason_ordinal",
            name=op.f("pk_decision_quality_reasons"),
        ),
        sa.UniqueConstraint(
            "dataset_contract_version",
            "decision_id",
            "reason_code",
            name=op.f(
                "uq_decision_quality_reasons_dataset_contract_version_decision_id_reason_code"
            ),
        ),
        schema="f1_strategy",
    )
    op.create_index(
        "ix_decision_quality_reasons_reason_code",
        "decision_quality_reasons",
        ["dataset_contract_version", "reason_code"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_table(
        "pit_duration_quality_reasons",
        sa.Column("dataset_contract_version", sa.String(length=32), nullable=False),
        sa.Column("pit_event_id", sa.String(length=64), nullable=False),
        sa.Column("reason_ordinal", sa.SmallInteger(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "scope = 'PIT_DURATION_TARGET'",
            name=op.f("ck_pit_duration_quality_reasons_scope_exact"),
        ),
        sa.CheckConstraint(
            "reason_ordinal >= 0",
            name=op.f("ck_pit_duration_quality_reasons_reason_ordinal_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_contract_version", "pit_event_id"],
            [
                "f1_strategy.pit_duration_observations.dataset_contract_version",
                "f1_strategy.pit_duration_observations.pit_event_id",
            ],
            name=op.f(
                "fk_pit_duration_quality_reasons_dataset_contract_version_pit_event_id_pit_duration_observations"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_contract_version", "scope", "reason_code"],
            [
                "f1_strategy.quality_reasons.dataset_contract_version",
                "f1_strategy.quality_reasons.scope",
                "f1_strategy.quality_reasons.reason_code",
            ],
            name=op.f(
                "fk_pit_duration_quality_reasons_dataset_contract_version_scope_reason_code_quality_reasons"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_contract_version",
            "pit_event_id",
            "reason_ordinal",
            name=op.f("pk_pit_duration_quality_reasons"),
        ),
        sa.UniqueConstraint(
            "dataset_contract_version",
            "pit_event_id",
            "reason_code",
            name=op.f(
                "uq_pit_duration_quality_reasons_dataset_contract_version_pit_event_id_reason_code"
            ),
        ),
        schema="f1_strategy",
    )
    op.create_index(
        "ix_pit_duration_quality_reasons_reason_code",
        "pit_duration_quality_reasons",
        ["dataset_contract_version", "reason_code"],
        unique=False,
        schema="f1_strategy",
    )
    op.create_table(
        "lap_target_quality_reasons",
        sa.Column("dataset_contract_version", sa.String(length=32), nullable=False),
        sa.Column("decision_id", sa.String(length=96), nullable=False),
        sa.Column("reason_ordinal", sa.SmallInteger(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "scope = 'LAP_TARGET'",
            name=op.f("ck_lap_target_quality_reasons_scope_exact"),
        ),
        sa.CheckConstraint(
            "reason_ordinal >= 0",
            name=op.f("ck_lap_target_quality_reasons_reason_ordinal_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_contract_version", "decision_id"],
            [
                "f1_strategy.decision_labels.dataset_contract_version",
                "f1_strategy.decision_labels.decision_id",
            ],
            name=op.f(
                "fk_lap_target_quality_reasons_dataset_contract_version_decision_id_decision_labels"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_contract_version", "scope", "reason_code"],
            [
                "f1_strategy.quality_reasons.dataset_contract_version",
                "f1_strategy.quality_reasons.scope",
                "f1_strategy.quality_reasons.reason_code",
            ],
            name=op.f(
                "fk_lap_target_quality_reasons_dataset_contract_version_scope_reason_code_quality_reasons"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_contract_version",
            "decision_id",
            "reason_ordinal",
            name=op.f("pk_lap_target_quality_reasons"),
        ),
        sa.UniqueConstraint(
            "dataset_contract_version",
            "decision_id",
            "reason_code",
            name=op.f(
                "uq_lap_target_quality_reasons_dataset_contract_version_decision_id_reason_code"
            ),
        ),
        schema="f1_strategy",
    )
    op.create_index(
        "ix_lap_target_quality_reasons_reason_code",
        "lap_target_quality_reasons",
        ["dataset_contract_version", "reason_code"],
        unique=False,
        schema="f1_strategy",
    )


def downgrade() -> None:
    """Remove every schema V1 object."""
    op.drop_index(
        "ix_lap_target_quality_reasons_reason_code",
        table_name="lap_target_quality_reasons",
        schema="f1_strategy",
    )
    op.drop_table("lap_target_quality_reasons", schema="f1_strategy")
    op.drop_index(
        "ix_pit_duration_quality_reasons_reason_code",
        table_name="pit_duration_quality_reasons",
        schema="f1_strategy",
    )
    op.drop_table("pit_duration_quality_reasons", schema="f1_strategy")
    op.drop_index(
        "ix_decision_quality_reasons_reason_code",
        table_name="decision_quality_reasons",
        schema="f1_strategy",
    )
    op.drop_table("decision_quality_reasons", schema="f1_strategy")
    op.drop_index(
        "ix_decision_labels_session_driver_lap",
        table_name="decision_labels",
        schema="f1_strategy",
    )
    op.drop_index(
        "ix_decision_labels_lap_target_eligible",
        table_name="decision_labels",
        schema="f1_strategy",
        postgresql_where=sa.text("is_lap_time_target_eligible"),
    )
    op.drop_index(
        "ix_decision_labels_action", table_name="decision_labels", schema="f1_strategy"
    )
    op.drop_table("decision_labels", schema="f1_strategy")
    op.drop_index(
        "ix_stint_quality_reasons_reason_code",
        table_name="stint_quality_reasons",
        schema="f1_strategy",
    )
    op.drop_table("stint_quality_reasons", schema="f1_strategy")
    op.drop_index(
        "ix_session_split_assignments_session",
        table_name="session_split_assignments",
        schema="f1_strategy",
    )
    op.drop_index(
        "ix_session_split_assignments_fold_role",
        table_name="session_split_assignments",
        schema="f1_strategy",
    )
    op.drop_table("session_split_assignments", schema="f1_strategy")
    op.drop_index(
        "ix_processed_lap_quality_reasons_reason_code",
        table_name="processed_lap_quality_reasons",
        schema="f1_strategy",
    )
    op.drop_table("processed_lap_quality_reasons", schema="f1_strategy")
    op.drop_index(
        "ix_pit_event_quality_reasons_reason_code",
        table_name="pit_event_quality_reasons",
        schema="f1_strategy",
    )
    op.drop_table("pit_event_quality_reasons", schema="f1_strategy")
    op.drop_index(
        "ix_pit_duration_observations_target_eligible",
        table_name="pit_duration_observations",
        schema="f1_strategy",
        postgresql_where=sa.text("is_pit_duration_target_eligible"),
    )
    op.drop_index(
        "ix_pit_duration_observations_source_event",
        table_name="pit_duration_observations",
        schema="f1_strategy",
    )
    op.drop_index(
        "ix_pit_duration_observations_session_driver_pit_lap",
        table_name="pit_duration_observations",
        schema="f1_strategy",
    )
    op.drop_table("pit_duration_observations", schema="f1_strategy")
    op.drop_index(
        "ix_decision_rows_session_driver_lap",
        table_name="decision_rows",
        schema="f1_strategy",
    )
    op.drop_index(
        "ix_decision_rows_eligible",
        table_name="decision_rows",
        schema="f1_strategy",
        postgresql_where=sa.text("is_decision_eligible"),
    )
    op.drop_table("decision_rows", schema="f1_strategy")
    op.drop_index(
        "ix_reconstructed_stints_session_driver",
        table_name="reconstructed_stints",
        schema="f1_strategy",
    )
    op.drop_table("reconstructed_stints", schema="f1_strategy")
    op.drop_index(
        "ix_reconstructed_pit_events_session_driver_pit_lap",
        table_name="reconstructed_pit_events",
        schema="f1_strategy",
    )
    op.drop_table("reconstructed_pit_events", schema="f1_strategy")
    op.drop_index(
        "ix_processed_laps_session_team",
        table_name="processed_laps",
        schema="f1_strategy",
    )
    op.drop_index(
        "ix_processed_laps_session_driver_lap",
        table_name="processed_laps",
        schema="f1_strategy",
    )
    op.drop_index(
        "ix_processed_laps_eligible",
        table_name="processed_laps",
        schema="f1_strategy",
        postgresql_where=sa.text("is_eligible"),
    )
    op.drop_table("processed_laps", schema="f1_strategy")
    op.drop_index(
        "ix_dataset_sessions_session_id",
        table_name="dataset_sessions",
        schema="f1_strategy",
    )
    op.drop_index(
        "ix_dataset_sessions_processed_partition_id",
        table_name="dataset_sessions",
        schema="f1_strategy",
    )
    op.drop_index(
        "ix_dataset_sessions_created_by_run_id",
        table_name="dataset_sessions",
        schema="f1_strategy",
    )
    op.drop_table("dataset_sessions", schema="f1_strategy")
    op.drop_index(
        "ix_session_participants_team_id_session_id",
        table_name="session_participants",
        schema="f1_strategy",
    )
    op.drop_index(
        "ix_session_participants_driver_id",
        table_name="session_participants",
        schema="f1_strategy",
    )
    op.drop_table("session_participants", schema="f1_strategy")
    op.drop_index(
        "ix_processed_session_partitions_versions",
        table_name="processed_session_partitions",
        schema="f1_strategy",
    )
    op.drop_index(
        "ix_processed_session_partitions_session_id",
        table_name="processed_session_partitions",
        schema="f1_strategy",
    )
    op.drop_table("processed_session_partitions", schema="f1_strategy")
    op.drop_index(
        "ix_race_sessions_season_round_number",
        table_name="race_sessions",
        schema="f1_strategy",
    )
    op.drop_index(
        "ix_race_sessions_event_id", table_name="race_sessions", schema="f1_strategy"
    )
    op.drop_table("race_sessions", schema="f1_strategy")
    op.drop_table("temporal_folds", schema="f1_strategy")
    op.drop_table("quality_reasons", schema="f1_strategy")
    op.drop_index(
        "ix_events_season_event_date", table_name="events", schema="f1_strategy"
    )
    op.drop_index(
        "ix_events_circuit_id_season", table_name="events", schema="f1_strategy"
    )
    op.drop_table("events", schema="f1_strategy")
    op.drop_index(
        "ix_dataset_builds_version_started_at",
        table_name="dataset_builds",
        schema="f1_strategy",
    )
    op.drop_table("dataset_builds", schema="f1_strategy")
    op.drop_table("teams", schema="f1_strategy")
    op.drop_table("seasons", schema="f1_strategy")
    op.drop_table("drivers", schema="f1_strategy")
    op.drop_index(
        "ix_dataset_versions_source_versions",
        table_name="dataset_versions",
        schema="f1_strategy",
    )
    op.drop_table("dataset_versions", schema="f1_strategy")
    op.drop_table("circuits", schema="f1_strategy")
    op.execute(sa.schema.DropSchema("f1_strategy"))
