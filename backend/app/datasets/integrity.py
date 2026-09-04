"""Verify complete stored modelling datasets without modifying them."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import pandas as pd

from app.datasets.catalog import (
    _build_catalog_frame,
    _build_catalog_row,
    _validate_catalog,
)
from app.datasets.contracts import (
    DEVELOPMENT_SEASONS,
    EXPECTED_DEVELOPMENT_TOTALS,
    EXPECTED_SEASON_TOTALS,
)
from app.datasets.paths import DatasetPaths
from app.datasets.splits import (
    validate_temporal_splits,
)
from app.datasets.storage import (
    _validate_completed_partition,
)
from app.pipeline.models import SessionKey
from app.pipeline.serialization import read_parquet_table


class DatasetIntegrityIssueCode(StrEnum):
    """Stable complete-dataset integrity issue codes."""

    MISSING_VERSION_DIRECTORY = (
        "MISSING_VERSION_DIRECTORY"
    )
    PROTECTED_SEASON_DIRECTORY = (
        "PROTECTED_SEASON_DIRECTORY"
    )
    UNEXPECTED_SESSION_DIRECTORY = (
        "UNEXPECTED_SESSION_DIRECTORY"
    )
    TEMPORARY_ARTIFACTS_PRESENT = (
        "TEMPORARY_ARTIFACTS_PRESENT"
    )
    BACKUP_ARTIFACTS_PRESENT = (
        "BACKUP_ARTIFACTS_PRESENT"
    )
    MISSING_SESSION_DIRECTORY = (
        "MISSING_SESSION_DIRECTORY"
    )
    INVALID_SESSION_PARTITION = (
        "INVALID_SESSION_PARTITION"
    )
    MISSING_CATALOG = "MISSING_CATALOG"
    INVALID_CATALOG = "INVALID_CATALOG"
    CATALOG_CONTENT_MISMATCH = (
        "CATALOG_CONTENT_MISMATCH"
    )
    MISSING_SPLITS = "MISSING_SPLITS"
    INVALID_SPLITS = "INVALID_SPLITS"


@dataclass(frozen=True, slots=True)
class DatasetIntegrityIssue:
    """Describe one complete-dataset integrity failure."""

    code: DatasetIntegrityIssueCode
    message: str
    path: Path
    session_id: str | None = None

    def to_document(self) -> dict[str, object]:
        """Return a JSON-safe issue representation."""
        return {
            "code": self.code.value,
            "message": self.message,
            "path": str(self.path),
            "session_id": self.session_id,
        }


class DatasetIntegrityError(RuntimeError):
    """Raised when a complete dataset fails integrity."""


@dataclass(frozen=True, slots=True)
class DatasetIntegrityReport:
    """Summarize read-only validation of one dataset version."""

    directory: Path
    requested_sessions: int
    valid_sessions: int
    catalog_rows: int
    split_rows: int
    issues: tuple[DatasetIntegrityIssue, ...]

    @property
    def is_valid(self) -> bool:
        """Return whether every integrity requirement passed."""
        return not self.issues

    @property
    def issue_count(self) -> int:
        """Return the number of detected integrity issues."""
        return len(self.issues)

    def raise_for_errors(self) -> None:
        """Raise one deterministic summary when invalid."""
        if self.is_valid:
            return

        details = "; ".join(
            (
                f"{issue.code.value}: "
                f"{issue.message}"
            )
            for issue in self.issues
        )

        raise DatasetIntegrityError(
            "dataset integrity failed: "
            f"{details}"
        )


def verify_complete_dataset(
    dataset_paths: DatasetPaths,
    session_keys: Iterable[SessionKey],
) -> DatasetIntegrityReport:
    """Verify all session and global artifacts without writes."""
    if not isinstance(
        dataset_paths,
        DatasetPaths,
    ):
        raise TypeError(
            "dataset_paths must be DatasetPaths"
        )

    requested_sessions = _validate_session_keys(
        session_keys
    )
    version_root = dataset_paths.version_root

    if not version_root.is_dir():
        return DatasetIntegrityReport(
            directory=version_root,
            requested_sessions=len(
                requested_sessions
            ),
            valid_sessions=0,
            catalog_rows=0,
            split_rows=0,
            issues=(
                DatasetIntegrityIssue(
                    code=(
                        DatasetIntegrityIssueCode
                        .MISSING_VERSION_DIRECTORY
                    ),
                    message=(
                        "dataset version directory does not exist"
                    ),
                    path=version_root,
                ),
            ),
        )

    issues: list[DatasetIntegrityIssue] = []
    _validate_directory_boundaries(
        dataset_paths=dataset_paths,
        session_keys=requested_sessions,
        issues=issues,
    )

    valid_sessions = _validate_session_partitions(
        dataset_paths=dataset_paths,
        session_keys=requested_sessions,
        issues=issues,
    )

    catalog, catalog_rows = _validate_stored_catalog(
        dataset_paths=dataset_paths,
        session_keys=requested_sessions,
        sessions_are_valid=(
            valid_sessions
            == len(requested_sessions)
        ),
        issues=issues,
    )

    split_rows = _validate_stored_splits(
        dataset_paths=dataset_paths,
        session_keys=requested_sessions,
        issues=issues,
    )

    if catalog is not None:
        _validate_expected_catalog_totals(
            catalog,
            dataset_paths=dataset_paths,
            issues=issues,
        )

    return DatasetIntegrityReport(
        directory=version_root,
        requested_sessions=len(
            requested_sessions
        ),
        valid_sessions=valid_sessions,
        catalog_rows=catalog_rows,
        split_rows=split_rows,
        issues=tuple(issues),
    )


def _validate_directory_boundaries(
    *,
    dataset_paths: DatasetPaths,
    session_keys: tuple[SessionKey, ...],
    issues: list[DatasetIntegrityIssue],
) -> None:
    """Detect protected, unexpected and temporary directories."""
    protected_directory = (
        dataset_paths.version_root
        / "season=2025"
    )

    if protected_directory.exists():
        issues.append(
            DatasetIntegrityIssue(
                code=(
                    DatasetIntegrityIssueCode
                    .PROTECTED_SEASON_DIRECTORY
                ),
                message=(
                    "protected evaluation season exists "
                    "inside the development dataset"
                ),
                path=protected_directory,
            )
        )

    expected_directories = {
        dataset_paths.for_session(
            session_key
        ).directory
        for session_key in session_keys
    }
    actual_directories = {
        path
        for path in dataset_paths.version_root.glob(
            "season=*/round=*/session=*"
        )
        if path.is_dir()
    }

    for unexpected in sorted(
        actual_directories - expected_directories,
        key=str,
    ):
        issues.append(
            DatasetIntegrityIssue(
                code=(
                    DatasetIntegrityIssueCode
                    .UNEXPECTED_SESSION_DIRECTORY
                ),
                message=(
                    "session directory is outside the "
                    "frozen development schedule"
                ),
                path=unexpected,
            )
        )

    temporary_directory = (
        dataset_paths.version_root
        / ".tmp"
    )
    temporary_entries = _directory_entries(
        temporary_directory
    )

    if temporary_entries:
        issues.append(
            DatasetIntegrityIssue(
                code=(
                    DatasetIntegrityIssueCode
                    .TEMPORARY_ARTIFACTS_PRESENT
                ),
                message=(
                    "temporary dataset artifacts remain: "
                    f"{len(temporary_entries)}"
                ),
                path=temporary_directory,
            )
        )

    backup_directory = (
        dataset_paths.version_root
        / ".backup"
    )
    backup_entries = _directory_entries(
        backup_directory
    )

    if backup_entries:
        issues.append(
            DatasetIntegrityIssue(
                code=(
                    DatasetIntegrityIssueCode
                    .BACKUP_ARTIFACTS_PRESENT
                ),
                message=(
                    "backup dataset artifacts remain: "
                    f"{len(backup_entries)}"
                ),
                path=backup_directory,
            )
        )


def _directory_entries(
    directory: Path,
) -> tuple[Path, ...]:
    """Return deterministic direct children when a directory exists."""
    if not directory.is_dir():
        return ()

    return tuple(
        sorted(
            directory.iterdir(),
            key=str,
        )
    )


def _validate_session_partitions(
    *,
    dataset_paths: DatasetPaths,
    session_keys: tuple[SessionKey, ...],
    issues: list[DatasetIntegrityIssue],
) -> int:
    """Verify every expected atomic session partition."""
    valid_sessions = 0

    for session_key in session_keys:
        session_paths = dataset_paths.for_session(
            session_key
        )

        if not session_paths.directory.is_dir():
            issues.append(
                DatasetIntegrityIssue(
                    code=(
                        DatasetIntegrityIssueCode
                        .MISSING_SESSION_DIRECTORY
                    ),
                    message=(
                        "expected dataset session directory "
                        "does not exist"
                    ),
                    path=session_paths.directory,
                    session_id=(
                        session_key.identifier
                    ),
                )
            )
            continue

        try:
            _validate_completed_partition(
                session_paths
            )
        except Exception as error:  # noqa: BLE001
            issues.append(
                DatasetIntegrityIssue(
                    code=(
                        DatasetIntegrityIssueCode
                        .INVALID_SESSION_PARTITION
                    ),
                    message=(
                        f"{type(error).__name__}: "
                        f"{error}"
                    ),
                    path=session_paths.directory,
                    session_id=(
                        session_key.identifier
                    ),
                )
            )
            continue

        valid_sessions += 1

    return valid_sessions


def _validate_stored_catalog(
    *,
    dataset_paths: DatasetPaths,
    session_keys: tuple[SessionKey, ...],
    sessions_are_valid: bool,
    issues: list[DatasetIntegrityIssue],
) -> tuple[pd.DataFrame | None, int]:
    """Verify the stored catalog and its session-derived contents."""
    if not dataset_paths.catalog.is_file():
        issues.append(
            DatasetIntegrityIssue(
                code=(
                    DatasetIntegrityIssueCode
                    .MISSING_CATALOG
                ),
                message=(
                    "dataset catalog does not exist"
                ),
                path=dataset_paths.catalog,
            )
        )
        return None, 0

    try:
        catalog = read_parquet_table(
            dataset_paths.catalog
        )
        _validate_catalog(
            catalog=catalog,
            expected_sessions=session_keys,
        )
    except Exception as error:  # noqa: BLE001
        issues.append(
            DatasetIntegrityIssue(
                code=(
                    DatasetIntegrityIssueCode
                    .INVALID_CATALOG
                ),
                message=(
                    f"{type(error).__name__}: "
                    f"{error}"
                ),
                path=dataset_paths.catalog,
            )
        )
        return None, 0

    if sessions_are_valid:
        try:
            expected_catalog = (
                _build_expected_catalog(
                    dataset_paths=dataset_paths,
                    session_keys=session_keys,
                )
            )
            pd.testing.assert_frame_equal(
                catalog,
                expected_catalog,
            )
        except Exception as error:  # noqa: BLE001
            issues.append(
                DatasetIntegrityIssue(
                    code=(
                        DatasetIntegrityIssueCode
                        .CATALOG_CONTENT_MISMATCH
                    ),
                    message=(
                        "catalog differs from verified "
                        "session manifests: "
                        f"{type(error).__name__}: "
                        f"{error}"
                    ),
                    path=dataset_paths.catalog,
                )
            )

    return catalog, len(catalog)


def _build_expected_catalog(
    *,
    dataset_paths: DatasetPaths,
    session_keys: tuple[SessionKey, ...],
) -> pd.DataFrame:
    """Reconstruct the expected catalog entirely in memory."""
    rows = [
        _build_catalog_row(
            dataset_paths=dataset_paths,
            session_key=session_key,
        )
        for session_key in session_keys
    ]
    expected = _build_catalog_frame(rows)
    _validate_catalog(
        catalog=expected,
        expected_sessions=session_keys,
    )
    return expected


def _validate_stored_splits(
    *,
    dataset_paths: DatasetPaths,
    session_keys: tuple[SessionKey, ...],
    issues: list[DatasetIntegrityIssue],
) -> int:
    """Verify the frozen temporal split artifact."""
    if not dataset_paths.splits.is_file():
        issues.append(
            DatasetIntegrityIssue(
                code=(
                    DatasetIntegrityIssueCode
                    .MISSING_SPLITS
                ),
                message=(
                    "temporal split table does not exist"
                ),
                path=dataset_paths.splits,
            )
        )
        return 0

    try:
        splits = read_parquet_table(
            dataset_paths.splits
        )
        report = validate_temporal_splits(
            splits,
            session_keys,
        )
        report.raise_for_errors()
    except Exception as error:  # noqa: BLE001
        issues.append(
            DatasetIntegrityIssue(
                code=(
                    DatasetIntegrityIssueCode
                    .INVALID_SPLITS
                ),
                message=(
                    f"{type(error).__name__}: "
                    f"{error}"
                ),
                path=dataset_paths.splits,
            )
        )
        return 0

    return len(splits)


def _validate_expected_catalog_totals(
    catalog: pd.DataFrame,
    *,
    dataset_paths: DatasetPaths,
    issues: list[DatasetIntegrityIssue],
) -> None:
    """Require frozen development row and season totals."""
    expected = EXPECTED_DEVELOPMENT_TOTALS
    expected_totals = {
        "decision_rows": (
            expected.candidate_decisions
        ),
        "decision_label_rows": (
            expected.candidate_decisions
        ),
        "eligible_decisions": (
            expected.eligible_decisions
        ),
        "ineligible_decisions": (
            expected.ineligible_decisions
        ),
        "pit_now_rows": expected.eligible_pit_now,
        "stay_out_rows": (
            expected.eligible_stay_out
        ),
        "lap_time_target_eligible_rows": (
            expected.eligible_lap_targets
        ),
        "pit_duration_rows": (
            expected.pit_duration_observations
        ),
        "pit_duration_target_eligible_rows": (
            expected.eligible_pit_duration_targets
        ),
    }

    actual_totals = {
        column: int(catalog[column].sum())
        for column in expected_totals
    }

    if actual_totals != expected_totals:
        issues.append(
            DatasetIntegrityIssue(
                code=(
                    DatasetIntegrityIssueCode
                    .CATALOG_CONTENT_MISMATCH
                ),
                message=(
                    "catalog development totals differ from "
                    f"the contract: expected {expected_totals}, "
                    f"got {actual_totals}"
                ),
                path=dataset_paths.catalog,
            )
        )

    expected_seasons = {
        total.season: {
            "sessions": total.sessions,
            "eligible_decisions": (
                total.eligible_decisions
            ),
            "eligible_pit_now": (
                total.eligible_pit_now
            ),
        }
        for total in EXPECTED_SEASON_TOTALS
    }
    actual_seasons: dict[
        int,
        dict[str, int],
    ] = {}

    for season, rows in catalog.groupby(
        "season",
        sort=True,
    ):
        actual_seasons[int(season)] = {
            "sessions": len(rows),
            "eligible_decisions": int(
                rows[
                    "eligible_decisions"
                ].sum()
            ),
            "eligible_pit_now": int(
                rows[
                    "pit_now_rows"
                ].sum()
            ),
        }

    if actual_seasons != expected_seasons:
        issues.append(
            DatasetIntegrityIssue(
                code=(
                    DatasetIntegrityIssueCode
                    .CATALOG_CONTENT_MISMATCH
                ),
                message=(
                    "catalog season totals differ from "
                    f"the contract: expected {expected_seasons}, "
                    f"got {actual_seasons}"
                ),
                path=dataset_paths.catalog,
            )
        )


def _validate_session_keys(
    session_keys: Iterable[SessionKey],
) -> tuple[SessionKey, ...]:
    """Require the exact frozen development-session coverage."""
    if isinstance(
        session_keys,
        (str, bytes),
    ):
        raise TypeError(
            "session_keys must be an iterable of SessionKey objects"
        )

    try:
        requested = tuple(session_keys)
    except TypeError as error:
        raise TypeError(
            "session_keys must be iterable"
        ) from error

    if not requested:
        raise DatasetIntegrityError(
            "at least one session key is required"
        )

    for session_key in requested:
        if not isinstance(
            session_key,
            SessionKey,
        ):
            raise TypeError(
                "every requested session must be a SessionKey"
            )

        if session_key.season not in DEVELOPMENT_SEASONS:
            raise DatasetIntegrityError(
                f"{session_key.identifier} is outside the "
                "development seasons"
            )

    identifiers = [
        session_key.identifier
        for session_key in requested
    ]

    if len(identifiers) != len(set(identifiers)):
        raise DatasetIntegrityError(
            "duplicate session keys are not allowed"
        )

    if (
        len(requested)
        != EXPECTED_DEVELOPMENT_TOTALS.sessions
    ):
        raise DatasetIntegrityError(
            "complete dataset verification requires exactly "
            f"{EXPECTED_DEVELOPMENT_TOTALS.sessions} sessions"
        )

    actual_season_counts = Counter(
        session_key.season
        for session_key in requested
    )
    expected_season_counts = {
        total.season: total.sessions
        for total in EXPECTED_SEASON_TOTALS
    }

    if dict(actual_season_counts) != expected_season_counts:
        raise DatasetIntegrityError(
            "verification season counts differ from the "
            f"contract: expected {expected_season_counts}, "
            f"got {dict(actual_season_counts)}"
        )

    return tuple(
        sorted(
            requested,
            key=lambda session_key: (
                session_key.season,
                session_key.round_number,
                session_key.session_type,
            ),
        )
    )