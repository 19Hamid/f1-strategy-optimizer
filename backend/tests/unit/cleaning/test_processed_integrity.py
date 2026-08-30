"""Tests for processed-partition integrity verification."""

from pathlib import Path

import pandas as pd
import pytest

from app.cleaning.integrity import (
    ProcessedIntegrityError,
    verify_processed_partition,
)
from app.cleaning.paths import ProcessedDataPaths
from app.cleaning.processing import (
    PROCESSED_CONTRACT_VERSION,
    ProcessedSessionData,
)
from app.cleaning.storage import (
    ProcessedSessionWriter,
)
from app.pipeline.models import SessionKey
from app.pipeline.serialization import (
    read_json_document,
    sha256_file,
    write_json_document,
)


def make_processed_data() -> ProcessedSessionData:
    """Build one valid processed session."""
    session_key = SessionKey(2024, 1)

    laps = pd.DataFrame(
        {
            "Season": [2024, 2024],
            "RoundNumber": [1, 1],
            "SessionType": ["R", "R"],
            "EventName": [
                "Bahrain Grand Prix",
                "Bahrain Grand Prix",
            ],
            "Driver": ["VER", "VER"],
            "LapNumber": [1.0, 2.0],
            "IsEligible": [False, True],
            "QualityReasons": [
                "FIRST_LAP",
                "",
            ],
            "Rainfall": [False, False],
        }
    )

    stints = pd.DataFrame(
        {
            "season": [2024],
            "round_number": [1],
            "session_type": ["R"],
            "event_name": [
                "Bahrain Grand Prix"
            ],
            "driver": ["VER"],
            "stint_number": [1],
            "recorded_laps": [2],
            "is_complete": [True],
            "warnings": [""],
        }
    )

    pit_events = pd.DataFrame(
        {
            "pit_event_id": [
                "2024-01-R-VER-P001"
            ],
            "season": [2024],
            "round_number": [1],
            "session_type": ["R"],
            "event_name": [
                "Bahrain Grand Prix"
            ],
            "driver": ["VER"],
            "pit_in_lap": [1.0],
            "pit_out_lap": [2.0],
            "is_complete": [True],
            "entry_rainfall": [False],
            "exit_rainfall": [False],
            "is_dry_weather_pair": [True],
            "is_duration_analysis_candidate": [
                True
            ],
            "warnings": [""],
        }
    )

    quality_report: dict[str, object] = {
        "processed_contract_version": (
            PROCESSED_CONTRACT_VERSION
        ),
        "cleaning_rule_version": "1.0",
        "source_contract_version": "1.0",
        "session": {
            "identifier": session_key.identifier,
            "season": session_key.season,
            "round_number": (
                session_key.round_number
            ),
            "session_type": (
                session_key.session_type
            ),
            "event_name": (
                "Bahrain Grand Prix"
            ),
        },
        "tables": {
            "laps_rows": len(laps),
            "stints_rows": len(stints),
            "pit_events_rows": len(
                pit_events
            ),
        },
        "validation": {
            "status": "passed",
        },
    }

    return ProcessedSessionData(
        session_key=session_key,
        laps=laps,
        stints=stints,
        pit_events=pit_events,
        quality_report=quality_report,
    )


def write_partition(
    tmp_path: Path,
) -> tuple[
    ProcessedDataPaths,
    SessionKey,
]:
    """Write one valid partition and return its identity."""
    data = make_processed_data()
    processed_paths = ProcessedDataPaths(
        tmp_path / "processed"
    )

    ProcessedSessionWriter(
        processed_paths
    ).write(data)

    return (
        processed_paths,
        data.session_key,
    )


def issue_codes(
    report: object,
) -> set[str]:
    """Return issue codes from an integrity report."""
    assert hasattr(report, "issues")

    return {
        issue.code
        for issue in report.issues
    }


def update_quality_report_record(
    *,
    processed_paths: ProcessedDataPaths,
    session_key: SessionKey,
) -> None:
    """Refresh manifest metadata after changing the report."""
    session_paths = processed_paths.for_session(
        session_key
    )

    manifest = read_json_document(
        session_paths.manifest
    )
    files = manifest["files"]

    assert isinstance(files, dict)

    record = files["quality_report.json"]

    assert isinstance(record, dict)

    record["sha256"] = sha256_file(
        session_paths.quality_report
    )
    record["size_bytes"] = (
        session_paths.quality_report.stat().st_size
    )

    write_json_document(
        manifest,
        session_paths.manifest,
    )


def test_accepts_valid_processed_partition(
    tmp_path: Path,
) -> None:
    """A writer-produced partition must pass verification."""
    processed_paths, session_key = (
        write_partition(tmp_path)
    )

    report = verify_processed_partition(
        processed_paths,
        session_key,
    )

    assert report.is_valid
    assert report.issues == ()
    assert report.manifest is not None
    assert (
        report.directory
        == processed_paths.for_session(
            session_key
        ).directory
    )

    report.raise_for_errors()


def test_reports_missing_directory(
    tmp_path: Path,
) -> None:
    """An absent partition must be reported clearly."""
    report = verify_processed_partition(
        ProcessedDataPaths(
            tmp_path / "processed"
        ),
        SessionKey(2024, 1),
    )

    assert not report.is_valid
    assert issue_codes(report) == {
        "MISSING_DIRECTORY"
    }
    assert report.manifest is None


def test_reports_missing_manifest(
    tmp_path: Path,
) -> None:
    """A directory without completion proof is invalid."""
    processed_paths = ProcessedDataPaths(
        tmp_path / "processed"
    )
    session_key = SessionKey(2024, 1)

    processed_paths.for_session(
        session_key
    ).directory.mkdir(
        parents=True
    )

    report = verify_processed_partition(
        processed_paths,
        session_key,
    )

    assert issue_codes(report) == {
        "MISSING_MANIFEST"
    }


def test_reports_corrupted_processed_file(
    tmp_path: Path,
) -> None:
    """Checksum and size changes must be detected."""
    processed_paths, session_key = (
        write_partition(tmp_path)
    )
    session_paths = processed_paths.for_session(
        session_key
    )

    with session_paths.laps.open("ab") as stream:
        stream.write(b"corruption")

    report = verify_processed_partition(
        processed_paths,
        session_key,
    )

    assert {
        "CHECKSUM_MISMATCH",
        "SIZE_MISMATCH",
    }.issubset(
        issue_codes(report)
    )


def test_reports_missing_processed_file(
    tmp_path: Path,
) -> None:
    """A manifest cannot excuse a missing table."""
    processed_paths, session_key = (
        write_partition(tmp_path)
    )
    session_paths = processed_paths.for_session(
        session_key
    )

    session_paths.stints.unlink()

    report = verify_processed_partition(
        processed_paths,
        session_key,
    )

    assert "MISSING_FILE" in issue_codes(
        report
    )


def test_reports_unexpected_file(
    tmp_path: Path,
) -> None:
    """Unmanifested files must remain visible."""
    processed_paths, session_key = (
        write_partition(tmp_path)
    )
    session_paths = processed_paths.for_session(
        session_key
    )

    (
        session_paths.directory / "mystery.txt"
    ).write_text(
        "who invited this file",
        encoding="utf-8",
    )

    report = verify_processed_partition(
        processed_paths,
        session_key,
    )

    assert "UNEXPECTED_FILE" in issue_codes(
        report
    )


def test_reports_manifest_session_mismatch(
    tmp_path: Path,
) -> None:
    """Stored identity must agree with its partition path."""
    processed_paths, session_key = (
        write_partition(tmp_path)
    )
    session_paths = processed_paths.for_session(
        session_key
    )

    manifest = read_json_document(
        session_paths.manifest
    )
    session = manifest["session"]

    assert isinstance(session, dict)

    session["identifier"] = "2024-02-R"

    write_json_document(
        manifest,
        session_paths.manifest,
    )

    report = verify_processed_partition(
        processed_paths,
        session_key,
    )

    assert (
        "SESSION_IDENTITY_MISMATCH"
        in issue_codes(report)
    )


def test_reports_version_mismatches(
    tmp_path: Path,
) -> None:
    """Contract and cleaning versions must be enforced."""
    processed_paths, session_key = (
        write_partition(tmp_path)
    )
    session_paths = processed_paths.for_session(
        session_key
    )

    manifest = read_json_document(
        session_paths.manifest
    )
    manifest[
        "processed_contract_version"
    ] = "999.0"
    manifest[
        "cleaning_rule_version"
    ] = "999.0"

    write_json_document(
        manifest,
        session_paths.manifest,
    )

    report = verify_processed_partition(
        processed_paths,
        session_key,
    )
    codes = issue_codes(report)

    assert "CONTRACT_VERSION_MISMATCH" in codes
    assert "CLEANING_VERSION_MISMATCH" in codes


def test_reports_invalid_file_manifest(
    tmp_path: Path,
) -> None:
    """The file manifest must be a JSON object."""
    processed_paths, session_key = (
        write_partition(tmp_path)
    )
    session_paths = processed_paths.for_session(
        session_key
    )

    manifest = read_json_document(
        session_paths.manifest
    )
    manifest["files"] = []

    write_json_document(
        manifest,
        session_paths.manifest,
    )

    report = verify_processed_partition(
        processed_paths,
        session_key,
    )

    assert issue_codes(report) == {
        "INVALID_FILE_MANIFEST"
    }


def test_reports_quality_report_row_mismatch(
    tmp_path: Path,
) -> None:
    """Quality counts must match restored tables."""
    processed_paths, session_key = (
        write_partition(tmp_path)
    )
    session_paths = processed_paths.for_session(
        session_key
    )

    quality_report = read_json_document(
        session_paths.quality_report
    )
    tables = quality_report["tables"]

    assert isinstance(tables, dict)

    tables["laps_rows"] = 999

    write_json_document(
        quality_report,
        session_paths.quality_report,
    )
    update_quality_report_record(
        processed_paths=processed_paths,
        session_key=session_key,
    )

    report = verify_processed_partition(
        processed_paths,
        session_key,
    )

    assert (
        "REPORT_ROW_COUNT_MISMATCH"
        in issue_codes(report)
    )


def test_reports_manifest_column_mismatch(
    tmp_path: Path,
) -> None:
    """Recorded table columns must match Parquet."""
    processed_paths, session_key = (
        write_partition(tmp_path)
    )
    session_paths = processed_paths.for_session(
        session_key
    )

    manifest = read_json_document(
        session_paths.manifest
    )
    files = manifest["files"]

    assert isinstance(files, dict)

    laps_record = files["laps.parquet"]

    assert isinstance(laps_record, dict)

    laps_record["columns"] = [
        "definitely_not_the_real_columns"
    ]

    write_json_document(
        manifest,
        session_paths.manifest,
    )

    report = verify_processed_partition(
        processed_paths,
        session_key,
    )

    assert "COLUMN_MISMATCH" in issue_codes(
        report
    )


def test_reports_malformed_manifest_json(
    tmp_path: Path,
) -> None:
    """Unreadable JSON must become an integrity issue."""
    processed_paths, session_key = (
        write_partition(tmp_path)
    )
    session_paths = processed_paths.for_session(
        session_key
    )

    session_paths.manifest.write_text(
        "{ definitely not json",
        encoding="utf-8",
    )

    report = verify_processed_partition(
        processed_paths,
        session_key,
    )

    assert issue_codes(report) == {
        "INVALID_JSON"
    }
    assert report.manifest is None


def test_raises_combined_integrity_error(
    tmp_path: Path,
) -> None:
    """Callers may promote all issues into one exception."""
    report = verify_processed_partition(
        ProcessedDataPaths(
            tmp_path / "processed"
        ),
        SessionKey(2024, 1),
    )

    with pytest.raises(
        ProcessedIntegrityError,
        match=(
            r"2024-01-R:"
            r"\n\[MISSING_DIRECTORY\]"
        ),
    ):
        report.raise_for_errors()


def test_rejects_invalid_verifier_inputs(
    tmp_path: Path,
) -> None:
    """Verifier arguments must use validated models."""
    processed_paths = ProcessedDataPaths(
        tmp_path / "processed"
    )
    session_key = SessionKey(2024, 1)

    with pytest.raises(TypeError):
        verify_processed_partition(
            tmp_path,  # type: ignore[arg-type]
            session_key,
        )

    with pytest.raises(TypeError):
        verify_processed_partition(
            processed_paths,
            "2024-01-R",  # type: ignore[arg-type]
        )