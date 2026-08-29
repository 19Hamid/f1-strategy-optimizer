"""Tests for atomic on-demand telemetry storage."""

from pathlib import Path

import pandas as pd
import pytest

from app.pipeline.models import SessionKey
from app.pipeline.serialization import (
    read_json_document,
    read_parquet_table,
    sha256_file,
)
from app.pipeline.telemetry import (
    TelemetryDataPaths,
    TelemetryRequest,
)
from app.pipeline.telemetry_source import TelemetryLapData
from app.pipeline.telemetry_storage import (
    MANIFEST_FILENAME,
    METADATA_FILENAME,
    TELEMETRY_FILENAME,
    TelemetryStorageError,
    TelemetryWriter,
)


def make_request() -> TelemetryRequest:
    """Create a valid telemetry request."""
    return TelemetryRequest(
        session_key=SessionKey(2024, 1),
        driver="VER",
        lap_number=39,
    )


def make_telemetry(
    *,
    speed: float = 250.0,
) -> pd.DataFrame:
    """Create telemetry with FastF1-style row labels."""
    telemetry = pd.DataFrame(
        {
            "Season": [
                2024,
                2024,
            ],
            "RoundNumber": [
                1,
                1,
            ],
            "SessionType": [
                "R",
                "R",
            ],
            "EventName": [
                "Bahrain Grand Prix",
                "Bahrain Grand Prix",
            ],
            "Driver": [
                "VER",
                "VER",
            ],
            "LapNumber": [
                39,
                39,
            ],
            "Time": pd.to_timedelta(
                [
                    0.0,
                    0.1,
                ],
                unit="s",
            ),
            "Distance": [
                0.0,
                8.5,
            ],
            "Speed": [
                speed,
                speed + 5.0,
            ],
        }
    )

    telemetry.index = pd.Index(
        [
            1042,
            1043,
        ],
        name="FastF1Row",
    )

    return telemetry


def make_data(
    *,
    speed: float = 250.0,
) -> TelemetryLapData:
    """Create telemetry ready for storage."""
    request = make_request()
    telemetry = make_telemetry(
        speed=speed,
    )

    return TelemetryLapData(
        request=request,
        telemetry=telemetry,
        metadata={
            "telemetry_id": request.identifier,
            "session_id": request.session_key.identifier,
            "event_name": "Bahrain Grand Prix",
            "driver": request.driver,
            "lap_number": request.lap_number,
            "sample_count": len(telemetry),
            "telemetry_loaded": True,
            "fastf1_version": "test-version",
        },
    )


def make_writer(
    tmp_path: Path,
) -> TelemetryWriter:
    """Create a telemetry writer."""
    return TelemetryWriter(
        TelemetryDataPaths(
            raw_root=tmp_path / "raw",
        )
    )


def test_writes_complete_telemetry_partition(
    tmp_path: Path,
) -> None:
    writer = make_writer(tmp_path)
    data = make_data()

    result = writer.write(data)

    assert result.status == "written"
    assert (
        result.directory / TELEMETRY_FILENAME
    ).is_file()
    assert (
        result.directory / METADATA_FILENAME
    ).is_file()
    assert (
        result.directory / MANIFEST_FILENAME
    ).is_file()

    stored = read_parquet_table(
        result.directory / TELEMETRY_FILENAME
    )

    pd.testing.assert_frame_equal(
        stored,
        data.telemetry.reset_index(drop=True),
    )


def test_writes_authoritative_metadata(
    tmp_path: Path,
) -> None:
    result = make_writer(tmp_path).write(
        make_data()
    )

    metadata = read_json_document(
        result.directory / METADATA_FILENAME
    )

    assert metadata["contract_version"] == "1.0"
    assert (
        metadata["telemetry_id"]
        == "2024-01-R-VER-L039"
    )
    assert metadata["sample_count"] == 2
    assert metadata["storage_format"] == "parquet"
    assert metadata["compression"] == "zstd"


def test_manifest_contains_valid_file_records(
    tmp_path: Path,
) -> None:
    result = make_writer(tmp_path).write(
        make_data()
    )

    manifest = read_json_document(
        result.directory / MANIFEST_FILENAME
    )
    files = manifest["files"]

    assert isinstance(files, dict)

    for filename in (
        TELEMETRY_FILENAME,
        METADATA_FILENAME,
    ):
        record = files[filename]

        assert isinstance(record, dict)

        path = result.directory / filename

        assert (
            record["size_bytes"]
            == path.stat().st_size
        )
        assert record["sha256"] == sha256_file(path)


def test_skips_verified_existing_partition(
    tmp_path: Path,
) -> None:
    writer = make_writer(tmp_path)

    first = writer.write(
        make_data(speed=250.0)
    )
    second = writer.write(
        make_data(speed=100.0)
    )

    assert first.status == "written"
    assert second.status == "skipped"

    stored = read_parquet_table(
        second.directory / TELEMETRY_FILENAME
    )

    assert stored["Speed"].iloc[0] == 250.0


def test_force_replaces_existing_partition(
    tmp_path: Path,
) -> None:
    writer = make_writer(tmp_path)

    writer.write(
        make_data(speed=250.0)
    )
    result = writer.write(
        make_data(speed=100.0),
        force=True,
    )

    assert result.status == "written"

    stored = read_parquet_table(
        result.directory / TELEMETRY_FILENAME
    )

    assert stored["Speed"].iloc[0] == 100.0


def test_rejects_corrupted_existing_partition(
    tmp_path: Path,
) -> None:
    writer = make_writer(tmp_path)
    result = writer.write(make_data())

    telemetry_path = (
        result.directory / TELEMETRY_FILENAME
    )
    telemetry_path.write_bytes(
        b"corrupted telemetry"
    )

    with pytest.raises(
        TelemetryStorageError,
        match="incomplete or corrupted",
    ):
        writer.write(make_data())


def test_force_recovers_corrupted_partition(
    tmp_path: Path,
) -> None:
    writer = make_writer(tmp_path)
    result = writer.write(make_data())

    telemetry_path = (
        result.directory / TELEMETRY_FILENAME
    )
    telemetry_path.write_bytes(
        b"corrupted telemetry"
    )

    replacement = writer.write(
        make_data(speed=175.0),
        force=True,
    )

    stored = read_parquet_table(
        replacement.directory / TELEMETRY_FILENAME
    )

    assert replacement.status == "written"
    assert stored["Speed"].iloc[0] == 175.0


def test_cleans_temporary_directory_after_write(
    tmp_path: Path,
) -> None:
    writer = make_writer(tmp_path)

    writer.write(make_data())

    temporary_root = writer.paths.temporary_root

    assert temporary_root.is_dir()
    assert list(temporary_root.iterdir()) == []


def test_rejects_empty_telemetry(
    tmp_path: Path,
) -> None:
    request = make_request()
    data = TelemetryLapData(
        request=request,
        telemetry=pd.DataFrame(),
        metadata={},
    )

    with pytest.raises(
        TelemetryStorageError,
        match="must not be empty",
    ):
        make_writer(tmp_path).write(data)


def test_rejects_invalid_data_type(
    tmp_path: Path,
) -> None:
    with pytest.raises(TypeError):
        make_writer(tmp_path).write(  # type: ignore[arg-type]
            "telemetry"
        )