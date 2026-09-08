"""Tests for immutable database repository primitives."""

from collections.abc import Mapping
from typing import Self

import pytest
from sqlalchemy.dialects import postgresql

from app.db import (
    Circuit,
    ImmutableRepository,
    ImmutableRowConflictError,
    RepositoryConflictError,
    Season,
    insert_rows,
)


class _MappingResult:
    """Minimal SQLAlchemy mapping-result test double."""

    def __init__(
        self,
        row: Mapping[str, object] | None,
    ) -> None:
        self.row = row

    def mappings(self) -> Self:
        """Return the mapping-result interface."""
        return self

    def one_or_none(
        self,
    ) -> Mapping[str, object] | None:
        """Return the configured single row."""
        return self.row


class _RecordingSession:
    """Record statements and return configured mapping rows."""

    def __init__(
        self,
        *rows: Mapping[str, object] | None,
    ) -> None:
        self.rows = list(rows)
        self.calls: list[tuple[object, object]] = []

    def execute(
        self,
        statement: object,
        parameters: object = None,
    ) -> _MappingResult:
        """Record execution and return the next configured row."""
        self.calls.append((statement, parameters))
        row = self.rows.pop(0) if self.rows else None
        return _MappingResult(row)


def _season_repository() -> ImmutableRepository:
    """Return the simplest immutable model repository."""
    return ImmutableRepository(
        table=Season.__table__,
        identity_columns=("season",),
    )


def test_repository_inserts_new_immutable_row() -> None:
    """A new natural identity returns its stored row."""
    session = _RecordingSession({"season": 2024})

    result = _season_repository().insert_or_verify(
        session,  # type: ignore[arg-type]
        {"season": 2024},
    )

    assert result.status == "inserted"
    assert result.row == {"season": 2024}
    assert len(session.calls) == 1
    compiled = str(
        session.calls[0][0].compile(
            dialect=postgresql.dialect()
        )
    )
    assert "ON CONFLICT DO NOTHING" in compiled
    assert "RETURNING" in compiled


def test_repository_verifies_identical_retry() -> None:
    """An identical existing row is a safe idempotent retry."""
    session = _RecordingSession(None, {"season": 2024})

    result = _season_repository().insert_or_verify(
        session,  # type: ignore[arg-type]
        {"season": 2024},
    )

    assert result.status == "verified"
    assert result.row == {"season": 2024}
    assert len(session.calls) == 2


def test_repository_rejects_changed_immutable_row() -> None:
    """A retry may not silently mutate source-backed values."""
    repository = ImmutableRepository(
        table=Circuit.__table__,
        identity_columns=("country", "location"),
    )
    session = _RecordingSession(
        None,
        {
            "circuit_id": 1,
            "country": "Italy",
            "location": "Monza",
            "circuit_name": "Stored name",
        },
    )

    with pytest.raises(ImmutableRowConflictError) as caught:
        repository.insert_or_verify(
            session,  # type: ignore[arg-type]
            {
                "country": "Italy",
                "location": "Monza",
                "circuit_name": "Source name",
            },
        )

    assert caught.value.identity == {
        "country": "Italy",
        "location": "Monza",
    }
    assert caught.value.differences == {
        "circuit_name": (
            "Source name",
            "Stored name",
        )
    }


def test_repository_rejects_unrelated_unique_conflict() -> None:
    """A conflict must resolve to the requested natural identity."""
    session = _RecordingSession(None, None)

    with pytest.raises(
        RepositoryConflictError,
        match="different unique constraint",
    ):
        _season_repository().insert_or_verify(
            session,  # type: ignore[arg-type]
            {"season": 2024},
        )


def test_repository_requires_complete_known_identity() -> None:
    """Repository input is checked before SQL is emitted."""
    session = _RecordingSession()
    repository = _season_repository()

    with pytest.raises(ValueError, match="missing identity"):
        repository.insert_or_verify(
            session,  # type: ignore[arg-type]
            {},
        )

    with pytest.raises(ValueError, match="unknown columns"):
        repository.insert_or_verify(
            session,  # type: ignore[arg-type]
            {"season": 2024, "future": True},
        )

    assert session.calls == []


def test_repository_requires_a_unique_identity() -> None:
    """Verification queries cannot use an ambiguous identity."""
    with pytest.raises(ValueError, match="primary key or unique"):
        ImmutableRepository(
            table=Circuit.__table__,
            identity_columns=("country",),
        )


def test_bulk_insert_uses_bounded_batches() -> None:
    """Large authoritative tables do not form one unbounded call."""
    session = _RecordingSession()
    rows = ({"season": season} for season in range(2020, 2025))

    inserted_count = insert_rows(
        session,  # type: ignore[arg-type]
        Season.__table__,
        rows,
        chunk_size=2,
    )

    assert inserted_count == 5
    assert [
        len(parameters)  # type: ignore[arg-type]
        for _, parameters in session.calls
    ] == [2, 2, 1]


def test_bulk_insert_validates_configuration_and_rows() -> None:
    """Invalid batches fail before their affected SQL execution."""
    session = _RecordingSession()

    with pytest.raises(ValueError, match="positive"):
        insert_rows(
            session,  # type: ignore[arg-type]
            Season.__table__,
            (),
            chunk_size=0,
        )

    with pytest.raises(ValueError, match="unknown columns"):
        insert_rows(
            session,  # type: ignore[arg-type]
            Season.__table__,
            ({"championship": 2024},),
        )

    assert session.calls == []
