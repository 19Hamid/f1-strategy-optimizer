"""Tests for atomic raw-session storage."""

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from app.pipeline.models import SessionKey
from app.pipeline.paths import RawDataPaths
from app.pipeline.serialization import (
    read_json_document,
    read_parquet_table,
    sha256_file,
)
from app.pipeline.source import RawSessionData
from app.pipeline.storage import (
    IncompleteSessionDirectoryError,
    RawSessionWriter,
)
from app.pipeline.validation import RawDataValidationError


def make_raw_session() -> RawSessionData:
    """Create a minimal valid raw race session."""
    provenance = {
        "Season": [2024],
        "RoundNumber": [1],
        "SessionType": ["R"],
        "EventName": ["Bahrain Grand Prix"],
    }

    laps = pd.DataFrame(
        provenance
        | {
            "Driver": ["VER"],
            "Team": ["Red Bull Racing"],
            "LapNumber": [1.0],
            "LapTime": [pd.Timedelta(95, unit="s")],
            "Stint": [1.0],
            "Compound": ["SOFT"],
            "TyreLife": [1.0],
            "PitInTime": [pd.NaT],
            "PitOutTime": [pd.NaT],
            "TrackStatus": ["1"],
            "LapStartTime": [pd.Timedelta(0, unit="s")],
        }
    )

    weather = pd.DataFrame(
        provenance
        | {
            "Time": [pd.Timedelta(0, unit="s")],
            "AirTemp": [18.5],
            "TrackTemp": [22.0],
            "Humidity": [45.0],
            "Pressure": [1015.0],
            "Rainfall": [False],
            "WindDirection": [180],
            "WindSpeed": [2.5],
        }
    )

    results = pd.DataFrame(
        provenance
        | {
            "Abbreviation": ["VER"],
            "TeamName": ["Red Bull Racing"],
            "Position": [1.0],
            "ClassifiedPosition": ["1"],
            "GridPosition": [1.0],
            "Status": ["Finished"],
            "Points": [25.0],
        }
    )

    return RawSessionData(
        session_key=SessionKey(
            season=2024,
            round_number=1,
        ),
        laps=laps,
        weather=weather,
        results=results,
        metadata={
            "season": 2024,
            "round_number": 1,
            "session_type": "R",
            "event_name": "Bahrain Grand Prix",
            "telemetry_loaded": False,
            "fastf1_version": "test-version",
        },
    )


def test_writes_complete_session_partition(
    tmp_path: Path,
) -> None:
    raw_session = make_raw_session()
    raw_paths = RawDataPaths(tmp_path / "raw")
    writer = RawSessionWriter(raw_paths)

    result = writer.write(raw_session)
    session_paths = raw_paths.for_session(
        raw_session.session_key
    )

    assert result.status == "written"
    assert result.directory == session_paths.directory
    assert session_paths.laps.is_file()
    assert session_paths.weather.is_file()
    assert session_paths.results.is_file()
    assert session_paths.metadata.is_file()
    assert session_paths.manifest.is_file()
    assert not session_paths.temporary_directory.exists()

    stored_laps = read_parquet_table(session_paths.laps)

    pd.testing.assert_frame_equal(
        stored_laps,
        raw_session.laps.reset_index(drop=True),
    )

    assert (
        read_json_document(session_paths.metadata)
        == raw_session.metadata
    )

    files = result.manifest["files"]
    assert isinstance(files, dict)

    laps_record = files["laps.parquet"]
    assert isinstance(laps_record, dict)
    assert laps_record["rows"] == 1
    assert (
        laps_record["sha256"]
        == sha256_file(session_paths.laps)
    )


def test_skips_completed_session_by_default(
    tmp_path: Path,
) -> None:
    raw_session = make_raw_session()
    writer = RawSessionWriter(
        RawDataPaths(tmp_path / "raw")
    )

    first_result = writer.write(raw_session)
    second_result = writer.write(raw_session)

    assert first_result.status == "written"
    assert second_result.status == "skipped"
    assert second_result.manifest == first_result.manifest


def test_force_replaces_completed_session(
    tmp_path: Path,
) -> None:
    raw_session = make_raw_session()
    raw_paths = RawDataPaths(tmp_path / "raw")
    writer = RawSessionWriter(raw_paths)

    writer.write(raw_session)

    expanded_laps = (
        raw_session.laps.iloc[[0, 0]]
        .copy()
        .reset_index(drop=True)
    )
    expanded_laps.loc[1, "LapNumber"] = 2.0

    updated_session = replace(
        raw_session,
        laps=expanded_laps,
    )

    result = writer.write(
        updated_session,
        force=True,
    )

    assert result.status == "written"

    files = result.manifest["files"]
    assert isinstance(files, dict)

    laps_record = files["laps.parquet"]
    assert isinstance(laps_record, dict)
    assert laps_record["rows"] == 2


def test_rejects_invalid_session_before_writing(
    tmp_path: Path,
) -> None:
    raw_session = make_raw_session()
    invalid_session = replace(
        raw_session,
        laps=raw_session.laps.drop(
            columns=["LapTime"]
        ),
    )
    raw_paths = RawDataPaths(tmp_path / "raw")
    writer = RawSessionWriter(raw_paths)

    with pytest.raises(RawDataValidationError):
        writer.write(invalid_session)

    session_paths = raw_paths.for_session(
        raw_session.session_key
    )
    assert not session_paths.directory.exists()


def test_rejects_incomplete_final_directory(
    tmp_path: Path,
) -> None:
    raw_session = make_raw_session()
    raw_paths = RawDataPaths(tmp_path / "raw")
    session_paths = raw_paths.for_session(
        raw_session.session_key
    )
    session_paths.directory.mkdir(
        parents=True,
    )

    writer = RawSessionWriter(raw_paths)

    with pytest.raises(
        IncompleteSessionDirectoryError,
        match="without a completed manifest",
    ):
        writer.write(raw_session)