"""Whole-session temporal split construction and validation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

import pandas as pd

from app.datasets.contracts import (
    DEVELOPMENT_SEASONS,
    EXPECTED_DEVELOPMENT_TOTALS,
    EXPECTED_SEASON_TOTALS,
    PROTECTED_EVALUATION_SEASON,
    SPLITS_CONTRACT,
    TEMPORAL_FOLDS,
    DatasetContractError,
    SplitRole,
    TemporalFold,
    temporal_fold,
)
from app.pipeline import SessionKey

TEMPORAL_SPLIT_FOLD_IDS = tuple(
    fold.fold_id
    for fold in TEMPORAL_FOLDS
)


class TemporalSplitIssueCode(StrEnum):
    """Stable machine-readable temporal-split issue codes."""

    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    REQUIRED_VALUE_MISSING = "REQUIRED_VALUE_MISSING"
    ROW_COUNT_MISMATCH = "ROW_COUNT_MISMATCH"
    SOURCE_COVERAGE_MISMATCH = "SOURCE_COVERAGE_MISMATCH"
    DUPLICATE_SOURCE_SESSION = "DUPLICATE_SOURCE_SESSION"
    DUPLICATE_ASSIGNMENT = "DUPLICATE_ASSIGNMENT"
    SESSION_SET_MISMATCH = "SESSION_SET_MISMATCH"
    FOLD_SET_MISMATCH = "FOLD_SET_MISMATCH"
    FOLD_COVERAGE_MISMATCH = "FOLD_COVERAGE_MISMATCH"
    SESSION_COVERAGE_MISMATCH = "SESSION_COVERAGE_MISMATCH"
    INVALID_ROLE = "INVALID_ROLE"
    ROLE_ASSIGNMENT_MISMATCH = "ROLE_ASSIGNMENT_MISMATCH"
    SOURCE_IDENTITY_MISMATCH = "SOURCE_IDENTITY_MISMATCH"
    EVALUATION_SEASON_DETECTED = "EVALUATION_SEASON_DETECTED"
    UNSUPPORTED_SEASON_DETECTED = "UNSUPPORTED_SEASON_DETECTED"
    TEMPORAL_ORDER_VIOLATION = "TEMPORAL_ORDER_VIOLATION"


@dataclass(frozen=True, slots=True)
class TemporalSplitIssue:
    """One independent temporal-split validation failure."""

    code: TemporalSplitIssueCode
    message: str
    affected_rows: int = 0


class TemporalSplitError(ValueError):
    """Raised when temporal splits cannot be built or validated."""


@dataclass(frozen=True, slots=True)
class TemporalSplitValidationReport:
    """Integrity report for one complete split table."""

    rows: int
    source_sessions: int
    stored_sessions: int
    stored_folds: int
    evaluation_season_rows: int
    issues: tuple[TemporalSplitIssue, ...]

    @property
    def is_valid(self) -> bool:
        """Return whether no temporal-split issue was found."""
        return not self.issues

    @property
    def issue_count(self) -> int:
        """Return the number of distinct reported issues."""
        return len(self.issues)

    def raise_for_errors(self) -> None:
        """Raise one concise fail-closed validation error."""
        if self.is_valid:
            return

        summary = "; ".join(
            f"{issue.code.value}: {issue.message}"
            for issue in self.issues
        )

        raise TemporalSplitError(
            f"temporal split table is invalid: {summary}"
        )


@dataclass(frozen=True, slots=True)
class TemporalSplitBuildResult:
    """One validated complete development split table."""

    splits: pd.DataFrame
    validation: TemporalSplitValidationReport

    @property
    def session_count(self) -> int:
        """Return the number of unique development sessions."""
        return self.validation.source_sessions

    @property
    def fold_count(self) -> int:
        """Return the number of frozen temporal folds."""
        return self.validation.stored_folds

    @property
    def row_count(self) -> int:
        """Return the number of fold-session assignments."""
        return len(self.splits)


def _append_issue(
    issues: list[TemporalSplitIssue],
    code: TemporalSplitIssueCode,
    message: str,
    *,
    affected_rows: int = 0,
) -> None:
    """Append one issue with a normalized non-negative count."""
    issues.append(
        TemporalSplitIssue(
            code=code,
            message=message,
            affected_rows=max(
                0,
                int(affected_rows),
            ),
        )
    )


def _materialize_session_keys(
    session_keys: Iterable[SessionKey],
) -> tuple[SessionKey, ...]:
    """Materialize and type-check a session-key iterable."""
    if isinstance(session_keys, (str, bytes)):
        raise TypeError(
            "session_keys must be an iterable of SessionKey values"
        )

    try:
        keys = tuple(session_keys)
    except TypeError as error:
        raise TypeError(
            "session_keys must be an iterable of SessionKey values"
        ) from error

    for key in keys:
        if not isinstance(key, SessionKey):
            raise TypeError(
                "every session key must be a SessionKey"
            )

    return keys


def _expected_season_counts() -> dict[int, int]:
    """Return the frozen development session totals by season."""
    return {
        total.season: total.sessions
        for total in EXPECTED_SEASON_TOTALS
    }


def _source_coverage_issues(
    session_keys: tuple[SessionKey, ...],
    issues: list[TemporalSplitIssue],
) -> None:
    """Validate complete development source coverage."""
    if not session_keys:
        _append_issue(
            issues,
            TemporalSplitIssueCode.SOURCE_COVERAGE_MISMATCH,
            "no source sessions were provided",
        )
        return

    identifiers = [
        key.identifier
        for key in session_keys
    ]
    duplicate_count = len(identifiers) - len(
        set(identifiers)
    )

    if duplicate_count:
        _append_issue(
            issues,
            TemporalSplitIssueCode.DUPLICATE_SOURCE_SESSION,
            f"source contains {duplicate_count} duplicate sessions",
            affected_rows=duplicate_count,
        )

    protected_count = sum(
        key.season == PROTECTED_EVALUATION_SEASON
        for key in session_keys
    )

    if protected_count:
        _append_issue(
            issues,
            TemporalSplitIssueCode.EVALUATION_SEASON_DETECTED,
            f"source contains {protected_count} protected "
            "evaluation-season sessions",
            affected_rows=protected_count,
        )

    unsupported_count = sum(
        key.season not in DEVELOPMENT_SEASONS
        and key.season != PROTECTED_EVALUATION_SEASON
        for key in session_keys
    )

    if unsupported_count:
        _append_issue(
            issues,
            TemporalSplitIssueCode.UNSUPPORTED_SEASON_DETECTED,
            f"source contains {unsupported_count} unsupported sessions",
            affected_rows=unsupported_count,
        )

    non_race_count = sum(
        key.session_type != "R"
        for key in session_keys
    )

    if non_race_count:
        _append_issue(
            issues,
            TemporalSplitIssueCode.SOURCE_COVERAGE_MISMATCH,
            f"source contains {non_race_count} non-race sessions",
            affected_rows=non_race_count,
        )

    actual_counts = Counter(
        key.season
        for key in session_keys
        if key.season in DEVELOPMENT_SEASONS
    )
    expected_counts = _expected_season_counts()

    if dict(actual_counts) != expected_counts:
        _append_issue(
            issues,
            TemporalSplitIssueCode.SOURCE_COVERAGE_MISMATCH,
            "development season counts differ from the contract; "
            f"actual={dict(actual_counts)}, expected={expected_counts}",
        )

    expected_sessions = EXPECTED_DEVELOPMENT_TOTALS.sessions

    if len(session_keys) != expected_sessions:
        _append_issue(
            issues,
            TemporalSplitIssueCode.SOURCE_COVERAGE_MISMATCH,
            f"source contains {len(session_keys)} sessions; "
            f"expected {expected_sessions}",
            affected_rows=abs(
                len(session_keys) - expected_sessions
            ),
        )


def _validate_schema(
    splits: pd.DataFrame,
    issues: list[TemporalSplitIssue],
) -> None:
    """Validate exact split columns, order, dtypes and nullability."""
    expected_columns = tuple(
        column.name
        for column in SPLITS_CONTRACT.columns
    )
    actual_columns = tuple(
        str(column)
        for column in splits.columns
    )

    if actual_columns != expected_columns:
        missing = sorted(
            set(expected_columns)
            - set(actual_columns)
        )
        extra = sorted(
            set(actual_columns)
            - set(expected_columns)
        )
        _append_issue(
            issues,
            TemporalSplitIssueCode.SCHEMA_MISMATCH,
            "split columns differ from the contract; "
            f"missing={missing}, extra={extra}",
        )

    for column in SPLITS_CONTRACT.columns:
        if column.name not in splits.columns:
            continue

        actual_dtype = str(
            splits[column.name].dtype
        )

        if actual_dtype != column.pandas_dtype:
            _append_issue(
                issues,
                TemporalSplitIssueCode.SCHEMA_MISMATCH,
                f"splits.{column.name} has dtype {actual_dtype}; "
                f"expected {column.pandas_dtype}",
            )

        if not column.nullable:
            missing_count = int(
                splits[column.name].isna().sum()
            )

            if missing_count:
                _append_issue(
                    issues,
                    TemporalSplitIssueCode.REQUIRED_VALUE_MISSING,
                    f"splits.{column.name} contains "
                    f"{missing_count} missing values",
                    affected_rows=missing_count,
                )


def _validate_declared_temporal_order(
    issues: list[TemporalSplitIssue],
) -> None:
    """Require training seasons to precede validation seasons."""
    for fold in TEMPORAL_FOLDS:
        if not fold.validation_seasons:
            continue

        if max(fold.train_seasons) >= min(
            fold.validation_seasons
        ):
            _append_issue(
                issues,
                TemporalSplitIssueCode.TEMPORAL_ORDER_VIOLATION,
                f"{fold.fold_id} does not train strictly before "
                "its validation seasons",
            )


def _expected_assignment_records(
    session_keys: tuple[SessionKey, ...],
) -> list[dict[str, object]]:
    """Create deterministic records from frozen fold definitions."""
    ordered_keys = sorted(
        session_keys,
        key=lambda key: (
            key.season,
            key.round_number,
            key.session_type,
        ),
    )
    records: list[dict[str, object]] = []

    for fold in TEMPORAL_FOLDS:
        for key in ordered_keys:
            role = fold.role_for_season(
                key.season
            )
            records.append(
                {
                    "fold_id": fold.fold_id,
                    "session_id": key.identifier,
                    "season": key.season,
                    "round_number": key.round_number,
                    "session_type": key.session_type,
                    "role": role.value,
                }
            )

    return records


def _cast_split_contract(
    splits: pd.DataFrame,
) -> pd.DataFrame:
    """Cast and order a split table to its executable contract."""
    result = splits.copy(deep=True)

    for column in SPLITS_CONTRACT.columns:
        result[column.name] = result[
            column.name
        ].astype(column.pandas_dtype)

    return result[
        [
            column.name
            for column in SPLITS_CONTRACT.columns
        ]
    ]


def validate_temporal_splits(
    splits: pd.DataFrame,
    session_keys: Iterable[SessionKey],
) -> TemporalSplitValidationReport:
    """Independently validate a complete development split table."""
    if not isinstance(splits, pd.DataFrame):
        raise TypeError(
            "splits must be a pandas DataFrame"
        )

    keys = _materialize_session_keys(
        session_keys
    )
    issues: list[TemporalSplitIssue] = []

    _source_coverage_issues(keys, issues)
    _validate_schema(splits, issues)
    _validate_declared_temporal_order(issues)

    unique_source_keys = {
        key.identifier: key
        for key in keys
    }
    source_ids = set(unique_source_keys)
    expected_fold_ids = set(
        TEMPORAL_SPLIT_FOLD_IDS
    )
    stored_session_ids: set[str] = set()
    stored_fold_ids: set[str] = set()
    evaluation_season_rows = 0

    if "session_id" in splits.columns:
        stored_session_ids = set(
            splits["session_id"]
            .dropna()
            .astype(str)
        )

        if stored_session_ids != source_ids:
            difference_count = len(
                stored_session_ids
                ^ source_ids
            )
            _append_issue(
                issues,
                TemporalSplitIssueCode.SESSION_SET_MISMATCH,
                "stored and source session identity sets differ",
                affected_rows=difference_count,
            )

    if "fold_id" in splits.columns:
        stored_fold_ids = set(
            splits["fold_id"]
            .dropna()
            .astype(str)
        )

        if stored_fold_ids != expected_fold_ids:
            difference_count = len(
                stored_fold_ids
                ^ expected_fold_ids
            )
            _append_issue(
                issues,
                TemporalSplitIssueCode.FOLD_SET_MISMATCH,
                "stored fold identities differ from the contract",
                affected_rows=difference_count,
            )

    if "season" in splits.columns:
        numeric_seasons = pd.to_numeric(
            splits["season"],
            errors="coerce",
        )
        protected = numeric_seasons.eq(
            PROTECTED_EVALUATION_SEASON
        )
        unsupported = (
            numeric_seasons.notna()
            & ~numeric_seasons.isin(
                DEVELOPMENT_SEASONS
            )
            & ~protected
        )
        evaluation_season_rows = int(
            protected.sum()
        )
        unsupported_count = int(
            unsupported.sum()
        )

        if evaluation_season_rows:
            _append_issue(
                issues,
                TemporalSplitIssueCode.EVALUATION_SEASON_DETECTED,
                f"split table contains {evaluation_season_rows} "
                "protected evaluation-season rows",
                affected_rows=evaluation_season_rows,
            )

        if unsupported_count:
            _append_issue(
                issues,
                TemporalSplitIssueCode.UNSUPPORTED_SEASON_DETECTED,
                f"split table contains {unsupported_count} "
                "unsupported season rows",
                affected_rows=unsupported_count,
            )

    assignment_columns = (
        "fold_id",
        "session_id",
    )

    if all(
        column in splits.columns
        for column in assignment_columns
    ):
        duplicate_count = int(
            splits.duplicated(
                subset=list(
                    assignment_columns
                )
            ).sum()
        )

        if duplicate_count:
            _append_issue(
                issues,
                TemporalSplitIssueCode.DUPLICATE_ASSIGNMENT,
                f"split table contains {duplicate_count} duplicate "
                "fold-session assignments",
                affected_rows=duplicate_count,
            )

        fold_counts = splits.groupby(
            "fold_id",
            dropna=False,
        )["session_id"].nunique()
        expected_sessions = len(
            unique_source_keys
        )
        bad_fold_count = int(
            fold_counts.ne(
                expected_sessions
            ).sum()
        )

        if bad_fold_count:
            _append_issue(
                issues,
                TemporalSplitIssueCode.FOLD_COVERAGE_MISMATCH,
                f"{bad_fold_count} folds do not cover every "
                "source session exactly once",
                affected_rows=bad_fold_count,
            )

        session_counts = splits.groupby(
            "session_id",
            dropna=False,
        )["fold_id"].nunique()
        bad_session_count = int(
            session_counts.ne(
                len(TEMPORAL_FOLDS)
            ).sum()
        )

        if bad_session_count:
            _append_issue(
                issues,
                TemporalSplitIssueCode.SESSION_COVERAGE_MISMATCH,
                f"{bad_session_count} sessions do not appear in "
                "every fold",
                affected_rows=bad_session_count,
            )

    if "role" in splits.columns:
        allowed_roles = {
            role.value
            for role in SplitRole
        }
        invalid_roles = ~splits[
            "role"
        ].astype("string").isin(
            allowed_roles
        )
        invalid_role_count = int(
            invalid_roles.fillna(True).sum()
        )

        if invalid_role_count:
            _append_issue(
                issues,
                TemporalSplitIssueCode.INVALID_ROLE,
                f"split table contains {invalid_role_count} invalid "
                "role values",
                affected_rows=invalid_role_count,
            )

    identity_columns = (
        "session_id",
        "season",
        "round_number",
        "session_type",
    )

    if all(
        column in splits.columns
        for column in identity_columns
    ):
        identity_mismatch_count = 0

        for row in splits[
            list(identity_columns)
        ].itertuples(index=False):
            source_key = unique_source_keys.get(
                str(row.session_id)
            )

            if source_key is None:
                continue

            try:
                row_season = int(row.season)
                row_round = int(
                    row.round_number
                )
            except (
                TypeError,
                ValueError,
                OverflowError,
            ):
                identity_mismatch_count += 1
                continue

            if (
                row_season != source_key.season
                or row_round
                != source_key.round_number
                or str(row.session_type)
                != source_key.session_type
            ):
                identity_mismatch_count += 1

        if identity_mismatch_count:
            _append_issue(
                issues,
                TemporalSplitIssueCode.SOURCE_IDENTITY_MISMATCH,
                f"{identity_mismatch_count} assignments disagree "
                "with source session identities",
                affected_rows=identity_mismatch_count,
            )

    role_columns = (
        "fold_id",
        "season",
        "role",
    )

    if all(
        column in splits.columns
        for column in role_columns
    ):
        folds_by_id: dict[str, TemporalFold] = {
            fold.fold_id: fold
            for fold in TEMPORAL_FOLDS
        }
        role_mismatch_count = 0

        for row in splits[
            list(role_columns)
        ].itertuples(index=False):
            fold = folds_by_id.get(
                str(row.fold_id)
            )

            if fold is None:
                continue

            try:
                season = int(row.season)
                expected_role = (
                    fold.role_for_season(
                        season
                    ).value
                )
            except (
                TypeError,
                ValueError,
                OverflowError,
                DatasetContractError,
            ):
                role_mismatch_count += 1
                continue

            if str(row.role) != expected_role:
                role_mismatch_count += 1

        if role_mismatch_count:
            _append_issue(
                issues,
                TemporalSplitIssueCode.ROLE_ASSIGNMENT_MISMATCH,
                f"{role_mismatch_count} assignments disagree with "
                "the frozen season roles",
                affected_rows=role_mismatch_count,
            )

    expected_rows = (
        EXPECTED_DEVELOPMENT_TOTALS.split_rows
    )

    if len(splits) != expected_rows:
        _append_issue(
            issues,
            TemporalSplitIssueCode.ROW_COUNT_MISMATCH,
            f"split table contains {len(splits)} rows; "
            f"expected {expected_rows}",
            affected_rows=abs(
                len(splits) - expected_rows
            ),
        )

    return TemporalSplitValidationReport(
        rows=len(splits),
        source_sessions=len(
            unique_source_keys
        ),
        stored_sessions=len(
            stored_session_ids
        ),
        stored_folds=len(
            stored_fold_ids
        ),
        evaluation_season_rows=(
            evaluation_season_rows
        ),
        issues=tuple(issues),
    )


def build_temporal_splits(
    session_keys: Iterable[SessionKey],
) -> TemporalSplitBuildResult:
    """Build all frozen whole-session development assignments."""
    keys = _materialize_session_keys(
        session_keys
    )
    source_issues: list[TemporalSplitIssue] = []
    _source_coverage_issues(
        keys,
        source_issues,
    )

    if source_issues:
        report = TemporalSplitValidationReport(
            rows=0,
            source_sessions=len(
                {
                    key.identifier
                    for key in keys
                }
            ),
            stored_sessions=0,
            stored_folds=0,
            evaluation_season_rows=sum(
                key.season
                == PROTECTED_EVALUATION_SEASON
                for key in keys
            ),
            issues=tuple(source_issues),
        )
        report.raise_for_errors()

    records = _expected_assignment_records(
        keys
    )
    columns = [
        column.name
        for column in SPLITS_CONTRACT.columns
    ]
    splits = pd.DataFrame.from_records(
        records,
        columns=columns,
    )
    splits = _cast_split_contract(
        splits
    )
    report = validate_temporal_splits(
        splits,
        keys,
    )
    report.raise_for_errors()

    return TemporalSplitBuildResult(
        splits=splits,
        validation=report,
    )


def session_ids_for_fold_role(
    splits: pd.DataFrame,
    *,
    fold_id: str,
    role: SplitRole,
) -> tuple[str, ...]:
    """Return deterministic session IDs for one explicit fold role."""
    if not isinstance(splits, pd.DataFrame):
        raise TypeError(
            "splits must be a pandas DataFrame"
        )

    if not isinstance(fold_id, str):
        raise TypeError("fold_id must be a string")

    if not isinstance(role, SplitRole):
        raise TypeError("role must be a SplitRole")

    temporal_fold(fold_id)

    required_columns = {
        "fold_id",
        "session_id",
        "season",
        "round_number",
        "session_type",
        "role",
    }
    missing_columns = sorted(
        required_columns
        - set(splits.columns)
    )

    if missing_columns:
        raise TemporalSplitError(
            "cannot select split sessions; missing columns: "
            f"{missing_columns}"
        )

    selected = splits.loc[
        splits["fold_id"].eq(fold_id)
        & splits["role"].eq(role.value)
    ].sort_values(
        [
            "season",
            "round_number",
            "session_type",
        ],
        kind="stable",
    )

    if selected["session_id"].duplicated().any():
        raise TemporalSplitError(
            f"{fold_id} {role.value} contains duplicate sessions"
        )

    return tuple(
        selected["session_id"].astype(str)
    )
