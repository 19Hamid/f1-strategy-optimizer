"""Tests for raw-data path generation."""

from pathlib import Path

from app.pipeline.models import SessionKey
from app.pipeline.paths import RawDataPaths


def test_builds_partitioned_session_directory(
    tmp_path: Path,
) -> None:
    paths = RawDataPaths(tmp_path / "fastf1")
    session = paths.for_session(
        SessionKey(
            season=2024,
            round_number=1,
        )
    )

    assert session.directory == (
        tmp_path
        / "fastf1"
        / "season=2024"
        / "round=01"
        / "session=R"
    )


def test_builds_expected_session_files(
    tmp_path: Path,
) -> None:
    paths = RawDataPaths(tmp_path / "fastf1")
    session = paths.for_session(
        SessionKey(
            season=2025,
            round_number=3,
        )
    )

    assert session.table_paths == {
        "laps": session.directory / "laps.parquet",
        "weather": session.directory / "weather.parquet",
        "results": session.directory / "results.parquet",
    }
    assert session.metadata == session.directory / "metadata.json"
    assert session.manifest == session.directory / "manifest.json"


def test_builds_dataset_and_temporary_paths(
    tmp_path: Path,
) -> None:
    paths = RawDataPaths(tmp_path / "fastf1")
    session = paths.for_session(
        SessionKey(
            season=2024,
            round_number=1,
        )
    )

    assert paths.catalog == tmp_path / "fastf1" / "catalog.parquet"
    assert paths.runs_directory == tmp_path / "fastf1" / "runs"
    assert session.temporary_directory == (
        tmp_path / "fastf1" / ".tmp" / "2024-01-R"
    )

    assert not session.directory.exists()
    assert not session.temporary_directory.exists()