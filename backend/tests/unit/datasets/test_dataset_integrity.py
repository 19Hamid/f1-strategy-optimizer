"""Tests for read-only complete-dataset integrity verification."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import app.datasets.integrity as integrity_module
from app.datasets.contracts import (
    CATALOG_CONTRACT,
    DATASET_CONTRACT_VERSION,
    EXPECTED_DEVELOPMENT_TOTALS,
    EXPECTED_SEASON_TOTALS,
    SOURCE_CLEANING_RULE_VERSION,
    SOURCE_PROCESSED_CONTRACT_VERSION,
)
from app.datasets.integrity import (
    DatasetIntegrityError,
    DatasetIntegrityIssue,
    DatasetIntegrityIssueCode,
    DatasetIntegrityReport,
    _validate_session_keys,
    verify_complete_dataset,
)
from app.datasets.paths import DatasetPaths
from app.datasets.splits import build_temporal_splits
from app.datasets.storage import DatasetStorageError
from app.pipeline.models import SessionKey


@pytest.fixture
def development_session_keys() -> tuple[
    SessionKey,
    ...,
]:
    """Return the frozen 22/22/24 development schedule."""
    return tuple(
        SessionKey(
            season=season,
            round_number=round_number,
            session_type="R",
        )
        for season, session_count in (
            (2022, 22),
            (2023, 22),
            (2024, 24),
        )
        for round_number in range(
            1,
            session_count + 1,
        )
    )


@pytest.fixture
def dataset_paths(
    tmp_path: Path,
) -> DatasetPaths:
    """Return isolated modelling-dataset paths."""
    return DatasetPaths(
        tmp_path / "datasets"
    )


def _allocate(
    total: int,
    count: int,
) -> list[int]:
    """Distribute an integer total deterministically."""
    quotient, remainder = divmod(
        total,
        count,
    )

    return [
        quotient + int(index < remainder)
        for index in range(count)
    ]


def _synthetic_catalog(
    session_keys: tuple[SessionKey, ...],
) -> pd.DataFrame:
    """Build a contract-valid catalog with frozen totals."""
    expected = EXPECTED_DEVELOPMENT_TOTALS
    ineligible = _allocate(
        expected.ineligible_decisions,
        len(session_keys),
    )
    lap_targets = _allocate(
        expected.eligible_lap_targets,
        len(session_keys),
    )
    pit_durations = _allocate(
        expected.pit_duration_observations,
        len(session_keys),
    )
    eligible_pit_durations = _allocate(
        expected.eligible_pit_duration_targets,
        len(session_keys),
    )
    season_expectations = {
        total.season: total
        for total in EXPECTED_SEASON_TOTALS
    }
    eligible_by_id: dict[str, int] = {}
    pit_now_by_id: dict[str, int] = {}

    for season in (2022, 2023, 2024):
        keys_for_season = tuple(
            session_key
            for session_key in session_keys
            if session_key.season == season
        )
        season_expected = season_expectations[
            season
        ]
        eligible_values = _allocate(
            season_expected.eligible_decisions,
            len(keys_for_season),
        )
        pit_now_values = _allocate(
            season_expected.eligible_pit_now,
            len(keys_for_season),
        )

        for (
            session_key,
            eligible_value,
            pit_now_value,
        ) in zip(
            keys_for_season,
            eligible_values,
            pit_now_values,
            strict=True,
        ):
            eligible_by_id[
                session_key.identifier
            ] = eligible_value
            pit_now_by_id[
                session_key.identifier
            ] = pit_now_value

    records: list[dict[str, object]] = []

    for index, session_key in enumerate(
        session_keys
    ):
        eligible = eligible_by_id[
            session_key.identifier
        ]
        pit_now = pit_now_by_id[
            session_key.identifier
        ]
        decision_rows = (
            eligible + ineligible[index]
        )

        records.append(
            {
                "session_id": (
                    session_key.identifier
                ),
                "season": session_key.season,
                "round_number": (
                    session_key.round_number
                ),
                "session_type": (
                    session_key.session_type
                ),
                "event_name": (
                    f"Synthetic {session_key.identifier}"
                ),
                "dataset_contract_version": (
                    DATASET_CONTRACT_VERSION
                ),
                "cleaning_rule_version": (
                    SOURCE_CLEANING_RULE_VERSION
                ),
                "processed_contract_version": (
                    SOURCE_PROCESSED_CONTRACT_VERSION
                ),
                "created_at_utc": (
                    "2026-09-04T00:00:00Z"
                ),
                "decision_rows": decision_rows,
                "eligible_decisions": eligible,
                "ineligible_decisions": (
                    ineligible[index]
                ),
                "decision_label_rows": (
                    decision_rows
                ),
                "lap_time_target_eligible_rows": (
                    lap_targets[index]
                ),
                "pit_now_rows": pit_now,
                "stay_out_rows": (
                    eligible - pit_now
                ),
                "pit_duration_rows": (
                    pit_durations[index]
                ),
                "pit_duration_target_eligible_rows": (
                    eligible_pit_durations[index]
                ),
                "total_size_bytes": (
                    1000 + index
                ),
                "session_directory": (
                    "dataset_contract_version=1.0/"
                    f"season={session_key.season}/"
                    "round="
                    f"{session_key.round_number:02d}/"
                    "session=R"
                ),
            }
        )

    catalog = pd.DataFrame.from_records(
        records,
        columns=[
            column.name
            for column in CATALOG_CONTRACT.columns
        ],
    )

    for column in CATALOG_CONTRACT.columns:
        catalog[column.name] = catalog[
            column.name
        ].astype(
            column.pandas_dtype
        )

    return catalog


def _prepare_synthetic_dataset(
    *,
    dataset_paths: DatasetPaths,
    session_keys: tuple[SessionKey, ...],
    monkeypatch: pytest.MonkeyPatch,
    missing_session: SessionKey | None = None,
    invalid_session: SessionKey | None = None,
    include_catalog: bool = True,
    include_splits: bool = True,
    catalog: pd.DataFrame | None = None,
    splits: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create lightweight paths and patch expensive validation."""
    dataset_paths.version_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    for session_key in session_keys:
        if session_key == missing_session:
            continue

        dataset_paths.for_session(
            session_key
        ).directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    catalog_frame = (
        catalog.copy(deep=True)
        if catalog is not None
        else _synthetic_catalog(session_keys)
    )
    split_frame = (
        splits.copy(deep=True)
        if splits is not None
        else build_temporal_splits(
            session_keys
        ).splits
    )

    if include_catalog:
        dataset_paths.catalog.write_bytes(
            b"synthetic-catalog"
        )

    if include_splits:
        dataset_paths.splits.write_bytes(
            b"synthetic-splits"
        )

    def fake_partition_validation(
        session_paths: object,
    ) -> tuple[
        dict[str, object],
        dict[str, object],
    ]:
        if (
            invalid_session is not None
            and session_paths.directory
            == dataset_paths.for_session(
                invalid_session
            ).directory
        ):
            raise DatasetStorageError(
                "synthetic checksum mismatch"
            )

        return (
            {"validation": "passed"},
            {"validation": "passed"},
        )

    def fake_read(path: Path) -> pd.DataFrame:
        if path == dataset_paths.catalog:
            return catalog_frame.copy(
                deep=True
            )

        if path == dataset_paths.splits:
            return split_frame.copy(
                deep=True
            )

        raise AssertionError(
            f"unexpected read: {path}"
        )

    monkeypatch.setattr(
        integrity_module,
        "_validate_completed_partition",
        fake_partition_validation,
    )
    monkeypatch.setattr(
        integrity_module,
        "read_parquet_table",
        fake_read,
    )
    monkeypatch.setattr(
        integrity_module,
        "_build_expected_catalog",
        lambda **kwargs: catalog_frame.copy(
            deep=True
        ),
    )

    return catalog_frame, split_frame


def _issue_codes(
    report: DatasetIntegrityReport,
) -> list[DatasetIntegrityIssueCode]:
    """Return issue codes in their reported order."""
    return [
        issue.code
        for issue in report.issues
    ]


def test_issue_document_is_json_safe(
    tmp_path: Path,
) -> None:
    """Integrity issues expose stable serialized fields."""
    issue = DatasetIntegrityIssue(
        code=(
            DatasetIntegrityIssueCode
            .INVALID_SESSION_PARTITION
        ),
        message="checksum failed",
        path=tmp_path / "session",
        session_id="2024-01-R",
    )

    assert issue.to_document() == {
        "code": "INVALID_SESSION_PARTITION",
        "message": "checksum failed",
        "path": str(tmp_path / "session"),
        "session_id": "2024-01-R",
    }


def test_valid_report_properties(
    tmp_path: Path,
) -> None:
    """A report without issues is valid and does not raise."""
    report = DatasetIntegrityReport(
        directory=tmp_path,
        requested_sessions=68,
        valid_sessions=68,
        catalog_rows=68,
        split_rows=204,
        issues=(),
    )

    assert report.is_valid
    assert report.issue_count == 0
    assert report.raise_for_errors() is None


def test_invalid_report_raises_deterministic_summary(
    tmp_path: Path,
) -> None:
    """Every issue is included in the raised summary."""
    report = DatasetIntegrityReport(
        directory=tmp_path,
        requested_sessions=68,
        valid_sessions=67,
        catalog_rows=0,
        split_rows=0,
        issues=(
            DatasetIntegrityIssue(
                code=(
                    DatasetIntegrityIssueCode
                    .MISSING_CATALOG
                ),
                message="catalog missing",
                path=tmp_path / "catalog.parquet",
            ),
            DatasetIntegrityIssue(
                code=(
                    DatasetIntegrityIssueCode
                    .MISSING_SPLITS
                ),
                message="splits missing",
                path=tmp_path / "splits.parquet",
            ),
        ),
    )

    assert not report.is_valid
    assert report.issue_count == 2

    with pytest.raises(
        DatasetIntegrityError,
        match=(
            "MISSING_CATALOG: catalog missing; "
            "MISSING_SPLITS: splits missing"
        ),
    ):
        report.raise_for_errors()


def test_verifier_rejects_invalid_dataset_paths(
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
) -> None:
    """Verification requires concrete versioned paths."""
    with pytest.raises(
        TypeError,
        match="dataset_paths must be DatasetPaths",
    ):
        verify_complete_dataset(
            object(),  # type: ignore[arg-type]
            development_session_keys,
        )


@pytest.mark.parametrize(
    "invalid",
    ("sessions", b"sessions", 123, None),
)
def test_schedule_rejects_non_iterables(
    invalid: object,
) -> None:
    """The expected schedule must be an iterable."""
    with pytest.raises(TypeError):
        _validate_session_keys(
            invalid  # type: ignore[arg-type]
        )


def test_schedule_rejects_empty_input() -> None:
    """Complete verification cannot use an empty schedule."""
    with pytest.raises(
        DatasetIntegrityError,
        match="at least one session key is required",
    ):
        _validate_session_keys(())


def test_schedule_rejects_invalid_item(
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
) -> None:
    """Every schedule item must be a SessionKey."""
    invalid = (
        *development_session_keys[:-1],
        object(),
    )

    with pytest.raises(
        TypeError,
        match="every requested session must be a SessionKey",
    ):
        _validate_session_keys(
            invalid  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "season",
    (2021, 2025),
)
def test_schedule_rejects_non_development_season(
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    season: int,
) -> None:
    """Protected and unsupported seasons fail before access."""
    invalid = (
        *development_session_keys[:-1],
        SessionKey(
            season=season,
            round_number=24,
            session_type="R",
        ),
    )

    with pytest.raises(
        DatasetIntegrityError,
        match="outside the development seasons",
    ):
        _validate_session_keys(invalid)


def test_schedule_rejects_duplicates(
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
) -> None:
    """Duplicate sessions cannot fake complete coverage."""
    invalid = (
        *development_session_keys,
        development_session_keys[0],
    )

    with pytest.raises(
        DatasetIntegrityError,
        match="duplicate session keys",
    ):
        _validate_session_keys(invalid)


@pytest.mark.parametrize(
    "count",
    (1, 67, 69),
)
def test_schedule_requires_exact_session_total(
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    count: int,
) -> None:
    """Complete integrity always covers exactly 68 races."""
    if count <= 68:
        invalid = development_session_keys[:count]
    else:
        invalid = (
            *development_session_keys,
            SessionKey(
                season=2024,
                round_number=25,
                session_type="R",
            ),
        )

    with pytest.raises(
        DatasetIntegrityError,
        match="requires exactly 68 sessions",
    ):
        _validate_session_keys(invalid)


def test_schedule_requires_exact_season_counts(
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
) -> None:
    """A 68-session input must retain 22/22/24 coverage."""
    invalid = (
        *development_session_keys[:-1],
        SessionKey(
            season=2023,
            round_number=23,
            session_type="R",
        ),
    )

    with pytest.raises(
        DatasetIntegrityError,
        match="season counts differ from the contract",
    ):
        _validate_session_keys(invalid)


def test_schedule_is_sorted_deterministically(
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
) -> None:
    """Verification order is independent of caller order."""
    assert _validate_session_keys(
        reversed(development_session_keys)
    ) == development_session_keys


def test_missing_version_directory_returns_single_issue(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
) -> None:
    """An absent dataset is reported without 68 noisy failures."""
    report = verify_complete_dataset(
        dataset_paths,
        development_session_keys,
    )

    assert not report.is_valid
    assert report.requested_sessions == 68
    assert report.valid_sessions == 0
    assert report.catalog_rows == 0
    assert report.split_rows == 0
    assert _issue_codes(report) == [
        DatasetIntegrityIssueCode
        .MISSING_VERSION_DIRECTORY
    ]


def test_complete_synthetic_dataset_is_valid(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All complete session and global checks can pass together."""
    _prepare_synthetic_dataset(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        monkeypatch=monkeypatch,
    )

    report = verify_complete_dataset(
        dataset_paths,
        reversed(development_session_keys),
    )

    assert report.is_valid
    assert report.issue_count == 0
    assert report.requested_sessions == 68
    assert report.valid_sessions == 68
    assert report.catalog_rows == 68
    assert report.split_rows == 204


def test_protected_season_directory_is_detected(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any stored 2025 directory breaks development integrity."""
    _prepare_synthetic_dataset(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        monkeypatch=monkeypatch,
    )
    protected = (
        dataset_paths.version_root
        / "season=2025"
    )
    protected.mkdir()

    report = verify_complete_dataset(
        dataset_paths,
        development_session_keys,
    )

    assert DatasetIntegrityIssueCode.PROTECTED_SEASON_DIRECTORY in (
        _issue_codes(report)
    )


def test_unexpected_session_directory_is_detected(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An extra partition cannot hide outside the catalog."""
    _prepare_synthetic_dataset(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        monkeypatch=monkeypatch,
    )
    unexpected = (
        dataset_paths.version_root
        / "season=2024"
        / "round=25"
        / "session=R"
    )
    unexpected.mkdir(parents=True)

    report = verify_complete_dataset(
        dataset_paths,
        development_session_keys,
    )

    issues = [
        issue
        for issue in report.issues
        if issue.code
        == DatasetIntegrityIssueCode
        .UNEXPECTED_SESSION_DIRECTORY
    ]
    assert len(issues) == 1
    assert issues[0].path == unexpected


@pytest.mark.parametrize(
    ("directory_name", "expected_code"),
    (
        (
            ".tmp",
            DatasetIntegrityIssueCode
            .TEMPORARY_ARTIFACTS_PRESENT,
        ),
        (
            ".backup",
            DatasetIntegrityIssueCode
            .BACKUP_ARTIFACTS_PRESENT,
        ),
    ),
)
def test_leftover_internal_artifacts_are_detected(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
    directory_name: str,
    expected_code: DatasetIntegrityIssueCode,
) -> None:
    """Non-empty temporary and backup roots invalidate storage."""
    _prepare_synthetic_dataset(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        monkeypatch=monkeypatch,
    )
    internal = (
        dataset_paths.version_root
        / directory_name
    )
    internal.mkdir(exist_ok=True)
    (internal / "leftover").write_text(
        "partial",
        encoding="utf-8",
    )

    report = verify_complete_dataset(
        dataset_paths,
        development_session_keys,
    )

    assert expected_code in _issue_codes(report)


def test_empty_internal_directories_are_allowed(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty operational roots are harmless after publication."""
    _prepare_synthetic_dataset(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        monkeypatch=monkeypatch,
    )
    (
        dataset_paths.version_root
        / ".tmp"
    ).mkdir(exist_ok=True)
    (
        dataset_paths.version_root
        / ".backup"
    ).mkdir(exist_ok=True)

    report = verify_complete_dataset(
        dataset_paths,
        development_session_keys,
    )

    assert report.is_valid


def test_missing_session_directory_is_detected(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every expected race must have an authoritative partition."""
    missing = development_session_keys[7]
    _prepare_synthetic_dataset(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        monkeypatch=monkeypatch,
        missing_session=missing,
    )

    report = verify_complete_dataset(
        dataset_paths,
        development_session_keys,
    )

    missing_issues = [
        issue
        for issue in report.issues
        if issue.code
        == DatasetIntegrityIssueCode
        .MISSING_SESSION_DIRECTORY
    ]
    assert report.valid_sessions == 67
    assert len(missing_issues) == 1
    assert missing_issues[0].session_id == (
        missing.identifier
    )


def test_invalid_session_partition_is_detected(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session checksum failures become structured issues."""
    invalid = development_session_keys[12]
    _prepare_synthetic_dataset(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        monkeypatch=monkeypatch,
        invalid_session=invalid,
    )

    report = verify_complete_dataset(
        dataset_paths,
        development_session_keys,
    )

    invalid_issues = [
        issue
        for issue in report.issues
        if issue.code
        == DatasetIntegrityIssueCode
        .INVALID_SESSION_PARTITION
    ]
    assert report.valid_sessions == 67
    assert len(invalid_issues) == 1
    assert invalid_issues[0].session_id == (
        invalid.identifier
    )
    assert "synthetic checksum mismatch" in (
        invalid_issues[0].message
    )


def test_missing_catalog_is_detected(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A complete dataset requires its global catalog."""
    _prepare_synthetic_dataset(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        monkeypatch=monkeypatch,
        include_catalog=False,
    )

    report = verify_complete_dataset(
        dataset_paths,
        development_session_keys,
    )

    assert report.catalog_rows == 0
    assert DatasetIntegrityIssueCode.MISSING_CATALOG in (
        _issue_codes(report)
    )


def test_unreadable_catalog_is_detected(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog read failures become invalid-catalog issues."""
    _prepare_synthetic_dataset(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        monkeypatch=monkeypatch,
    )
    original_read = integrity_module.read_parquet_table

    def fail_catalog_read(
        path: Path,
    ) -> pd.DataFrame:
        if path == dataset_paths.catalog:
            raise OSError("catalog unreadable")

        return original_read(path)

    monkeypatch.setattr(
        integrity_module,
        "read_parquet_table",
        fail_catalog_read,
    )

    report = verify_complete_dataset(
        dataset_paths,
        development_session_keys,
    )

    assert report.catalog_rows == 0
    assert DatasetIntegrityIssueCode.INVALID_CATALOG in (
        _issue_codes(report)
    )


def test_invalid_catalog_schema_is_detected(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog columns must exactly match the executable contract."""
    invalid_catalog = _synthetic_catalog(
        development_session_keys
    ).drop(
        columns="session_directory"
    )
    _prepare_synthetic_dataset(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        monkeypatch=monkeypatch,
        catalog=invalid_catalog,
    )

    report = verify_complete_dataset(
        dataset_paths,
        development_session_keys,
    )

    assert report.catalog_rows == 0
    assert DatasetIntegrityIssueCode.INVALID_CATALOG in (
        _issue_codes(report)
    )


def test_catalog_session_content_mismatch_is_detected(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stored catalog values must match verified manifests."""
    catalog, _ = _prepare_synthetic_dataset(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        monkeypatch=monkeypatch,
    )
    expected_catalog = catalog.copy(
        deep=True
    )
    expected_catalog.loc[
        0,
        "created_at_utc",
    ] = "2026-09-04T01:00:00Z"
    monkeypatch.setattr(
        integrity_module,
        "_build_expected_catalog",
        lambda **kwargs: expected_catalog,
    )

    report = verify_complete_dataset(
        dataset_paths,
        development_session_keys,
    )

    assert (
        DatasetIntegrityIssueCode
        .CATALOG_CONTENT_MISMATCH
        in _issue_codes(report)
    )


def test_catalog_total_mismatch_is_detected(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Frozen development totals are verified independently."""
    catalog = _synthetic_catalog(
        development_session_keys
    )
    catalog.loc[0, "decision_rows"] += 1
    catalog.loc[0, "decision_label_rows"] += 1
    _prepare_synthetic_dataset(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        monkeypatch=monkeypatch,
        catalog=catalog,
    )

    report = verify_complete_dataset(
        dataset_paths,
        development_session_keys,
    )

    matching = [
        issue
        for issue in report.issues
        if issue.code
        == DatasetIntegrityIssueCode
        .CATALOG_CONTENT_MISMATCH
        and "development totals" in issue.message
    ]
    assert len(matching) == 1


def test_catalog_season_total_mismatch_is_detected(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-season eligible totals cannot drift between races."""
    catalog = _synthetic_catalog(
        development_session_keys
    )
    first_2022 = catalog.index[
        catalog["season"].eq(2022)
    ][0]
    first_2023 = catalog.index[
        catalog["season"].eq(2023)
    ][0]
    catalog.loc[
        first_2022,
        "eligible_decisions",
    ] -= 1
    catalog.loc[
        first_2022,
        "stay_out_rows",
    ] -= 1
    catalog.loc[
        first_2023,
        "eligible_decisions",
    ] += 1
    catalog.loc[
        first_2023,
        "stay_out_rows",
    ] += 1
    _prepare_synthetic_dataset(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        monkeypatch=monkeypatch,
        catalog=catalog,
    )

    report = verify_complete_dataset(
        dataset_paths,
        development_session_keys,
    )

    matching = [
        issue
        for issue in report.issues
        if issue.code
        == DatasetIntegrityIssueCode
        .CATALOG_CONTENT_MISMATCH
        and "season totals" in issue.message
    ]
    assert len(matching) == 1


def test_missing_splits_are_detected(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The complete dataset requires frozen temporal assignments."""
    _prepare_synthetic_dataset(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        monkeypatch=monkeypatch,
        include_splits=False,
    )

    report = verify_complete_dataset(
        dataset_paths,
        development_session_keys,
    )

    assert report.split_rows == 0
    assert DatasetIntegrityIssueCode.MISSING_SPLITS in (
        _issue_codes(report)
    )


def test_unreadable_splits_are_detected(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Split read failures become structured issues."""
    _prepare_synthetic_dataset(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        monkeypatch=monkeypatch,
    )
    original_read = integrity_module.read_parquet_table

    def fail_split_read(
        path: Path,
    ) -> pd.DataFrame:
        if path == dataset_paths.splits:
            raise OSError("splits unreadable")

        return original_read(path)

    monkeypatch.setattr(
        integrity_module,
        "read_parquet_table",
        fail_split_read,
    )

    report = verify_complete_dataset(
        dataset_paths,
        development_session_keys,
    )

    assert report.split_rows == 0
    assert DatasetIntegrityIssueCode.INVALID_SPLITS in (
        _issue_codes(report)
    )


def test_invalid_split_assignments_are_detected(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every frozen fold must contain every session once."""
    invalid_splits = build_temporal_splits(
        development_session_keys
    ).splits.iloc[:-1].copy()
    _prepare_synthetic_dataset(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        monkeypatch=monkeypatch,
        splits=invalid_splits,
    )

    report = verify_complete_dataset(
        dataset_paths,
        development_session_keys,
    )

    assert report.split_rows == 0
    assert DatasetIntegrityIssueCode.INVALID_SPLITS in (
        _issue_codes(report)
    )


def test_verification_does_not_modify_existing_files(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read-only verification leaves global artifact bytes intact."""
    _prepare_synthetic_dataset(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        monkeypatch=monkeypatch,
    )
    catalog_before = dataset_paths.catalog.read_bytes()
    splits_before = dataset_paths.splits.read_bytes()

    report = verify_complete_dataset(
        dataset_paths,
        development_session_keys,
    )

    assert report.is_valid
    assert (
        dataset_paths.catalog.read_bytes()
        == catalog_before
    )
    assert (
        dataset_paths.splits.read_bytes()
        == splits_before
    )