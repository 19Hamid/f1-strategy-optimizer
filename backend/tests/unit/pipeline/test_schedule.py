"""Tests for Formula 1 race-schedule discovery."""

import pandas as pd
import pytest

from app.pipeline.config import ExtractionPlan
from app.pipeline.models import SessionKey
from app.pipeline.schedule import (
    discover_session_keys,
    extract_round_numbers,
)


def test_extracts_sorted_round_numbers() -> None:
    schedule = pd.DataFrame(
        {
            "RoundNumber": [3, 1, 2],
            "EventName": [
                "Australian Grand Prix",
                "Bahrain Grand Prix",
                "Saudi Arabian Grand Prix",
            ],
        }
    )

    assert extract_round_numbers(schedule) == (1, 2, 3)


def test_discovers_sessions_for_multiple_seasons() -> None:
    schedules = {
        2023: pd.DataFrame({"RoundNumber": [1, 2]}),
        2024: pd.DataFrame({"RoundNumber": [1, 2, 3]}),
    }
    calls: list[tuple[int, bool]] = []

    def fake_loader(
        year: int,
        *,
        include_testing: bool,
    ) -> pd.DataFrame:
        calls.append((year, include_testing))
        return schedules[year]

    plan = ExtractionPlan(seasons=(2024, 2023))
    sessions = discover_session_keys(
        plan,
        schedule_loader=fake_loader,
    )

    assert sessions == (
        SessionKey(2023, 1),
        SessionKey(2023, 2),
        SessionKey(2024, 1),
        SessionKey(2024, 2),
        SessionKey(2024, 3),
    )
    assert calls == [
        (2023, False),
        (2024, False),
    ]


def test_rejects_schedule_without_round_number() -> None:
    schedule = pd.DataFrame(
        {
            "EventName": ["Bahrain Grand Prix"],
        }
    )

    with pytest.raises(
        ValueError,
        match="missing the RoundNumber column",
    ):
        extract_round_numbers(schedule)


def test_rejects_empty_schedule() -> None:
    schedule = pd.DataFrame(
        {
            "RoundNumber": pd.Series(dtype="int64"),
        }
    )

    with pytest.raises(
        ValueError,
        match="does not contain any races",
    ):
        extract_round_numbers(schedule)


def test_rejects_duplicate_round_numbers() -> None:
    schedule = pd.DataFrame(
        {
            "RoundNumber": [1, 1],
        }
    )

    with pytest.raises(
        ValueError,
        match="duplicate round numbers",
    ):
        extract_round_numbers(schedule)


@pytest.mark.parametrize(
    "round_number",
    [
        0,
        31,
    ],
)
def test_rejects_round_numbers_outside_valid_range(
    round_number: int,
) -> None:
    schedule = pd.DataFrame(
        {
            "RoundNumber": [round_number],
        }
    )

    plan = ExtractionPlan(seasons=(2024,))

    def fake_loader(
        year: int,
        *,
        include_testing: bool,
    ) -> pd.DataFrame:
        del year, include_testing
        return schedule

    with pytest.raises(ValueError):
        discover_session_keys(
            plan,
            schedule_loader=fake_loader,
        )


@pytest.mark.parametrize(
    "round_number",
    [
        1.5,
        "1",
        True,
        None,
    ],
)
def test_rejects_invalid_round_number_types(
    round_number: object,
) -> None:
    schedule = pd.DataFrame(
        {
            "RoundNumber": [round_number],
        }
    )

    plan = ExtractionPlan(seasons=(2024,))

    def fake_loader(
        year: int,
        *,
        include_testing: bool,
    ) -> pd.DataFrame:
        del year, include_testing
        return schedule

    with pytest.raises(TypeError):
        discover_session_keys(
            plan,
            schedule_loader=fake_loader,
        )