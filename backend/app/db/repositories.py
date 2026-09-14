"""Reusable repositories for immutable verified database rows."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import islice
from typing import Literal

from sqlalchemy import (
    Table,
    UniqueConstraint,
    insert,
    select,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

RepositoryWriteStatus = Literal["inserted", "verified"]


class RepositoryError(RuntimeError):
    """Base error for database repository failures."""


class RepositoryConflictError(RepositoryError):
    """Raised when a uniqueness conflict has no expected identity."""


class ImmutableRowConflictError(RepositoryError):
    """Raised when an existing immutable row differs from its source."""

    def __init__(
        self,
        *,
        table_name: str,
        identity: Mapping[str, object],
        differences: Mapping[
            str,
            tuple[object, object],
        ],
    ) -> None:
        """Record deterministic expected and stored differences."""
        self.table_name = table_name
        self.identity = dict(identity)
        self.differences = dict(differences)
        fields = ", ".join(sorted(differences))
        super().__init__(
            f"immutable {table_name} row differs for "
            f"fields: {fields}"
        )


@dataclass(frozen=True, slots=True)
class RepositoryWriteResult:
    """Describe whether an immutable row was inserted or verified."""

    status: RepositoryWriteStatus
    row: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ImmutableRepository:
    """Insert immutable rows once and verify identical retries."""

    table: Table
    identity_columns: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate the table and its natural identity columns."""
        if not isinstance(self.table, Table):
            raise TypeError("table must be a SQLAlchemy Table")

        if not isinstance(self.identity_columns, tuple):
            raise TypeError("identity_columns must be a tuple")

        if not self.identity_columns:
            raise ValueError("identity_columns must not be empty")

        if len(set(self.identity_columns)) != len(
            self.identity_columns
        ):
            raise ValueError(
                "identity_columns must not contain duplicates"
            )

        unknown_columns = set(
            self.identity_columns
        ) - set(self.table.c.keys())

        if unknown_columns:
            names = ", ".join(sorted(unknown_columns))
            raise ValueError(
                f"unknown identity columns for "
                f"{self.table.name}: {names}"
            )

        identity = frozenset(self.identity_columns)
        unique_identities = {
            frozenset(
                column.name
                for column in constraint.columns
            )
            for constraint in self.table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        primary_key_identity = frozenset(
            column.name
            for column in self.table.primary_key.columns
        )

        if primary_key_identity:
            unique_identities.add(primary_key_identity)

        if identity not in unique_identities:
            raise ValueError(
                "identity_columns must match a primary key "
                f"or unique constraint on {self.table.name}"
            )

    def insert_or_verify(
        self,
        session: Session,
        values: Mapping[str, object],
    ) -> RepositoryWriteResult:
        """Insert one row or verify its complete stored value set."""
        record = _validated_record(self.table, values)
        identity = self._identity(record)
        statement = (
            postgresql_insert(self.table)
            .values(record)
            .on_conflict_do_nothing()
            .returning(*self.table.c)
        )
        inserted = (
            session.execute(statement)
            .mappings()
            .one_or_none()
        )

        if inserted is not None:
            return RepositoryWriteResult(
                status="inserted",
                row=dict(inserted),
            )

        existing_statement = select(
            *self.table.c
        ).where(
            *(
                self.table.c[column_name]
                == identity[column_name]
                for column_name in self.identity_columns
            )
        )
        existing = (
            session.execute(existing_statement)
            .mappings()
            .one_or_none()
        )

        if existing is None:
            raise RepositoryConflictError(
                f"a different unique constraint blocked "
                f"the {self.table.name} insert"
            )

        differences = {
            column_name: (
                expected_value,
                existing[column_name],
            )
            for column_name, expected_value in record.items()
            if existing[column_name] != expected_value
        }

        if differences:
            raise ImmutableRowConflictError(
                table_name=self.table.name,
                identity=identity,
                differences=differences,
            )

        return RepositoryWriteResult(
            status="verified",
            row=dict(existing),
        )

    def _identity(
        self,
        record: Mapping[str, object],
    ) -> dict[str, object]:
        """Extract the complete natural identity for one row."""
        missing_columns = tuple(
            column_name
            for column_name in self.identity_columns
            if column_name not in record
        )

        if missing_columns:
            names = ", ".join(missing_columns)
            raise ValueError(
                f"missing identity values for "
                f"{self.table.name}: {names}"
            )

        return {
            column_name: record[column_name]
            for column_name in self.identity_columns
        }


def insert_rows(
    session: Session,
    table: Table,
    rows: Iterable[Mapping[str, object]],
    *,
    chunk_size: int = 1_000,
) -> int:
    """Insert authoritative rows in bounded executemany batches."""
    if not isinstance(table, Table):
        raise TypeError("table must be a SQLAlchemy Table")

    if (
        not isinstance(chunk_size, int)
        or isinstance(chunk_size, bool)
    ):
        raise TypeError("chunk_size must be an integer")

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    row_iterator = iter(rows)
    inserted_count = 0

    while True:
        batch = list(islice(row_iterator, chunk_size))

        if not batch:
            return inserted_count

        validated_batch = [
            _validated_record(table, row)
            for row in batch
        ]
        session.execute(
            insert(table),
            validated_batch,
        )
        inserted_count += len(validated_batch)


def _validated_record(
    table: Table,
    values: Mapping[str, object],
) -> dict[str, object]:
    """Copy one record and reject fields outside the ORM schema."""
    if not isinstance(values, Mapping):
        raise TypeError("row values must be a mapping")

    record = dict(values)
    unknown_columns = set(record) - set(table.c.keys())

    if unknown_columns:
        names = ", ".join(sorted(unknown_columns))
        raise ValueError(
            f"unknown columns for {table.name}: {names}"
        )

    return record
