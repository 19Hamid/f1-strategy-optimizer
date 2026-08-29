"""Tests for the on-demand FastF1 telemetry source."""

from collections.abc import Callable
from pathlib import Path
from typing import Self

import pandas as pd
import pytest

from app.pipeline.models import SessionKey
from app.pipeline.telemetry import TelemetryRequest
from app.pipeline.telemetry_source import (
    TELEMETRY_PROVENANCE_COLUMNS,
    FastF1TelemetrySource,
    TelemetryExtractionError,
)


class FakeTelemetryLap:
    """Provide telemetry for a fake selected lap."""

    def __init__(
        self,
        telemetry: pd.DataFrame,
    ) -> None:
        self.telemetry = telemetry

    def get_telemetry(self) -> pd.DataFrame:
        """Return the configured telemetry."""
        return self.telemetry


class FakeLapIndexer:
    """Provide positional access to a fake lap."""

    def __init__(
        self,
        lap: FakeTelemetryLap,
    ) -> None:
        self.lap = lap

    def __getitem__(
        self,
        index: int,
    ) -> FakeTelemetryLap:
        """Return the single fake lap."""
        if index != 0:
            raise IndexError(index)

        return self.lap


class FakeLapCollection:
    """Record FastF1-style lap selections."""

    def __init__(
        self,
        lap: FakeTelemetryLap,
        *,
        selected_count: int = 1,
    ) -> None:
        self.iloc = FakeLapIndexer(lap)
        self.selected_count = selected_count
        self.selected_driver: str | None = None
        self.selected_lap_number: int | None = None

    def pick_drivers(
        self,
        drivers: str,
    ) -> Self:
        """Record the selected driver."""
        self.selected_driver = drivers
        return self

    def pick_laps(
        self,
        laps: int,
    ) -> Self:
        """Record the selected lap number."""
        self.selected_lap_number = laps
        return self

    def __len__(self) -> int:
        """Return the configured selection size."""
        return self.selected_count


class FakeRaceSession:
    """Provide the session behaviour required by the source."""

    def __init__(
        self,
        laps: FakeLapCollection,
    ) -> None:
        self.event: dict[str, object] = {
            "EventName": "Bahrain Grand Prix",
        }
        self.laps = laps
        self.load_calls: list[dict[str, bool]] = []

    def load(
        self,
        *,
        laps: bool,
        telemetry: bool,
        weather: bool,
        messages: bool,
    ) -> None:
        """Record the session loading options."""
        self.load_calls.append(
            {
                "laps": laps,
                "telemetry": telemetry,
                "weather": weather,
                "messages": messages,
            }
        )


def make_telemetry() -> pd.DataFrame:
    """Create representative FastF1 telemetry."""
    return pd.DataFrame(
        {
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
            "RPM": [
                5000.0,
                5500.0,
            ],
            "Speed": [
                80.0,
                90.0,
            ],
            "nGear": [
                2,
                3,
            ],
            "Throttle": [
                30.0,
                45.0,
            ],
            "Brake": [
                False,
                False,
            ],
            "DRS": [
                0,
                0,
            ],
            "X": [
                100.0,
                105.0,
            ],
            "Y": [
                200.0,
                205.0,
            ],
            "Z": [
                0.0,
                0.0,
            ],
        }
    )


def make_request() -> TelemetryRequest:
    """Create a valid telemetry request."""
    return TelemetryRequest(
        session_key=SessionKey(2024, 1),
        driver="VER",
        lap_number=39,
    )


def make_source(
    tmp_path: Path,
    session: FakeRaceSession,
    calls: list[tuple[int, int, str]],
) -> FastF1TelemetrySource:
    """Create a source backed by a fake session loader."""

    def fake_loader(
        season: int,
        round_number: int,
        session_type: str,
    ) -> FakeRaceSession:
        calls.append(
            (
                season,
                round_number,
                session_type,
            )
        )
        return session

    loader: Callable[
        [int, int, str],
        FakeRaceSession,
    ] = fake_loader

    return FastF1TelemetrySource(
        cache_directory=tmp_path / "cache",
        session_loader=loader,
    )


def test_extracts_requested_lap_telemetry(
    tmp_path: Path,
) -> None:
    original = make_telemetry()
    fake_laps = FakeLapCollection(
        FakeTelemetryLap(original),
    )
    fake_session = FakeRaceSession(fake_laps)
    loader_calls: list[tuple[int, int, str]] = []

    source = make_source(
        tmp_path,
        fake_session,
        loader_calls,
    )

    result = source.extract(make_request())

    assert loader_calls == [
        (
            2024,
            1,
            "R",
        )
    ]
    assert fake_session.load_calls == [
        {
            "laps": True,
            "telemetry": True,
            "weather": False,
            "messages": False,
        }
    ]
    assert fake_laps.selected_driver == "VER"
    assert fake_laps.selected_lap_number == 39
    assert len(result.telemetry) == 2


def test_adds_telemetry_provenance(
    tmp_path: Path,
) -> None:
    original = make_telemetry()
    fake_session = FakeRaceSession(
        FakeLapCollection(
            FakeTelemetryLap(original),
        )
    )
    source = make_source(
        tmp_path,
        fake_session,
        [],
    )

    result = source.extract(make_request())

    assert tuple(
        result.telemetry.columns[
            : len(TELEMETRY_PROVENANCE_COLUMNS)
        ]
    ) == TELEMETRY_PROVENANCE_COLUMNS

    assert result.telemetry["Season"].tolist() == [
        2024,
        2024,
    ]
    assert result.telemetry["Driver"].tolist() == [
        "VER",
        "VER",
    ]
    assert result.telemetry["LapNumber"].tolist() == [
        39,
        39,
    ]


def test_builds_telemetry_metadata(
    tmp_path: Path,
) -> None:
    fake_session = FakeRaceSession(
        FakeLapCollection(
            FakeTelemetryLap(make_telemetry()),
        )
    )
    source = make_source(
        tmp_path,
        fake_session,
        [],
    )

    result = source.extract(make_request())

    assert result.metadata["session_id"] == "2024-01-R"
    assert (
        result.metadata["telemetry_id"]
        == "2024-01-R-VER-L039"
    )
    assert (
        result.metadata["event_name"]
        == "Bahrain Grand Prix"
    )
    assert result.metadata["driver"] == "VER"
    assert result.metadata["lap_number"] == 39
    assert result.metadata["sample_count"] == 2
    assert result.metadata["telemetry_loaded"] is True


def test_does_not_modify_source_dataframe(
    tmp_path: Path,
) -> None:
    original = make_telemetry()
    expected = original.copy(deep=True)

    fake_session = FakeRaceSession(
        FakeLapCollection(
            FakeTelemetryLap(original),
        )
    )
    source = make_source(
        tmp_path,
        fake_session,
        [],
    )

    source.extract(make_request())

    pd.testing.assert_frame_equal(
        original,
        expected,
    )


@pytest.mark.parametrize(
    "selected_count",
    [
        0,
        2,
    ],
)
def test_rejects_invalid_selection_count(
    tmp_path: Path,
    selected_count: int,
) -> None:
    fake_session = FakeRaceSession(
        FakeLapCollection(
            FakeTelemetryLap(make_telemetry()),
            selected_count=selected_count,
        )
    )
    source = make_source(
        tmp_path,
        fake_session,
        [],
    )

    with pytest.raises(
        TelemetryExtractionError,
    ):
        source.extract(make_request())


def test_rejects_empty_telemetry(
    tmp_path: Path,
) -> None:
    fake_session = FakeRaceSession(
        FakeLapCollection(
            FakeTelemetryLap(pd.DataFrame()),
        )
    )
    source = make_source(
        tmp_path,
        fake_session,
        [],
    )

    with pytest.raises(
        TelemetryExtractionError,
        match="empty telemetry",
    ):
        source.extract(make_request())


def test_rejects_missing_required_columns(
    tmp_path: Path,
) -> None:
    telemetry = make_telemetry().drop(
        columns=["Speed"],
    )
    fake_session = FakeRaceSession(
        FakeLapCollection(
            FakeTelemetryLap(telemetry),
        )
    )
    source = make_source(
        tmp_path,
        fake_session,
        [],
    )

    with pytest.raises(
        TelemetryExtractionError,
        match="Speed",
    ):
        source.extract(make_request())


def test_creates_cache_directory(
    tmp_path: Path,
) -> None:
    cache_directory = tmp_path / "missing-cache"
    fake_session = FakeRaceSession(
        FakeLapCollection(
            FakeTelemetryLap(make_telemetry()),
        )
    )

    FastF1TelemetrySource(
        cache_directory=cache_directory,
        session_loader=lambda *_: fake_session,
    )

    assert cache_directory.is_dir()


def test_rejects_invalid_request_type(
    tmp_path: Path,
) -> None:
    fake_session = FakeRaceSession(
        FakeLapCollection(
            FakeTelemetryLap(make_telemetry()),
        )
    )
    source = make_source(
        tmp_path,
        fake_session,
        [],
    )

    with pytest.raises(TypeError):
        source.extract(  # type: ignore[arg-type]
            "2024-01-R-VER-L039"
        )