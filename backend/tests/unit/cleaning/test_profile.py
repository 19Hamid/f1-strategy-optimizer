from pathlib import Path

import pandas as pd
import pytest

from app.cleaning import (
    DataProfileError,
    profile_development_data,
)
from app.pipeline.models import SessionKey
from app.pipeline.serialization import write_parquet_table


def _make_laps(session_key: SessionKey) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Season": [
                session_key.season,
                session_key.season,
            ],
            "RoundNumber": [
                session_key.round_number,
                session_key.round_number,
            ],
            "SessionType": [
                session_key.session_type,
                session_key.session_type,
            ],
            "Driver": ["VER", "VER"],
            "Team": ["Red Bull Racing", "Red Bull Racing"],
            "LapNumber": [1.0, 2.0],
            "LapTime": pd.to_timedelta(
                [90.0, None],
                unit="s",
            ),
            "Stint": [1.0, 1.0],
            "Compound": ["SOFT", "INTERMEDIATE"],
            "TyreLife": [1.0, None],
            "TrackStatus": ["1", "4"],
            "LapStartTime": pd.to_timedelta(
                [0.0, 90.0],
                unit="s",
            ),
            "IsAccurate": [True, False],
            "Sector1Time": pd.to_timedelta(
                [30.0, None],
                unit="s",
            ),
            "Sector2Time": pd.to_timedelta(
                [30.0, 31.0],
                unit="s",
            ),
            "Sector3Time": pd.to_timedelta(
                [30.0, 32.0],
                unit="s",
            ),
            "PitInTime": pd.to_timedelta(
                [None, 180.0],
                unit="s",
            ),
            "PitOutTime": pd.to_timedelta(
                [None, None],
                unit="s",
            ),
            "Deleted": [False, False],
            "FastF1Generated": [False, True],
            "IsPersonalBest": [True, None],
        }
    )


def _make_weather() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Rainfall": [False, True],
        }
    )


def _make_results() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Status": ["Finished", "Retired"],
        }
    )


def _write_catalog(
    raw_root: Path,
    session_keys: tuple[SessionKey, ...],
) -> None:
    catalog = pd.DataFrame(
        {
            "session_id": [
                session_key.identifier
                for session_key in session_keys
            ],
            "season": [
                session_key.season
                for session_key in session_keys
            ],
            "round_number": [
                session_key.round_number
                for session_key in session_keys
            ],
            "session_type": [
                session_key.session_type
                for session_key in session_keys
            ],
        }
    )

    write_parquet_table(
        catalog,
        raw_root / "catalog.parquet",
    )


def _write_session(
    raw_root: Path,
    session_key: SessionKey,
    *,
    laps: pd.DataFrame | None = None,
) -> None:
    session_directory = raw_root.joinpath(
        *session_key.partition_parts
    )

    write_parquet_table(
        _make_laps(session_key) if laps is None else laps,
        session_directory / "laps.parquet",
    )
    write_parquet_table(
        _make_weather(),
        session_directory / "weather.parquet",
    )
    write_parquet_table(
        _make_results(),
        session_directory / "results.parquet",
    )


def test_profiles_development_data(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    session_key = SessionKey(2022, 1)

    _write_catalog(raw_root, (session_key,))
    _write_session(raw_root, session_key)

    profile = profile_development_data(
        raw_root,
        seasons=(2022,),
    )

    assert profile.session_count == 1
    assert profile.seasons == (2022,)
    assert profile.row_counts == {
        "laps": 2,
        "weather": 2,
        "results": 2,
    }
    assert profile.quality_counts["duplicate_laps"] == 0
    assert profile.quality_counts["missing_lap_times"] == 1
    assert profile.quality_counts["inaccurate_laps"] == 1
    assert profile.quality_counts["first_laps"] == 1
    assert profile.quality_counts["pit_in_laps"] == 1
    assert profile.quality_counts["pit_out_laps"] == 0
    assert profile.quality_counts["missing_sector_laps"] == 1
    assert profile.quality_counts["generated_laps"] == 1
    assert profile.missing_required_lap_values["LapTime"] == 1
    assert profile.missing_required_lap_values["TyreLife"] == 1
    assert profile.track_status_counts == {
        "1": 1,
        "4": 1,
    }
    assert profile.compound_counts == {
        "INTERMEDIATE": 1,
        "SOFT": 1,
    }
    assert profile.rainy_sessions == ("2022-01-R",)
    assert profile.wet_compound_sessions == ("2022-01-R",)
    assert profile.sessions_with_duplicate_laps == {}
    assert profile.sessions_with_missing_lap_times == {
        "2022-01-R": 1,
    }
    assert profile.result_status_counts == {
        "Finished": 1,
        "Retired": 1,
    }

    repeated_profile = profile_development_data(
        raw_root,
        seasons=(2022,),
    )

    assert repeated_profile == profile


def test_detects_duplicate_lap_identities(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    session_key = SessionKey(2023, 1)
    duplicate_laps = (
        _make_laps(session_key)
        .iloc[[0, 0]]
        .reset_index(drop=True)
    )

    _write_catalog(raw_root, (session_key,))
    _write_session(
        raw_root,
        session_key,
        laps=duplicate_laps,
    )

    profile = profile_development_data(
        raw_root,
        seasons=(2023,),
    )

    assert profile.quality_counts["duplicate_laps"] == 2
    assert profile.sessions_with_duplicate_laps == {
        "2023-01-R": 2,
    }


def test_rejects_evaluation_season(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="restricted to development seasons",
    ):
        profile_development_data(
            tmp_path,
            seasons=(2025,),
        )


def test_rejects_duplicate_season_selection(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="must not contain duplicates",
    ):
        profile_development_data(
            tmp_path,
            seasons=(2022, 2022),
        )


def test_reports_missing_required_lap_column(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    session_key = SessionKey(2024, 1)
    incomplete_laps = _make_laps(session_key).drop(
        columns="TrackStatus"
    )

    _write_catalog(raw_root, (session_key,))
    _write_session(
        raw_root,
        session_key,
        laps=incomplete_laps,
    )

    with pytest.raises(
        DataProfileError,
        match=(
            "laps table is missing required columns: "
            "TrackStatus"
        ),
    ):
        profile_development_data(
            raw_root,
            seasons=(2024,),
        )