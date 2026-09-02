"""Pit-duration target construction from normalized processed events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd

from app.datasets.contracts import (
    DATASET_CONTRACT_VERSION,
    DEVELOPMENT_SEASONS,
    DRY_COMPOUNDS,
    PIT_DURATION_OBSERVATIONS_CONTRACT,
    PROTECTED_EVALUATION_SEASON,
)
from app.datasets.normalization import (
    NormalizedProcessedSession,
)
from app.pipeline import SessionKey


class PitDurationExclusionReason(StrEnum):
    """Frozen reasons why an observed event has no duration target."""

    INCOMPLETE_EVENT = "INCOMPLETE_EVENT"
    NO_STINT_CHANGE = "NO_STINT_CHANGE"
    NON_GREEN_FLAG_PAIR = "NON_GREEN_FLAG_PAIR"
    UNSUPPORTED_DRY_COMPOUND_PAIR = (
        "UNSUPPORTED_DRY_COMPOUND_PAIR"
    )
    NON_DRY_WEATHER_PAIR = "NON_DRY_WEATHER_PAIR"
    INTERRUPTED_DURATION = "INTERRUPTED_DURATION"


PIT_DURATION_EXCLUSION_REASON_ORDER = (
    PitDurationExclusionReason.INCOMPLETE_EVENT,
    PitDurationExclusionReason.NO_STINT_CHANGE,
    PitDurationExclusionReason.NON_GREEN_FLAG_PAIR,
    PitDurationExclusionReason.UNSUPPORTED_DRY_COMPOUND_PAIR,
    PitDurationExclusionReason.NON_DRY_WEATHER_PAIR,
    PitDurationExclusionReason.INTERRUPTED_DURATION,
)


class PitDurationIssueCode(StrEnum):
    """Stable machine-readable pit-duration validation issue codes."""

    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    REQUIRED_VALUE_MISSING = "REQUIRED_VALUE_MISSING"
    ROW_COUNT_MISMATCH = "ROW_COUNT_MISMATCH"
    DUPLICATE_PIT_EVENT_ID = "DUPLICATE_PIT_EVENT_ID"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    CONTRACT_VERSION_MISMATCH = "CONTRACT_VERSION_MISMATCH"
    EVALUATION_SEASON_DETECTED = "EVALUATION_SEASON_DETECTED"
    UNSUPPORTED_SEASON_DETECTED = "UNSUPPORTED_SEASON_DETECTED"
    ELIGIBILITY_MISMATCH = "ELIGIBILITY_MISMATCH"
    TARGET_NULLABILITY_MISMATCH = (
        "TARGET_NULLABILITY_MISMATCH"
    )
    TARGET_VALUE_MISMATCH = "TARGET_VALUE_MISMATCH"
    EXCLUSION_ENCODING_MISMATCH = (
        "EXCLUSION_ENCODING_MISMATCH"
    )


@dataclass(frozen=True, slots=True)
class PitDurationIssue:
    """One independent pit-duration validation failure."""

    code: PitDurationIssueCode
    message: str
    affected_rows: int = 0


class PitDurationConstructionError(ValueError):
    """Raised when pit-duration targets cannot be constructed safely."""


@dataclass(frozen=True, slots=True)
class PitDurationValidationReport:
    """Independent validation result for one session's observations."""

    session_key: SessionKey
    rows: int
    eligible_targets: int
    ineligible_targets: int
    evaluation_season_rows: int
    issues: tuple[PitDurationIssue, ...]

    @property
    def is_valid(self) -> bool:
        """Return whether no construction or integrity issue exists."""
        return not self.issues

    @property
    def issue_count(self) -> int:
        """Return the number of distinct reported issues."""
        return len(self.issues)

    def raise_for_errors(self) -> None:
        """Raise one concise fail-closed construction error."""
        if self.is_valid:
            return

        summary = "; ".join(
            f"{issue.code.value}: {issue.message}"
            for issue in self.issues
        )

        raise PitDurationConstructionError(
            "pit-duration observations for "
            f"{self.session_key.identifier} are invalid: "
            f"{summary}"
        )


@dataclass(frozen=True, slots=True)
class PitDurationSessionData:
    """Validated pit-duration observations for one development race."""

    session_key: SessionKey
    event_name: str
    source_pit_event_count: int
    observations: pd.DataFrame

    @property
    def eligible_target_count(self) -> int:
        """Return the number of usable duration targets."""
        return int(
            self.observations[
                "is_pit_duration_target_eligible"
            ]
            .eq(True)
            .sum()
        )

    @property
    def ineligible_target_count(self) -> int:
        """Return the number of excluded duration targets."""
        return (
            len(self.observations)
            - self.eligible_target_count
        )


def _append_issue(
    issues: list[PitDurationIssue],
    code: PitDurationIssueCode,
    message: str,
    *,
    affected_rows: int = 0,
) -> None:
    """Append one issue with a normalized non-negative row count."""
    issues.append(
        PitDurationIssue(
            code=code,
            message=message,
            affected_rows=max(
                0,
                int(affected_rows),
            ),
        )
    )


def _validate_development_key(
    session_key: SessionKey,
) -> None:
    """Reject protected or unsupported sessions immediately."""
    if not isinstance(session_key, SessionKey):
        raise TypeError(
            "session_key must be a SessionKey"
        )

    if session_key.season == (
        PROTECTED_EVALUATION_SEASON
    ):
        raise PitDurationConstructionError(
            f"{session_key.identifier} belongs to the "
            "protected evaluation season"
        )

    if session_key.season not in DEVELOPMENT_SEASONS:
        raise PitDurationConstructionError(
            f"{session_key.identifier} is outside the "
            "development seasons"
        )

    if session_key.session_type != "R":
        raise PitDurationConstructionError(
            f"{session_key.identifier} is not a race session"
        )


def _is_true(value: object) -> bool:
    """Return whether a possibly-null scalar is explicitly true."""
    if pd.isna(value):
        return False

    return bool(
        value is True
        or (
            isinstance(value, np.bool_)
            and bool(value)
        )
    )


def _is_supported_dry_compound_pair(
    compound_before: object,
    compound_after: object,
) -> bool:
    """Return whether both event compounds are supported and dry."""
    if (
        pd.isna(compound_before)
        or pd.isna(compound_after)
    ):
        return False

    return bool(
        str(compound_before) in DRY_COMPOUNDS
        and str(compound_after) in DRY_COMPOUNDS
    )


def _expected_exclusion_reasons(
    row: pd.Series,
) -> tuple[PitDurationExclusionReason, ...]:
    """Recompute ordered exclusion reasons from stored context."""
    reasons: list[PitDurationExclusionReason] = []

    if not _is_true(row["is_complete"]):
        reasons.append(
            PitDurationExclusionReason.INCOMPLETE_EVENT
        )

    if not _is_true(row["is_stint_change"]):
        reasons.append(
            PitDurationExclusionReason.NO_STINT_CHANGE
        )

    if not _is_true(row["is_green_flag_pair"]):
        reasons.append(
            PitDurationExclusionReason.NON_GREEN_FLAG_PAIR
        )

    if not _is_supported_dry_compound_pair(
        row["compound_before"],
        row["compound_after"],
    ):
        reasons.append(
            PitDurationExclusionReason
            .UNSUPPORTED_DRY_COMPOUND_PAIR
        )

    if not _is_true(row["is_dry_weather_pair"]):
        reasons.append(
            PitDurationExclusionReason.NON_DRY_WEATHER_PAIR
        )

    if _is_true(row["is_interrupted_duration"]):
        reasons.append(
            PitDurationExclusionReason.INTERRUPTED_DURATION
        )

    return tuple(reasons)


def _cast_contract(
    observations: pd.DataFrame,
) -> pd.DataFrame:
    """Cast and order one observation table to its contract."""
    result = observations.copy(deep=True)

    for column in (
        PIT_DURATION_OBSERVATIONS_CONTRACT.columns
    ):
        result[column.name] = result[
            column.name
        ].astype(column.pandas_dtype)

    return result[
        [
            column.name
            for column in (
                PIT_DURATION_OBSERVATIONS_CONTRACT.columns
            )
        ]
    ]


def _validate_source_consistency(
    pit_events: pd.DataFrame,
    session_key: SessionKey,
) -> None:
    """Independently verify Phase 3 candidate and context flags."""
    duplicate_count = int(
        pit_events[
            "pit_event_id"
        ].duplicated().sum()
    )

    if duplicate_count:
        raise PitDurationConstructionError(
            f"{session_key.identifier} contains "
            f"{duplicate_count} duplicate pit-event IDs"
        )

    dry_compound_pair = pd.Series(
        (
            _is_supported_dry_compound_pair(
                before,
                after,
            )
            for before, after in zip(
                pit_events["compound_before"],
                pit_events["compound_after"],
                strict=True,
            )
        ),
        index=pit_events.index,
        dtype="bool",
    )
    source_dry_compound_pair = pit_events[
        "is_dry_compound_pair"
    ].astype(bool)
    compound_mismatch_count = int(
        source_dry_compound_pair.ne(
            dry_compound_pair
        ).sum()
    )

    if compound_mismatch_count:
        raise PitDurationConstructionError(
            f"{session_key.identifier} contains "
            f"{compound_mismatch_count} inconsistent "
            "dry-compound flags"
        )

    expected_dry_weather = (
        pit_events["entry_rainfall"].eq(False)
        & pit_events["exit_rainfall"].eq(False)
    ).fillna(False)
    weather_mismatch_count = int(
        pit_events[
            "is_dry_weather_pair"
        ]
        .astype(bool)
        .ne(expected_dry_weather)
        .sum()
    )

    if weather_mismatch_count:
        raise PitDurationConstructionError(
            f"{session_key.identifier} contains "
            f"{weather_mismatch_count} inconsistent "
            "dry-weather flags"
        )

    observed_duration = pit_events[
        "observed_pit_lane_duration_seconds"
    ]
    complete = pit_events[
        "is_complete"
    ].astype(bool)
    invalid_complete_duration = (
        complete
        & (
            observed_duration.isna()
            | observed_duration.le(0)
        )
    )
    invalid_complete_count = int(
        invalid_complete_duration.sum()
    )

    if invalid_complete_count:
        raise PitDurationConstructionError(
            f"{session_key.identifier} contains "
            f"{invalid_complete_count} complete events "
            "without positive observed durations"
        )

    recomputed_candidate = (
        complete
        & pit_events[
            "is_stint_change"
        ].eq(True).fillna(False)
        & pit_events[
            "is_green_flag_pair"
        ].astype(bool)
        & dry_compound_pair
        & pit_events[
            "is_dry_weather_pair"
        ].astype(bool)
        & ~pit_events[
            "is_interrupted_duration"
        ].astype(bool)
    )
    source_candidate = pit_events[
        "is_duration_analysis_candidate"
    ].astype(bool)
    candidate_mismatch_count = int(
        source_candidate.ne(
            recomputed_candidate
        ).sum()
    )

    if candidate_mismatch_count:
        raise PitDurationConstructionError(
            f"{session_key.identifier} contains "
            f"{candidate_mismatch_count} inconsistent "
            "duration-analysis candidate flags"
        )


def _build_observation_records(
    source: NormalizedProcessedSession,
) -> list[dict[str, object]]:
    """Construct target-separated records from normalized events."""
    records: list[dict[str, object]] = []
    pit_events = source.pit_events

    for _, event in pit_events.iterrows():
        reasons = _expected_exclusion_reasons(
            pd.Series(
                {
                    "is_complete": event[
                        "is_complete"
                    ],
                    "is_stint_change": event[
                        "is_stint_change"
                    ],
                    "is_green_flag_pair": event[
                        "is_green_flag_pair"
                    ],
                    "compound_before": event[
                        "compound_before"
                    ],
                    "compound_after": event[
                        "compound_after"
                    ],
                    "is_dry_weather_pair": event[
                        "is_dry_weather_pair"
                    ],
                    "is_interrupted_duration": event[
                        "is_interrupted_duration"
                    ],
                }
            )
        )
        eligible = not reasons
        observed_duration = event[
            "observed_pit_lane_duration_seconds"
        ]

        records.append(
            {
                "pit_event_id": event[
                    "pit_event_id"
                ],
                "session_id": (
                    source.session_key.identifier
                ),
                "season": source.session_key.season,
                "round_number": (
                    source.session_key.round_number
                ),
                "session_type": (
                    source.session_key.session_type
                ),
                "event_name": source.event_name,
                "driver": event["driver"],
                "team": event["team"],
                "event_type": event["event_type"],
                "pit_in_lap": event["pit_in_lap"],
                "pit_out_lap": event["pit_out_lap"],
                "stint_before": event[
                    "stint_before"
                ],
                "stint_after": event["stint_after"],
                "compound_before": event[
                    "compound_before"
                ],
                "compound_after": event[
                    "compound_after"
                ],
                "tyre_life_before": event[
                    "tyre_life_before"
                ],
                "tyre_life_after": event[
                    "tyre_life_after"
                ],
                "is_stint_change": event[
                    "is_stint_change"
                ],
                "is_compound_change": event[
                    "is_compound_change"
                ],
                "is_complete": event[
                    "is_complete"
                ],
                "is_green_flag_pair": event[
                    "is_green_flag_pair"
                ],
                "is_dry_weather_pair": event[
                    "is_dry_weather_pair"
                ],
                "is_interrupted_duration": event[
                    "is_interrupted_duration"
                ],
                "is_pit_duration_target_eligible": (
                    eligible
                ),
                "pit_duration_target_seconds": (
                    float(observed_duration)
                    if eligible
                    else np.nan
                ),
                "pit_duration_exclusion_count": len(
                    reasons
                ),
                "pit_duration_exclusion_reasons": (
                    "|".join(
                        reason.value
                        for reason in reasons
                    )
                ),
                "dataset_contract_version": (
                    DATASET_CONTRACT_VERSION
                ),
            }
        )

    return records


def _validate_constructed_against_source(
    observations: pd.DataFrame,
    pit_events: pd.DataFrame,
    session_key: SessionKey,
) -> None:
    """Verify constructed identities, eligibility and target values."""
    observed_ids = observations[
        "pit_event_id"
    ].reset_index(drop=True)
    source_ids = pit_events[
        "pit_event_id"
    ].reset_index(drop=True)

    if not observed_ids.equals(source_ids):
        raise PitDurationConstructionError(
            f"{session_key.identifier} pit-event identity "
            "or ordering changed during construction"
        )

    source_eligible = pit_events[
        "is_duration_analysis_candidate"
    ].astype(bool).reset_index(drop=True)
    built_eligible = observations[
        "is_pit_duration_target_eligible"
    ].astype(bool).reset_index(drop=True)

    if not source_eligible.equals(built_eligible):
        mismatch_count = int(
            source_eligible.ne(
                built_eligible
            ).sum()
        )
        raise PitDurationConstructionError(
            f"{session_key.identifier} contains "
            f"{mismatch_count} constructed eligibility "
            "mismatches"
        )

    eligible_mask = built_eligible.to_numpy(
        dtype=bool
    )
    source_targets = pit_events[
        "observed_pit_lane_duration_seconds"
    ].reset_index(drop=True)
    built_targets = observations[
        "pit_duration_target_seconds"
    ].reset_index(drop=True)

    if not np.allclose(
        built_targets[eligible_mask].to_numpy(
            dtype=float
        ),
        source_targets[eligible_mask].to_numpy(
            dtype=float
        ),
        rtol=0.0,
        atol=0.0,
    ):
        raise PitDurationConstructionError(
            f"{session_key.identifier} pit-duration targets "
            "differ from eligible source observations"
        )


def _validate_schema(
    observations: pd.DataFrame,
    issues: list[PitDurationIssue],
) -> None:
    """Validate exact columns, dtypes and required nullability."""
    expected_columns = tuple(
        column.name
        for column in (
            PIT_DURATION_OBSERVATIONS_CONTRACT.columns
        )
    )
    actual_columns = tuple(
        str(column)
        for column in observations.columns
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
            PitDurationIssueCode.SCHEMA_MISMATCH,
            "pit-duration columns differ from the contract; "
            f"missing={missing}, extra={extra}",
        )

    for column in (
        PIT_DURATION_OBSERVATIONS_CONTRACT.columns
    ):
        if column.name not in observations.columns:
            continue

        actual_dtype = str(
            observations[column.name].dtype
        )

        if actual_dtype != column.pandas_dtype:
            _append_issue(
                issues,
                PitDurationIssueCode.SCHEMA_MISMATCH,
                f"pit_duration_observations.{column.name} "
                f"has dtype {actual_dtype}; expected "
                f"{column.pandas_dtype}",
            )

        if not column.nullable:
            missing_count = int(
                observations[
                    column.name
                ].isna().sum()
            )

            if missing_count:
                _append_issue(
                    issues,
                    PitDurationIssueCode.REQUIRED_VALUE_MISSING,
                    f"pit_duration_observations.{column.name} "
                    f"contains {missing_count} missing values",
                    affected_rows=missing_count,
                )


def _encoded_reason_count(value: object) -> int:
    """Count one deterministic pipe-delimited exclusion string."""
    if pd.isna(value):
        return -1

    text = str(value)

    if not text:
        return 0

    return len(text.split("|"))


def _safe_whole_number(value: object) -> int | None:
    """Return a whole-number scalar or None without raising."""
    if pd.isna(value):
        return None

    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None

    if not np.isfinite(numeric) or not numeric.is_integer():
        return None

    return int(numeric)


def _is_positive_finite_number(value: object) -> bool:
    """Return whether a scalar is a finite positive number."""
    if pd.isna(value):
        return False

    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return False

    return bool(
        np.isfinite(numeric)
        and numeric > 0
    )


def validate_pit_duration_session(
    data: PitDurationSessionData,
) -> PitDurationValidationReport:
    """Independently validate one session's duration observations."""
    if not isinstance(data, PitDurationSessionData):
        raise TypeError(
            "data must be a PitDurationSessionData"
        )

    session_key = data.session_key

    if not isinstance(session_key, SessionKey):
        raise TypeError(
            "data.session_key must be a SessionKey"
        )

    if not isinstance(
        data.observations,
        pd.DataFrame,
    ):
        raise TypeError(
            "data.observations must be a pandas DataFrame"
        )

    observations = data.observations.copy(
        deep=True
    )
    issues: list[PitDurationIssue] = []

    _validate_schema(observations, issues)

    if session_key.season == (
        PROTECTED_EVALUATION_SEASON
    ):
        _append_issue(
            issues,
            PitDurationIssueCode.EVALUATION_SEASON_DETECTED,
            "session key belongs to the protected evaluation season",
            affected_rows=len(observations),
        )
    elif session_key.season not in DEVELOPMENT_SEASONS:
        _append_issue(
            issues,
            PitDurationIssueCode.UNSUPPORTED_SEASON_DETECTED,
            "session key is outside the development seasons",
            affected_rows=len(observations),
        )

    source_count = _safe_whole_number(
        data.source_pit_event_count
    )

    if source_count is None or source_count < 0:
        _append_issue(
            issues,
            PitDurationIssueCode.ROW_COUNT_MISMATCH,
            "source pit-event count must be a non-negative integer",
        )
    elif len(observations) != source_count:
        _append_issue(
            issues,
            PitDurationIssueCode.ROW_COUNT_MISMATCH,
            f"stored rows {len(observations)} differ from "
            f"source rows {source_count}",
            affected_rows=abs(
                len(observations)
                - source_count
            ),
        )

    if "pit_event_id" in observations.columns:
        duplicate_count = int(
            observations[
                "pit_event_id"
            ].duplicated().sum()
        )

        if duplicate_count:
            _append_issue(
                issues,
                PitDurationIssueCode.DUPLICATE_PIT_EVENT_ID,
                f"observations contain {duplicate_count} "
                "duplicate pit-event IDs",
                affected_rows=duplicate_count,
            )

    expected_identity = {
        "session_id": session_key.identifier,
        "season": session_key.season,
        "round_number": session_key.round_number,
        "session_type": session_key.session_type,
        "event_name": data.event_name,
    }

    for column, expected in expected_identity.items():
        if column not in observations.columns:
            continue

        mismatch_count = int(
            observations[column]
            .astype("string")
            .ne(str(expected))
            .fillna(True)
            .sum()
        )

        if mismatch_count:
            _append_issue(
                issues,
                PitDurationIssueCode.IDENTITY_MISMATCH,
                f"{mismatch_count} {column} values disagree "
                "with the session",
                affected_rows=mismatch_count,
            )

    evaluation_season_rows = 0

    if "season" in observations.columns:
        numeric_seasons = pd.to_numeric(
            observations["season"],
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
                PitDurationIssueCode.EVALUATION_SEASON_DETECTED,
                f"observations contain {evaluation_season_rows} "
                "protected evaluation-season rows",
                affected_rows=evaluation_season_rows,
            )

        if unsupported_count:
            _append_issue(
                issues,
                PitDurationIssueCode.UNSUPPORTED_SEASON_DETECTED,
                f"observations contain {unsupported_count} "
                "unsupported season rows",
                affected_rows=unsupported_count,
            )

    if "dataset_contract_version" in observations.columns:
        version_mismatch_count = int(
            observations[
                "dataset_contract_version"
            ]
            .astype("string")
            .ne(DATASET_CONTRACT_VERSION)
            .fillna(True)
            .sum()
        )

        if version_mismatch_count:
            _append_issue(
                issues,
                PitDurationIssueCode.CONTRACT_VERSION_MISMATCH,
                f"{version_mismatch_count} rows differ from "
                f"dataset contract {DATASET_CONTRACT_VERSION}",
                affected_rows=version_mismatch_count,
            )

    semantic_columns = (
        "compound_before",
        "compound_after",
        "is_stint_change",
        "is_complete",
        "is_green_flag_pair",
        "is_dry_weather_pair",
        "is_interrupted_duration",
        "is_pit_duration_target_eligible",
        "pit_duration_target_seconds",
        "pit_duration_exclusion_count",
        "pit_duration_exclusion_reasons",
    )

    if all(
        column in observations.columns
        for column in semantic_columns
    ):
        eligibility_mismatches = 0
        target_nullability_mismatches = 0
        target_value_mismatches = 0
        exclusion_mismatches = 0

        for _, row in observations.iterrows():
            expected_reasons = (
                _expected_exclusion_reasons(
                    row
                )
            )
            expected_reason_string = "|".join(
                reason.value
                for reason in expected_reasons
            )
            expected_eligible = not expected_reasons
            stored_eligible = _is_true(
                row[
                    "is_pit_duration_target_eligible"
                ]
            )

            if stored_eligible != expected_eligible:
                eligibility_mismatches += 1

            target = row[
                "pit_duration_target_seconds"
            ]

            if expected_eligible:
                if pd.isna(target):
                    target_nullability_mismatches += 1
                elif not _is_positive_finite_number(
                    target
                ):
                    target_value_mismatches += 1
            elif pd.notna(target):
                target_nullability_mismatches += 1

            reason_value = row[
                "pit_duration_exclusion_reasons"
            ]
            stored_reason_string = (
                str(reason_value)
                if pd.notna(reason_value)
                else "<MISSING>"
            )
            stored_count = _safe_whole_number(
                row[
                    "pit_duration_exclusion_count"
                ]
            )

            if (
                stored_reason_string
                != expected_reason_string
                or stored_count
                != len(expected_reasons)
                or stored_count
                != _encoded_reason_count(
                    stored_reason_string
                )
            ):
                exclusion_mismatches += 1

        if eligibility_mismatches:
            _append_issue(
                issues,
                PitDurationIssueCode.ELIGIBILITY_MISMATCH,
                f"{eligibility_mismatches} eligibility flags "
                "disagree with source context",
                affected_rows=eligibility_mismatches,
            )

        if target_nullability_mismatches:
            _append_issue(
                issues,
                PitDurationIssueCode
                .TARGET_NULLABILITY_MISMATCH,
                f"{target_nullability_mismatches} targets violate "
                "eligibility nullability",
                affected_rows=(
                    target_nullability_mismatches
                ),
            )

        if target_value_mismatches:
            _append_issue(
                issues,
                PitDurationIssueCode.TARGET_VALUE_MISMATCH,
                f"{target_value_mismatches} eligible targets "
                "are non-positive or non-finite",
                affected_rows=target_value_mismatches,
            )

        if exclusion_mismatches:
            _append_issue(
                issues,
                PitDurationIssueCode
                .EXCLUSION_ENCODING_MISMATCH,
                f"{exclusion_mismatches} rows have invalid "
                "exclusion encoding",
                affected_rows=exclusion_mismatches,
            )

    eligible_targets = 0

    if (
        "is_pit_duration_target_eligible"
        in observations.columns
    ):
        eligible_targets = int(
            observations[
                "is_pit_duration_target_eligible"
            ]
            .eq(True)
            .sum()
        )

    return PitDurationValidationReport(
        session_key=session_key,
        rows=len(observations),
        eligible_targets=eligible_targets,
        ineligible_targets=(
            len(observations)
            - eligible_targets
        ),
        evaluation_season_rows=(
            evaluation_season_rows
        ),
        issues=tuple(issues),
    )


def build_pit_duration_observations(
    source: NormalizedProcessedSession,
) -> PitDurationSessionData:
    """Build validated duration targets for all source pit events."""
    if not isinstance(
        source,
        NormalizedProcessedSession,
    ):
        raise TypeError(
            "source must be a NormalizedProcessedSession"
        )

    _validate_development_key(
        source.session_key
    )
    original_pit_events = (
        source.pit_events.copy(deep=True)
    )
    _validate_source_consistency(
        source.pit_events,
        source.session_key,
    )

    records = _build_observation_records(
        source
    )
    columns = [
        column.name
        for column in (
            PIT_DURATION_OBSERVATIONS_CONTRACT.columns
        )
    ]
    observations = pd.DataFrame.from_records(
        records,
        columns=columns,
    )
    observations = _cast_contract(
        observations
    )
    _validate_constructed_against_source(
        observations,
        source.pit_events,
        source.session_key,
    )

    data = PitDurationSessionData(
        session_key=source.session_key,
        event_name=source.event_name,
        source_pit_event_count=len(
            source.pit_events
        ),
        observations=observations,
    )
    report = validate_pit_duration_session(
        data
    )
    report.raise_for_errors()

    pd.testing.assert_frame_equal(
        source.pit_events,
        original_pit_events,
    )

    return data