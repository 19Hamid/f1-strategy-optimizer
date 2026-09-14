"""Tests for reproducible Alembic schema migrations."""

from __future__ import annotations

import re
from io import StringIO
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql

from app.db import DATABASE_SCHEMA_NAME, Base

BACKEND_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_CONFIG_PATH = BACKEND_ROOT / "alembic.ini"
INITIAL_REVISION = "20260914_0001"


def _config(*, output_buffer: StringIO | None = None) -> Config:
    """Return an Alembic configuration rooted at the backend directory."""
    config = Config(str(ALEMBIC_CONFIG_PATH), output_buffer=output_buffer)
    config.set_main_option(
        "script_location",
        str(BACKEND_ROOT / "migrations"),
    )
    return config


def _statements(sql: str) -> list[str]:
    """Normalize emitted SQL into comparable non-Alembic statements."""
    statements: list[str] = []
    sql_without_comments = re.sub(r"(?m)^--.*$", "", sql)
    for statement in sql_without_comments.split(";"):
        normalized = re.sub(r"\s+", " ", statement).strip()
        if not normalized or normalized in {"BEGIN", "COMMIT"}:
            continue
        if "alembic_version" in normalized:
            continue
        statements.append(normalized)
    return statements


class _MigrationRecorder:
    """Build metadata from the explicit operations in one revision."""

    def __init__(self) -> None:
        self.metadata = sa.MetaData()
        self.created_schemas: list[str] = []

    def f(self, name: str) -> str:
        """Resolve an already frozen naming-convention name."""
        return name

    def execute(self, statement: object) -> None:
        """Record schema DDL separately from table metadata."""
        assert isinstance(statement, sa.schema.CreateSchema)
        self.created_schemas.append(statement.element)

    def create_table(
        self,
        table_name: str,
        *elements: object,
        schema: str | None = None,
        **options: object,
    ) -> sa.Table:
        """Reconstruct one table from the revision operation."""
        assert options == {}
        return sa.Table(
            table_name,
            self.metadata,
            *elements,  # type: ignore[arg-type]
            schema=schema,
        )

    def create_index(
        self,
        name: str,
        table_name: str,
        columns: list[str],
        *,
        unique: bool = False,
        schema: str | None = None,
        **dialect_options: object,
    ) -> sa.Index:
        """Reconstruct one index from the revision operation."""
        table_key = f"{schema}.{table_name}" if schema else table_name
        table = self.metadata.tables[table_key]
        expressions = [table.c[column] for column in columns]
        return sa.Index(
            name,
            *expressions,
            unique=unique,
            **dialect_options,
        )


def _sql_text(value: object) -> str:
    """Render one SQL expression using the target PostgreSQL dialect."""
    if value is None:
        return ""
    if hasattr(value, "compile"):
        return str(
            value.compile(  # type: ignore[union-attr]
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
    return str(value)


def _metadata_signature(metadata: sa.MetaData) -> tuple[object, ...]:
    """Describe schema semantics independently of declaration order."""
    table_signatures: list[object] = []
    dialect = postgresql.dialect()
    for table in sorted(metadata.tables.values(), key=lambda item: item.fullname):
        columns = tuple(
            (
                column.name,
                column.type.compile(dialect=dialect),
                column.nullable,
                column.autoincrement,
                str(column.identity) if column.identity is not None else None,
                _sql_text(column.server_default.arg)
                if column.server_default is not None
                and hasattr(column.server_default, "arg")
                else None,
            )
            for column in table.columns
        )
        primary_key = (
            table.primary_key.name,
            tuple(column.name for column in table.primary_key.columns),
        )
        unique_constraints = sorted(
            (
                constraint.name,
                tuple(column.name for column in constraint.columns),
            )
            for constraint in table.constraints
            if isinstance(constraint, sa.UniqueConstraint)
        )
        check_constraints = sorted(
            (constraint.name, _sql_text(constraint.sqltext))
            for constraint in table.constraints
            if isinstance(constraint, sa.CheckConstraint)
        )
        foreign_keys = sorted(
            (
                constraint.name,
                tuple(column.name for column in constraint.columns),
                tuple(element.target_fullname for element in constraint.elements),
                constraint.ondelete,
                constraint.onupdate,
            )
            for constraint in table.constraints
            if isinstance(constraint, sa.ForeignKeyConstraint)
        )
        indexes = sorted(
            (
                index.name,
                tuple(expression.name for expression in index.expressions),
                index.unique,
                _sql_text(index.dialect_options["postgresql"].get("where")),
            )
            for index in table.indexes
        )
        table_signatures.append(
            (
                table.fullname,
                columns,
                primary_key,
                tuple(unique_constraints),
                tuple(check_constraints),
                tuple(foreign_keys),
                tuple(indexes),
            )
        )
    return tuple(table_signatures)


def test_alembic_has_one_frozen_initial_revision() -> None:
    """Expose one deterministic root and head revision for schema V1."""
    scripts = ScriptDirectory.from_config(_config())

    assert scripts.get_bases() == [INITIAL_REVISION]
    assert scripts.get_heads() == [INITIAL_REVISION]
    assert scripts.get_revision(INITIAL_REVISION).down_revision is None


def test_initial_revision_exactly_matches_orm_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject any table, column, constraint or index migration drift."""
    scripts = ScriptDirectory.from_config(_config())
    revision = scripts.get_revision(INITIAL_REVISION).module
    recorder = _MigrationRecorder()
    monkeypatch.setattr(revision, "op", recorder)

    revision.upgrade()

    assert recorder.created_schemas == [DATABASE_SCHEMA_NAME]
    assert _metadata_signature(recorder.metadata) == _metadata_signature(Base.metadata)


def test_offline_upgrade_compiles_complete_postgresql_sql() -> None:
    """Render the initial migration without connecting to PostgreSQL."""
    output = StringIO()

    command.upgrade(_config(output_buffer=output), "head", sql=True)

    sql = output.getvalue()
    for table in Base.metadata.sorted_tables:
        assert f"CREATE TABLE {table.fullname}" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "SMALLINT[]" in sql


def test_offline_downgrade_removes_every_application_table() -> None:
    """Downgrade the initial revision to an empty application schema."""
    output = StringIO()

    command.downgrade(
        _config(output_buffer=output),
        "head:base",
        sql=True,
    )

    statements = _statements(output.getvalue())
    dropped_tables = [
        statement.split(" ", maxsplit=2)[2]
        for statement in statements
        if statement.startswith("DROP TABLE ")
    ]
    expected_tables = [
        table.fullname for table in reversed(Base.metadata.sorted_tables)
    ]

    assert dropped_tables == expected_tables
    assert statements[-1] == f"DROP SCHEMA {DATABASE_SCHEMA_NAME}"


def test_offline_configuration_contains_no_credentials() -> None:
    """Keep migration configuration safe to commit and share."""
    configured_url = _config().get_main_option("sqlalchemy.url")

    assert configured_url == "postgresql+psycopg://offline/f1_strategy"
    assert "password" not in ALEMBIC_CONFIG_PATH.read_text().lower()
