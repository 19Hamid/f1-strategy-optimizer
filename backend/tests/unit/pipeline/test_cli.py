"""Tests for the raw pipeline command-line interface."""

from pathlib import Path

import pytest

from app.pipeline.cli import (
    build_parser,
    main,
    select_sessions,
    selected_seasons,
)
from app.pipeline.config import CORE_STUDY_SEASONS
from app.pipeline.models import SessionKey


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
    assert "no completed session manifests" in captured.err