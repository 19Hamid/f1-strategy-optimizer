"""Independent integrity and leakage validation for decision tables."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd

from app.datasets.contracts import (
    DATASET_CONTRACT_VERSION,
    DECISION_EXCLUSION_REASON_ORDER,
    DECISION_LABELS_CONTRACT,
    DECISION_MODEL_FEATURE_COLUMNS,
    DECISION_ROWS_CONTRACT,
    DEVELOPMENT_SEASONS,
    PROTECTED_EVALUATION_SEASON,
    SOURCE_CLEANING_RULE_VERSION,
    SOURCE_PROCESSED_CONTRACT_VERSION,
    ColumnRole,
    TableContract,
)
from app.datasets.decisions import DecisionSessionData
from app.pipeline import SessionKey

DECISION_AUDIT_RULES = (
    (
        "has_consecutive_previous_lap",
        "NON_CONSECUTIVE_PREVIOUS_LAP",
    ),
    (
        "weather_available_by_decision",
        "WEATHER_NOT_AVAILABLE_BY_DECISION",
    ),
    (
        "previous_lap_not_pit_commitment",
        "PREVIOUS_LAP_PIT_COMMITMENT",
    ),
    (
        "state_reconstruction_consistent",
        "STATE_RECONSTRUCTION_CONFLICT",
    ),
    (
        "supported_dry_compound",
        "UNSUPPORTED_CURRENT_COMPOUND",
    ),
    (
        "valid_current_tyre_age",
        "INVALID_CURRENT_TYRE_AGE",
    ),
    (
        "current_stint_identified",
        "MISSING_CURRENT_STINT",
    ),
    (
        "dry_at_decision",
        "WET_AT_DECISION",
    ),
    (
        "previous_lap_green",
        "PREVIOUS_LAP_NOT_GREEN",
    ),
    (
        "minimum_history_available",
        "INSUFFICIENT_ELIGIBLE_HISTORY",
    ),
    (
        "previous_position_available",
        "MISSING_PREVIOUS_POSITION",
    ),
)

CURRENT_LAP_TIMING_COLUMNS = frozenset(
    {
        "LapTime",
        "LapTimeSeconds",
        "Sector1Time",
        "Sector1TimeSeconds",
        "Sector2Time",
        "Sector2TimeSeconds",
        "Sector3Time",
        "Sector3TimeSeconds",
        "current_lap_time_seconds",
        "current_sector1_time_seconds",
        "current_sector2_time_seconds",
        "current_sector3_time_seconds",
        "lap_time_seconds",
        "sector1_time_seconds",
        "sector2_time_seconds",
        "sector3_time_seconds",
    }
)

CURRENT_LAP_QUALITY_COLUMNS = frozenset(
    {
        "ExclusionReasonCount",
        "ExclusionReasons",
        "IsAccurate",
        "IsEligible",
        "QualityFlags",
        "exclusion_reason_count",
        "exclusion_reasons",
        "historical_action",
        "did_pit",
        "pit_event_id",
        "is_lap_time_target_eligible",
        "lap_time_target_seconds",
        "lap_target_exclusion_count",
        "lap_target_exclusion_reasons",
        "is_accurate",
        "is_eligible",
        "quality_flags",
    }
)


class DecisionValidationIssueCode(StrEnum):
    """Stable machine-readable decision-validation issue codes."""

    DECISION_SCHEMA_MISMATCH = "DECISION_SCHEMA_MISMATCH"
    LABEL_SCHEMA_MISMATCH = "LABEL_SCHEMA_MISMATCH"
    REQUIRED_VALUE_MISSING = "REQUIRED_VALUE_MISSING"
    DUPLICATE_DECISION_ID = "DUPLICATE_DECISION_ID"
    DUPLICATE_LABEL_ID = "DUPLICATE_LABEL_ID"
    IDENTITY_SET_MISMATCH = "IDENTITY_SET_MISMATCH"
    IDENTITY_VALUE_MISMATCH = "IDENTITY_VALUE_MISMATCH"
    NON_DETERMINISTIC_DECISION_ID = "NON_DETERMINISTIC_DECISION_ID"
    CONTRACT_VERSION_MISMATCH = "CONTRACT_VERSION_MISMATCH"
    EVALUATION_SEASON_DETECTED = "EVALUATION_SEASON_DETECTED"
    UNSUPPORTED_SEASON_DETECTED = "UNSUPPORTED_SEASON_DETECTED"
    FUTURE_WEATHER_DETECTED = "FUTURE_WEATHER_DETECTED"
    NEGATIVE_WEATHER_AGE = "NEGATIVE_WEATHER_AGE"
    EXCLUSION_ENCODING_MISMATCH = "EXCLUSION_ENCODING_MISMATCH"
    DECISION_ELIGIBILITY_MISMATCH = "DECISION_ELIGIBILITY_MISMATCH"
    HISTORICAL_ACTION_MISMATCH = "HISTORICAL_ACTION_MISMATCH"
    PIT_EVENT_LINEAGE_MISMATCH = "PIT_EVENT_LINEAGE_MISMATCH"
    TARGET_NULLABILITY_MISMATCH = "TARGET_NULLABILITY_MISMATCH"
    TARGET_EXCLUSION_MISMATCH = "TARGET_EXCLUSION_MISMATCH"
    IMMEDIATE_HISTORY_MISMATCH = "IMMEDIATE_HISTORY_MISMATCH"
    ROLLING_HISTORY_MISMATCH = "ROLLING_HISTORY_MISMATCH"
    HISTORICAL_VALUE_MISMATCH = "HISTORICAL_VALUE_MISMATCH"
    CURRENT_LAP_TIMING_FEATURE = "CURRENT_LAP_TIMING_FEATURE"
    CURRENT_LAP_QUALITY_FEATURE = "CURRENT_LAP_QUALITY_FEATURE"
    FEATURE_OUTSIDE_ALLOWLIST = "FEATURE_OUTSIDE_ALLOWLIST"


@dataclass(frozen=True, slots=True)
class DecisionValidationIssue:
    """One independent decision-table validation failure."""

    code: DecisionValidationIssueCode
    message: str
    affected_rows: int = 0


class DecisionDatasetValidationError(ValueError):
    """Raised when a decision validation report is invalid."""


@dataclass(frozen=True, slots=True)
class DecisionValidationReport:
    """Independent integrity report for one decision session."""

    session_key: SessionKey
    decision_rows: int
    label_rows: int
    eligible_decisions: int
    ineligible_decisions: int
    future_weather_matches: int
    evaluation_season_rows: int
    current_lap_timing_features: tuple[str, ...]
    current_lap_quality_features: tuple[str, ...]
    feature_columns_outside_allowlist: tuple[str, ...]
    issues: tuple[DecisionValidationIssue, ...]

    @property
    def is_valid(self) -> bool:
        """Return whether no integrity or leakage issue was found."""
        return not self.issues

    @property
    def issue_count(self) -> int:
        """Return the number of distinct reported issues."""
        return len(self.issues)

    def raise_for_errors(self) -> None:
        """Raise one concise error when validation failed."""
        if self.is_valid:
            return

        summary = "; ".join(
            f"{issue.code.value}: {issue.message}"
            for issue in self.issues
        )

        raise DecisionDatasetValidationError(
            f"decision dataset for {self.session_key.identifier} "
            f"is invalid: {summary}"
        )


def model_feature_columns_outside_allowlist(
    feature_columns: Iterable[str],
) -> tuple[str, ...]:
    """Return requested model features outside the frozen allowlist."""
    if isinstance(feature_columns, (str, bytes)):
        raise TypeError(
            "feature_columns must be an iterable of column names"
        )

    normalized: list[str] = []

    for column in feature_columns:
        if not isinstance(column, str):
            raise TypeError(
                "every feature column name must be a string"
            )

        normalized.append(column)

    allowed = set(DECISION_MODEL_FEATURE_COLUMNS)

    return tuple(
        sorted(
            {
                column
                for column in normalized
                if column not in allowed
            }
        )
    )


def require_allowed_model_features(
    feature_columns: Iterable[str],
) -> tuple[str, ...]:
    """Validate and return a frozen explicit model-feature selection."""
    if isinstance(feature_columns, (str, bytes)):
        raise TypeError(
            "feature_columns must be an iterable of column names"
        )

    columns = tuple(feature_columns)

    if not columns:
        raise DecisionDatasetValidationError(
            "at least one model feature must be selected"
        )

    if len(set(columns)) != len(columns):
        raise DecisionDatasetValidationError(
            "model feature selection contains duplicates"
        )

    outside = model_feature_columns_outside_allowlist(columns)

    if outside:
        raise DecisionDatasetValidationError(
            "model feature selection contains columns outside "
            f"the allowlist: {list(outside)}"
        )

    return columns


def _append_issue(
    issues: list[DecisionValidationIssue],
    code: DecisionValidationIssueCode,
    message: str,
    *,
    affected_rows: int = 0,
) -> None:
    """Append one issue with a normalized non-negative row count."""
    issues.append(
        DecisionValidationIssue(
            code=code,
            message=message,
            affected_rows=max(0, int(affected_rows)),
        )
    )


def _validate_table_contract(
    table: pd.DataFrame,
    contract: TableContract,
    *,
    schema_issue_code: DecisionValidationIssueCode,
    issues: list[DecisionValidationIssue],
) -> bool:
    """Validate exact order, dtypes and required-value nullability."""
    expected_columns = tuple(
        column.name
        for column in contract.columns
    )
    actual_columns = tuple(str(column) for column in table.columns)

    schema_valid = True

    if actual_columns != expected_columns:
        schema_valid = False
        missing = sorted(set(expected_columns) - set(actual_columns))
        extra = sorted(set(actual_columns) - set(expected_columns))

        _append_issue(
            issues,
            schema_issue_code,
            f"{contract.name} columns differ from the contract; "
            f"missing={missing}, extra={extra}",
        )

    for column in contract.columns:
        if column.name not in table.columns:
            continue

        actual_dtype = str(table[column.name].dtype)

        if actual_dtype != column.pandas_dtype:
            schema_valid = False
            _append_issue(
                issues,
                schema_issue_code,
                f"{contract.name}.{column.name} has dtype "
                f"{actual_dtype}; expected {column.pandas_dtype}",
            )

        if not column.nullable:
            missing_count = int(table[column.name].isna().sum())

            if missing_count:
                schema_valid = False
                _append_issue(
                    issues,
                    DecisionValidationIssueCode.REQUIRED_VALUE_MISSING,
                    f"{contract.name}.{column.name} contains "
                    f"{missing_count} missing values",
                    affected_rows=missing_count,
                )

    return schema_valid


def _encoded_reason_count(value: object) -> int:
    """Count one deterministic pipe-delimited reason string."""
    if pd.isna(value):
        return -1

    text = str(value)

    if text == "":
        return 0

    return len(text.split("|"))


def _required_columns_present(
    table: pd.DataFrame,
    columns: Iterable[str],
) -> bool:
    """Return whether every dependent validation column exists."""
    return all(column in table.columns for column in columns)


def _numeric_values_match(
    stored: object,
    expected: float,
) -> bool:
    """Compare one stored numeric value with a recomputed value."""
    if pd.isna(stored):
        return False

    try:
        numeric_stored = float(stored)
    except (TypeError, ValueError):
        return False

    return bool(
        np.isclose(
            numeric_stored,
            expected,
            rtol=1e-10,
            atol=1e-10,
        )
    )


def _rolling_expectations(
    history: list[float],
) -> tuple[float, float, float, float] | None:
    """Return frozen rolling statistics for past eligible laps."""
    if len(history) < 3:
        return None

    latest_three = np.asarray(history[-3:], dtype="float64")
    latest_five = np.asarray(history[-5:], dtype="float64")
    positions = np.arange(len(latest_five), dtype="float64")

    slope = float(
        np.polyfit(
            positions,
            latest_five,
            deg=1,
        )[0]
    )

    return (
        float(np.median(latest_three)),
        float(np.median(latest_five)),
        float(np.std(latest_five, ddof=0)),
        slope,
    )


def _past_only_history_mismatch_count(
    rows: pd.DataFrame,
    labels: pd.DataFrame,
) -> int:
    """Recompute stored rolling values from strictly earlier labels."""
    row_columns = (
        "driver",
        "decision_lap",
        "previous_lap_was_target_eligible",
        "previous_lap_time_seconds",
        "eligible_laps_completed",
        "rolling_lap_time_median_3",
        "rolling_lap_time_median_5",
        "rolling_lap_time_std_5",
        "rolling_lap_time_trend_5",
    )
    label_columns = (
        "driver",
        "decision_lap",
        "is_lap_time_target_eligible",
        "lap_time_target_seconds",
    )

    if not _required_columns_present(rows, row_columns):
        return 0

    if not _required_columns_present(labels, label_columns):
        return 0

    if rows[list(row_columns)].isna().any().any():
        nullable_columns = (
            "previous_lap_time_seconds",
            "rolling_lap_time_median_3",
            "rolling_lap_time_median_5",
            "rolling_lap_time_std_5",
            "rolling_lap_time_trend_5",
        )
        required_columns = tuple(
            column
            for column in row_columns
            if column not in nullable_columns
        )

        if rows[list(required_columns)].isna().any().any():
            return 0

    required_label_columns = (
        "driver",
        "decision_lap",
        "is_lap_time_target_eligible",
    )

    if labels[list(required_label_columns)].isna().any().any():
        return 0

    mismatched_indices: set[object] = set()

    for driver, driver_rows in rows.groupby(
        "driver",
        sort=False,
        dropna=False,
    ):
        ordered_rows = driver_rows.sort_values(
            "decision_lap",
            kind="stable",
        )
        driver_labels = labels.loc[
            labels["driver"].eq(driver)
        ].copy()
        labels_by_lap = {
            int(label.decision_lap): label
            for label in driver_labels.itertuples(index=False)
        }
        history: list[float] = []

        for position, (index, row) in enumerate(
            ordered_rows.iterrows()
        ):
            decision_lap = int(row["decision_lap"])

            if position == 0:
                if bool(
                    row["previous_lap_was_target_eligible"]
                ):
                    previous_value = row[
                        "previous_lap_time_seconds"
                    ]

                    if pd.notna(previous_value):
                        history.append(float(previous_value))
            else:
                previous_label = labels_by_lap.get(
                    decision_lap - 1
                )

                if previous_label is not None:
                    previous_eligible = bool(
                        previous_label.is_lap_time_target_eligible
                    )
                    stored_eligible = bool(
                        row[
                            "previous_lap_was_target_eligible"
                        ]
                    )

                    if stored_eligible != previous_eligible:
                        mismatched_indices.add(index)

                    if previous_eligible:
                        previous_target = (
                            previous_label.lap_time_target_seconds
                        )

                        if pd.isna(previous_target):
                            mismatched_indices.add(index)
                        else:
                            target_value = float(previous_target)

                            if not _numeric_values_match(
                                row["previous_lap_time_seconds"],
                                target_value,
                            ):
                                mismatched_indices.add(index)

                            history.append(target_value)

            if int(row["eligible_laps_completed"]) != len(
                history
            ):
                mismatched_indices.add(index)

            expectations = _rolling_expectations(history)
            rolling_columns = (
                "rolling_lap_time_median_3",
                "rolling_lap_time_median_5",
                "rolling_lap_time_std_5",
                "rolling_lap_time_trend_5",
            )

            if expectations is None:
                if row[list(rolling_columns)].notna().any():
                    mismatched_indices.add(index)

                continue

            for column, expected in zip(
                rolling_columns,
                expectations,
                strict=True,
            ):
                if not _numeric_values_match(
                    row[column],
                    expected,
                ):
                    mismatched_indices.add(index)
                    break

    return len(mismatched_indices)


def validate_decision_session(
    data: DecisionSessionData,
) -> DecisionValidationReport:
    """Independently validate one session's decision rows and labels."""
    if not isinstance(data, DecisionSessionData):
        raise TypeError("data must be a DecisionSessionData")

    rows = data.decision_rows.copy(deep=True)
    labels = data.decision_labels.copy(deep=True)
    session_key = data.session_key
    issues: list[DecisionValidationIssue] = []

    _validate_table_contract(
        rows,
        DECISION_ROWS_CONTRACT,
        schema_issue_code=(
            DecisionValidationIssueCode.DECISION_SCHEMA_MISMATCH
        ),
        issues=issues,
    )
    _validate_table_contract(
        labels,
        DECISION_LABELS_CONTRACT,
        schema_issue_code=(
            DecisionValidationIssueCode.LABEL_SCHEMA_MISMATCH
        ),
        issues=issues,
    )

    row_columns = {str(column) for column in rows.columns}
    expected_row_columns = {
        column.name
        for column in DECISION_ROWS_CONTRACT.columns
    }
    extra_row_columns = row_columns - expected_row_columns

    timing_features = tuple(
        sorted(row_columns & CURRENT_LAP_TIMING_COLUMNS)
    )
    quality_features = tuple(
        sorted(row_columns & CURRENT_LAP_QUALITY_COLUMNS)
    )

    contract_feature_columns = tuple(
        column.name
        for column in DECISION_ROWS_CONTRACT.columns
        if column.role == ColumnRole.FEATURE
    )
    feature_outside_allowlist = tuple(
        sorted(
            set(
                model_feature_columns_outside_allowlist(
                    contract_feature_columns
                )
            )
            | extra_row_columns
        )
    )

    if timing_features:
        _append_issue(
            issues,
            DecisionValidationIssueCode.CURRENT_LAP_TIMING_FEATURE,
            f"current-lap timing columns detected: {list(timing_features)}",
        )

    if quality_features:
        _append_issue(
            issues,
            DecisionValidationIssueCode.CURRENT_LAP_QUALITY_FEATURE,
            f"current-lap quality or label columns detected: "
            f"{list(quality_features)}",
        )

    if feature_outside_allowlist:
        _append_issue(
            issues,
            DecisionValidationIssueCode.FEATURE_OUTSIDE_ALLOWLIST,
            "columns outside the model-feature allowlist detected: "
            f"{list(feature_outside_allowlist)}",
        )

    if session_key.season == PROTECTED_EVALUATION_SEASON:
        _append_issue(
            issues,
            DecisionValidationIssueCode.EVALUATION_SEASON_DETECTED,
            f"session key belongs to protected season "
            f"{PROTECTED_EVALUATION_SEASON}",
            affected_rows=len(rows),
        )
    elif session_key.season not in DEVELOPMENT_SEASONS:
        _append_issue(
            issues,
            DecisionValidationIssueCode.UNSUPPORTED_SEASON_DETECTED,
            f"session key season {session_key.season} is unsupported",
            affected_rows=len(rows),
        )

    evaluation_season_rows = 0

    for table_name, table in (("decision_rows", rows), ("decision_labels", labels)):
        if "season" not in table.columns:
            continue

        numeric_seasons = pd.to_numeric(table["season"], errors="coerce")
        protected = numeric_seasons.eq(PROTECTED_EVALUATION_SEASON)
        unsupported = (
            numeric_seasons.notna()
            & ~numeric_seasons.isin(DEVELOPMENT_SEASONS)
            & ~protected
        )

        protected_count = int(protected.sum())
        unsupported_count = int(unsupported.sum())
        evaluation_season_rows += protected_count

        if protected_count:
            _append_issue(
                issues,
                DecisionValidationIssueCode.EVALUATION_SEASON_DETECTED,
                f"{table_name} contains {protected_count} protected "
                "evaluation-season rows",
                affected_rows=protected_count,
            )

        if unsupported_count:
            _append_issue(
                issues,
                DecisionValidationIssueCode.UNSUPPORTED_SEASON_DETECTED,
                f"{table_name} contains {unsupported_count} unsupported "
                "season rows",
                affected_rows=unsupported_count,
            )

    row_ids_are_unique = False
    label_ids_are_unique = False

    if "decision_id" in rows.columns:
        duplicate_count = int(
            rows["decision_id"].duplicated().sum()
        )
        row_ids_are_unique = duplicate_count == 0

        if duplicate_count:
            _append_issue(
                issues,
                DecisionValidationIssueCode.DUPLICATE_DECISION_ID,
                f"decision rows contain {duplicate_count} duplicate IDs",
                affected_rows=duplicate_count,
            )

    if "decision_id" in labels.columns:
        duplicate_count = int(
            labels["decision_id"].duplicated().sum()
        )
        label_ids_are_unique = duplicate_count == 0

        if duplicate_count:
            _append_issue(
                issues,
                DecisionValidationIssueCode.DUPLICATE_LABEL_ID,
                f"labels contain {duplicate_count} duplicate IDs",
                affected_rows=duplicate_count,
            )

    if "decision_id" in rows.columns and "decision_id" in labels.columns:
        row_ids = set(rows["decision_id"].dropna().astype(str))
        label_ids = set(labels["decision_id"].dropna().astype(str))

        if row_ids != label_ids:
            difference_count = len(row_ids ^ label_ids)
            _append_issue(
                issues,
                DecisionValidationIssueCode.IDENTITY_SET_MISMATCH,
                "decision and label identity sets differ",
                affected_rows=difference_count,
            )

    identity_columns = (
        "session_id",
        "season",
        "round_number",
        "session_type",
        "driver",
        "decision_lap",
    )

    identities_available = _required_columns_present(
        rows,
        ("decision_id", *identity_columns),
    ) and _required_columns_present(
        labels,
        ("decision_id", *identity_columns),
    )

    if (
        identities_available
        and row_ids_are_unique
        and label_ids_are_unique
    ):
        left = rows[["decision_id", *identity_columns]].copy()
        right = labels[["decision_id", *identity_columns]].copy()
        joined = left.merge(
            right,
            on="decision_id",
            how="inner",
            suffixes=("_row", "_label"),
            validate="one_to_one",
        )

        mismatch = np.zeros(len(joined), dtype=bool)

        for column in identity_columns:
            mismatch |= (
                joined[f"{column}_row"].astype("string").fillna("<NA>")
                != joined[f"{column}_label"].astype("string").fillna("<NA>")
            ).to_numpy(dtype=bool)

        mismatch_count = int(mismatch.sum())

        if mismatch_count:
            _append_issue(
                issues,
                DecisionValidationIssueCode.IDENTITY_VALUE_MISMATCH,
                f"{mismatch_count} joined rows disagree on identity values",
                affected_rows=mismatch_count,
            )

    deterministic_columns = (
        "decision_id",
        "session_id",
        "driver",
        "decision_lap",
    )

    if _required_columns_present(rows, deterministic_columns):
        numeric_laps = pd.to_numeric(
            rows["decision_lap"],
            errors="coerce",
        )
        valid_laps = (
            numeric_laps.notna()
            & numeric_laps.mod(1).eq(0)
        )
        expected_ids = pd.Series(
            pd.NA,
            index=rows.index,
            dtype="string",
        )
        expected_ids.loc[valid_laps] = (
            rows.loc[valid_laps, "session_id"].astype("string")
            + "-"
            + rows.loc[valid_laps, "driver"].astype("string")
            + "-"
            + numeric_laps.loc[valid_laps]
            .astype("int64")
            .map(lambda value: f"{value:03d}")
        )
        mismatch = (
            ~valid_laps
            | rows["decision_id"].astype("string").ne(expected_ids)
        )
        mismatch_count = int(mismatch.fillna(True).sum())

        if mismatch_count:
            _append_issue(
                issues,
                DecisionValidationIssueCode.NON_DETERMINISTIC_DECISION_ID,
                f"{mismatch_count} decision IDs are not deterministic",
                affected_rows=mismatch_count,
            )

    expected_identity = {
        "session_id": session_key.identifier,
        "season": session_key.season,
        "round_number": session_key.round_number,
        "session_type": session_key.session_type,
    }

    for table_name, table in (("decision_rows", rows), ("decision_labels", labels)):
        for column, expected_value in expected_identity.items():
            if column not in table.columns:
                continue

            mismatch_count = int(
                table[column].astype("string").ne(str(expected_value)).sum()
            )

            if mismatch_count:
                _append_issue(
                    issues,
                    DecisionValidationIssueCode.IDENTITY_VALUE_MISMATCH,
                    f"{table_name}.{column} disagrees with the session key",
                    affected_rows=mismatch_count,
                )

    version_checks = (
        (rows, "decision_rows", "dataset_contract_version", DATASET_CONTRACT_VERSION),
        (rows, "decision_rows", "cleaning_rule_version", SOURCE_CLEANING_RULE_VERSION),
        (
            rows,
            "decision_rows",
            "processed_contract_version",
            SOURCE_PROCESSED_CONTRACT_VERSION,
        ),
        (
            labels,
            "decision_labels",
            "dataset_contract_version",
            DATASET_CONTRACT_VERSION,
        ),
    )

    for table, table_name, column, expected_value in version_checks:
        if column not in table.columns:
            continue

        mismatch_count = int(table[column].astype("string").ne(expected_value).sum())

        if mismatch_count:
            _append_issue(
                issues,
                DecisionValidationIssueCode.CONTRACT_VERSION_MISMATCH,
                f"{table_name}.{column} differs from {expected_value}",
                affected_rows=mismatch_count,
            )

    future_weather_matches = 0

    if _required_columns_present(
        rows,
        ("weather_observation_time_seconds", "decision_time_seconds"),
    ):
        future = rows["weather_observation_time_seconds"].gt(
            rows["decision_time_seconds"]
        )
        future_weather_matches = int(future.sum())

        if future_weather_matches:
            _append_issue(
                issues,
                DecisionValidationIssueCode.FUTURE_WEATHER_DETECTED,
                f"{future_weather_matches} decisions use future weather",
                affected_rows=future_weather_matches,
            )

    if "weather_age_seconds" in rows.columns:
        negative_count = int(rows["weather_age_seconds"].lt(0).sum())

        if negative_count:
            _append_issue(
                issues,
                DecisionValidationIssueCode.NEGATIVE_WEATHER_AGE,
                f"{negative_count} decisions have negative weather age",
                affected_rows=negative_count,
            )

    audit_columns = tuple(column for column, _ in DECISION_AUDIT_RULES)

    audit_values_available = _required_columns_present(
        rows,
        (
            *audit_columns,
            "is_decision_eligible",
            "decision_exclusion_count",
            "decision_exclusion_reasons",
        ),
    ) and not rows[
        [
            *audit_columns,
            "is_decision_eligible",
            "decision_exclusion_count",
            "decision_exclusion_reasons",
        ]
    ].isna().any().any()

    if audit_values_available:
        expected_reason_order = tuple(
            reason.value for reason in DECISION_EXCLUSION_REASON_ORDER
        )
        rule_reason_order = tuple(reason for _, reason in DECISION_AUDIT_RULES)

        if rule_reason_order != expected_reason_order:
            raise RuntimeError(
                "decision audit rule order differs from the contract"
            )

        expected_reason_strings: list[str] = []
        expected_counts: list[int] = []
        expected_eligibility: list[bool] = []

        for row in rows.itertuples(index=False):
            failed = [
                reason
                for column, reason in DECISION_AUDIT_RULES
                if not bool(getattr(row, column))
            ]
            expected_reason_strings.append("|".join(failed))
            expected_counts.append(len(failed))
            expected_eligibility.append(not failed)

        stored_reasons = rows["decision_exclusion_reasons"].astype(str)
        reason_mismatch = stored_reasons.ne(expected_reason_strings)
        count_mismatch = rows["decision_exclusion_count"].ne(expected_counts)

        encoded_counts = rows["decision_exclusion_reasons"].map(
            _encoded_reason_count
        )
        count_mismatch |= rows["decision_exclusion_count"].ne(encoded_counts)

        encoding_mismatch_count = int((reason_mismatch | count_mismatch).sum())

        if encoding_mismatch_count:
            _append_issue(
                issues,
                DecisionValidationIssueCode.EXCLUSION_ENCODING_MISMATCH,
                f"{encoding_mismatch_count} rows have invalid exclusion encoding",
                affected_rows=encoding_mismatch_count,
            )

        eligibility_mismatch_count = int(
            rows["is_decision_eligible"].ne(expected_eligibility).sum()
        )

        if eligibility_mismatch_count:
            _append_issue(
                issues,
                DecisionValidationIssueCode.DECISION_ELIGIBILITY_MISMATCH,
                f"{eligibility_mismatch_count} eligibility values disagree "
                "with the audit flags",
                affected_rows=eligibility_mismatch_count,
            )

    immediate_columns = (
        "previous_lap_time_seconds",
        "previous_sector1_time_seconds",
        "previous_sector2_time_seconds",
        "previous_sector3_time_seconds",
    )

    immediate_values_available = _required_columns_present(
        rows,
        ("previous_lap_was_target_eligible", *immediate_columns),
    ) and rows["previous_lap_was_target_eligible"].notna().all()

    if immediate_values_available:
        previous_eligible = rows["previous_lap_was_target_eligible"].astype(bool)
        immediate_available = rows[list(immediate_columns)].notna().all(axis=1)
        immediate_absent = rows[list(immediate_columns)].isna().all(axis=1)
        mismatch = (previous_eligible & ~immediate_available) | (
            ~previous_eligible & ~immediate_absent
        )
        mismatch_count = int(mismatch.sum())

        if mismatch_count:
            _append_issue(
                issues,
                DecisionValidationIssueCode.IMMEDIATE_HISTORY_MISMATCH,
                f"{mismatch_count} rows violate immediate-history nullability",
                affected_rows=mismatch_count,
            )

    rolling_columns = (
        "rolling_lap_time_median_3",
        "rolling_lap_time_median_5",
        "rolling_lap_time_std_5",
        "rolling_lap_time_trend_5",
    )

    rolling_values_available = _required_columns_present(
        rows,
        ("eligible_laps_completed", "minimum_history_available", *rolling_columns),
    ) and rows[
        ["eligible_laps_completed", "minimum_history_available"]
    ].notna().all().all()

    if rolling_values_available:
        sufficient = rows["eligible_laps_completed"].ge(3)
        flag_mismatch = rows["minimum_history_available"].ne(sufficient)
        rolling_available = rows[list(rolling_columns)].notna().all(axis=1)
        rolling_absent = rows[list(rolling_columns)].isna().all(axis=1)
        value_mismatch = (sufficient & ~rolling_available) | (
            ~sufficient & ~rolling_absent
        )
        mismatch_count = int((flag_mismatch | value_mismatch).sum())

        if mismatch_count:
            _append_issue(
                issues,
                DecisionValidationIssueCode.ROLLING_HISTORY_MISMATCH,
                f"{mismatch_count} rows violate rolling-history availability",
                affected_rows=mismatch_count,
            )

    if row_ids_are_unique and label_ids_are_unique:
        historical_mismatch_count = (
            _past_only_history_mismatch_count(
                rows,
                labels,
            )
        )

        if historical_mismatch_count:
            _append_issue(
                issues,
                DecisionValidationIssueCode.HISTORICAL_VALUE_MISMATCH,
                f"{historical_mismatch_count} rows disagree with "
                "strictly earlier lap labels",
                affected_rows=historical_mismatch_count,
            )

    action_values_available = _required_columns_present(
        labels,
        ("did_pit", "historical_action"),
    ) and labels[["did_pit", "historical_action"]].notna().all().all()

    if action_values_available:
        did_pit = labels["did_pit"].astype(bool)
        expected_actions = np.where(did_pit, "PIT_NOW", "STAY_OUT")
        mismatch_count = int(
            labels["historical_action"].astype(str).ne(expected_actions).sum()
        )

        if mismatch_count:
            _append_issue(
                issues,
                DecisionValidationIssueCode.HISTORICAL_ACTION_MISMATCH,
                f"{mismatch_count} historical actions disagree with did_pit",
                affected_rows=mismatch_count,
            )

    lineage_values_available = _required_columns_present(
        labels,
        ("did_pit", "pit_event_id"),
    ) and labels["did_pit"].notna().all()

    if lineage_values_available:
        did_pit = labels["did_pit"].astype(bool)
        lineage_mismatch = (did_pit & labels["pit_event_id"].isna()) | (
            ~did_pit & labels["pit_event_id"].notna()
        )
        mismatch_count = int(lineage_mismatch.sum())

        if mismatch_count:
            _append_issue(
                issues,
                DecisionValidationIssueCode.PIT_EVENT_LINEAGE_MISMATCH,
                f"{mismatch_count} labels have inconsistent pit-event lineage",
                affected_rows=mismatch_count,
            )

    target_values_available = _required_columns_present(
        labels,
        ("is_lap_time_target_eligible", "lap_time_target_seconds"),
    ) and labels["is_lap_time_target_eligible"].notna().all()

    if target_values_available:
        target_eligible = labels["is_lap_time_target_eligible"].astype(bool)
        target_mismatch = (
            target_eligible & labels["lap_time_target_seconds"].isna()
        ) | (~target_eligible & labels["lap_time_target_seconds"].notna())
        mismatch_count = int(target_mismatch.sum())

        if mismatch_count:
            _append_issue(
                issues,
                DecisionValidationIssueCode.TARGET_NULLABILITY_MISMATCH,
                f"{mismatch_count} labels violate target nullability",
                affected_rows=mismatch_count,
            )

    target_exclusions_available = _required_columns_present(
        labels,
        (
            "lap_target_exclusion_count",
            "lap_target_exclusion_reasons",
            "is_lap_time_target_eligible",
        ),
    ) and labels[
        [
            "lap_target_exclusion_count",
            "lap_target_exclusion_reasons",
            "is_lap_time_target_eligible",
        ]
    ].notna().all().all()

    if target_exclusions_available:
        encoded_counts = labels["lap_target_exclusion_reasons"].map(
            _encoded_reason_count
        )
        count_mismatch = labels["lap_target_exclusion_count"].ne(encoded_counts)
        eligible_with_exclusion = labels["is_lap_time_target_eligible"].astype(
            bool
        ) & labels["lap_target_exclusion_count"].ne(0)
        mismatch_count = int((count_mismatch | eligible_with_exclusion).sum())

        if mismatch_count:
            _append_issue(
                issues,
                DecisionValidationIssueCode.TARGET_EXCLUSION_MISMATCH,
                f"{mismatch_count} labels have inconsistent target exclusions",
                affected_rows=mismatch_count,
            )

    eligible_decisions = 0

    if "is_decision_eligible" in rows.columns:
        eligible_decisions = int(rows["is_decision_eligible"].eq(True).sum())

    return DecisionValidationReport(
        session_key=session_key,
        decision_rows=len(rows),
        label_rows=len(labels),
        eligible_decisions=eligible_decisions,
        ineligible_decisions=len(rows) - eligible_decisions,
        future_weather_matches=future_weather_matches,
        evaluation_season_rows=evaluation_season_rows,
        current_lap_timing_features=timing_features,
        current_lap_quality_features=quality_features,
        feature_columns_outside_allowlist=feature_outside_allowlist,
        issues=tuple(issues),
    )
