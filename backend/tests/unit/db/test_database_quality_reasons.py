"""Tests for normalized quality-reason database persistence."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.cleaning.laps import (
    EXCLUDING_REASONS,
    LapQualityReason,
)
from app.cleaning.pits import PitEventWarning
from app.cleaning.stints import StintWarning
from app.datasets.contracts import (
    DECISION_EXCLUSION_REASON_ORDER,
)
from app.datasets.pit_durations import (
    PIT_DURATION_EXCLUSION_REASON_ORDER,
)
from app.db import (
    DATABASE_SCHEMA_NAME,
    QUALITY_REASON_CODES_BY_SCOPE,
    QUALITY_REASON_EXCLUSION_CODES_BY_SCOPE,
    QUALITY_REASON_LINK_TABLE_NAMES,
    QUALITY_REASON_SCOPES,
    QUALITY_REASON_TABLE_NAME,
    Base,
    DecisionQualityReason,
    LapTargetQualityReason,
    PitDurationQualityReason,
    PitEventQualityReason,
    ProcessedLapQualityReason,
    QualityReason,
    StintQualityReason,
)

LINK_MODELS = {
    "processed_lap_quality_reasons": (
        ProcessedLapQualityReason
    ),
    "stint_quality_reasons": StintQualityReason,
    "pit_event_quality_reasons": PitEventQualityReason,
    "decision_quality_reasons": DecisionQualityReason,
    "lap_target_quality_reasons": LapTargetQualityReason,
    "pit_duration_quality_reasons": (
        PitDurationQualityReason
    ),
}

EXPECTED_PRIMARY_KEYS = {
    "processed_lap_quality_reasons": (
        "dataset_contract_version",
        "processed_partition_id",
        "source_row_number",
        "reason_ordinal",
    ),
    "stint_quality_reasons": (
        "dataset_contract_version",
        "processed_partition_id",
        "driver_id",
        "stint_number",
        "reason_ordinal",
    ),
    "pit_event_quality_reasons": (
        "dataset_contract_version",
        "processed_partition_id",
        "pit_event_id",
        "reason_ordinal",
    ),
    "decision_quality_reasons": (
        "dataset_contract_version",
        "decision_id",
        "reason_ordinal",
    ),
    "lap_target_quality_reasons": (
        "dataset_contract_version",
        "decision_id",
        "reason_ordinal",
    ),
    "pit_duration_quality_reasons": (
        "dataset_contract_version",
        "pit_event_id",
        "reason_ordinal",
    ),
}

EXPECTED_SCOPES = {
    "processed_lap_quality_reasons": "PROCESSED_LAP",
    "stint_quality_reasons": "RECONSTRUCTED_STINT",
    "pit_event_quality_reasons": (
        "RECONSTRUCTED_PIT_EVENT"
    ),
    "decision_quality_reasons": "DECISION",
    "lap_target_quality_reasons": "LAP_TARGET",
    "pit_duration_quality_reasons": (
        "PIT_DURATION_TARGET"
    ),
}

EXPECTED_PARENT_TABLES = {
    "processed_lap_quality_reasons": "processed_laps",
    "stint_quality_reasons": "reconstructed_stints",
    "pit_event_quality_reasons": (
        "reconstructed_pit_events"
    ),
    "decision_quality_reasons": "decision_rows",
    "lap_target_quality_reasons": "decision_labels",
    "pit_duration_quality_reasons": (
        "pit_duration_observations"
    ),
}


def _table(table_name: str):
    """Return one registered quality table."""
    return Base.metadata.tables[
        f"{DATABASE_SCHEMA_NAME}.{table_name}"
    ]


def _check_names(table_name: str) -> set[str]:
    """Return deterministic check names for one table."""
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


def _foreign_keys(table_name: str):
    """Return composite foreign-key constraints for a table."""
    return tuple(
        constraint
        for constraint in _table(
            table_name
        ).constraints
        if isinstance(
            constraint,
            ForeignKeyConstraint,
        )
    )


def test_quality_tables_are_registered() -> None:
    """One definition and six link tables use frozen names."""
    assert QUALITY_REASON_TABLE_NAME == "quality_reasons"
    assert tuple(LINK_MODELS) == (
        QUALITY_REASON_LINK_TABLE_NAMES
    )
    assert {
        model.__tablename__
        for model in LINK_MODELS.values()
    } == set(
        QUALITY_REASON_LINK_TABLE_NAMES
    )
    assert QualityReason.__tablename__ == "quality_reasons"


def test_reason_scopes_are_exact() -> None:
    """Only six documented reason scopes are declared."""
    assert QUALITY_REASON_SCOPES == (
        "PROCESSED_LAP",
        "RECONSTRUCTED_STINT",
        "RECONSTRUCTED_PIT_EVENT",
        "DECISION",
        "LAP_TARGET",
        "PIT_DURATION_TARGET",
    )
    assert tuple(
        QUALITY_REASON_CODES_BY_SCOPE
    ) == QUALITY_REASON_SCOPES


def test_reason_codes_match_source_enums() -> None:
    """Database definitions cannot drift from producer order."""
    expected = {
        "PROCESSED_LAP": tuple(
            reason.value
            for reason in LapQualityReason
        ),
        "RECONSTRUCTED_STINT": tuple(
            warning.value
            for warning in StintWarning
        ),
        "RECONSTRUCTED_PIT_EVENT": tuple(
            warning.value
            for warning in PitEventWarning
        ),
        "DECISION": tuple(
            reason.value
            for reason in (
                DECISION_EXCLUSION_REASON_ORDER
            )
        ),
        "LAP_TARGET": tuple(
            reason.value
            for reason in LapQualityReason
            if reason in EXCLUDING_REASONS
        ),
        "PIT_DURATION_TARGET": tuple(
            reason.value
            for reason in (
                PIT_DURATION_EXCLUSION_REASON_ORDER
            )
        ),
    }

    assert QUALITY_REASON_CODES_BY_SCOPE == expected
    assert sum(
        len(codes)
        for codes in expected.values()
    ) == 72


def test_exclusion_codes_match_source_semantics() -> None:
    """Definitions distinguish exclusions from warning-only codes."""
    expected = {
        "PROCESSED_LAP": frozenset(
            reason.value
            for reason in EXCLUDING_REASONS
        ),
        "RECONSTRUCTED_STINT": frozenset(),
        "RECONSTRUCTED_PIT_EVENT": frozenset(),
        "DECISION": frozenset(
            reason.value
            for reason in (
                DECISION_EXCLUSION_REASON_ORDER
            )
        ),
        "LAP_TARGET": frozenset(
            reason.value
            for reason in EXCLUDING_REASONS
        ),
        "PIT_DURATION_TARGET": frozenset(
            reason.value
            for reason in (
                PIT_DURATION_EXCLUSION_REASON_ORDER
            )
        ),
    }

    assert (
        QUALITY_REASON_EXCLUSION_CODES_BY_SCOPE
        == expected
    )


def test_quality_reason_primary_key_is_exact() -> None:
    """Version, scope and code identify one definition."""
    assert tuple(
        column.name
        for column in _table(
            "quality_reasons"
        ).primary_key.columns
    ) == (
        "dataset_contract_version",
        "scope",
        "reason_code",
    )


def test_quality_reason_definition_shape_is_exact() -> None:
    """Definitions store only identity and canonical order."""
    table = _table(
        "quality_reasons"
    )

    assert tuple(table.columns.keys()) == (
        "dataset_contract_version",
        "scope",
        "reason_code",
        "canonical_ordinal",
        "is_exclusion",
    )
    assert all(
        column.nullable is False
        for column in table.columns
    )
    assert isinstance(
        table.c.canonical_ordinal.type,
        SmallInteger,
    )
    assert isinstance(
        table.c.is_exclusion.type,
        Boolean,
    )


def test_quality_reason_definition_constraints_exist() -> None:
    """Scopes, codes and canonical order are constrained."""
    assert _check_names(
        "quality_reasons"
    ) == {
        "ck_quality_reasons_scope_allowed",
        "ck_quality_reasons_reason_code_normalized",
        (
            "ck_quality_reasons_"
            "canonical_ordinal_non_negative"
        ),
    }
    unique_columns = {
        tuple(
            column.name
            for column in constraint.columns
        )
        for constraint in _table(
            "quality_reasons"
        ).constraints
        if isinstance(
            constraint,
            UniqueConstraint,
        )
    }

    assert unique_columns == {
        (
            "dataset_contract_version",
            "scope",
            "canonical_ordinal",
        ),
    }


def test_quality_reasons_reference_dataset_version() -> None:
    """Every definition belongs to a declared dataset version."""
    targets = {
        foreign_key.target_fullname
        for foreign_key in _table(
            "quality_reasons"
        ).foreign_keys
    }

    assert targets == {
        (
            "f1_strategy.dataset_versions."
            "dataset_contract_version"
        ),
    }


def test_link_primary_keys_preserve_parent_and_order() -> None:
    """Every parent can hold ordered, versioned reason links."""
    for table_name, expected in (
        EXPECTED_PRIMARY_KEYS.items()
    ):
        actual = tuple(
            column.name
            for column in _table(
                table_name
            ).primary_key.columns
        )

        assert actual == expected


def test_link_columns_are_required_and_ordinal_is_small() -> None:
    """Normalized links cannot contain null identities."""
    for table_name in LINK_MODELS:
        table = _table(
            table_name
        )

        assert all(
            column.nullable is False
            for column in table.columns
        )
        assert isinstance(
            table.c.reason_ordinal.type,
            SmallInteger,
        )


def test_exclusion_semantics_are_not_duplicated_on_links() -> None:
    """Only canonical definitions classify exclusion codes."""
    for table_name in LINK_MODELS:
        assert "is_exclusion" not in _table(
            table_name
        ).columns


def test_each_link_has_exact_scope_and_non_negative_order() -> None:
    """A link table cannot point into another reason scope."""
    for table_name, scope in EXPECTED_SCOPES.items():
        names = _check_names(
            table_name
        )

        assert names == {
            f"ck_{table_name}_scope_exact",
            (
                f"ck_{table_name}_"
                "reason_ordinal_non_negative"
            ),
        }
        scope_check = next(
            constraint
            for constraint in _table(
                table_name
            ).constraints
            if isinstance(
                constraint,
                CheckConstraint,
            )
            and str(constraint.name).endswith(
                "scope_exact"
            )
        )

        assert scope in str(
            scope_check.sqltext
        )


def test_each_link_references_one_scoped_definition() -> None:
    """Reason links use the full version-scope-code key."""
    for table_name in LINK_MODELS:
        reason_foreign_key = next(
            constraint
            for constraint in _foreign_keys(
                table_name
            )
            if any(
                "quality_reasons"
                in element.target_fullname
                for element in constraint.elements
            )
        )

        assert tuple(
            element.parent.name
            for element in reason_foreign_key.elements
        ) == (
            "dataset_contract_version",
            "scope",
            "reason_code",
        )
        assert {
            element.target_fullname.split(
                "."
            )[-1]
            for element in reason_foreign_key.elements
        } == {
            "dataset_contract_version",
            "scope",
            "reason_code",
        }
        assert reason_foreign_key.ondelete == "RESTRICT"


def test_each_link_cascades_only_from_analytical_parent() -> None:
    """Deleting one parent artifact removes only its links."""
    for table_name, parent_table in (
        EXPECTED_PARENT_TABLES.items()
    ):
        parent_foreign_key = next(
            constraint
            for constraint in _foreign_keys(
                table_name
            )
            if any(
                f".{parent_table}."
                in element.target_fullname
                for element in constraint.elements
            )
        )

        assert parent_foreign_key.ondelete == "CASCADE"
        assert len(
            _foreign_keys(
                table_name
            )
        ) == 2


def test_each_parent_has_one_reason_code_link() -> None:
    """One reason code cannot repeat on the same parent."""
    for table_name, primary_key in (
        EXPECTED_PRIMARY_KEYS.items()
    ):
        unique_constraints = tuple(
            constraint
            for constraint in _table(
                table_name
            ).constraints
            if isinstance(
                constraint,
                UniqueConstraint,
            )
        )

        assert len(unique_constraints) == 1
        unique_columns = tuple(
            column.name
            for column in unique_constraints[
                0
            ].columns
        )
        expected = (
            *primary_key[:-1],
            "reason_code",
        )

        assert unique_columns == expected


def test_quality_link_indexes_cover_reason_queries() -> None:
    """Every link table supports versioned reason counts."""
    for table_name in LINK_MODELS:
        indexes = tuple(
            index
            for index in _table(
                table_name
            ).indexes
            if isinstance(index, Index)
        )

        assert len(indexes) == 1
        assert str(indexes[0].name) == (
            f"ix_{table_name}_reason_code"
        )
        assert tuple(
            column.name
            for column in indexes[0].columns
        ) == (
            "dataset_contract_version",
            "reason_code",
        )


def test_quality_tables_compile_for_postgresql() -> None:
    """All seven tables and six indexes produce PostgreSQL DDL."""
    dialect = postgresql.dialect()
    table_names = (
        QUALITY_REASON_TABLE_NAME,
        *QUALITY_REASON_LINK_TABLE_NAMES,
    )

    for table_name in table_names:
        ddl = str(
            CreateTable(
                _table(
                    table_name
                )
            ).compile(
                dialect=dialect
            )
        )

        assert "CREATE TABLE" in ddl
        assert f"f1_strategy.{table_name}" in ddl

    for table_name in QUALITY_REASON_LINK_TABLE_NAMES:
        index = next(
            iter(
                _table(
                    table_name
                ).indexes
            )
        )
        index_ddl = str(
            CreateIndex(
                index
            ).compile(
                dialect=dialect
            )
        )

        assert "CREATE INDEX" in index_ddl
        assert "reason_code" in index_ddl
