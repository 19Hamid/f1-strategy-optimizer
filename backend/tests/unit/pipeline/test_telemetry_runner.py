"""Tests for incremental telemetry pipeline execution."""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

from app.pipeline.models import SessionKey
from app.pipeline.serialization import read_parquet_table
from app.pipeline.telemetry import (
    TelemetryDataPaths,
    TelemetryRequest,
)
from app.pipeline.telemetry_runner import (
    TelemetryPipelineRunner,
)
from app.pipeline.telemetry_source import TelemetryLapData
from app.pipeline.telemetry_storage import (
    TELEMETRY_FILENAME,
    TelemetryStorageError,
    TelemetryWriter,
)


@dataclass(slots=True)
class FakeTelemetrySource:
    """Return configured telemetry and count extractions."""

    data: TelemetryLapData
    extraction_count: int = 0

    def extract(
        self,
        request: TelemetryRequest,
    ) -> TelemetryLapData:
        """Return the configured telemetry."""
        self.extraction_count += 1

        if request != self.data.request:
            raise ValueError("unexpected telemetry request")

        return self.data


def make_request() -> TelemetryRequest:
    """Create a valid telemetry request."""
    return TelemetryRequest(
        session_key=SessionKey(2024, 1),
        driver="VER",
        lap_number=39,
    )


def make_data(
    *,
    speed: float = 250.0,
) -> TelemetryLapData:
    """Create representative telemetry."""
    request = make_request()
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
            "Speed": [
                speed,
                speed + 5.0,
            ],
        }
    )

    return TelemetryLapData(
        request=request,
        telemetry=telemetry,
        metadata={
            "telemetry_id": request.identifier,
            "session_id": request.session_key.identifier,
            "event_name": "Bahrain Grand Prix",
            "sample_count": len(telemetry),
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


def test_extracts_and_writes_missing_telemetry(
    tmp_path: Path,
) -> None:
    source = FakeTelemetrySource(
        make_data()
    )
    writer = make_writer(tmp_path)
    runner = TelemetryPipelineRunner(
        source=source,
        writer=writer,
    )

    result = runner.run(make_request())

    assert result.status == "written"
    assert source.extraction_count == 1
    assert (
        result.directory / TELEMETRY_FILENAME
    ).is_file()


def test_skips_before_calling_source(
    tmp_path: Path,
) -> None:
    data = make_data()
    writer = make_writer(tmp_path)
    writer.write(data)

    source = FakeTelemetrySource(data)
    runner = TelemetryPipelineRunner(
        source=source,
        writer=writer,
    )

    result = runner.run(make_request())

    assert result.status == "skipped"
    assert source.extraction_count == 0


def test_force_extracts_and_replaces_telemetry(
    tmp_path: Path,
) -> None:
    writer = make_writer(tmp_path)
    writer.write(
        make_data(speed=250.0)
    )

    source = FakeTelemetrySource(
        make_data(speed=100.0)
    )
    runner = TelemetryPipelineRunner(
        source=source,
        writer=writer,
    )

    result = runner.run(
        make_request(),
        force=True,
    )

    stored = read_parquet_table(
        result.directory / TELEMETRY_FILENAME
    )

    assert result.status == "written"
    assert source.extraction_count == 1
    assert stored["Speed"].iloc[0] == 100.0


def test_corruption_fails_before_calling_source(
    tmp_path: Path,
) -> None:
    data = make_data()
    writer = make_writer(tmp_path)
    written = writer.write(data)

    telemetry_path = (
        written.directory / TELEMETRY_FILENAME
    )
    telemetry_path.write_bytes(
        b"corrupted telemetry"
    )

    source = FakeTelemetrySource(data)
    runner = TelemetryPipelineRunner(
        source=source,
        writer=writer,
    )

    with pytest.raises(
        TelemetryStorageError,
        match="incomplete or corrupted",
    ):
        runner.run(make_request())

    assert source.extraction_count == 0


def test_force_recovers_corruption(
    tmp_path: Path,
) -> None:
    writer = make_writer(tmp_path)
    written = writer.write(
        make_data(speed=250.0)
    )

    telemetry_path = (
        written.directory / TELEMETRY_FILENAME
    )
    telemetry_path.write_bytes(
        b"corrupted telemetry"
    )

    source = FakeTelemetrySource(
        make_data(speed=175.0)
    )
    runner = TelemetryPipelineRunner(
        source=source,
        writer=writer,
    )

    result = runner.run(
        make_request(),
        force=True,
    )

    stored = read_parquet_table(
        result.directory / TELEMETRY_FILENAME
    )

    assert result.status == "written"
    assert source.extraction_count == 1
    assert stored["Speed"].iloc[0] == 175.0


def test_rejects_invalid_request_type(
    tmp_path: Path,
) -> None:
    data = make_data()
    runner = TelemetryPipelineRunner(
        source=FakeTelemetrySource(data),
        writer=make_writer(tmp_path),
    )

    with pytest.raises(TypeError):
        runner.run(  # type: ignore[arg-type]
            "2024-01-R-VER-L039"
        )


def test_rejects_invalid_force_type(
    tmp_path: Path,
) -> None:
    data = make_data()
    runner = TelemetryPipelineRunner(
        source=FakeTelemetrySource(data),
        writer=make_writer(tmp_path),
    )

    with pytest.raises(TypeError):
        runner.run(
            make_request(),
            force="yes",  # type: ignore[arg-type]
        )