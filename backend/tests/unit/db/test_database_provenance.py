"""Tests for database version and artifact provenance."""

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.db import (
    DATABASE_SCHEMA_NAME,
    PROVENANCE_TABLE_NAMES,
    Base,
    DatasetBuild,
    DatasetSession,
    DatasetVersion,
    ProcessedSessionPartition,
)


def _table(table_name: str):
    """Return one registered provenance table."""
    return Base.metadata.tables[
        (
            f"{DATABASE_SCHEMA_NAME}."
            f"{table_name}"
        )
    ]


def _primary_key_columns(
    table_name: str,
) -> tuple[str, ...]:
    """Return ordered primary-key column names."""
    return tuple(
        column.name
        for column in _table(
            table_name
        ).primary_key.columns
    )


def _unique_column_sets(
    table_name: str,
) -> set[tuple[str, ...]]:
    """Return every declared uniqueness column set."""
    return {
        tuple(
            column.name
            for column in constraint.columns
        )
        for constraint in _table(
            table_name
        ).constraints
        if isinstance(
            constraint,
            UniqueConstraint,
        )
    }


def _check_names(
    table_name: str,
) -> set[str]:
    """Return deterministic check names."""
    return {
        str(constraint.name)
        for constraint in _table(
            table_name
        ).constraints
        if isinstance(
            constraint,
            CheckConstraint,
        )
    }


def _index_names(
    table_name: str,
) -> set[str]:
    """Return explicit index names."""
    return {
        str(index.name)
        for index in _table(
            table_name
        ).indexes
        if isinstance(index, Index)
    }


def test_all_provenance_tables_are_registered() -> None:
    """Metadata contains all version and artifact tables."""
    registered = {
        table.name
        for table in Base.metadata.tables.values()
    }

    assert set(
        PROVENANCE_TABLE_NAMES
    ) <= registered
    assert len(PROVENANCE_TABLE_NAMES) == 4


def test_provenance_model_table_names_are_exact() -> None:
    """ORM models map to the frozen physical names."""
    models = (
        ProcessedSessionPartition,
        DatasetVersion,
        DatasetBuild,
        DatasetSession,
    )

    assert tuple(
        model.__tablename__
        for model in models
    ) == PROVENANCE_TABLE_NAMES


def test_provenance_primary_keys_are_exact() -> None:
    """Artifact and version identities cannot drift."""
    assert _primary_key_columns(
        "processed_session_partitions"
    ) == ("processed_partition_id",)
    assert _primary_key_columns(
        "dataset_versions"
    ) == ("dataset_contract_version",)
    assert _primary_key_columns(
        "dataset_builds"
    ) == ("run_id",)
    assert _primary_key_columns(
        "dataset_sessions"
    ) == (
        "dataset_contract_version",
        "session_id",
    )


def test_provenance_natural_keys_are_unique() -> None:
    """Immutable artifacts have protected natural keys."""
    assert (
        "session_id",
        "source_contract_version",
        "processed_contract_version",
        "cleaning_rule_version",
    ) in _unique_column_sets(
        "processed_session_partitions"
    )
    assert (
        "processed_partition_id",
        "session_id",
    ) in _unique_column_sets(
        "processed_session_partitions"
    )
    assert (
        "run_id",
        "dataset_contract_version",
    ) in _unique_column_sets(
        "dataset_builds"
    )
    assert (
        "dataset_contract_version",
        "processed_partition_id",
    ) in _unique_column_sets(
        "dataset_sessions"
    )


def test_provenance_foreign_keys_are_exact() -> None:
    """Every artifact points to its version and source."""
    targets = {
        foreign_key.target_fullname
        for table_name in (
            "processed_session_partitions",
            "dataset_builds",
            "dataset_sessions",
        )
        for foreign_key in _table(
            table_name
        ).foreign_keys
    }

    assert targets == {
        (
            "f1_strategy.dataset_builds."
            "dataset_contract_version"
        ),
        (
            "f1_strategy.dataset_builds."
            "run_id"
        ),
        (
            "f1_strategy.dataset_versions."
            "dataset_contract_version"
        ),
        (
            "f1_strategy."
            "processed_session_partitions."
            "processed_partition_id"
        ),
        (
            "f1_strategy."
            "processed_session_partitions."
            "session_id"
        ),
        (
            "f1_strategy.race_sessions."
            "session_id"
        ),
    }


def test_provenance_timestamps_are_timezone_aware() -> None:
    """Stored instants use timestamp with time zone."""
    timestamp_columns = (
        (
            "processed_session_partitions",
            "created_at_utc",
        ),
        (
            "dataset_versions",
            "created_at_utc",
        ),
        (
            "dataset_builds",
            "started_at_utc",
        ),
        (
            "dataset_builds",
            "completed_at_utc",
        ),
        (
            "dataset_sessions",
            "created_at_utc",
        ),
    )

    for table_name, column_name in timestamp_columns:
        column_type = _table(
            table_name
        ).c[column_name].type

        assert isinstance(
            column_type,
            DateTime,
        )
        assert column_type.timezone is True

    assert (
        _table(
            "dataset_builds"
        ).c.completed_at_utc.nullable
        is True
    )


def test_provenance_hash_columns_are_fixed_length() -> None:
    """Every artifact digest stores one SHA-256 value."""
    hash_columns = (
        (
            "processed_session_partitions",
            "processed_manifest_sha256",
        ),
        (
            "processed_session_partitions",
            "laps_sha256",
        ),
        (
            "processed_session_partitions",
            "stints_sha256",
        ),
        (
            "processed_session_partitions",
            "pit_events_sha256",
        ),
        (
            "processed_session_partitions",
            "quality_report_sha256",
        ),
        (
            "dataset_builds",
            "catalog_sha256",
        ),
        (
            "dataset_builds",
            "splits_sha256",
        ),
        (
            "dataset_sessions",
            "dataset_manifest_sha256",
        ),
        (
            "dataset_sessions",
            "decision_rows_sha256",
        ),
        (
            "dataset_sessions",
            "decision_labels_sha256",
        ),
        (
            "dataset_sessions",
            (
                "pit_duration_"
                "observations_sha256"
            ),
        ),
        (
            "dataset_sessions",
            "quality_report_sha256",
        ),
    )

    for table_name, column_name in hash_columns:
        assert (
            _table(
                table_name
            ).c[column_name].type.length
            == 64
        )


def test_dataset_build_lifecycle_checks_exist() -> None:
    """Build status, counts and artifacts fail closed."""
    required = {
        (
            "ck_dataset_builds_"
            "status_allowed"
        ),
        (
            "ck_dataset_builds_"
            "terminal_count_balance"
        ),
        (
            "ck_dataset_builds_"
            "completion_state"
        ),
        (
            "ck_dataset_builds_"
            "successful_without_failures"
        ),
        (
            "ck_dataset_builds_"
            "successful_artifacts_present"
        ),
    }

    assert required <= _check_names(
        "dataset_builds"
    )


def test_dataset_session_reconciliation_checks_exist() -> None:
    """Catalog totals are protected by database checks."""
    required = {
        (
            "ck_dataset_sessions_"
            "decision_count_balance"
        ),
        (
            "ck_dataset_sessions_"
            "label_count_balance"
        ),
        (
            "ck_dataset_sessions_"
            "action_count_balance"
        ),
        (
            "ck_dataset_sessions_"
            "lap_target_within_eligible"
        ),
        (
            "ck_dataset_sessions_"
            "pit_target_within_observations"
        ),
    }

    assert required <= _check_names(
        "dataset_sessions"
    )


def test_provenance_indexes_cover_access_paths() -> None:
    """Version, session and build lookups are indexed."""
    assert _index_names(
        "processed_session_partitions"
    ) == {
        (
            "ix_processed_session_"
            "partitions_session_id"
        ),
        (
            "ix_processed_session_"
            "partitions_versions"
        ),
    }
    assert _index_names(
        "dataset_versions"
    ) == {
        (
            "ix_dataset_versions_"
            "source_versions"
        ),
    }
    assert _index_names(
        "dataset_builds"
    ) == {
        (
            "ix_dataset_builds_"
            "version_started_at"
        ),
    }
    assert _index_names(
        "dataset_sessions"
    ) == {
        (
            "ix_dataset_sessions_"
            "created_by_run_id"
        ),
        (
            "ix_dataset_sessions_"
            "processed_partition_id"
        ),
        (
            "ix_dataset_sessions_"
            "session_id"
        ),
    }


def test_provenance_tables_compile_for_postgresql() -> None:
    """Every provenance table produces PostgreSQL DDL."""
    dialect = postgresql.dialect()

    compiled = {
        table_name: str(
            CreateTable(
                _table(table_name)
            ).compile(
                dialect=dialect
            )
        )
        for table_name in PROVENANCE_TABLE_NAMES
    }

    assert all(compiled.values())
    assert (
        "GENERATED BY DEFAULT AS IDENTITY"
        in compiled[
            "processed_session_partitions"
        ]
    )
    assert (
        "TIMESTAMP WITH TIME ZONE"
        in compiled[
            "processed_session_partitions"
        ]
    )
    assert (
        "TIMESTAMP WITH TIME ZONE"
        in compiled["dataset_builds"]
    )
    assert (
        "CHAR(64)"
        in compiled["dataset_sessions"]
    )
    assert (
        "REFERENCES "
        "f1_strategy.dataset_versions"
        in compiled["dataset_builds"]
    )