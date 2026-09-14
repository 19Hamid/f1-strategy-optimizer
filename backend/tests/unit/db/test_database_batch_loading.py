"""Tests for complete development-database build orchestration."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.datasets import DatasetPaths
from app.db.batch_loading import (
    DatabaseBatchLoadError,
    _global_artifact_hashes,
    _normalize_started_at,
    _validate_run_id,
    _validate_session_keys,
)
from app.pipeline import SessionKey
from app.pipeline.serialization import sha256_file


def _complete_schedule() -> tuple[SessionKey, ...]:
    """Return the frozen season counts with canonical synthetic rounds."""
    return tuple(
        SessionKey(season, round_number, "R")
        for season, rounds in ((2022, 22), (2023, 22), (2024, 24))
        for round_number in range(1, rounds + 1)
    )


def test_complete_schedule_is_canonicalized() -> None:
    """Accept only the exact 68-race development population."""
    expected = _complete_schedule()
    actual = _validate_session_keys(reversed(expected))
    assert actual == expected


def test_schedule_rejects_protected_season_before_sql() -> None:
    """Keep protected evaluation identities outside database access."""
    keys = list(_complete_schedule())
    keys[-1] = SessionKey(2025, 1, "R")
    with pytest.raises(
        DatabaseBatchLoadError,
        match="protected evaluation",
    ):
        _validate_session_keys(keys)


@pytest.mark.parametrize(
    ("keys", "message"),
    [
        (_complete_schedule()[:-1], "exactly 68"),
        (
            _complete_schedule()[:-1] + (_complete_schedule()[0],),
            "unique",
        ),
        (
            _complete_schedule()[:-1] + (SessionKey(2024, 24, "Q"),),
            "development race",
        ),
    ],
)
def test_schedule_rejects_incomplete_or_invalid_population(
    keys: tuple[SessionKey, ...],
    message: str,
) -> None:
    """Fail closed before opening a partial global build."""
    with pytest.raises(DatabaseBatchLoadError, match=message):
        _validate_session_keys(keys)


def test_schedule_rejects_non_session_values() -> None:
    """Reject malformed schedule members explicitly."""
    with pytest.raises(TypeError, match="only SessionKey"):
        _validate_session_keys([object()])


@pytest.mark.parametrize("run_id", ["", " run-1", "run-1 "])
def test_run_id_must_be_canonical(run_id: str) -> None:
    """Prevent ambiguous run-record identities."""
    with pytest.raises(DatabaseBatchLoadError, match="canonical"):
        _validate_run_id(run_id)


def test_started_at_is_normalized_to_utc() -> None:
    """Persist timezone-aware build timestamps."""
    value = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    assert _normalize_started_at(value) == value
    with pytest.raises(DatabaseBatchLoadError, match="timezone-aware"):
        _normalize_started_at(datetime(2026, 9, 14, 12, 0))


def test_global_artifacts_are_hashed_before_sql(tmp_path: Path) -> None:
    """Capture immutable catalog and split identities for the build."""
    paths = DatasetPaths(tmp_path)
    paths.version_root.mkdir(parents=True)
    paths.catalog.write_bytes(b"catalog")
    paths.splits.write_bytes(b"splits")
    assert _global_artifact_hashes(paths) == (
        sha256_file(paths.catalog),
        sha256_file(paths.splits),
    )


def test_global_artifacts_are_required(tmp_path: Path) -> None:
    """Refuse a build whose authoritative globals are absent."""
    with pytest.raises(DatabaseBatchLoadError, match="missing"):
        _global_artifact_hashes(DatasetPaths(tmp_path))
