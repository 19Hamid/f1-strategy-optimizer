"""Tests for pipeline configuration models."""

import pytest

from app.pipeline.models import SessionKey


def test_session_key_builds_stable_identity() -> None:
    session = SessionKey(
        season=2024,
        round_number=1,
        session_type="R",
    )

    assert session.identifier == "2024-01-R"
    assert session.partition_parts == (
        "season=2024",
        "round=01",
        "session=R",
    )


def test_session_key_normalizes_session_type() -> None:
    session = SessionKey(
        season=2024,
        round_number=1,
        session_type=" r ",
    )

    assert session.session_type == "R"


@pytest.mark.parametrize(
    ("season", "round_number"),
    [
        (2017, 1),
        (2024, 0),
        (2024, 31),
    ],
)
def test_session_key_rejects_out_of_range_values(
    season: int,
    round_number: int,
) -> None:
    with pytest.raises(ValueError):
        SessionKey(
            season=season,
            round_number=round_number,
        )


def test_session_key_rejects_unsupported_session_type() -> None:
    with pytest.raises(ValueError, match="unsupported session_type"):
        SessionKey(
            season=2024,
            round_number=1,
            session_type="Q",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("season", "2024"),
        ("round_number", "1"),
        ("session_type", 1),
    ],
)
def test_session_key_rejects_invalid_types(
    field: str,
    value: object,
) -> None:
    values = {
        "season": 2024,
        "round_number": 1,
        "session_type": "R",
    }
    values[field] = value

    with pytest.raises(TypeError):
        SessionKey(**values)