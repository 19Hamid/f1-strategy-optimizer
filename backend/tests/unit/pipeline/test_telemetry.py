"""Tests for on-demand telemetry models and paths."""

from pathlib import Path

import pytest

from app.pipeline.models import SessionKey
from app.pipeline.telemetry import (
    TelemetryDataPaths,
    TelemetryRequest,
)


def make_request() -> TelemetryRequest:
    """Create a valid telemetry request."""
    return TelemetryRequest(
        session_key=SessionKey(
            season=2024,
            round_number=1,
        ),
        driver="VER",
        lap_number=39,
    )


def test_normalizes_driver_abbreviation() -> None:
    request = TelemetryRequest(
        session_key=SessionKey(2024, 1),
        driver=" ver ",
        lap_number=39,
    )

    assert request.driver == "VER"


def test_builds_stable_identifier() -> None:
    request = make_request()

    assert request.identifier == "2024-01-R-VER-L039"


def test_builds_partition_parts() -> None:
    request = make_request()

    assert request.partition_parts == (
        "season=2024",
        "round=01",
        "session=R",
        "driver=VER",
        "lap=039",
    )


@pytest.mark.parametrize(
    "driver",
    [
        "",
        "VE",
        "VERX",
        "V1R",
        "VÉR",
    ],
)
def test_rejects_invalid_driver_abbreviations(
    driver: str,
) -> None:
    with pytest.raises(ValueError):
        TelemetryRequest(
            session_key=SessionKey(2024, 1),
            driver=driver,
            lap_number=39,
        )


@pytest.mark.parametrize(
    "driver",
    [
        None,
        1,
        True,
    ],
)
def test_rejects_invalid_driver_types(
    driver: object,
) -> None:
    with pytest.raises(TypeError):
        TelemetryRequest(
            session_key=SessionKey(2024, 1),
            driver=driver,  # type: ignore[arg-type]
            lap_number=39,
        )


@pytest.mark.parametrize(
    "lap_number",
    [
        0,
        201,
    ],
)
def test_rejects_laps_outside_valid_range(
    lap_number: int,
) -> None:
    with pytest.raises(ValueError):
        TelemetryRequest(
            session_key=SessionKey(2024, 1),
            driver="VER",
            lap_number=lap_number,
        )


@pytest.mark.parametrize(
    "lap_number",
    [
        1.5,
        "39",
        True,
        None,
    ],
)
def test_rejects_invalid_lap_number_types(
    lap_number: object,
) -> None:
    with pytest.raises(TypeError):
        TelemetryRequest(
            session_key=SessionKey(2024, 1),
            driver="VER",
            lap_number=lap_number,  # type: ignore[arg-type]
        )


def test_rejects_invalid_session_key_type() -> None:
    with pytest.raises(TypeError):
        TelemetryRequest(
            session_key="2024-01-R",  # type: ignore[arg-type]
            driver="VER",
            lap_number=39,
        )


def test_builds_telemetry_storage_paths(
    tmp_path: Path,
) -> None:
    request = make_request()
    paths = TelemetryDataPaths(
        raw_root=tmp_path / "raw",
    )

    expected_directory = (
        tmp_path
        / "raw"
        / "telemetry"
        / "season=2024"
        / "round=01"
        / "session=R"
        / "driver=VER"
        / "lap=039"
    )

    assert paths.directory_for(request) == expected_directory
    assert (
        paths.telemetry_file_for(request)
        == expected_directory / "telemetry.parquet"
    )
    assert (
        paths.metadata_file_for(request)
        == expected_directory / "metadata.json"
    )
    assert (
        paths.manifest_file_for(request)
        == expected_directory / "manifest.json"
    )


def test_builds_temporary_telemetry_root(
    tmp_path: Path,
) -> None:
    paths = TelemetryDataPaths(
        raw_root=tmp_path / "raw",
    )

    assert (
        paths.temporary_root
        == tmp_path / "raw" / ".tmp" / "telemetry"
    )


def test_requires_path_object_for_raw_root() -> None:
    with pytest.raises(TypeError):
        TelemetryDataPaths(
            raw_root="data/raw/fastf1",  # type: ignore[arg-type]
        )