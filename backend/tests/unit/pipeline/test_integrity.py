"""Tests for stored raw-session integrity verification."""

from pathlib import Path

import pandas as pd

from app.pipeline.integrity import verify_session_partition
from app.pipeline.models import SessionKey
from app.pipeline.paths import RawDataPaths
from app.pipeline.serialization import (
    read_json_document,
    write_json_document,
)
from app.pipeline.source import RawSessionData
from app.pipeline.storage import RawSessionWriter


def make_raw_session() -> RawSessionData:
    """Create a minimal valid raw session."""
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


def store_valid_session(
    tmp_path: Path,
) -> tuple[RawDataPaths, RawSessionData]:
    """Store and return one valid test session."""
    raw_session = make_raw_session()
    raw_paths = RawDataPaths(tmp_path / "raw")

    RawSessionWriter(raw_paths).write(raw_session)

    return raw_paths, raw_session


def issue_codes(
    raw_paths: RawDataPaths,
    session_key: SessionKey,
) -> set[str]:
    """Return the integrity issue codes for one session."""
    report = verify_session_partition(
        raw_paths,
        session_key,
    )

    return {
        issue.code
        for issue in report.issues
    }


def test_accepts_complete_session_partition(
    tmp_path: Path,
) -> None:
    raw_paths, raw_session = store_valid_session(tmp_path)

    report = verify_session_partition(
        raw_paths,
        raw_session.session_key,
    )

    assert report.is_valid is True
    assert report.issues == ()


def test_reports_missing_manifest(
    tmp_path: Path,
) -> None:
    raw_paths = RawDataPaths(tmp_path / "raw")
    session_key = SessionKey(2024, 1)

    report = verify_session_partition(
        raw_paths,
        session_key,
    )

    assert report.is_valid is False
    assert issue_codes(
        raw_paths,
        session_key,
    ) == {"missing_manifest"}


def test_reports_missing_stored_file(
    tmp_path: Path,
) -> None:
    raw_paths, raw_session = store_valid_session(tmp_path)
    session_paths = raw_paths.for_session(
        raw_session.session_key
    )
    session_paths.weather.unlink()

    assert "missing_file" in issue_codes(
        raw_paths,
        raw_session.session_key,
    )


def test_reports_corrupted_file(
    tmp_path: Path,
) -> None:
    raw_paths, raw_session = store_valid_session(tmp_path)
    session_paths = raw_paths.for_session(
        raw_session.session_key
    )
    session_paths.laps.write_bytes(
        b"corrupted parquet data"
    )

    codes = issue_codes(
        raw_paths,
        raw_session.session_key,
    )

    assert "size_mismatch" in codes
    assert "checksum_mismatch" in codes


def test_reports_manifest_identity_mismatch(
    tmp_path: Path,
) -> None:
    raw_paths, raw_session = store_valid_session(tmp_path)
    session_paths = raw_paths.for_session(
        raw_session.session_key
    )
    manifest = read_json_document(
        session_paths.manifest
    )
    session = manifest["session"]

    assert isinstance(session, dict)
    session["identifier"] = "2023-01-R"

    write_json_document(
        manifest,
        session_paths.manifest,
    )

    assert "identity_mismatch" in issue_codes(
        raw_paths,
        raw_session.session_key,
    )


def test_reports_invalid_recorded_file_path(
    tmp_path: Path,
) -> None:
    raw_paths, raw_session = store_valid_session(tmp_path)
    session_paths = raw_paths.for_session(
        raw_session.session_key
    )
    manifest = read_json_document(
        session_paths.manifest
    )
    files = manifest["files"]

    assert isinstance(files, dict)

    laps_record = files["laps.parquet"]
    assert isinstance(laps_record, dict)
    laps_record["path"] = "../wrong.parquet"

    write_json_document(
        manifest,
        session_paths.manifest,
    )

    assert "invalid_file_path" in issue_codes(
        raw_paths,
        raw_session.session_key,
    )