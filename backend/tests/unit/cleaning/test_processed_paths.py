"""Tests for processed-data path generation."""

from pathlib import Path

import pytest

from app.cleaning.paths import (
    ProcessedDataPaths,
    ProcessedSessionPaths,
)
from app.pipeline.models import SessionKey


def test_builds_versioned_session_directory(
    tmp_path: Path,
) -> None:
    """Session partitions must include the cleaning version."""
    paths = ProcessedDataPaths(
        tmp_path / "processed"
    )

    session_paths = paths.for_session(
        SessionKey(2024, 1)
    )

    assert session_paths.directory == (
        tmp_path
        / "processed"
        / "cleaning_version=1.0"
        / "season=2024"
        / "round=01"
        / "session=R"
    )


def test_builds_atomic_working_directories(
    tmp_path: Path,
) -> None:
    """Temporary and backup paths must remain isolated."""
    session_paths = ProcessedDataPaths(
        tmp_path / "processed"
    ).for_session(
        SessionKey(2024, 3)
    )

    assert session_paths.temporary_directory == (
        tmp_path
        / "processed"
        / "cleaning_version=1.0"
        / ".tmp"
        / "2024-03-R"
    )
    assert session_paths.backup_directory == (
        tmp_path
        / "processed"
        / "cleaning_version=1.0"
        / ".backup"
        / "2024-03-R"
    )


def test_builds_authoritative_file_paths(
    tmp_path: Path,
) -> None:
    """Every processed output must have one stable path."""
    session_paths = ProcessedDataPaths(
        tmp_path / "processed"
    ).for_session(
        SessionKey(2023, 7)
    )

    assert session_paths.laps.name == "laps.parquet"
    assert session_paths.stints.name == "stints.parquet"
    assert (
        session_paths.pit_events.name
        == "pit_events.parquet"
    )
    assert (
        session_paths.quality_report.name
        == "quality_report.json"
    )
    assert session_paths.manifest.name == "manifest.json"

    assert session_paths.table_paths == {
        "laps": session_paths.laps,
        "stints": session_paths.stints,
        "pit_events": session_paths.pit_events,
    }


def test_builds_dataset_level_paths(
    tmp_path: Path,
) -> None:
    """Catalogs and run records belong to one version."""
    paths = ProcessedDataPaths(
        tmp_path / "processed",
        cleaning_rule_version="2.0",
    )

    assert paths.version_root == (
        tmp_path
        / "processed"
        / "cleaning_version=2.0"
    )
    assert paths.catalog == (
        paths.version_root / "catalog.parquet"
    )
    assert paths.runs_directory == (
        paths.version_root / "runs"
    )


def test_normalizes_root_and_version(
    tmp_path: Path,
) -> None:
    """Path-like roots and surrounding spaces are normalized."""
    paths = ProcessedDataPaths(
        str(tmp_path / "processed"),
        cleaning_rule_version=" 1.1 ",
    )

    assert isinstance(paths.processed_root, Path)
    assert paths.cleaning_rule_version == "1.1"


@pytest.mark.parametrize(
    "cleaning_rule_version",
    [
        "",
        "   ",
        ".",
        "..",
        "1/0",
        r"1\0",
    ],
)
def test_rejects_unsafe_cleaning_versions(
    tmp_path: Path,
    cleaning_rule_version: str,
) -> None:
    """A version must not escape its dataset directory."""
    with pytest.raises(ValueError):
        ProcessedDataPaths(
            tmp_path,
            cleaning_rule_version=(
                cleaning_rule_version
            ),
        )


def test_rejects_non_string_cleaning_version(
    tmp_path: Path,
) -> None:
    """Cleaning versions must be explicit strings."""
    with pytest.raises(TypeError):
        ProcessedDataPaths(
            tmp_path,
            cleaning_rule_version=1,  # type: ignore[arg-type]
        )


def test_rejects_invalid_session_key(
    tmp_path: Path,
) -> None:
    """Session paths require a validated SessionKey."""
    with pytest.raises(TypeError):
        ProcessedSessionPaths(
            processed_root=tmp_path,
            cleaning_rule_version="1.0",
            session_key="2024-01-R",  # type: ignore[arg-type]
        )