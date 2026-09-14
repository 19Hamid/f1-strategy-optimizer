"""Tests for atomic modelling-dataset session storage."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

import app.datasets.storage as storage_module
from app.datasets.contracts import (
    DATASET_CONTRACT_VERSION,
    SOURCE_CLEANING_RULE_VERSION,
    SOURCE_PROCESSED_CONTRACT_VERSION,
)
from app.datasets.decisions import (
    DecisionSessionData,
    build_session_decisions,
)
from app.datasets.normalization import (
    NormalizedProcessedSession,
)
from app.datasets.paths import DatasetPaths
from app.datasets.pit_durations import (
    PitDurationSessionData,
    build_pit_duration_observations,
)
from app.datasets.storage import (
    EXPECTED_SESSION_FILES,
    DatasetSessionData,
    DatasetSessionWriter,
    DatasetStorageError,
    IncompleteDatasetSessionError,
    ProcessedSourceReference,
    build_dataset_quality_report,
)
from app.pipeline import SessionKey
from app.pipeline.serialization import (
    read_json_document,
    read_parquet_table,
    sha256_file,
)

DIGESTS = {
    "manifest_sha256": "a" * 64,
    "laps_sha256": "b" * 64,
    "stints_sha256": "c" * 64,
    "pit_events_sha256": "d" * 64,
}


def _pit_events() -> pd.DataFrame:
    """Return one complete normalized pit event."""
    table = pd.DataFrame(
        {
            "pit_event_id": ["2024-01-R-VER-005-006"],
            "season": [2024],
            "round_number": [1],
            "session_type": ["R"],
            "event_name": ["Bahrain Grand Prix"],
            "driver": ["VER"],
            "team": ["Red Bull Racing"],
            "event_type": ["MATCHED"],
            "pit_in_lap": [5],
            "pit_out_lap": [6],
            "stint_before": [1],
            "stint_after": [2],
            "compound_before": ["MEDIUM"],
            "compound_after": ["HARD"],
            "tyre_life_before": [5.0],
            "tyre_life_after": [1.0],
            "pit_in_time_seconds": [390.0],
            "pit_out_time_seconds": [413.5],
            "observed_pit_lane_duration_seconds": [23.5],
            "entry_track_status": ["1"],
            "exit_track_status": ["1"],
            "is_stint_change": [True],
            "is_compound_change": [True],
            "is_green_flag_pair": [True],
            "is_dry_compound_pair": [True],
            "is_interrupted_duration": [False],
            "is_complete": [True],
            "is_duration_analysis_candidate": [True],
            "warning_count": [0],
            "warnings": [""],
            "entry_rainfall": [False],
            "exit_rainfall": [False],
            "is_dry_weather_pair": [True],
        }
    )

    for column in (
        "pit_event_id",
        "session_type",
        "event_name",
        "driver",
        "team",
        "event_type",
        "compound_before",
        "compound_after",
        "entry_track_status",
        "exit_track_status",
        "warnings",
    ):
        table[column] = table[column].astype("string")

    for column in (
        "season",
        "round_number",
        "warning_count",
    ):
        table[column] = table[column].astype("int64")

    for column in (
        "pit_in_lap",
        "pit_out_lap",
        "stint_before",
        "stint_after",
    ):
        table[column] = table[column].astype("Int64")

    for column in (
        "tyre_life_before",
        "tyre_life_after",
        "pit_in_time_seconds",
        "pit_out_time_seconds",
        "observed_pit_lane_duration_seconds",
    ):
        table[column] = table[column].astype("float64")

    for column in (
        "is_stint_change",
        "is_compound_change",
        "entry_rainfall",
        "exit_rainfall",
    ):
        table[column] = table[column].astype("boolean")

    for column in (
        "is_green_flag_pair",
        "is_dry_compound_pair",
        "is_interrupted_duration",
        "is_complete",
        "is_duration_analysis_candidate",
        "is_dry_weather_pair",
    ):
        table[column] = table[column].astype("bool")

    return table


def _normalized_session() -> NormalizedProcessedSession:
    """Create one normalized seven-lap race session."""
    laps = pd.DataFrame(
        {
            "SourceRowNumber": pd.Series(
                range(7),
                dtype="int64",
            ),
            "Season": pd.Series(
                [2024] * 7,
                dtype="int64",
            ),
            "RoundNumber": pd.Series(
                [1] * 7,
                dtype="int64",
            ),
            "SessionType": pd.Series(
                ["R"] * 7,
                dtype="string",
            ),
            "EventName": pd.Series(
                ["Bahrain Grand Prix"] * 7,
                dtype="string",
            ),
            "Driver": pd.Series(
                ["VER"] * 7,
                dtype="string",
            ),
            "DriverNumber": pd.Series(
                ["1"] * 7,
                dtype="string",
            ),
            "Team": pd.Series(
                ["Red Bull Racing"] * 7,
                dtype="string",
            ),
            "LapNumber": pd.Series(
                range(1, 8),
                dtype="Int64",
            ),
            "Stint": pd.Series(
                [1, 1, 1, 1, 1, 2, 2],
                dtype="Int64",
            ),
            "Compound": pd.Series(
                [
                    "MEDIUM",
                    "MEDIUM",
                    "MEDIUM",
                    "MEDIUM",
                    "MEDIUM",
                    "HARD",
                    "HARD",
                ],
                dtype="string",
            ),
            "TyreLife": pd.Series(
                [1, 2, 3, 4, 5, 1, 2],
                dtype="Int64",
            ),
            "LapStartTime": pd.to_timedelta(
                [0, 90, 180, 270, 360, 450, 540],
                unit="s",
            ),
            "TrackStatus": pd.Series(
                ["1"] * 7,
                dtype="string",
            ),
            "Position": pd.Series(
                [1] * 7,
                dtype="Int64",
            ),
            "WeatherObservationTime": pd.to_timedelta(
                [0, 60, 150, 240, 330, 420, 510],
                unit="s",
            ),
            "AirTemp": pd.Series(
                [25.0, 25.1, 25.2, 25.3, 25.4, 25.5, 25.6],
                dtype="float64",
            ),
            "Humidity": pd.Series(
                [45.0, 45.1, 45.2, 45.3, 45.4, 45.5, 45.6],
                dtype="float64",
            ),
            "Pressure": pd.Series(
                [1012.0] * 7,
                dtype="float64",
            ),
            "Rainfall": pd.Series(
                [False] * 7,
                dtype="boolean",
            ),
            "TrackTemp": pd.Series(
                [34.0, 34.1, 34.2, 34.3, 34.4, 34.5, 34.6],
                dtype="float64",
            ),
            "WindDirection": pd.Series(
                [180, 181, 182, 183, 184, 185, 186],
                dtype="int64",
            ),
            "WindSpeed": pd.Series(
                [2.0, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6],
                dtype="float64",
            ),
            "WeatherMatched": pd.Series(
                [True] * 7,
                dtype="bool",
            ),
            "WeatherAgeSeconds": pd.Series(
                [0.0, 30.0, 30.0, 30.0, 30.0, 30.0, 30.0],
                dtype="float64",
            ),
            "LapTimeSeconds": pd.Series(
                [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0],
                dtype="float64",
            ),
            "Sector1TimeSeconds": pd.Series(
                [33.0, 33.1, 33.2, 33.3, 33.4, 33.5, 33.6],
                dtype="float64",
            ),
            "Sector2TimeSeconds": pd.Series(
                [33.0, 33.1, 33.2, 33.3, 33.4, 33.5, 33.6],
                dtype="float64",
            ),
            "Sector3TimeSeconds": pd.Series(
                [34.0, 34.8, 35.6, 36.4, 37.2, 38.0, 38.8],
                dtype="float64",
            ),
            "PitInTime": pd.to_timedelta(
                [None, None, None, None, 390, None, None],
                unit="s",
            ),
            "PitOutTime": pd.to_timedelta(
                [None, None, None, None, None, 470, None],
                unit="s",
            ),
            "IsEligible": pd.Series(
                [True, True, True, True, False, False, True],
                dtype="bool",
            ),
            "ExclusionReasonCount": pd.Series(
                [0, 0, 0, 0, 1, 1, 0],
                dtype="int64",
            ),
            "ExclusionReasons": pd.Series(
                [
                    "",
                    "",
                    "",
                    "",
                    "PIT_IN_LAP",
                    "PIT_OUT_LAP",
                    "",
                ],
                dtype="string",
            ),
        }
    )

    return NormalizedProcessedSession(
        session_key=SessionKey(2024, 1),
        event_name="Bahrain Grand Prix",
        laps=laps,
        stints=pd.DataFrame(),
        pit_events=_pit_events(),
    )


def _source_reference() -> ProcessedSourceReference:
    """Return valid immutable processed-source provenance."""
    return ProcessedSourceReference(
        cleaning_rule_version=(
            SOURCE_CLEANING_RULE_VERSION
        ),
        processed_contract_version=(
            SOURCE_PROCESSED_CONTRACT_VERSION
        ),
        session_directory=(
            "data/processed/fastf1/cleaning_version=1.0/"
            "season=2024/round=01/session=R"
        ),
        **DIGESTS,
    )


@pytest.fixture
def session_data() -> DatasetSessionData:
    """Return one complete validated dataset session."""
    source = _normalized_session()

    return DatasetSessionData(
        source_lap_count=len(source.laps),
        decisions=build_session_decisions(source),
        pit_durations=(
            build_pit_duration_observations(source)
        ),
        source=_source_reference(),
    )


@pytest.fixture
def writer(tmp_path: Path) -> DatasetSessionWriter:
    """Return a writer rooted in an isolated directory."""
    return DatasetSessionWriter(
        DatasetPaths(tmp_path)
    )


def _read_document(path: Path) -> dict[str, object]:
    """Read one JSON object for mutation tests."""
    document = json.loads(
        path.read_text(encoding="utf-8")
    )

    assert isinstance(document, dict)

    return document


def _write_document(
    path: Path,
    document: dict[str, object],
) -> None:
    """Write deterministic JSON for corruption tests."""
    path.write_text(
        json.dumps(
            document,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _mutate_manifest(
    writer: DatasetSessionWriter,
    data: DatasetSessionData,
    mutation: Callable[[dict[str, object]], None],
) -> Path:
    """Write a session and mutate its untracked manifest."""
    result = writer.write(data)
    manifest_path = result.directory / "manifest.json"
    manifest = _read_document(manifest_path)
    mutation(manifest)
    _write_document(manifest_path, manifest)

    return result.directory


def _mutate_quality_report(
    writer: DatasetSessionWriter,
    data: DatasetSessionData,
    mutation: Callable[[dict[str, object]], None],
) -> Path:
    """Mutate quality JSON and refresh its manifest file record."""
    result = writer.write(data)
    quality_path = result.directory / "quality_report.json"
    quality = _read_document(quality_path)
    mutation(quality)
    _write_document(quality_path, quality)

    manifest_path = result.directory / "manifest.json"
    manifest = _read_document(manifest_path)
    files = manifest["files"]

    assert isinstance(files, dict)

    record = files["quality_report.json"]

    assert isinstance(record, dict)

    record["sha256"] = sha256_file(quality_path)
    record["size_bytes"] = quality_path.stat().st_size
    _write_document(manifest_path, manifest)

    return result.directory


def test_source_reference_exposes_manifest_document() -> None:
    """Processed provenance is deterministic and filename keyed."""
    source = _source_reference()

    assert source.table_sha256 == {
        "laps.parquet": "b" * 64,
        "stints.parquet": "c" * 64,
        "pit_events.parquet": "d" * 64,
    }
    assert source.as_document() == {
        "cleaning_rule_version": (
            SOURCE_CLEANING_RULE_VERSION
        ),
        "processed_contract_version": (
            SOURCE_PROCESSED_CONTRACT_VERSION
        ),
        "session_directory": source.session_directory,
        "manifest_sha256": "a" * 64,
        "table_sha256": source.table_sha256,
    }


@pytest.mark.parametrize(
    "field_name",
    (
        "cleaning_rule_version",
        "processed_contract_version",
        "session_directory",
        "manifest_sha256",
        "laps_sha256",
        "stints_sha256",
        "pit_events_sha256",
    ),
)
def test_source_reference_rejects_non_string_fields(
    field_name: str,
) -> None:
    """Every provenance field has an explicit string boundary."""
    values = {
        "cleaning_rule_version": (
            SOURCE_CLEANING_RULE_VERSION
        ),
        "processed_contract_version": (
            SOURCE_PROCESSED_CONTRACT_VERSION
        ),
        "session_directory": (
            "season=2024/round=01/session=R"
        ),
        **DIGESTS,
    }
    values[field_name] = 1

    with pytest.raises(
        TypeError,
        match=f"{field_name} must be a string",
    ):
        ProcessedSourceReference(
            **values  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "field_name",
    (
        "cleaning_rule_version",
        "processed_contract_version",
        "session_directory",
        "manifest_sha256",
        "laps_sha256",
        "stints_sha256",
        "pit_events_sha256",
    ),
)
def test_source_reference_rejects_empty_fields(
    field_name: str,
) -> None:
    """Empty provenance values cannot enter a manifest."""
    values = {
        "cleaning_rule_version": (
            SOURCE_CLEANING_RULE_VERSION
        ),
        "processed_contract_version": (
            SOURCE_PROCESSED_CONTRACT_VERSION
        ),
        "session_directory": (
            "season=2024/round=01/session=R"
        ),
        **DIGESTS,
    }
    values[field_name] = " "

    with pytest.raises(
        ValueError,
        match=f"{field_name} must not be empty",
    ):
        ProcessedSourceReference(**values)


@pytest.mark.parametrize(
    ("field_name", "message"),
    (
        (
            "cleaning_rule_version",
            "source cleaning-rule version",
        ),
        (
            "processed_contract_version",
            "source processed-contract version",
        ),
    ),
)
def test_source_reference_rejects_unsupported_versions(
    field_name: str,
    message: str,
) -> None:
    """Dataset provenance accepts only frozen source versions."""
    source = _source_reference()

    with pytest.raises(
        ValueError,
        match=message,
    ):
        replace(
            source,
            **{field_name: "9.9"},
        )


@pytest.mark.parametrize(
    "field_name",
    (
        "manifest_sha256",
        "laps_sha256",
        "stints_sha256",
        "pit_events_sha256",
    ),
)
@pytest.mark.parametrize(
    "digest",
    (
        "a" * 63,
        "A" * 64,
        "z" * 64,
    ),
)
def test_source_reference_rejects_invalid_digests(
    field_name: str,
    digest: str,
) -> None:
    """Source hashes must be canonical lowercase SHA-256 text."""
    source = _source_reference()

    with pytest.raises(
        ValueError,
        match=f"{field_name} must be a lowercase SHA-256",
    ):
        replace(
            source,
            **{field_name: digest},
        )


def test_session_data_exposes_shared_identity_and_tables(
    session_data: DatasetSessionData,
) -> None:
    """Storage input exposes the three authoritative tables."""
    assert isinstance(
        session_data.decisions,
        DecisionSessionData,
    )
    assert isinstance(
        session_data.pit_durations,
        PitDurationSessionData,
    )
    assert session_data.session_key == SessionKey(2024, 1)
    assert session_data.event_name == "Bahrain Grand Prix"
    assert session_data.decision_rows is (
        session_data.decisions.decision_rows
    )
    assert session_data.decision_labels is (
        session_data.decisions.decision_labels
    )
    assert session_data.pit_duration_observations is (
        session_data.pit_durations.observations
    )
    assert tuple(session_data.tables) == (
        "decision_rows",
        "decision_labels",
        "pit_duration_observations",
    )


def test_quality_report_contains_exact_fixture_totals(
    session_data: DatasetSessionData,
) -> None:
    """Quality reporting keeps feature, target and leakage counts apart."""
    report = build_dataset_quality_report(
        session_data
    )

    assert report["dataset_contract_version"] == (
        DATASET_CONTRACT_VERSION
    )
    assert report["session"] == {
        "identifier": "2024-01-R",
        "season": 2024,
        "round_number": 1,
        "session_type": "R",
        "event_name": "Bahrain Grand Prix",
    }
    assert report["source_counts"] == {
        "processed_source_laps": 7,
        "candidate_decision_rows": 6,
        "omitted_first_recorded_laps": 1,
        "source_pit_events": 1,
    }

    decision_quality = report["decision_quality"]
    target_quality = report["target_quality"]
    leakage = report["leakage_validation"]

    assert isinstance(decision_quality, dict)
    assert isinstance(target_quality, dict)
    assert isinstance(leakage, dict)
    assert decision_quality["eligible_decisions"] == 3
    assert decision_quality["ineligible_decisions"] == 3
    assert decision_quality["decision_eligibility_rate"] == 0.5
    assert decision_quality["historical_pit_now_actions"] == 1
    assert decision_quality["historical_stay_out_actions"] == 2
    assert target_quality["lap_time_target_eligible_rows"] == 2
    assert target_quality["lap_time_target_ineligible_rows"] == 1
    assert target_quality["pit_duration_target_eligible_rows"] == 1
    assert target_quality["pit_duration_target_ineligible_rows"] == 0
    assert leakage == {
        "future_weather_matches": 0,
        "current_lap_timing_features": [],
        "current_lap_quality_features": [],
        "features_outside_allowlist": [],
        "evaluation_season_rows": 0,
        "protected_evaluation_season_accessed": False,
        "status": "passed",
    }
    assert report["validation"] == {
        "status": "passed",
        "issue_count": 0,
    }


def test_quality_report_requires_dataset_session_data() -> None:
    """Arbitrary objects cannot bypass storage aggregation."""
    with pytest.raises(
        TypeError,
        match="data must be DatasetSessionData",
    ):
        build_dataset_quality_report(
            None  # type: ignore[arg-type]
        )


def test_writer_requires_dataset_paths(tmp_path: Path) -> None:
    """Writer construction has an explicit path abstraction boundary."""
    with pytest.raises(
        TypeError,
        match="dataset_paths must be DatasetPaths",
    ):
        DatasetSessionWriter(
            tmp_path  # type: ignore[arg-type]
        )


def test_writer_rejects_wrong_contract_path_version(
    tmp_path: Path,
) -> None:
    """A writer cannot store V1 data below another version path."""
    with pytest.raises(
        ValueError,
        match="dataset path version must equal",
    ):
        DatasetSessionWriter(
            DatasetPaths(
                tmp_path,
                dataset_contract_version="9.9",
            )
        )


def test_writer_requires_session_data(
    writer: DatasetSessionWriter,
) -> None:
    """The atomic writer accepts only aggregated session data."""
    with pytest.raises(
        TypeError,
        match="data must be DatasetSessionData",
    ):
        writer.write(
            None  # type: ignore[arg-type]
        )


def test_writer_requires_boolean_force(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """Replacement must be requested with an explicit boolean."""
    with pytest.raises(
        TypeError,
        match="force must be a boolean",
    ):
        writer.write(
            session_data,
            force=1,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "source_lap_count",
    (True, 7.0, "7"),
)
def test_writer_requires_integer_source_lap_count(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
    source_lap_count: object,
) -> None:
    """Source row accounting cannot rely on coercion."""
    invalid = replace(
        session_data,
        source_lap_count=source_lap_count,
    )

    with pytest.raises(
        TypeError,
        match="source_lap_count must be an integer",
    ):
        writer.write(invalid)


@pytest.mark.parametrize(
    "source_lap_count",
    (0, -1),
)
def test_writer_requires_positive_source_lap_count(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
    source_lap_count: int,
) -> None:
    """A non-empty decision partition must have source laps."""
    invalid = replace(
        session_data,
        source_lap_count=source_lap_count,
    )

    with pytest.raises(
        DatasetStorageError,
        match="source_lap_count must be positive",
    ):
        writer.write(invalid)


def test_writer_rejects_fewer_source_laps_than_decisions(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """Candidate decisions cannot outnumber their source laps."""
    invalid = replace(
        session_data,
        source_lap_count=5,
    )

    with pytest.raises(
        DatasetStorageError,
        match="smaller than candidate decisions",
    ):
        writer.write(invalid)


def test_writer_rejects_mismatched_session_identity(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """Decision and pit targets must describe the same race."""
    pit_durations = replace(
        session_data.pit_durations,
        session_key=SessionKey(2024, 2),
    )
    invalid = replace(
        session_data,
        pit_durations=pit_durations,
    )

    with pytest.raises(
        DatasetStorageError,
        match="session identities differ",
    ):
        writer.write(invalid)


def test_writer_rejects_mismatched_event_name(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """Decision and pit targets must retain one event name."""
    pit_durations = replace(
        session_data.pit_durations,
        event_name="Different Grand Prix",
    )
    invalid = replace(
        session_data,
        pit_durations=pit_durations,
    )

    with pytest.raises(
        DatasetStorageError,
        match="event names differ",
    ):
        writer.write(invalid)


def test_writer_rejects_mismatched_source_directory(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """Source provenance must end in the same partition identity."""
    source = replace(
        session_data.source,
        session_directory=(
            "data/processed/fastf1/cleaning_version=1.0/"
            "season=2024/round=02/session=R"
        ),
    )
    invalid = replace(
        session_data,
        source=source,
    )

    with pytest.raises(
        DatasetStorageError,
        match="source directory does not match",
    ):
        writer.write(invalid)


def test_writer_rejects_empty_decision_rows(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """An authoritative session cannot contain no decisions."""
    decisions = replace(
        session_data.decisions,
        decision_rows=(
            session_data.decision_rows.iloc[0:0].copy()
        ),
    )
    invalid = replace(
        session_data,
        decisions=decisions,
    )

    with pytest.raises(
        DatasetStorageError,
        match="decision-row table must not be empty",
    ):
        writer.write(invalid)


def test_writer_creates_complete_authoritative_partition(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """A successful write stores tables, quality and manifest."""
    result = writer.write(session_data)
    paths = writer.dataset_paths.for_session(
        session_data.session_key
    )

    assert result.status == "written"
    assert result.directory == paths.directory
    assert paths.directory.is_dir()
    assert not paths.temporary_directory.exists()
    assert not paths.backup_directory.exists()
    assert {
        path.name
        for path in paths.directory.iterdir()
    } == {
        *EXPECTED_SESSION_FILES,
        "manifest.json",
    }
    assert result.manifest == read_json_document(
        paths.manifest
    )
    assert result.quality_report == read_json_document(
        paths.quality_report
    )


def test_writer_preserves_all_table_values_and_dtypes(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """Parquet readback equals every in-memory authoritative table."""
    writer.write(session_data)
    paths = writer.dataset_paths.for_session(
        session_data.session_key
    )

    for table_name, original in session_data.tables.items():
        restored = read_parquet_table(
            paths.table_paths[table_name]
        )
        pd.testing.assert_frame_equal(
            restored,
            original.reset_index(drop=True),
        )


def test_manifest_records_identity_source_and_files(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """Manifest metadata and file evidence are complete."""
    result = writer.write(session_data)
    manifest = result.manifest

    assert set(manifest) == {
        "dataset_contract_version",
        "created_at_utc",
        "session",
        "source",
        "files",
        "validation",
    }
    assert manifest["dataset_contract_version"] == (
        DATASET_CONTRACT_VERSION
    )
    assert manifest["source"] == (
        session_data.source.as_document()
    )

    files = manifest["files"]

    assert isinstance(files, dict)
    assert set(files) == EXPECTED_SESSION_FILES

    for filename, record in files.items():
        assert isinstance(record, dict)

        path = result.directory / filename

        assert record["path"] == filename
        assert record["sha256"] == sha256_file(path)
        assert record["size_bytes"] == path.stat().st_size

        if filename.endswith(".parquet"):
            table = read_parquet_table(path)

            assert record["rows"] == len(table)
            assert record["columns"] == list(
                table.columns
            )

    validation = manifest["validation"]

    assert isinstance(validation, dict)
    assert validation["status"] == "passed"
    assert validation["issue_count"] == 0
    assert validation["decision_identity_unique"] is True
    assert validation["decision_label_identity_equal"] is True
    assert validation["feature_label_row_count_equal"] is True
    assert validation["future_weather_match_count"] == 0
    assert validation["leakage_check_status"] == "passed"
    assert validation["evaluation_season_rows"] == 0
    assert (
        validation["protected_evaluation_season_accessed"]
        is False
    )
    assert validation["parquet_readback"] == "passed"
    assert validation["quality_report_readback"] == "passed"


def test_second_valid_write_is_skipped(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """A valid completed partition is verified and reused."""
    first = writer.write(session_data)
    second = writer.write(session_data)

    assert first.status == "written"
    assert second.status == "skipped"
    assert second.directory == first.directory
    assert second.manifest == first.manifest
    assert second.quality_report == first.quality_report


def test_force_replaces_the_whole_partition(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """Forced rebuilding removes stale authoritative files."""
    first = writer.write(session_data)
    stale_path = first.directory / "stale.txt"
    stale_path.write_text("stale", encoding="utf-8")

    second = writer.write(
        session_data,
        force=True,
    )

    assert second.status == "written"
    assert not stale_path.exists()
    assert not writer.dataset_paths.for_session(
        session_data.session_key
    ).backup_directory.exists()


def test_writer_removes_stale_temporary_directory(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """Interrupted temporary output is cleared before rebuilding."""
    paths = writer.dataset_paths.for_session(
        session_data.session_key
    )
    paths.temporary_directory.mkdir(
        parents=True
    )
    stale_path = (
        paths.temporary_directory / "stale.txt"
    )
    stale_path.write_text("stale", encoding="utf-8")

    result = writer.write(session_data)

    assert result.status == "written"
    assert not paths.temporary_directory.exists()
    assert not stale_path.exists()


def test_writer_recovers_an_interrupted_backup(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """A backup is restored when no authoritative directory remains."""
    first = writer.write(session_data)
    paths = writer.dataset_paths.for_session(
        session_data.session_key
    )
    paths.backup_directory.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    paths.directory.rename(
        paths.backup_directory
    )

    second = writer.write(session_data)

    assert first.status == "written"
    assert second.status == "skipped"
    assert paths.directory.is_dir()
    assert not paths.backup_directory.exists()


def test_writer_discards_obsolete_backup_when_partition_exists(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """A completed authoritative partition wins over an old backup."""
    writer.write(session_data)
    paths = writer.dataset_paths.for_session(
        session_data.session_key
    )
    paths.backup_directory.mkdir(
        parents=True
    )
    stale_path = paths.backup_directory / "stale.txt"
    stale_path.write_text("stale", encoding="utf-8")

    result = writer.write(session_data)

    assert result.status == "skipped"
    assert paths.directory.is_dir()
    assert not paths.backup_directory.exists()


def test_incomplete_existing_partition_fails_closed(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """An unmanifested authoritative directory is never overwritten."""
    paths = writer.dataset_paths.for_session(
        session_data.session_key
    )
    paths.directory.mkdir(parents=True)

    with pytest.raises(
        IncompleteDatasetSessionError,
        match="exists without a completed manifest",
    ):
        writer.write(session_data)


def test_write_failure_leaves_no_authoritative_partition(
    monkeypatch: pytest.MonkeyPatch,
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """A table-write failure is contained inside temporary storage."""
    def fail_write(
        table: pd.DataFrame,
        path: Path,
    ) -> None:
        del table, path
        raise RuntimeError("synthetic write failure")

    monkeypatch.setattr(
        storage_module,
        "write_parquet_table",
        fail_write,
    )
    paths = writer.dataset_paths.for_session(
        session_data.session_key
    )

    with pytest.raises(
        RuntimeError,
        match="synthetic write failure",
    ):
        writer.write(session_data)

    assert not paths.directory.exists()
    assert not paths.temporary_directory.exists()
    assert not paths.backup_directory.exists()


def test_corrupted_stored_file_fails_checksum_validation(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """A changed authoritative file cannot be silently skipped."""
    result = writer.write(session_data)
    path = result.directory / "decision_rows.parquet"

    with path.open("ab") as stored_file:
        stored_file.write(b"corruption")

    with pytest.raises(
        DatasetStorageError,
        match="file checksum failed",
    ):
        writer.write(session_data)


def test_missing_stored_file_fails_closed(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """A manifest cannot make a missing authoritative file valid."""
    result = writer.write(session_data)
    (
        result.directory / "decision_labels.parquet"
    ).unlink()

    with pytest.raises(
        IncompleteDatasetSessionError,
        match="stored dataset file is missing",
    ):
        writer.write(session_data)


def test_force_can_replace_a_corrupted_partition(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """Explicit force rebuilding replaces invalid stored bytes."""
    first = writer.write(session_data)
    path = first.directory / "decision_rows.parquet"

    with path.open("ab") as stored_file:
        stored_file.write(b"corruption")

    second = writer.write(
        session_data,
        force=True,
    )

    files = second.manifest["files"]

    assert isinstance(files, dict)

    record = files["decision_rows.parquet"]

    assert isinstance(record, dict)
    assert second.status == "written"
    assert sha256_file(path) == record["sha256"]


def test_stored_manifest_requires_supported_contract_version(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """Completed partitions remain tied to one dataset contract."""
    _mutate_manifest(
        writer,
        session_data,
        lambda manifest: manifest.__setitem__(
            "dataset_contract_version",
            "9.9",
        ),
    )

    with pytest.raises(
        DatasetStorageError,
        match="contract version is unsupported",
    ):
        writer.write(session_data)


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("identifier", "2024-02-R"),
        ("season", 2023),
        ("round_number", 2),
        ("session_type", "Q"),
    ),
)
def test_stored_manifest_identity_must_match_path(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
    field_name: str,
    value: object,
) -> None:
    """Stored identity cannot disagree with partition directories."""
    def mutate(manifest: dict[str, object]) -> None:
        session = manifest["session"]

        assert isinstance(session, dict)

        session[field_name] = value

    _mutate_manifest(
        writer,
        session_data,
        mutate,
    )

    with pytest.raises(
        DatasetStorageError,
        match=f"session {field_name} does not match",
    ):
        writer.write(session_data)


@pytest.mark.parametrize(
    "event_name",
    ("", None),
)
def test_stored_manifest_requires_event_name(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
    event_name: object,
) -> None:
    """Manifest session identity includes a non-empty event name."""
    def mutate(manifest: dict[str, object]) -> None:
        session = manifest["session"]

        assert isinstance(session, dict)

        session["event_name"] = event_name

    _mutate_manifest(
        writer,
        session_data,
        mutate,
    )

    with pytest.raises(
        DatasetStorageError,
        match="event name is invalid",
    ):
        writer.write(session_data)


def test_stored_manifest_requires_source_object(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """Stored processed-source provenance must be structured."""
    _mutate_manifest(
        writer,
        session_data,
        lambda manifest: manifest.__setitem__(
            "source",
            None,
        ),
    )

    with pytest.raises(
        DatasetStorageError,
        match="source must be an object",
    ):
        writer.write(session_data)


@pytest.mark.parametrize(
    ("field_name", "message"),
    (
        (
            "cleaning_rule_version",
            "source cleaning version is unsupported",
        ),
        (
            "processed_contract_version",
            "source processed contract is unsupported",
        ),
    ),
)
def test_stored_source_requires_supported_versions(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
    field_name: str,
    message: str,
) -> None:
    """A skipped partition must retain frozen source versions."""
    def mutate(manifest: dict[str, object]) -> None:
        source = manifest["source"]

        assert isinstance(source, dict)

        source[field_name] = "9.9"

    _mutate_manifest(
        writer,
        session_data,
        mutate,
    )

    with pytest.raises(
        DatasetStorageError,
        match=message,
    ):
        writer.write(session_data)


def test_stored_source_directory_must_match_partition(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """Stored provenance cannot point at another processed race."""
    def mutate(manifest: dict[str, object]) -> None:
        source = manifest["source"]

        assert isinstance(source, dict)

        source["session_directory"] = (
            "season=2024/round=02/session=R"
        )

    _mutate_manifest(
        writer,
        session_data,
        mutate,
    )

    with pytest.raises(
        DatasetStorageError,
        match="source session directory does not match",
    ):
        writer.write(session_data)


@pytest.mark.parametrize(
    "digest",
    (None, "A" * 64, "a" * 63),
)
def test_stored_source_requires_manifest_digest(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
    digest: object,
) -> None:
    """Stored source manifest evidence remains canonical."""
    def mutate(manifest: dict[str, object]) -> None:
        source = manifest["source"]

        assert isinstance(source, dict)

        source["manifest_sha256"] = digest

    _mutate_manifest(
        writer,
        session_data,
        mutate,
    )

    with pytest.raises(
        DatasetStorageError,
        match="source manifest SHA-256 is invalid",
    ):
        writer.write(session_data)


def test_stored_source_requires_exact_table_hash_keys(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """All three processed source tables remain traceable."""
    def mutate(manifest: dict[str, object]) -> None:
        source = manifest["source"]

        assert isinstance(source, dict)

        source["table_sha256"] = {
            "laps.parquet": "b" * 64,
        }

    _mutate_manifest(
        writer,
        session_data,
        mutate,
    )

    with pytest.raises(
        DatasetStorageError,
        match="source table hashes are invalid",
    ):
        writer.write(session_data)


def test_stored_source_requires_valid_table_digests(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """Each processed table reference uses canonical SHA-256 text."""
    def mutate(manifest: dict[str, object]) -> None:
        source = manifest["source"]

        assert isinstance(source, dict)

        table_hashes = source["table_sha256"]

        assert isinstance(table_hashes, dict)

        table_hashes["laps.parquet"] = "invalid"

    _mutate_manifest(
        writer,
        session_data,
        mutate,
    )

    with pytest.raises(
        DatasetStorageError,
        match="source hash for laps.parquet is invalid",
    ):
        writer.write(session_data)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda manifest: manifest.__setitem__(
            "validation",
            None,
        ),
        lambda manifest: manifest["validation"].__setitem__(
            "status",
            "failed",
        ),
        lambda manifest: manifest["validation"].__setitem__(
            "issue_count",
            1,
        ),
        lambda manifest: manifest["validation"].__setitem__(
            "leakage_check_status",
            "failed",
        ),
        lambda manifest: manifest["validation"].__setitem__(
            "protected_evaluation_season_accessed",
            True,
        ),
    ),
)
def test_stored_manifest_requires_passed_validation(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
    mutation: Callable[[dict[str, object]], None],
) -> None:
    """A failed stored validation cannot be reported as complete."""
    _mutate_manifest(
        writer,
        session_data,
        mutation,
    )

    with pytest.raises(
        DatasetStorageError,
        match="validation",
    ):
        writer.write(session_data)


def test_stored_manifest_requires_exact_file_set(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """Every authoritative session file must be represented."""
    def mutate(manifest: dict[str, object]) -> None:
        files = manifest["files"]

        assert isinstance(files, dict)

        del files["decision_labels.parquet"]

    _mutate_manifest(
        writer,
        session_data,
        mutate,
    )

    with pytest.raises(
        IncompleteDatasetSessionError,
        match="unexpected file manifest",
    ):
        writer.write(session_data)


def test_stored_manifest_requires_file_record_objects(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """Each file entry carries structured integrity evidence."""
    def mutate(manifest: dict[str, object]) -> None:
        files = manifest["files"]

        assert isinstance(files, dict)

        files["decision_rows.parquet"] = None

    _mutate_manifest(
        writer,
        session_data,
        mutate,
    )

    with pytest.raises(
        IncompleteDatasetSessionError,
        match="manifest record",
    ):
        writer.write(session_data)


def test_stored_manifest_requires_canonical_relative_path(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """A file record cannot redirect integrity checks elsewhere."""
    def mutate(manifest: dict[str, object]) -> None:
        files = manifest["files"]

        assert isinstance(files, dict)

        record = files["decision_rows.parquet"]

        assert isinstance(record, dict)

        record["path"] = "other.parquet"

    _mutate_manifest(
        writer,
        session_data,
        mutate,
    )

    with pytest.raises(
        DatasetStorageError,
        match="manifest path",
    ):
        writer.write(session_data)


def test_stored_manifest_requires_checksum_text(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """A missing checksum cannot validate a stored file."""
    def mutate(manifest: dict[str, object]) -> None:
        files = manifest["files"]

        assert isinstance(files, dict)

        record = files["decision_rows.parquet"]

        assert isinstance(record, dict)

        record["sha256"] = None

    _mutate_manifest(
        writer,
        session_data,
        mutate,
    )

    with pytest.raises(
        IncompleteDatasetSessionError,
        match="checksum",
    ):
        writer.write(session_data)


@pytest.mark.parametrize(
    "size_bytes",
    (True, -1, "1"),
)
def test_stored_manifest_requires_exact_file_size(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
    size_bytes: object,
) -> None:
    """Stored byte counts are checked before table reuse."""
    def mutate(manifest: dict[str, object]) -> None:
        files = manifest["files"]

        assert isinstance(files, dict)

        record = files["decision_rows.parquet"]

        assert isinstance(record, dict)

        record["size_bytes"] = size_bytes

    _mutate_manifest(
        writer,
        session_data,
        mutate,
    )

    with pytest.raises(
        DatasetStorageError,
        match="file size failed",
    ):
        writer.write(session_data)


def test_stored_manifest_requires_exact_row_count(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """Manifest row counts must equal Parquet readback."""
    def mutate(manifest: dict[str, object]) -> None:
        files = manifest["files"]

        assert isinstance(files, dict)

        record = files["decision_rows.parquet"]

        assert isinstance(record, dict)

        record["rows"] = 999

    _mutate_manifest(
        writer,
        session_data,
        mutate,
    )

    with pytest.raises(
        DatasetStorageError,
        match="row count failed",
    ):
        writer.write(session_data)


def test_stored_manifest_requires_exact_column_order(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """Manifest columns must preserve the table contract order."""
    def mutate(manifest: dict[str, object]) -> None:
        files = manifest["files"]

        assert isinstance(files, dict)

        record = files["decision_rows.parquet"]

        assert isinstance(record, dict)

        columns = record["columns"]

        assert isinstance(columns, list)

        record["columns"] = list(reversed(columns))

    _mutate_manifest(
        writer,
        session_data,
        mutate,
    )

    with pytest.raises(
        DatasetStorageError,
        match="column list failed",
    ):
        writer.write(session_data)


def test_stored_quality_report_requires_contract_version(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """Quality evidence belongs to the same dataset contract."""
    _mutate_quality_report(
        writer,
        session_data,
        lambda report: report.__setitem__(
            "dataset_contract_version",
            "9.9",
        ),
    )

    with pytest.raises(
        DatasetStorageError,
        match="quality-report contract version",
    ):
        writer.write(session_data)


def test_stored_quality_report_requires_matching_identity(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
) -> None:
    """Quality evidence cannot be moved between race partitions."""
    def mutate(report: dict[str, object]) -> None:
        session = report["session"]

        assert isinstance(session, dict)

        session["identifier"] = "2024-02-R"

    _mutate_quality_report(
        writer,
        session_data,
        mutate,
    )

    with pytest.raises(
        DatasetStorageError,
        match="quality-report session does not match",
    ):
        writer.write(session_data)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda report: report.__setitem__(
            "validation",
            None,
        ),
        lambda report: report["validation"].__setitem__(
            "status",
            "failed",
        ),
        lambda report: report["validation"].__setitem__(
            "issue_count",
            1,
        ),
    ),
)
def test_stored_quality_report_requires_passed_validation(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
    mutation: Callable[[dict[str, object]], None],
) -> None:
    """Failed quality validation prevents safe reuse."""
    _mutate_quality_report(
        writer,
        session_data,
        mutation,
    )

    with pytest.raises(
        DatasetStorageError,
        match="quality-report validation has not passed",
    ):
        writer.write(session_data)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda report: report.__setitem__(
            "leakage_validation",
            None,
        ),
        lambda report: report[
            "leakage_validation"
        ].__setitem__(
            "status",
            "failed",
        ),
        lambda report: report[
            "leakage_validation"
        ].__setitem__(
            "protected_evaluation_season_accessed",
            True,
        ),
        lambda report: report[
            "leakage_validation"
        ].__setitem__(
            "evaluation_season_rows",
            1,
        ),
    ),
)
def test_stored_quality_report_requires_passed_leakage_checks(
    writer: DatasetSessionWriter,
    session_data: DatasetSessionData,
    mutation: Callable[[dict[str, object]], None],
) -> None:
    """Stored leakage evidence is independently verified."""
    _mutate_quality_report(
        writer,
        session_data,
        mutation,
    )

    with pytest.raises(
        DatasetStorageError,
        match="quality-report leakage validation has not passed",
    ):
        writer.write(session_data)