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
from app.pipeline.telemetry import TelemetryRequest
from app.pipeline.telemetry_source import TelemetryLapData


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


def test_telemetry_cli_writes_then_skips_before_extraction(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extraction_requests: list[TelemetryRequest] = []
    cache_directories: list[Path] = []

    class FakeTelemetrySource:
        """Return telemetry without contacting FastF1."""

        def __init__(
            self,
            cache_directory: Path,
        ) -> None:
            cache_directories.append(
                cache_directory
            )

        def extract(
            self,
            request: TelemetryRequest,
        ) -> TelemetryLapData:
            extraction_requests.append(request)

            telemetry = pd.DataFrame(
                {
                    "Season": [
                        request.session_key.season,
                        request.session_key.season,
                    ],
                    "RoundNumber": [
                        request.session_key.round_number,
                        request.session_key.round_number,
                    ],
                    "SessionType": [
                        request.session_key.session_type,
                        request.session_key.session_type,
                    ],
                    "Driver": [
                        request.driver,
                        request.driver,
                    ],
                    "LapNumber": [
                        request.lap_number,
                        request.lap_number,
                    ],
                    "Speed": [
                        250.0,
                        255.0,
                    ],
                }
            )

            return TelemetryLapData(
                request=request,
                telemetry=telemetry,
                metadata={
                    "telemetry_id": request.identifier,
                    "session_id": (
                        request.session_key.identifier
                    ),
                    "sample_count": len(telemetry),
                },
            )

    monkeypatch.setattr(
        cli_module,
        "FastF1TelemetrySource",
        FakeTelemetrySource,
    )

    arguments = [
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
    ]

    first_exit_code = main(arguments)
    first_output = capsys.readouterr()

    second_exit_code = main(arguments)
    second_output = capsys.readouterr()

    assert first_exit_code == 0
    assert second_exit_code == 0
    assert len(extraction_requests) == 1
    assert extraction_requests[0].driver == "VER"
    assert (
        extraction_requests[0].identifier
        == "2024-01-R-VER-L039"
    )
    assert cache_directories == [
        tmp_path / "cache",
        tmp_path / "cache",
    ]
    assert (
        "2024-01-R-VER-L039: written"
        in first_output.out
    )
    assert "Samples: 2" in first_output.out
    assert first_output.err == ""
    assert (
        "2024-01-R-VER-L039: skipped"
        in second_output.out
    )
    assert "Samples: 2" in second_output.out
    assert second_output.err == ""


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