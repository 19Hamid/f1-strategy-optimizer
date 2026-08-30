"""Tests for the verified processed-data catalog."""

from pathlib import Path

import pandas as pd
import pytest

import app.cleaning.catalog as catalog_module
from app.cleaning.catalog import (
    PROCESSED_CATALOG_COLUMNS,
    ProcessedCatalogBuilder,
    ProcessedCatalogError,
)
from app.cleaning.paths import ProcessedDataPaths
from app.cleaning.processing import (
    PROCESSED_CONTRACT_VERSION,
    ProcessedSessionData,
)
from app.cleaning.storage import (
    ProcessedSessionWriter,
)
from app.pipeline.models import SessionKey
from app.pipeline.serialization import (
    read_parquet_table,
    sha256_file,
)


def make_processed_data(
    *,
    session_key: SessionKey,
    event_name: str,
    eligible_laps: int,
    excluded_laps: int,
) -> ProcessedSessionData:
    """Build one catalog-ready processed session."""
    total_laps = (
        eligible_laps + excluded_laps
    )
    lap_numbers = [
        float(number)
        for number in range(
            1,
            total_laps + 1,
        )
    ]

    laps = pd.DataFrame(
        {
            "Season": [
                session_key.season
                for _ in lap_numbers
            ],
            "RoundNumber": [
                session_key.round_number
                for _ in lap_numbers
            ],
            "SessionType": [
                session_key.session_type
                for _ in lap_numbers
            ],
            "EventName": [
                event_name
                for _ in lap_numbers
            ],
            "Driver": [
                "VER"
                for _ in lap_numbers
            ],
            "LapNumber": lap_numbers,
            "IsEligible": (
                [True] * eligible_laps
                + [False] * excluded_laps
            ),
            "QualityReasons": (
                [""] * eligible_laps
                + ["FIRST_LAP"]
                * excluded_laps
            ),
            "Rainfall": [
                False
                for _ in lap_numbers
            ],
        }
    )

    stints = pd.DataFrame(
        {
            "season": [
                session_key.season
            ],
            "round_number": [
                session_key.round_number
            ],
            "session_type": [
                session_key.session_type
            ],
            "event_name": [event_name],
            "driver": ["VER"],
            "stint_number": [1],
            "recorded_laps": [total_laps],
            "is_complete": [True],
            "warnings": [""],
        }
    )

    pit_events = pd.DataFrame(
        {
            "pit_event_id": [
                (
                    f"{session_key.identifier}"
                    "-VER-P001"
                )
            ],
            "season": [
                session_key.season
            ],
            "round_number": [
                session_key.round_number
            ],
            "session_type": [
                session_key.session_type
            ],
            "event_name": [event_name],
            "driver": ["VER"],
            "pit_in_lap": [1.0],
            "pit_out_lap": [2.0],
            "is_complete": [True],
            "entry_rainfall": [False],
            "exit_rainfall": [False],
            "is_dry_weather_pair": [True],
            "is_duration_analysis_candidate": [
                True
            ],
            "warnings": [""],
        }
    )

    quality_report: dict[str, object] = {
        "processed_contract_version": (
            PROCESSED_CONTRACT_VERSION
        ),
        "cleaning_rule_version": "1.0",
        "source_contract_version": "1.0",
        "session": {
            "identifier": (
                session_key.identifier
            ),
            "season": session_key.season,
            "round_number": (
                session_key.round_number
            ),
            "session_type": (
                session_key.session_type
            ),
            "event_name": event_name,
        },
        "tables": {
            "laps_rows": len(laps),
            "stints_rows": len(stints),
            "pit_events_rows": len(
                pit_events
            ),
        },
        "lap_quality": {
            "eligible_laps": (
                eligible_laps
            ),
            "excluded_laps": (
                excluded_laps
            ),
        },
        "stint_quality": {
            "complete_stints": 1,
            "incomplete_stints": 0,
        },
        "pit_event_quality": {
            "complete_events": 1,
            "incomplete_events": 0,
            "duration_analysis_candidates": 1,
        },
        "validation": {
            "status": "passed",
        },
    }

    return ProcessedSessionData(
        session_key=session_key,
        laps=laps,
        stints=stints,
        pit_events=pit_events,
        quality_report=quality_report,
    )


def write_development_sessions(
    *,
    processed_paths: ProcessedDataPaths,
) -> tuple[SessionKey, SessionKey]:
    """Write two valid development partitions."""
    first_key = SessionKey(2022, 1)
    second_key = SessionKey(2024, 2)

    writer = ProcessedSessionWriter(
        processed_paths
    )

    writer.write(
        make_processed_data(
            session_key=first_key,
            event_name="Bahrain Grand Prix",
            eligible_laps=8,
            excluded_laps=2,
        )
    )
    writer.write(
        make_processed_data(
            session_key=second_key,
            event_name=(
                "Saudi Arabian Grand Prix"
            ),
            eligible_laps=9,
            excluded_laps=3,
        )
    )

    return first_key, second_key


def test_builds_sorted_verified_catalog(
    tmp_path: Path,
) -> None:
    """Catalog rows must be sorted and fully described."""
    processed_paths = ProcessedDataPaths(
        tmp_path / "processed"
    )
    first_key, second_key = (
        write_development_sessions(
            processed_paths=processed_paths
        )
    )

    result = ProcessedCatalogBuilder(
        processed_paths
    ).build(
        (
            second_key,
            first_key,
        )
    )

    assert result.path == (
        processed_paths.catalog
    )
    assert result.path.is_file()
    assert result.sha256 == sha256_file(
        result.path
    )
    assert tuple(
        result.catalog.columns
    ) == PROCESSED_CATALOG_COLUMNS
    assert result.catalog[
        "session_id"
    ].tolist() == [
        "2022-01-R",
        "2024-02-R",
    ]
    assert result.catalog[
        "eligibility_rate"
    ].tolist() == pytest.approx(
        [
            0.8,
            0.75,
        ]
    )
    assert (
        result.catalog[
            "total_size_bytes"
        ]
        > 0
    ).all()
    assert (
        result.catalog[
            "duration_analysis_candidates"
        ]
        == 1
    ).all()

    stored_catalog = read_parquet_table(
        result.path
    )

    pd.testing.assert_frame_equal(
        stored_catalog,
        result.catalog,
    )


def test_repeated_build_is_deterministic(
    tmp_path: Path,
) -> None:
    """Identical verified inputs must reproduce one catalog."""
    processed_paths = ProcessedDataPaths(
        tmp_path / "processed"
    )
    session_keys = (
        write_development_sessions(
            processed_paths=processed_paths
        )
    )
    builder = ProcessedCatalogBuilder(
        processed_paths
    )

    first = builder.build(
        session_keys
    )
    second = builder.build(
        reversed(session_keys)
    )

    pd.testing.assert_frame_equal(
        first.catalog,
        second.catalog,
    )
    assert first.sha256 == second.sha256


def test_rejects_missing_partition(
    tmp_path: Path,
) -> None:
    """Every requested race must exist and pass integrity."""
    builder = ProcessedCatalogBuilder(
        ProcessedDataPaths(
            tmp_path / "processed"
        )
    )

    with pytest.raises(
        ProcessedCatalogError,
        match="MISSING_DIRECTORY",
    ):
        builder.build(
            (
                SessionKey(2024, 1),
            )
        )


def test_rejects_corrupted_partition(
    tmp_path: Path,
) -> None:
    """Catalog publication must stop on corrupted data."""
    processed_paths = ProcessedDataPaths(
        tmp_path / "processed"
    )
    first_key, second_key = (
        write_development_sessions(
            processed_paths=processed_paths
        )
    )
    session_paths = (
        processed_paths.for_session(
            second_key
        )
    )

    with session_paths.laps.open(
        "ab"
    ) as stream:
        stream.write(b"corruption")

    with pytest.raises(
        ProcessedCatalogError,
        match="CHECKSUM_MISMATCH",
    ):
        ProcessedCatalogBuilder(
            processed_paths
        ).build(
            (
                first_key,
                second_key,
            )
        )


def test_rejects_evaluation_season(
    tmp_path: Path,
) -> None:
    """The 2025 holdout cannot enter this catalog."""
    builder = ProcessedCatalogBuilder(
        ProcessedDataPaths(
            tmp_path / "processed"
        )
    )

    with pytest.raises(
        ValueError,
        match="cannot include evaluation",
    ):
        builder.build(
            (
                SessionKey(2025, 1),
            )
        )


def test_rejects_duplicate_sessions(
    tmp_path: Path,
) -> None:
    """One processed race must produce exactly one row."""
    builder = ProcessedCatalogBuilder(
        ProcessedDataPaths(
            tmp_path / "processed"
        )
    )
    session_key = SessionKey(2024, 1)

    with pytest.raises(
        ValueError,
        match="duplicate catalog sessions",
    ):
        builder.build(
            (
                session_key,
                session_key,
            )
        )


def test_rejects_empty_catalog_request(
    tmp_path: Path,
) -> None:
    """Catalog publication requires at least one race."""
    builder = ProcessedCatalogBuilder(
        ProcessedDataPaths(
            tmp_path / "processed"
        )
    )

    with pytest.raises(
        ValueError,
        match="at least one session",
    ):
        builder.build(())


@pytest.mark.parametrize(
    "session_keys",
    [
        ("2024-01-R",),
        "2024-01-R",
    ],
)
def test_rejects_invalid_session_collection(
    tmp_path: Path,
    session_keys: object,
) -> None:
    """Catalog requests must contain SessionKey models."""
    builder = ProcessedCatalogBuilder(
        ProcessedDataPaths(
            tmp_path / "processed"
        )
    )

    with pytest.raises(TypeError):
        builder.build(
            session_keys,  # type: ignore[arg-type]
        )


def test_rejects_invalid_builder_paths(
    tmp_path: Path,
) -> None:
    """Builder configuration must use ProcessedDataPaths."""
    with pytest.raises(TypeError):
        ProcessedCatalogBuilder(
            processed_paths=tmp_path,  # type: ignore[arg-type]
        )


def test_failed_readback_preserves_previous_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bad replacement must not destroy a good catalog."""
    processed_paths = ProcessedDataPaths(
        tmp_path / "processed"
    )
    session_keys = (
        write_development_sessions(
            processed_paths=processed_paths
        )
    )
    builder = ProcessedCatalogBuilder(
        processed_paths
    )

    first = builder.build(
        session_keys
    )
    original_checksum = sha256_file(
        first.path
    )

    def fake_read_parquet_table(
        path: Path,
    ) -> pd.DataFrame:
        del path
        return pd.DataFrame()

    monkeypatch.setattr(
        catalog_module,
        "read_parquet_table",
        fake_read_parquet_table,
    )

    with pytest.raises(
        ProcessedCatalogError,
        match="readback differs",
    ):
        builder.build(
            session_keys
        )

    assert processed_paths.catalog.is_file()
    assert (
        sha256_file(
            processed_paths.catalog
        )
        == original_checksum
    )
    assert not (
        processed_paths.version_root
        / ".tmp"
        / "catalog.parquet"
    ).exists()