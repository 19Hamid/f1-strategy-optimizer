"""Tests for the verified modelling-dataset catalog."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

import app.datasets.catalog as catalog_module
from app.datasets.catalog import (
    DATASET_CATALOG_COLUMNS,
    DatasetCatalogBuilder,
    DatasetCatalogBuildResult,
    DatasetCatalogError,
)
from app.datasets.contracts import (
    CATALOG_CONTRACT,
    DATASET_CONTRACT_VERSION,
    DEVELOPMENT_SEASONS,
    SOURCE_CLEANING_RULE_VERSION,
    SOURCE_PROCESSED_CONTRACT_VERSION,
)
from app.datasets.paths import DatasetPaths
from app.datasets.storage import DatasetStorageError
from app.pipeline import SessionKey
from app.pipeline.serialization import (
    read_parquet_table,
    sha256_file,
)

Documents = tuple[
    dict[str, object],
    dict[str, object],
]


def _partition_documents(
    session_key: SessionKey,
) -> Documents:
    """Return valid stored documents for one synthetic session."""
    event_name = (
        f"Development Event "
        f"{session_key.season}-"
        f"{session_key.round_number:02d}"
    )
    session = {
        "identifier": session_key.identifier,
        "season": session_key.season,
        "round_number": (
            session_key.round_number
        ),
        "session_type": (
            session_key.session_type
        ),
        "event_name": event_name,
    }
    files = {
        "decision_rows.parquet": {
            "path": "decision_rows.parquet",
            "rows": 6,
            "columns": [],
            "sha256": "a" * 64,
            "size_bytes": 100,
        },
        "decision_labels.parquet": {
            "path": "decision_labels.parquet",
            "rows": 6,
            "columns": [],
            "sha256": "b" * 64,
            "size_bytes": 80,
        },
        "pit_duration_observations.parquet": {
            "path": (
                "pit_duration_observations.parquet"
            ),
            "rows": 1,
            "columns": [],
            "sha256": "c" * 64,
            "size_bytes": 60,
        },
        "quality_report.json": {
            "path": "quality_report.json",
            "sha256": "d" * 64,
            "size_bytes": 40,
        },
    }
    manifest = {
        "dataset_contract_version": (
            DATASET_CONTRACT_VERSION
        ),
        "created_at_utc": (
            f"2026-09-02T"
            f"{session_key.round_number:02d}:00:00Z"
        ),
        "session": session,
        "source": {
            "cleaning_rule_version": (
                SOURCE_CLEANING_RULE_VERSION
            ),
            "processed_contract_version": (
                SOURCE_PROCESSED_CONTRACT_VERSION
            ),
            "session_directory": (
                "data/processed/fastf1/"
                "cleaning_version=1.0/"
                f"season={session_key.season}/"
                f"round={session_key.round_number:02d}/"
                "session=R"
            ),
            "manifest_sha256": "e" * 64,
            "table_sha256": {
                "laps.parquet": "f" * 64,
                "stints.parquet": "1" * 64,
                "pit_events.parquet": "2" * 64,
            },
        },
        "files": files,
        "validation": {
            "status": "passed",
            "issue_count": 0,
        },
    }
    quality_report = {
        "dataset_contract_version": (
            DATASET_CONTRACT_VERSION
        ),
        "session": session.copy(),
        "source_counts": {
            "processed_source_laps": 7,
            "candidate_decision_rows": 6,
            "omitted_first_recorded_laps": 1,
            "source_pit_events": 1,
        },
        "decision_quality": {
            "eligible_decisions": 3,
            "ineligible_decisions": 3,
            "decision_eligibility_rate": 0.5,
            "exclusion_reason_counts": {},
            "state_reconstruction_conflicts": 0,
            "historical_pit_now_actions": 1,
            "historical_stay_out_actions": 2,
        },
        "target_quality": {
            "lap_time_target_eligible_rows": 2,
            "lap_time_target_ineligible_rows": 1,
            "pit_duration_target_eligible_rows": 1,
            "pit_duration_target_ineligible_rows": 0,
            "pit_duration_exclusion_reason_counts": {},
        },
        "leakage_validation": {
            "future_weather_matches": 0,
            "current_lap_timing_features": [],
            "current_lap_quality_features": [],
            "features_outside_allowlist": [],
            "evaluation_season_rows": 0,
            "protected_evaluation_season_accessed": (
                False
            ),
            "status": "passed",
        },
        "validation": {
            "status": "passed",
            "issue_count": 0,
        },
    }

    return manifest, quality_report


def _install_verifier(
    monkeypatch: pytest.MonkeyPatch,
    documents_by_id: dict[str, Documents]
    | None = None,
) -> list[SessionKey]:
    """Install a deterministic completed-partition verifier."""
    calls: list[SessionKey] = []

    def verify(session_paths: object) -> Documents:
        session_key = session_paths.session_key

        assert isinstance(session_key, SessionKey)

        calls.append(session_key)

        if documents_by_id is not None:
            documents = documents_by_id[
                session_key.identifier
            ]
        else:
            documents = _partition_documents(
                session_key
            )

        return deepcopy(documents)

    monkeypatch.setattr(
        catalog_module,
        "_validate_completed_partition",
        verify,
    )

    return calls


@pytest.fixture
def dataset_paths(tmp_path: Path) -> DatasetPaths:
    """Return isolated modelling-dataset paths."""
    return DatasetPaths(tmp_path)


@pytest.fixture
def builder(
    dataset_paths: DatasetPaths,
) -> DatasetCatalogBuilder:
    """Return an isolated dataset catalog builder."""
    return DatasetCatalogBuilder(dataset_paths)


@pytest.fixture
def session_keys() -> tuple[SessionKey, ...]:
    """Return deliberately unsorted development sessions."""
    return (
        SessionKey(2024, 2),
        SessionKey(2022, 3),
        SessionKey(2023, 1),
    )


def test_catalog_column_constant_matches_contract() -> None:
    """The executable catalog order has one source of truth."""
    assert DATASET_CATALOG_COLUMNS == tuple(
        column.name
        for column in CATALOG_CONTRACT.columns
    )
    assert len(DATASET_CATALOG_COLUMNS) == 20


def test_builder_requires_dataset_paths() -> None:
    """Catalog construction requires typed path configuration."""
    with pytest.raises(
        TypeError,
        match="dataset_paths must be DatasetPaths",
    ):
        DatasetCatalogBuilder(
            dataset_paths=object()  # type: ignore[arg-type]
        )


def test_builder_requires_current_contract_version(
    tmp_path: Path,
) -> None:
    """A catalog cannot be written beneath another version."""
    paths = DatasetPaths(
        tmp_path,
        dataset_contract_version="9.9",
    )

    with pytest.raises(
        ValueError,
        match="dataset path version",
    ):
        DatasetCatalogBuilder(paths)


def test_builds_sorted_verified_catalog(
    builder: DatasetCatalogBuilder,
    session_keys: tuple[SessionKey, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verified sessions become one canonically sorted catalog."""
    calls = _install_verifier(monkeypatch)

    result = builder.build(session_keys)

    assert isinstance(
        result,
        DatasetCatalogBuildResult,
    )
    assert result.path == builder.dataset_paths.catalog
    assert result.path.is_file()
    assert result.sha256 == sha256_file(result.path)
    assert calls == list(session_keys)
    assert result.catalog["session_id"].tolist() == [
        "2022-03-R",
        "2023-01-R",
        "2024-02-R",
    ]
    assert result.catalog["season"].tolist() == [
        2022,
        2023,
        2024,
    ]


def test_catalog_has_exact_schema_and_dtypes(
    builder: DatasetCatalogBuilder,
    session_keys: tuple[SessionKey, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog publication preserves all 20 contract columns."""
    _install_verifier(monkeypatch)

    catalog = builder.build(
        session_keys
    ).catalog

    assert tuple(catalog.columns) == (
        DATASET_CATALOG_COLUMNS
    )

    for column in CATALOG_CONTRACT.columns:
        assert str(
            catalog[column.name].dtype
        ) == column.pandas_dtype
        assert not catalog[column.name].isna().any()


def test_catalog_contains_exact_fixture_metrics(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manifest and quality totals populate their exact fields."""
    _install_verifier(monkeypatch)
    session_key = SessionKey(2024, 1)

    row = builder.build(
        (session_key,)
    ).catalog.iloc[0]

    assert row["session_id"] == "2024-01-R"
    assert row["event_name"] == (
        "Development Event 2024-01"
    )
    assert row["dataset_contract_version"] == "1.0"
    assert row["cleaning_rule_version"] == "1.0"
    assert row["processed_contract_version"] == "1.0"
    assert row["decision_rows"] == 6
    assert row["eligible_decisions"] == 3
    assert row["ineligible_decisions"] == 3
    assert row["decision_label_rows"] == 6
    assert row["lap_time_target_eligible_rows"] == 2
    assert row["pit_now_rows"] == 1
    assert row["stay_out_rows"] == 2
    assert row["pit_duration_rows"] == 1
    assert row[
        "pit_duration_target_eligible_rows"
    ] == 1
    assert row["total_size_bytes"] == 280
    assert row["session_directory"] == str(
        builder.dataset_paths.for_session(
            session_key
        ).directory
    )


def test_published_catalog_matches_returned_frame(
    builder: DatasetCatalogBuilder,
    session_keys: tuple[SessionKey, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parquet publication exactly matches the returned catalog."""
    _install_verifier(monkeypatch)

    result = builder.build(session_keys)
    stored = read_parquet_table(result.path)

    pd.testing.assert_frame_equal(
        stored,
        result.catalog,
    )


def test_repeated_build_is_deterministic(
    builder: DatasetCatalogBuilder,
    session_keys: tuple[SessionKey, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unchanged session evidence creates the same catalog hash."""
    _install_verifier(monkeypatch)

    first = builder.build(session_keys)
    second = builder.build(
        tuple(reversed(session_keys))
    )

    pd.testing.assert_frame_equal(
        first.catalog,
        second.catalog,
    )
    assert first.sha256 == second.sha256


def test_empty_catalog_request_is_rejected(
    builder: DatasetCatalogBuilder,
) -> None:
    """An authoritative empty catalog cannot be published."""
    with pytest.raises(
        DatasetCatalogError,
        match="at least one session",
    ):
        builder.build(())


@pytest.mark.parametrize(
    "invalid_collection",
    [
        "2024-01-R",
        b"2024-01-R",
        42,
    ],
)
def test_session_collection_must_be_an_iterable_of_keys(
    builder: DatasetCatalogBuilder,
    invalid_collection: object,
) -> None:
    """Strings, bytes and non-iterables are not key lists."""
    with pytest.raises(
        TypeError,
        match="iterable of SessionKey",
    ):
        builder.build(  # type: ignore[arg-type]
            invalid_collection
        )


def test_session_collection_rejects_non_key_items(
    builder: DatasetCatalogBuilder,
) -> None:
    """Every requested identity must be a SessionKey."""
    with pytest.raises(
        TypeError,
        match="only SessionKey",
    ):
        builder.build(  # type: ignore[arg-type]
            (object(),)
        )


def test_duplicate_sessions_are_rejected_before_access(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session cannot produce multiple catalog rows."""
    calls = _install_verifier(monkeypatch)
    session_key = SessionKey(2024, 1)

    with pytest.raises(
        DatasetCatalogError,
        match="identities must be unique",
    ):
        builder.build(
            (session_key, session_key)
        )

    assert calls == []


def test_protected_season_is_rejected_before_access(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog construction must never inspect a 2025 path."""
    calls = _install_verifier(monkeypatch)

    with pytest.raises(
        DatasetCatalogError,
        match="protected evaluation season",
    ):
        builder.build((SessionKey(2025, 1),))

    assert calls == []


def test_unsupported_development_season_is_rejected(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the frozen 2022-2024 development years are valid."""
    calls = _install_verifier(monkeypatch)

    with pytest.raises(
        DatasetCatalogError,
        match="outside the development seasons",
    ):
        builder.build((SessionKey(2021, 1),))

    assert calls == []


def test_storage_validation_failure_is_wrapped(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid stored partitions fail with catalog context."""
    def fail(_session_paths: object) -> Documents:
        raise DatasetStorageError("checksum failed")

    monkeypatch.setattr(
        catalog_module,
        "_validate_completed_partition",
        fail,
    )

    with pytest.raises(
        DatasetCatalogError,
        match=(
            "2024-01-R: checksum failed"
        ),
    ):
        builder.build((SessionKey(2024, 1),))


@pytest.mark.parametrize(
    "error",
    [
        OSError("unreadable"),
        ValueError("invalid document"),
        TypeError("invalid structure"),
        AttributeError("missing mapping API"),
    ],
)
def test_partition_read_failures_are_wrapped(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    """Low-level partition failures cannot escape unlabelled."""
    def fail(_session_paths: object) -> Documents:
        raise error

    monkeypatch.setattr(
        catalog_module,
        "_validate_completed_partition",
        fail,
    )

    with pytest.raises(
        DatasetCatalogError,
        match="failed storage validation",
    ):
        builder.build((SessionKey(2024, 1),))


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("identifier", "2024-02-R"),
        ("season", 2023),
        ("round_number", 2),
        ("session_type", "SPRINT"),
    ],
)
def test_manifest_identity_must_match_request(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    invalid_value: object,
) -> None:
    """A catalog row cannot relabel a stored partition."""
    session_key = SessionKey(2024, 1)
    manifest, quality = _partition_documents(
        session_key
    )
    session = manifest["session"]

    assert isinstance(session, dict)

    session[field] = invalid_value
    _install_verifier(
        monkeypatch,
        {
            session_key.identifier: (
                manifest,
                quality,
            )
        },
    )

    with pytest.raises(
        DatasetCatalogError,
        match="identity mismatch",
    ):
        builder.build((session_key,))


@pytest.mark.parametrize(
    "event_name",
    [None, "", "   ", 42],
)
def test_manifest_requires_non_empty_event_name(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
    event_name: object,
) -> None:
    """Every catalog row requires meaningful event text."""
    session_key = SessionKey(2024, 1)
    manifest, quality = _partition_documents(
        session_key
    )
    session = manifest["session"]

    assert isinstance(session, dict)

    session["event_name"] = event_name
    _install_verifier(
        monkeypatch,
        {
            session_key.identifier: (
                manifest,
                quality,
            )
        },
    )

    with pytest.raises(
        DatasetCatalogError,
        match="event_name",
    ):
        builder.build((session_key,))


@pytest.mark.parametrize(
    "document_name",
    ["manifest", "quality"],
)
def test_dataset_contract_versions_must_match(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
    document_name: str,
) -> None:
    """Manifest and quality report must use contract 1.0."""
    session_key = SessionKey(2024, 1)
    manifest, quality = _partition_documents(
        session_key
    )
    document = (
        manifest
        if document_name == "manifest"
        else quality
    )
    document["dataset_contract_version"] = "9.9"
    _install_verifier(
        monkeypatch,
        {
            session_key.identifier: (
                manifest,
                quality,
            )
        },
    )

    with pytest.raises(
        DatasetCatalogError,
        match="dataset contract version mismatch",
    ):
        builder.build((session_key,))


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("cleaning_rule_version", "9.9"),
        ("processed_contract_version", "9.9"),
    ],
)
def test_source_versions_must_match(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    invalid_value: str,
) -> None:
    """Catalog provenance cannot accept unsupported sources."""
    session_key = SessionKey(2024, 1)
    manifest, quality = _partition_documents(
        session_key
    )
    source = manifest["source"]

    assert isinstance(source, dict)

    source[field] = invalid_value
    _install_verifier(
        monkeypatch,
        {
            session_key.identifier: (
                manifest,
                quality,
            )
        },
    )

    with pytest.raises(
        DatasetCatalogError,
        match="version mismatch",
    ):
        builder.build((session_key,))


def test_leakage_status_must_pass(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed stored leakage status blocks publication."""
    session_key = SessionKey(2024, 1)
    manifest, quality = _partition_documents(
        session_key
    )
    leakage = quality["leakage_validation"]

    assert isinstance(leakage, dict)

    leakage["status"] = "failed"
    _install_verifier(
        monkeypatch,
        {session_key.identifier: (manifest, quality)},
    )

    with pytest.raises(
        DatasetCatalogError,
        match="leakage validation failed",
    ):
        builder.build((session_key,))


@pytest.mark.parametrize(
    "field",
    [
        "future_weather_matches",
        "evaluation_season_rows",
    ],
)
def test_leakage_counts_must_be_zero(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    """Future or protected rows block catalog publication."""
    session_key = SessionKey(2024, 1)
    manifest, quality = _partition_documents(
        session_key
    )
    leakage = quality["leakage_validation"]

    assert isinstance(leakage, dict)

    leakage[field] = 1
    _install_verifier(
        monkeypatch,
        {session_key.identifier: (manifest, quality)},
    )

    with pytest.raises(
        DatasetCatalogError,
        match="leakage count is non-zero",
    ):
        builder.build((session_key,))


@pytest.mark.parametrize(
    "field",
    [
        "current_lap_timing_features",
        "current_lap_quality_features",
        "features_outside_allowlist",
    ],
)
def test_leakage_feature_lists_must_be_empty(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    """Detected forbidden features block catalog publication."""
    session_key = SessionKey(2024, 1)
    manifest, quality = _partition_documents(
        session_key
    )
    leakage = quality["leakage_validation"]

    assert isinstance(leakage, dict)

    leakage[field] = ["forbidden_column"]
    _install_verifier(
        monkeypatch,
        {session_key.identifier: (manifest, quality)},
    )

    with pytest.raises(
        DatasetCatalogError,
        match="must be empty",
    ):
        builder.build((session_key,))


@pytest.mark.parametrize(
    "invalid_value",
    [None, "", 0, False],
)
def test_leakage_feature_fields_must_be_lists(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
    invalid_value: object,
) -> None:
    """Leakage evidence uses explicit JSON arrays."""
    session_key = SessionKey(2024, 1)
    manifest, quality = _partition_documents(
        session_key
    )
    leakage = quality["leakage_validation"]

    assert isinstance(leakage, dict)

    leakage[
        "current_lap_timing_features"
    ] = invalid_value
    _install_verifier(
        monkeypatch,
        {session_key.identifier: (manifest, quality)},
    )

    with pytest.raises(
        DatasetCatalogError,
        match="must be a list",
    ):
        builder.build((session_key,))


@pytest.mark.parametrize(
    "invalid_value",
    [True, None, 0, "false"],
)
def test_protected_access_flag_must_be_false(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
    invalid_value: object,
) -> None:
    """Only literal false proves the holdout was not accessed."""
    session_key = SessionKey(2024, 1)
    manifest, quality = _partition_documents(
        session_key
    )
    leakage = quality["leakage_validation"]

    assert isinstance(leakage, dict)

    leakage[
        "protected_evaluation_season_accessed"
    ] = invalid_value
    _install_verifier(
        monkeypatch,
        {session_key.identifier: (manifest, quality)},
    )

    with pytest.raises(
        DatasetCatalogError,
        match="protected-season access",
    ):
        builder.build((session_key,))


@pytest.mark.parametrize(
    ("section", "field", "invalid_value"),
    [
        ("source_counts", "candidate_decision_rows", 5),
        ("decision_quality", "eligible_decisions", 2),
        (
            "decision_quality",
            "historical_pit_now_actions",
            0,
        ),
        (
            "target_quality",
            "lap_time_target_ineligible_rows",
            0,
        ),
        ("source_counts", "source_pit_events", 0),
        (
            "target_quality",
            "pit_duration_target_ineligible_rows",
            1,
        ),
    ],
)
def test_quality_counts_must_match_manifest_rows(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
    section: str,
    field: str,
    invalid_value: int,
) -> None:
    """Self-inconsistent quality metrics fail closed."""
    session_key = SessionKey(2024, 1)
    manifest, quality = _partition_documents(
        session_key
    )
    metrics = quality[section]

    assert isinstance(metrics, dict)

    metrics[field] = invalid_value
    _install_verifier(
        monkeypatch,
        {session_key.identifier: (manifest, quality)},
    )

    with pytest.raises(
        DatasetCatalogError,
        match="count mismatch",
    ):
        builder.build((session_key,))


def test_label_manifest_rows_must_match_decisions(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every decision must retain exactly one separated label."""
    session_key = SessionKey(2024, 1)
    manifest, quality = _partition_documents(
        session_key
    )
    files = manifest["files"]

    assert isinstance(files, dict)

    label_record = files[
        "decision_labels.parquet"
    ]

    assert isinstance(label_record, dict)

    label_record["rows"] = 5
    _install_verifier(
        monkeypatch,
        {session_key.identifier: (manifest, quality)},
    )

    with pytest.raises(
        DatasetCatalogError,
        match="decision labels count mismatch",
    ):
        builder.build((session_key,))


def test_session_requires_at_least_one_decision(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zero-decision partition is not catalog-authoritative."""
    session_key = SessionKey(2024, 1)
    manifest, quality = _partition_documents(
        session_key
    )
    files = manifest["files"]
    source_counts = quality["source_counts"]
    decision_quality = quality["decision_quality"]
    target_quality = quality["target_quality"]

    assert isinstance(files, dict)
    assert isinstance(source_counts, dict)
    assert isinstance(decision_quality, dict)
    assert isinstance(target_quality, dict)

    for filename in (
        "decision_rows.parquet",
        "decision_labels.parquet",
    ):
        record = files[filename]

        assert isinstance(record, dict)

        record["rows"] = 0

    source_counts["candidate_decision_rows"] = 0
    decision_quality["eligible_decisions"] = 0
    decision_quality["ineligible_decisions"] = 0
    decision_quality[
        "historical_pit_now_actions"
    ] = 0
    decision_quality[
        "historical_stay_out_actions"
    ] = 0
    target_quality[
        "lap_time_target_eligible_rows"
    ] = 0
    target_quality[
        "lap_time_target_ineligible_rows"
    ] = 0

    _install_verifier(
        monkeypatch,
        {session_key.identifier: (manifest, quality)},
    )

    with pytest.raises(
        DatasetCatalogError,
        match="must contain decisions",
    ):
        builder.build((session_key,))


@pytest.mark.parametrize(
    "invalid_value",
    [-1, True, 1.5, "1", None],
)
def test_catalog_counts_require_nonnegative_integers(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
    invalid_value: object,
) -> None:
    """Counts cannot silently accept booleans or coercions."""
    session_key = SessionKey(2024, 1)
    manifest, quality = _partition_documents(
        session_key
    )
    decision_quality = quality[
        "decision_quality"
    ]

    assert isinstance(decision_quality, dict)

    decision_quality[
        "eligible_decisions"
    ] = invalid_value
    _install_verifier(
        monkeypatch,
        {session_key.identifier: (manifest, quality)},
    )

    with pytest.raises(
        DatasetCatalogError,
        match="non-negative integer",
    ):
        builder.build((session_key,))


def test_manifest_file_records_must_be_objects(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stored-byte accounting rejects malformed records."""
    session_key = SessionKey(2024, 1)
    manifest, quality = _partition_documents(
        session_key
    )
    files = manifest["files"]

    assert isinstance(files, dict)

    files["quality_report.json"] = "invalid"
    _install_verifier(
        monkeypatch,
        {session_key.identifier: (manifest, quality)},
    )

    with pytest.raises(
        DatasetCatalogError,
        match="file record must be an object",
    ):
        builder.build((session_key,))


def test_manifest_requires_positive_stored_size(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed partition cannot claim zero stored bytes."""
    session_key = SessionKey(2024, 1)
    manifest, quality = _partition_documents(
        session_key
    )
    files = manifest["files"]

    assert isinstance(files, dict)

    for record in files.values():
        assert isinstance(record, dict)
        record["size_bytes"] = 0

    _install_verifier(
        monkeypatch,
        {session_key.identifier: (manifest, quality)},
    )

    with pytest.raises(
        DatasetCatalogError,
        match="must contain stored bytes",
    ):
        builder.build((session_key,))


def test_stale_temporary_catalog_is_replaced(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An obsolete temporary file cannot block publication."""
    _install_verifier(monkeypatch)
    temporary_path = (
        builder.dataset_paths.version_root
        / ".tmp"
        / CATALOG_CONTRACT.file_name
    )
    temporary_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    temporary_path.write_text(
        "stale",
        encoding="utf-8",
    )

    result = builder.build((SessionKey(2024, 1),))

    assert result.path.is_file()
    assert not temporary_path.exists()


def test_temporary_catalog_directory_fails_closed(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A directory cannot be mistaken for temporary Parquet."""
    _install_verifier(monkeypatch)
    temporary_path = (
        builder.dataset_paths.version_root
        / ".tmp"
        / CATALOG_CONTRACT.file_name
    )
    temporary_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    with pytest.raises(
        DatasetCatalogError,
        match="temporary catalog path is not a file",
    ):
        builder.build((SessionKey(2024, 1),))

    assert not builder.dataset_paths.catalog.exists()


def test_failed_readback_preserves_previous_catalog(
    builder: DatasetCatalogBuilder,
    session_keys: tuple[SessionKey, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bad readback never replaces the authoritative catalog."""
    _install_verifier(monkeypatch)
    original = builder.build(session_keys)
    original_sha256 = original.sha256
    real_reader = catalog_module.read_parquet_table

    def corrupt_readback(path: Path) -> pd.DataFrame:
        restored = real_reader(path)
        restored = restored.copy()
        restored.loc[0, "session_id"] = "CORRUPTED"
        return restored

    monkeypatch.setattr(
        catalog_module,
        "read_parquet_table",
        corrupt_readback,
    )

    with pytest.raises(
        DatasetCatalogError,
        match="readback differs",
    ):
        builder.build(session_keys)

    temporary_path = (
        builder.dataset_paths.version_root
        / ".tmp"
        / CATALOG_CONTRACT.file_name
    )

    assert builder.dataset_paths.catalog.is_file()
    assert sha256_file(
        builder.dataset_paths.catalog
    ) == original_sha256
    assert not temporary_path.exists()


def test_write_failure_removes_temporary_catalog(
    builder: DatasetCatalogBuilder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed publication leaves no partial temporary file."""
    _install_verifier(monkeypatch)

    def fail_write(
        _table: pd.DataFrame,
        path: Path,
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_bytes(b"partial")
        raise OSError("simulated write failure")

    monkeypatch.setattr(
        catalog_module,
        "write_parquet_table",
        fail_write,
    )

    with pytest.raises(
        OSError,
        match="simulated write failure",
    ):
        builder.build((SessionKey(2024, 1),))

    temporary_path = (
        builder.dataset_paths.version_root
        / ".tmp"
        / CATALOG_CONTRACT.file_name
    )

    assert not temporary_path.exists()
    assert not builder.dataset_paths.catalog.exists()


def test_catalog_seasons_remain_development_only(
    builder: DatasetCatalogBuilder,
    session_keys: tuple[SessionKey, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Published season values remain inside the frozen boundary."""
    _install_verifier(monkeypatch)

    catalog = builder.build(
        session_keys
    ).catalog

    assert set(catalog["season"]) == set(
        DEVELOPMENT_SEASONS
    )
    assert 2025 not in set(catalog["season"])