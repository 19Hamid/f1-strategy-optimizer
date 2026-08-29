"""Discover Formula 1 race sessions from FastF1 schedules."""

from numbers import Integral
from typing import Protocol

import fastf1
import pandas as pd

from app.pipeline.config import ExtractionPlan
from app.pipeline.models import SessionKey


class ScheduleLoader(Protocol):
    """Describe a function capable of loading an event schedule."""

    def __call__(
        self,
        year: int,
        *,
        include_testing: bool,
    ) -> pd.DataFrame:
        """Load the event schedule for one season."""


def load_fastf1_schedule(
    year: int,
    *,
    include_testing: bool,
) -> pd.DataFrame:
    """Load one season schedule using FastF1."""
    return fastf1.get_event_schedule(
        year,
        include_testing=include_testing,
    )


def extract_round_numbers(
    schedule: pd.DataFrame,
) -> tuple[int, ...]:
    """Extract and validate championship round numbers."""
    if "RoundNumber" not in schedule.columns:
        raise ValueError(
            "event schedule is missing the RoundNumber column"
        )

    if schedule.empty:
        raise ValueError("event schedule does not contain any races")

    round_numbers: list[int] = []

    for value in schedule["RoundNumber"]:
        if isinstance(value, bool) or not isinstance(value, Integral):
            raise TypeError(
                "every schedule round number must be an integer"
            )

        round_numbers.append(int(value))

    if len(set(round_numbers)) != len(round_numbers):
        raise ValueError(
            "event schedule contains duplicate round numbers"
        )

    return tuple(sorted(round_numbers))


def discover_session_keys(
    plan: ExtractionPlan,
    schedule_loader: ScheduleLoader | None = None,
) -> tuple[SessionKey, ...]:
    """Discover all race sessions selected by an extraction plan."""
    loader = schedule_loader or load_fastf1_schedule
    session_keys: list[SessionKey] = []

    for season in plan.seasons:
        schedule = loader(
            season,
            include_testing=False,
        )

        for round_number in extract_round_numbers(schedule):
            session_keys.append(
                SessionKey(
                    season=season,
                    round_number=round_number,
                    session_type=plan.session_type,
                )
            )

    return tuple(session_keys)