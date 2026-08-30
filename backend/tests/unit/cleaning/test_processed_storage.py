"""Tests for atomic processed-session storage."""

from pathlib import Path

import pandas as pd
import pytest

import app.cleaning.storage as storage_module
from app.cleaning.paths import ProcessedDataPaths
from app.cleaning.processing import (
    PROCESSED_CONTRACT_VERSION,
    ProcessedSessionData,
)
from app.cleaning.storage import (
    IncompleteProcessedSessionError,
    ProcessedParquetReadbackError,
    ProcessedSessionWriter,
    ProcessedStorageError,
)
from app.pipeline.models import SessionKey
from app.pipeline.serialization import (
    read_json_document,
    read_parquet_table,
)


def make_processed_data(
    lap_numbers: tuple[float, ...] = (
        1.0,
        2.0,
    ),
) -> ProcessedSessionData:
    """Build one valid processed-session fixture."""
    session_key = SessionKey(2024, 1)

    laps = pd.DataFrame(
        {
            "Season": [
                2024
                for _ in lap_numbers
            ],
            "RoundNumber": [
                1
                for _ in lap_numbers
            ],
            "SessionType": [
                "R"
                for _ in lap_numbers
            ],
            "EventName": [
                "Bahrain Grand Prix"
                for _ in lap_numbers
            ],
            "Driver": [
                "VER"
                for _ in lap_numbers
            ],
            "LapNumber": list(lap_numbers),
            "IsEligible": [
                True
                for _ in lap_numbers
            ],
            "QualityReasons": [
                ""
                for _ in lap_numbers
            ],
            "Rainfall": pd.Series(
                [
                    False
                    for _ in lap_numbers
                ],
                dtype="boolean",
            ),
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
            "recorded_laps": [
                len(lap_numbers)
            ],
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
            "entry_rainfall": pd.Series(
                [False],
                dtype="boolean",
            ),
            "exit_rainfall": pd.Series(
                [False],
                dtype="boolean",
            ),
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
            "raw_laps_preserved": True,
            "future_weather_matches": 0,
            "pit_weather_context_complete": True,
        },
    }

    return ProcessedSessionData(
        session_key=session_key,
        laps=laps,
        stints=stints,
        pit_events=pit_events,
        quality_report=quality_report,
    )


def make_writer(
    tmp_path: Path,
) -> ProcessedSessionWriter:
    """Build a writer rooted in one temporary directory."""
    return ProcessedSessionWriter(
        ProcessedDataPaths(
            tmp_path / "processed"
        )
    )


def test_writes_complete_processed_partition(
    tmp_path: Path,
) -> None:
    """Every authoritative output must be stored."""
    data = make_processed_data()
    writer = make_writer(tmp_path)

    result = writer.write(data)

    assert result.status == "written"
    assert result.directory.is_dir()

    assert {
        path.name
        for path in result.directory.iterdir()
    } == {
        "laps.parquet",
        "stints.parquet",
        "pit_events.parquet",
        "quality_report.json",
        "manifest.json",
    }

    pd.testing.assert_frame_equal(
        read_parquet_table(
            result.directory / "laps.parquet"
        ),
        data.laps,
    )
    pd.testing.assert_frame_equal(
        read_parquet_table(
            result.directory / "stints.parquet"
        ),
        data.stints,
    )
    pd.testing.assert_frame_equal(
        read_parquet_table(
            result.directory
            / "pit_events.parquet"
        ),
        data.pit_events,
    )

    assert read_json_document(
        result.directory / "quality_report.json"
    ) == data.quality_report

    assert (
        result.manifest[
            "processed_contract_version"
        ]
        == PROCESSED_CONTRACT_VERSION
    )
    assert (
        result.manifest["cleaning_rule_version"]
        == "1.0"
    )
    assert (
        result.manifest["validation"]
        == {
            "status": "passed",
            "parquet_readback": "passed",
            "quality_report_readback": "passed",
        }
    )


def test_skips_verified_completed_partition(
    tmp_path: Path,
) -> None:
    """A verified rerun must not rewrite its files."""
    data = make_processed_data()
    writer = make_writer(tmp_path)

    first = writer.write(data)
    second = writer.write(data)

    assert first.status == "written"
    assert second.status == "skipped"
    assert second.directory == first.directory
    assert second.manifest == first.manifest


def test_force_replaces_completed_partition(
    tmp_path: Path,
) -> None:
    """Force must atomically replace prior processed data."""
    writer = make_writer(tmp_path)

    first = writer.write(
        make_processed_data()
    )
    second = writer.write(
        make_processed_data(
            (
                1.0,
                2.0,
                3.0,
            )
        ),
        force=True,
    )

    assert second.status == "written"

    stored_laps = read_parquet_table(
        second.directory / "laps.parquet"
    )

    assert len(stored_laps) == 3

    first_files = first.manifest["files"]
    second_files = second.manifest["files"]

    assert isinstance(first_files, dict)
    assert isinstance(second_files, dict)

    first_laps = first_files["laps.parquet"]
    second_laps = second_files["laps.parquet"]

    assert isinstance(first_laps, dict)
    assert isinstance(second_laps, dict)

    assert (
        first_laps["sha256"]
        != second_laps["sha256"]
    )


def test_rejects_incomplete_existing_partition(
    tmp_path: Path,
) -> None:
    """An unmanifested directory must not be silently replaced."""
    data = make_processed_data()
    writer = make_writer(tmp_path)

    session_paths = (
        writer.processed_paths.for_session(
            data.session_key
        )
    )
    session_paths.directory.mkdir(
        parents=True
    )
    (
        session_paths.directory / "orphan.txt"
    ).write_text(
        "incomplete",
        encoding="utf-8",
    )

    with pytest.raises(
        IncompleteProcessedSessionError
    ):
        writer.write(data)


def test_force_replaces_incomplete_partition(
    tmp_path: Path,
) -> None:
    """Force may intentionally replace incomplete output."""
    data = make_processed_data()
    writer = make_writer(tmp_path)

    session_paths = (
        writer.processed_paths.for_session(
            data.session_key
        )
    )
    session_paths.directory.mkdir(
        parents=True
    )
    (
        session_paths.directory / "orphan.txt"
    ).write_text(
        "incomplete",
        encoding="utf-8",
    )

    result = writer.write(
        data,
        force=True,
    )

    assert result.status == "written"
    assert not (
        result.directory / "orphan.txt"
    ).exists()
    assert (
        result.directory / "manifest.json"
    ).is_file()


def test_detects_corrupted_file_before_skip(
    tmp_path: Path,
) -> None:
    """A checksum failure must prevent an unsafe skip."""
    data = make_processed_data()
    writer = make_writer(tmp_path)

    first = writer.write(data)

    laps_path = (
        first.directory / "laps.parquet"
    )

    with laps_path.open("ab") as stream:
        stream.write(b"corruption")

    with pytest.raises(
        ProcessedStorageError,
        match="checksum failed",
    ):
        writer.write(data)


def test_recovers_interrupted_backup(
    tmp_path: Path,
) -> None:
    """A lone backup must be restored before resuming."""
    data = make_processed_data()
    writer = make_writer(tmp_path)

    first = writer.write(data)

    session_paths = (
        writer.processed_paths.for_session(
            data.session_key
        )
    )
    session_paths.backup_directory.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    first.directory.rename(
        session_paths.backup_directory
    )

    assert not session_paths.directory.exists()
    assert session_paths.backup_directory.exists()

    resumed = writer.write(data)

    assert resumed.status == "skipped"
    assert session_paths.directory.exists()
    assert not (
        session_paths.backup_directory.exists()
    )


def test_removes_stale_temporary_partition(
    tmp_path: Path,
) -> None:
    """A stale temporary directory must not poison a rerun."""
    data = make_processed_data()
    writer = make_writer(tmp_path)

    session_paths = (
        writer.processed_paths.for_session(
            data.session_key
        )
    )
    session_paths.temporary_directory.mkdir(
        parents=True
    )
    stale_file = (
        session_paths.temporary_directory
        / "stale.txt"
    )
    stale_file.write_text(
        "stale",
        encoding="utf-8",
    )

    result = writer.write(data)

    assert result.status == "written"
    assert not stale_file.exists()
    assert not (
        session_paths.temporary_directory.exists()
    )


def test_rejects_wrong_cleaning_version(
    tmp_path: Path,
) -> None:
    """Reports cannot be written under another version."""
    data = make_processed_data()
    data.quality_report[
        "cleaning_rule_version"
    ] = "2.0"

    with pytest.raises(
        ProcessedStorageError,
        match="cleaning version",
    ):
        make_writer(tmp_path).write(data)


def test_rejects_wrong_reported_row_count(
    tmp_path: Path,
) -> None:
    """Reported rows must match their actual table."""
    data = make_processed_data()

    tables = data.quality_report["tables"]

    assert isinstance(tables, dict)

    tables["laps_rows"] = 999

    with pytest.raises(
        ProcessedStorageError,
        match="laps_rows",
    ):
        make_writer(tmp_path).write(data)


def test_rejects_failed_validation_report(
    tmp_path: Path,
) -> None:
    """Only validated processed sessions may be stored."""
    data = make_processed_data()

    validation = data.quality_report[
        "validation"
    ]

    assert isinstance(validation, dict)

    validation["status"] = "failed"

    with pytest.raises(
        ProcessedStorageError,
        match="has not passed",
    ):
        make_writer(tmp_path).write(data)


def test_rejects_non_boolean_force(
    tmp_path: Path,
) -> None:
    """Force must not accept truthy impostors."""
    with pytest.raises(TypeError):
        make_writer(tmp_path).write(
            make_processed_data(),
            force=1,  # type: ignore[arg-type]
        )


def test_rejects_invalid_writer_inputs(
    tmp_path: Path,
) -> None:
    """Writer configuration and data types are validated."""
    with pytest.raises(TypeError):
        ProcessedSessionWriter(
            processed_paths=tmp_path,  # type: ignore[arg-type]
        )

    writer = make_writer(tmp_path)

    with pytest.raises(TypeError):
        writer.write(
            "invalid",  # type: ignore[arg-type]
        )


def test_cleans_temporary_files_after_readback_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed verification must leave no partial partition."""
    data = make_processed_data()
    writer = make_writer(tmp_path)

    def fake_read_parquet_table(
        path: Path,
    ) -> pd.DataFrame:
        del path
        return pd.DataFrame()

    monkeypatch.setattr(
        storage_module,
        "read_parquet_table",
        fake_read_parquet_table,
    )

    with pytest.raises(
        ProcessedParquetReadbackError,
        match="shape changed",
    ):
        writer.write(data)

    session_paths = (
        writer.processed_paths.for_session(
            data.session_key
        )
    )

    assert not session_paths.directory.exists()
    assert not (
        session_paths.temporary_directory.exists()
    )