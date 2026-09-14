"""Tests for the Phase 4 PostgreSQL command-line interface."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.db.cli import (
    DEFAULT_DATASETS_ROOT,
    DEFAULT_PROCESSED_ROOT,
    DEFAULT_RAW_ROOT,
    _default_run_id,
    build_parser,
)


def test_parser_exposes_load_with_authoritative_defaults() -> None:
    """Point complete loads at the repository artifact roots."""
    arguments = build_parser().parse_args(["load"])
    assert arguments.command == "load"
    assert arguments.raw_root == DEFAULT_RAW_ROOT
    assert arguments.processed_root == DEFAULT_PROCESSED_ROOT
    assert arguments.datasets_root == DEFAULT_DATASETS_ROOT
    assert arguments.run_id is None


def test_parser_accepts_explicit_load_configuration(tmp_path: Path) -> None:
    """Permit intentional artifact roots and reproducible run identities."""
    arguments = build_parser().parse_args(
        [
            "load",
            "--raw-root",
            str(tmp_path / "raw"),
            "--processed-root",
            str(tmp_path / "processed"),
            "--datasets-root",
            str(tmp_path / "datasets"),
            "--run-id",
            "phase-4-audit",
        ]
    )
    assert arguments.raw_root == tmp_path / "raw"
    assert arguments.processed_root == tmp_path / "processed"
    assert arguments.datasets_root == tmp_path / "datasets"
    assert arguments.run_id == "phase-4-audit"


def test_parser_exposes_read_only_audit() -> None:
    """Keep post-load reconciliation available as a separate command."""
    arguments = build_parser().parse_args(["audit"])
    assert arguments.command == "audit"


def test_default_run_id_is_utc_and_filesystem_safe() -> None:
    """Generate stable identities without path separators or punctuation."""
    value = datetime(2026, 9, 14, 15, 7, 9, tzinfo=UTC)
    assert _default_run_id(value) == "database-20260914T150709Z"


def test_default_run_id_rejects_naive_datetime() -> None:
    """Require an unambiguous audit timestamp."""
    value = datetime(2026, 9, 14, 15, 7, 9, tzinfo=UTC)
    with pytest.raises(ValueError, match="timezone-aware"):
        _default_run_id(value.replace(tzinfo=None))


def test_parser_requires_a_command() -> None:
    """Avoid silently connecting to PostgreSQL without an operation."""
    with pytest.raises(SystemExit):
        build_parser().parse_args([])
