"""Tests for reproducible development-data exploration."""

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import app.cleaning.exploration as exploration_module
from app.cleaning.exploration import (
    EXPLORATION_VERSION,
    LAP_OUTLIER_POLICY,
    DevelopmentExplorationError,
    explore_development_data,
)
from app.cleaning.paths import ProcessedDataPaths
from app.pipeline.models import SessionKey
from app.pipeline.serialization import (
    read_parquet_table,
    write_parquet_table,
)


@pytest.fixture
def processed_paths(
    tmp_path: Path,
) -> ProcessedDataPaths:
    """Build one minimal processed development partition."""
    paths = ProcessedDataPaths(
        tmp_path / "processed"
    )
    _write_processed_fixture(paths)
    return paths


def test_explores_verified_development_data(
    processed_paths: ProcessedDataPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exploration must reconcile and summarize all tables."""
    _allow_integrity(monkeypatch)

    result = explore_development_data(
        processed_paths,
        seasons=(2024,),
    )

    assert result.seasons == (2024,)
    assert (
        result.exploration_version
        == EXPLORATION_VERSION
    )
    assert (
        result.lap_outlier_policy
        == LAP_OUTLIER_POLICY
        == "FLAG_ONLY"
    )
    assert result.session_count == 1
    assert result.processed_lap_count == 35
    assert result.eligible_lap_count == 30
    assert result.excluded_lap_count == 5
    assert result.stint_count == 5
    assert result.dry_stint_count == 5
    assert result.pit_event_count == 3
    assert (
        result.duration_analysis_candidate_count
        == 3
    )
    assert result.potential_lap_outlier_count == 5
    assert result.shared_lap_outlier_count == 5

    session = result.session_summary.iloc[0]

    assert session["session_id"] == "2024-01-R"
    assert session["input_laps"] == 35
    assert session["eligible_laps"] == 30
    assert session["excluded_laps"] == 5
    assert session["eligibility_rate"] == pytest.approx(
        30 / 35
    )
    assert session["potential_lap_outliers"] == 5

    compound_counts = dict(
        zip(
            result.compound_summary["compound"],
            result.compound_summary[
                "eligible_laps"
            ],
            strict=True,
        )
    )

    assert compound_counts == {
        "HARD": 12,
        "MEDIUM": 12,
        "SOFT": 6,
    }

    assert (
        result.stint_summary["stints"].sum()
        == 5
    )
    assert (
        result.pit_duration_summary[
            "median_seconds"
        ].iloc[0]
        == pytest.approx(25.0)
    )


def test_outliers_are_flagged_without_exclusion(
    processed_paths: ProcessedDataPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A statistical extreme must remain an eligible lap."""
    _allow_integrity(monkeypatch)

    result = explore_development_data(
        processed_paths,
        seasons=(2024,),
    )

    outliers = result.potential_lap_outliers

    assert len(outliers) == 5
    assert set(outliers["LapNumber"]) == {6.0}
    assert set(outliers["OutlierDirection"]) == {
        "SLOW"
    }
    assert outliers[
        "IsSharedLapCluster"
    ].all()
    assert set(
        outliers["SharedLapOutlierDrivers"]
    ) == {5}
    assert outliers[
        "ContextRobustScore"
    ].ge(6.0).all()

    stored_laps = read_parquet_table(
        processed_paths.for_session(
            SessionKey(2024, 1)
        ).laps
    )

    extreme_laps = stored_laps.loc[
        stored_laps["LapNumber"].eq(6.0)
    ]

    assert extreme_laps["IsEligible"].all()
    assert int(
        stored_laps["IsEligible"].sum()
    ) == 30


def test_rejects_evaluation_season(
    processed_paths: ProcessedDataPaths,
) -> None:
    """The protected 2025 holdout must be rejected."""
    with pytest.raises(
        ValueError,
        match="restricted to development seasons",
    ):
        explore_development_data(
            processed_paths,
            seasons=(2025,),
        )


def test_rejects_duplicate_season(
    processed_paths: ProcessedDataPaths,
) -> None:
    """Requested seasons must not be duplicated."""
    with pytest.raises(
        ValueError,
        match="duplicate season",
    ):
        explore_development_data(
            processed_paths,
            seasons=(
                2024,
                2024,
            ),
        )


def test_rejects_invalid_processed_paths() -> None:
    """The public function requires typed path configuration."""
    with pytest.raises(
        TypeError,
        match=(
            "processed_paths must be "
            "ProcessedDataPaths"
        ),
    ):
        explore_development_data(  # type: ignore[arg-type]
            Path("processed"),
            seasons=(2024,),
        )


def test_requires_processed_catalog(
    tmp_path: Path,
) -> None:
    """Exploration cannot guess which sessions exist."""
    paths = ProcessedDataPaths(
        tmp_path / "missing"
    )

    with pytest.raises(
        DevelopmentExplorationError,
        match="processed catalog does not exist",
    ):
        explore_development_data(
            paths,
            seasons=(2024,),
        )


def test_rejects_catalog_with_evaluation_data(
    processed_paths: ProcessedDataPaths,
) -> None:
    """A catalog containing 2025 must fail closed."""
    catalog = read_parquet_table(
        processed_paths.catalog
    )
    catalog.loc[0, "season"] = 2025
    catalog.loc[0, "session_id"] = "2025-01-R"

    write_parquet_table(
        catalog,
        processed_paths.catalog,
    )

    with pytest.raises(
        DevelopmentExplorationError,
        match="unsupported seasons",
    ):
        explore_development_data(
            processed_paths,
            seasons=(2024,),
        )


def test_rejects_failed_partition_integrity(
    processed_paths: ProcessedDataPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exploration must not consume an invalid partition."""
    issue = SimpleNamespace(
        code="CHECKSUM_MISMATCH",
        message="laps checksum differs",
    )
    report = SimpleNamespace(
        is_valid=False,
        issues=(issue,),
    )

    def fail_integrity(
        *_args: object,
        **_kwargs: object,
    ) -> SimpleNamespace:
        return report

    monkeypatch.setattr(
        exploration_module,
        "verify_processed_partition",
        fail_integrity,
    )

    with pytest.raises(
        DevelopmentExplorationError,
        match="CHECKSUM_MISMATCH",
    ):
        explore_development_data(
            processed_paths,
            seasons=(2024,),
        )


def test_rejects_missing_required_table_column(
    processed_paths: ProcessedDataPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exploration contract must reject schema loss."""
    _allow_integrity(monkeypatch)

    session_paths = processed_paths.for_session(
        SessionKey(2024, 1)
    )
    laps = read_parquet_table(
        session_paths.laps
    ).drop(
        columns=["Team"]
    )

    write_parquet_table(
        laps,
        session_paths.laps,
    )

    with pytest.raises(
        DevelopmentExplorationError,
        match="lacks required columns",
    ):
        explore_development_data(
            processed_paths,
            seasons=(2024,),
        )


def test_rejects_catalog_row_count_mismatch(
    processed_paths: ProcessedDataPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog and table row counts must reconcile."""
    _allow_integrity(monkeypatch)

    catalog = read_parquet_table(
        processed_paths.catalog
    )
    catalog.loc[0, "laps_rows"] = 36

    write_parquet_table(
        catalog,
        processed_paths.catalog,
    )

    with pytest.raises(
        DevelopmentExplorationError,
        match="laps count is 35; expected 36",
    ):
        explore_development_data(
            processed_paths,
            seasons=(2024,),
        )


def test_rejects_invalid_eligible_lap_time(
    processed_paths: ProcessedDataPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Eligible lap-time targets must remain valid."""
    _allow_integrity(monkeypatch)

    session_paths = processed_paths.for_session(
        SessionKey(2024, 1)
    )
    laps = read_parquet_table(
        session_paths.laps
    )
    laps.loc[
        laps["IsEligible"].idxmax(),
        "LapTimeSeconds",
    ] = float("nan")

    write_parquet_table(
        laps,
        session_paths.laps,
    )

    with pytest.raises(
        DevelopmentExplorationError,
        match="invalid lap times",
    ):
        explore_development_data(
            processed_paths,
            seasons=(2024,),
        )


def test_supports_no_pit_duration_candidates(
    processed_paths: ProcessedDataPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session may legitimately lack pit-duration samples."""
    _allow_integrity(monkeypatch)

    session_paths = processed_paths.for_session(
        SessionKey(2024, 1)
    )
    pit_events = read_parquet_table(
        session_paths.pit_events
    )
    pit_events[
        "is_duration_analysis_candidate"
    ] = False

    write_parquet_table(
        pit_events,
        session_paths.pit_events,
    )

    catalog = read_parquet_table(
        processed_paths.catalog
    )
    catalog.loc[
        0,
        "duration_analysis_candidates",
    ] = 0

    write_parquet_table(
        catalog,
        processed_paths.catalog,
    )

    result = explore_development_data(
        processed_paths,
        seasons=(2024,),
    )

    assert (
        result.duration_analysis_candidate_count
        == 0
    )
    assert result.pit_duration_summary.empty


def _allow_integrity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replace integrity verification with a valid report."""
    report = SimpleNamespace(
        is_valid=True,
        issues=(),
    )

    def pass_integrity(
        *_args: object,
        **_kwargs: object,
    ) -> SimpleNamespace:
        return report

    monkeypatch.setattr(
        exploration_module,
        "verify_processed_partition",
        pass_integrity,
    )


def _write_processed_fixture(
    processed_paths: ProcessedDataPaths,
) -> None:
    """Write one internally consistent processed fixture."""
    session_key = SessionKey(2024, 1)
    session_paths = processed_paths.for_session(
        session_key
    )

    lap_rows: list[dict[str, object]] = []
    lap_times = (
        90.0,
        90.5,
        91.0,
        91.5,
        92.0,
        120.0,
    )
    drivers = (
        "DRV1",
        "DRV2",
        "DRV3",
        "DRV4",
        "DRV5",
    )
    compounds = {
        "DRV1": "HARD",
        "DRV2": "HARD",
        "DRV3": "MEDIUM",
        "DRV4": "MEDIUM",
        "DRV5": "SOFT",
    }

    for driver in drivers:
        compound = compounds[driver]

        for lap_number, lap_time in enumerate(
            lap_times,
            start=1,
        ):
            lap_rows.append(
                _lap_row(
                    driver=driver,
                    compound=compound,
                    lap_number=lap_number,
                    lap_time=lap_time,
                    is_eligible=True,
                )
            )

        lap_rows.append(
            _lap_row(
                driver=driver,
                compound=compound,
                lap_number=7,
                lap_time=95.0,
                is_eligible=False,
            )
        )

    laps = pd.DataFrame(lap_rows)

    stints = pd.DataFrame(
        [
            {
                "season": 2024,
                "round_number": 1,
                "session_type": "R",
                "event_name": "Test Grand Prix",
                "driver": driver,
                "team": f"TEAM-{driver}",
                "stint_number": 1,
                "compound": compounds[driver],
                "start_lap": 1,
                "end_lap": 7,
                "recorded_laps": 7,
                "is_complete": True,
            }
            for driver in drivers
        ]
    )

    pit_events = pd.DataFrame(
        [
            {
                "season": 2024,
                "round_number": 1,
                "session_type": "R",
                "event_name": "Test Grand Prix",
                "driver": driver,
                "team": f"TEAM-{driver}",
                "compound_before": "MEDIUM",
                "compound_after": "HARD",
                "observed_pit_lane_duration_seconds": (
                    duration
                ),
                "is_duration_analysis_candidate": True,
            }
            for driver, duration in zip(
                drivers[:3],
                (
                    24.0,
                    25.0,
                    26.0,
                ),
                strict=True,
            )
        ]
    )

    write_parquet_table(
        laps,
        session_paths.laps,
    )
    write_parquet_table(
        stints,
        session_paths.stints,
    )
    write_parquet_table(
        pit_events,
        session_paths.pit_events,
    )

    catalog = pd.DataFrame(
        [
            {
                "session_id": session_key.identifier,
                "season": 2024,
                "round_number": 1,
                "session_type": "R",
                "event_name": "Test Grand Prix",
                "laps_rows": 35,
                "eligible_laps": 30,
                "excluded_laps": 5,
                "stints_rows": 5,
                "pit_events_rows": 3,
                "duration_analysis_candidates": 3,
            }
        ]
    )

    write_parquet_table(
        catalog,
        processed_paths.catalog,
    )


def _lap_row(
    *,
    driver: str,
    compound: str,
    lap_number: int,
    lap_time: float,
    is_eligible: bool,
) -> dict[str, object]:
    """Build one processed lap fixture row."""
    return {
        "Season": 2024,
        "RoundNumber": 1,
        "SessionType": "R",
        "EventName": "Test Grand Prix",
        "Driver": driver,
        "Team": f"TEAM-{driver}",
        "LapNumber": float(lap_number),
        "Compound": compound,
        "TyreLife": float(lap_number),
        "LapTimeSeconds": lap_time,
        "TrackStatus": "1",
        "Rainfall": False,
        "WeatherAgeSeconds": 30.0,
        "FastF1Generated": False,
        "IsEligible": is_eligible,
    }