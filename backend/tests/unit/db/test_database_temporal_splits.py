"""Tests for temporal fold and session assignment persistence."""

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.schema import CreateTable

from app.db import (
    DATABASE_SCHEMA_NAME,
    SESSION_SPLIT_ASSIGNMENT_SOURCE_COLUMN_MAP,
    SESSION_SPLIT_ASSIGNMENT_TABLE_NAME,
    TEMPORAL_FOLD_TABLE_NAME,
    Base,
    SessionSplitAssignment,
    TemporalFold,
)

EXPECTED_SOURCE_COLUMNS = (
    "fold_id",
    "session_id",
    "season",
    "round_number",
    "session_type",
    "role",
)


def _fold_table():
    """Return the registered temporal-fold table."""
    return Base.metadata.tables[
        (
            f"{DATABASE_SCHEMA_NAME}."
            f"{TEMPORAL_FOLD_TABLE_NAME}"
        )
    ]


def _assignment_table():
    """Return the registered split-assignment table."""
    return Base.metadata.tables[
        (
            f"{DATABASE_SCHEMA_NAME}."
            f"{SESSION_SPLIT_ASSIGNMENT_TABLE_NAME}"
        )
    ]


def _check_names(table) -> set[str]:
    """Return deterministic check names for one table."""
    return {
        str(constraint.name)
        for constraint in table.constraints
        if isinstance(
            constraint,
            CheckConstraint,
        )
    }


def test_temporal_tables_are_registered() -> None:
    """Both models map to their frozen table names."""
    assert TemporalFold.__tablename__ == "temporal_folds"
    assert (
        SessionSplitAssignment.__tablename__
        == "session_split_assignments"
    )
    assert TEMPORAL_FOLD_TABLE_NAME == "temporal_folds"
    assert (
        SESSION_SPLIT_ASSIGNMENT_TABLE_NAME
        == "session_split_assignments"
    )


def test_split_source_column_map_is_complete() -> None:
    """All six split-artifact fields map once."""
    assert tuple(
        SESSION_SPLIT_ASSIGNMENT_SOURCE_COLUMN_MAP
    ) == EXPECTED_SOURCE_COLUMNS
    assert len(
        SESSION_SPLIT_ASSIGNMENT_SOURCE_COLUMN_MAP
    ) == 6
    assert set(
        SESSION_SPLIT_ASSIGNMENT_SOURCE_COLUMN_MAP
    ) == set(
        SESSION_SPLIT_ASSIGNMENT_SOURCE_COLUMN_MAP.values()
    )


def test_temporal_fold_shape_and_primary_key_are_exact() -> None:
    """Fold definitions store versioned season groups."""
    assert tuple(
        _fold_table().columns.keys()
    ) == (
        "dataset_contract_version",
        "fold_id",
        "train_seasons",
        "validation_seasons",
        "excluded_seasons",
    )
    assert tuple(
        column.name
        for column in _fold_table().primary_key.columns
    ) == (
        "dataset_contract_version",
        "fold_id",
    )


def test_temporal_fold_references_dataset_version() -> None:
    """Every fold belongs to one declared dataset version."""
    targets = {
        foreign_key.target_fullname
        for foreign_key in _fold_table().foreign_keys
    }

    assert targets == {
        (
            "f1_strategy.dataset_versions."
            "dataset_contract_version"
        ),
    }


def test_temporal_fold_arrays_preserve_season_groups() -> None:
    """All three season groups use non-null smallint arrays."""
    for column_name in (
        "train_seasons",
        "validation_seasons",
        "excluded_seasons",
    ):
        column = _fold_table().c[column_name]

        assert isinstance(column.type, ARRAY)
        assert isinstance(
            column.type.item_type,
            SmallInteger,
        )
        assert column.nullable is False


def test_temporal_fold_checks_enforce_partition() -> None:
    """Fold groups are non-null, disjoint and exactly complete."""
    assert {
        "ck_temporal_folds_fold_id_not_blank",
        "ck_temporal_folds_training_seasons_present",
        "ck_temporal_folds_season_arrays_without_nulls",
        "ck_temporal_folds_season_groups_disjoint",
        "ck_temporal_folds_development_seasons_exact",
    } <= _check_names(
        _fold_table()
    )


def test_assignment_preserves_source_plus_version() -> None:
    """Six source fields plus dataset version are stored."""
    database_columns = set(
        _assignment_table().columns.keys()
    )

    assert set(
        SESSION_SPLIT_ASSIGNMENT_SOURCE_COLUMN_MAP.values()
    ) <= database_columns
    assert database_columns - set(
        SESSION_SPLIT_ASSIGNMENT_SOURCE_COLUMN_MAP.values()
    ) == {
        "dataset_contract_version",
    }
    assert len(database_columns) == 7


def test_assignment_primary_key_is_exact() -> None:
    """Version, fold and session form the assignment key."""
    assert tuple(
        column.name
        for column in _assignment_table().primary_key.columns
    ) == (
        "dataset_contract_version",
        "fold_id",
        "session_id",
    )


def test_assignment_foreign_keys_are_exact() -> None:
    """Assignments reference fold definitions and datasets."""
    targets = {
        foreign_key.target_fullname
        for foreign_key in _assignment_table().foreign_keys
    }

    assert targets == {
        (
            "f1_strategy.temporal_folds."
            "dataset_contract_version"
        ),
        "f1_strategy.temporal_folds.fold_id",
        (
            "f1_strategy.dataset_sessions."
            "dataset_contract_version"
        ),
        "f1_strategy.dataset_sessions.session_id",
    }

    composite_foreign_keys = {
        tuple(
            element.parent.name
            for element in constraint.elements
        )
        for constraint in _assignment_table().constraints
        if isinstance(
            constraint,
            ForeignKeyConstraint,
        )
    }

    assert composite_foreign_keys == {
        (
            "dataset_contract_version",
            "fold_id",
        ),
        (
            "dataset_contract_version",
            "session_id",
        ),
    }


def test_assignment_columns_are_required_and_typed() -> None:
    """Split identities and roles cannot be null."""
    assert all(
        column.nullable is False
        for column in _assignment_table().columns
    )
    for column_name in (
        "season",
        "round_number",
    ):
        assert isinstance(
            _assignment_table().c[column_name].type,
            SmallInteger,
        )


def test_assignment_checks_enforce_identity_and_role() -> None:
    """Only development race sessions and known roles persist."""
    assert {
        (
            "ck_session_split_assignments_"
            "fold_id_not_blank"
        ),
        (
            "ck_session_split_assignments_"
            "development_season_only"
        ),
        (
            "ck_session_split_assignments_"
            "round_number_range"
        ),
        (
            "ck_session_split_assignments_"
            "race_session_only"
        ),
        (
            "ck_session_split_assignments_"
            "canonical_session_identity"
        ),
        (
            "ck_session_split_assignments_"
            "role_allowed"
        ),
    } <= _check_names(
        _assignment_table()
    )


def test_assignment_indexes_cover_fold_and_session_queries() -> None:
    """Role selection and cross-fold audits are indexed."""
    indexes = {
        str(index.name): index
        for index in _assignment_table().indexes
        if isinstance(index, Index)
    }

    assert set(indexes) == {
        (
            "ix_session_split_assignments_"
            "fold_role"
        ),
        (
            "ix_session_split_assignments_"
            "session"
        ),
    }
    assert tuple(
        column.name
        for column in indexes[
            "ix_session_split_assignments_fold_role"
        ].columns
    ) == (
        "dataset_contract_version",
        "fold_id",
        "role",
        "session_id",
    )


def test_temporal_tables_compile_for_postgresql() -> None:
    """Both temporal tables produce PostgreSQL DDL."""
    dialect = postgresql.dialect()
    fold_ddl = str(
        CreateTable(
            _fold_table()
        ).compile(
            dialect=dialect
        )
    )
    assignment_ddl = str(
        CreateTable(
            _assignment_table()
        ).compile(
            dialect=dialect
        )
    )

    assert "f1_strategy.temporal_folds" in fold_ddl
    assert "SMALLINT[]" in fold_ddl
    assert "f1_strategy.session_split_assignments" in assignment_ddl
    assert "REFERENCES f1_strategy.temporal_folds" in assignment_ddl
    assert "REFERENCES f1_strategy.dataset_sessions" in assignment_ddl
