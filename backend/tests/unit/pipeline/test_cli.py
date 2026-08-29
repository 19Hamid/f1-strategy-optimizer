"""Tests for the raw pipeline command-line interface."""

from pathlib import Path

import pandas as pd
import pytest

import app.pipeline.cli as cli_module
from app.pipeline.cli import (
    build_parser,
    main,
    select_sessions,
    selected_seasons,
)
from app.pipeline.config import CORE_STUDY_SEASONS
from app.pipeline.models import SessionKey
from app.pipeline.telemetry import (
    TelemetryDataPaths,
    TelemetryRequest,
)
from app.pipeline.telemetry_source import TelemetryLapData
from app.pipeline.telemetry_storage import (
    TelemetryWriteResult,
)


def test_parser_accepts_single_race_extraction() -> None:
    namespace = build_parser().parse_args(
        [
            "extract",
            "--season",
            "2024",
            "--round",
            "2",
            "--force",
        ]
    )

    assert namespace.command == "extract"
    assert namespace.seasons == [2024]
    assert namespace.rounds == [2]
    assert namespace.force is True


def test_parser_accepts_telemetry_request() -> None:
    namespace = build_parser().parse_args(
        [
            "telemetry",
            "--season",
            "2024",
            "--round",
            "1",
            "--driver",
            "ver",
            "--lap",
            "39",
            "--force",
        ]
    )

    assert namespace.command == "telemetry"
    assert namespace.season == 2024
    assert namespace.round_number == 1
    assert namespace.driver == "ver"
    assert namespace.lap_number == 39
    assert namespace.force is True


def test_defaults_to_complete_v1_study_period() -> None:
    assert selected_seasons(None) == CORE_STUDY_SEASONS


def test_normalizes_repeated_seasons() -> None:
    assert selected_seasons(
        [2025, 2023, 2025]
    ) == (2023, 2025)


def test_filters_selected_rounds() -> None:
    discovered = (
        SessionKey(2024, 1),
        SessionKey(2024, 2),
        SessionKey(2024, 3),
    )

    selected = select_sessions(
        discovered,
        seasons=[2024],
        rounds=[3, 1],
    )

    assert selected == (
        SessionKey(2024, 1),
        SessionKey(2024, 3),
    )


def test_round_filter_requires_one_season() -> None:
    with pytest.raises(
        ValueError,
        match="requires exactly one",
    ):
        select_sessions(
            (
                SessionKey(2023, 1),
                SessionKey(2024, 1),
            ),
            seasons=[2023, 2024],
            rounds=[1],
        )


def test_rejects_unknown_round() -> None:
    with pytest.raises(
        ValueError,
        match="do not exist",
    ):
        select_sessions(
            (
                SessionKey(2024, 1),
                SessionKey(2024, 2),
            ),
            seasons=[2024],
            rounds=[99],
        )


def test_catalog_command_reports_empty_dataset(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "--raw-root",
            str(tmp_path / "raw"),
            "catalog",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Pipeline error:" in captured.err


def test_telemetry_command_extracts_and_stores_lap(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    class FakeTelemetrySource:
        """Return telemetry without contacting FastF1."""

        def __init__(
            self,
            cache_directory: Path,
        ) -> None:
            calls["cache_directory"] = cache_directory

        def extract(
            self,
            request: TelemetryRequest,
        ) -> TelemetryLapData:
            calls["request"] = request

            telemetry = pd.DataFrame(
                {
                    "Speed": [
                        250.0,
                        255.0,
                    ],
                }
            )

            return TelemetryLapData(
                request=request,
                telemetry=telemetry,
                metadata={},
            )

    class FakeTelemetryWriter:
        """Record telemetry storage requests."""

        def __init__(
            self,
            paths: TelemetryDataPaths,
        ) -> None:
            calls["raw_root"] = paths.raw_root

        def write(
            self,
            data: TelemetryLapData,
            *,
            force: bool = False,
        ) -> TelemetryWriteResult:
            calls["data"] = data
            calls["force"] = force

            return TelemetryWriteResult(
                request=data.request,
                status="written",
                directory=(
                    tmp_path
                    / "raw"
                    / "telemetry"
                    / "stored"
                ),
                manifest={},
            )

    monkeypatch.setattr(
        cli_module,
        "FastF1TelemetrySource",
        FakeTelemetrySource,
    )
    monkeypatch.setattr(
        cli_module,
        "TelemetryWriter",
        FakeTelemetryWriter,
    )

    exit_code = main(
        [
            "--raw-root",
            str(tmp_path / "raw"),
            "--cache-root",
            str(tmp_path / "cache"),
            "telemetry",
            "--season",
            "2024",
            "--round",
            "1",
            "--driver",
            "ver",
            "--lap",
            "39",
            "--force",
        ]
    )

    captured = capsys.readouterr()
    request = calls["request"]

    assert isinstance(request, TelemetryRequest)
    assert exit_code == 0
    assert request.driver == "VER"
    assert request.identifier == "2024-01-R-VER-L039"
    assert calls["cache_directory"] == (
        tmp_path / "cache"
    )
    assert calls["raw_root"] == tmp_path / "raw"
    assert calls["force"] is True
    assert "2024-01-R-VER-L039: written" in captured.out
    assert "Samples: 2" in captured.out
    assert "Path:" in captured.out
    assert captured.err == ""


def test_telemetry_command_reports_invalid_driver(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "--raw-root",
            str(tmp_path / "raw"),
            "--cache-root",
            str(tmp_path / "cache"),
            "telemetry",
            "--season",
            "2024",
            "--round",
            "1",
            "--driver",
            "MAXX",
            "--lap",
            "39",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Pipeline error:" in captured.err
    assert "three-letter" in captured.err