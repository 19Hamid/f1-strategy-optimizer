"""Tests for historical-data extraction configuration."""

import pytest

from app.pipeline.config import (
    CORE_STUDY_SEASONS,
    DEVELOPMENT_SEASONS,
    EVALUATION_SEASONS,
    ExtractionPlan,
)


def test_default_plan_covers_complete_v1_study() -> None:
    plan = ExtractionPlan()

    assert plan.seasons == (2022, 2023, 2024, 2025)
    assert plan.session_type == "R"
    assert plan.include_telemetry is False
    assert plan.is_core_study is True


def test_development_and_evaluation_seasons_are_separate() -> None:
    assert DEVELOPMENT_SEASONS == (2022, 2023, 2024)
    assert EVALUATION_SEASONS == (2025,)
    assert CORE_STUDY_SEASONS == (
        *DEVELOPMENT_SEASONS,
        *EVALUATION_SEASONS,
    )


def test_accepts_a_subset_of_v1_seasons() -> None:
    plan = ExtractionPlan(
        seasons=(2025, 2023),
    )

    assert plan.seasons == (2023, 2025)
    assert plan.is_core_study is False


def test_normalizes_session_type() -> None:
    plan = ExtractionPlan(
        seasons=(2024,),
        session_type=" r ",
    )

    assert plan.session_type == "R"


def test_can_enable_optional_telemetry() -> None:
    plan = ExtractionPlan(
        seasons=(2024,),
        include_telemetry=True,
    )

    assert plan.include_telemetry is True


@pytest.mark.parametrize(
    "seasons",
    [
        (),
        (2021,),
        (2026,),
        (2022, 2022),
    ],
)
def test_rejects_invalid_season_selections(
    seasons: tuple[int, ...],
) -> None:
    with pytest.raises(ValueError):
        ExtractionPlan(seasons=seasons)


@pytest.mark.parametrize(
    "seasons",
    [
        [2022, 2023],
        ("2024",),
        (True,),
    ],
)
def test_rejects_invalid_season_types(
    seasons: object,
) -> None:
    with pytest.raises(TypeError):
        ExtractionPlan(seasons=seasons)  # type: ignore[arg-type]


def test_rejects_non_boolean_telemetry_setting() -> None:
    with pytest.raises(TypeError):
        ExtractionPlan(
            seasons=(2024,),
            include_telemetry="yes",  # type: ignore[arg-type]
        )