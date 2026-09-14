"""Tests for independent decision-table leakage validation."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from app.datasets.contracts import (
    DATASET_CONTRACT_VERSION,
    DECISION_LABELS_CONTRACT,
    DECISION_MODEL_FEATURE_COLUMNS,
    DECISION_ROWS_CONTRACT,
    SOURCE_CLEANING_RULE_VERSION,
    SOURCE_PROCESSED_CONTRACT_VERSION,
    TableContract,
)
from app.datasets.decisions import DecisionSessionData
from app.datasets.validation import (
    DecisionDatasetValidationError,
    DecisionValidationIssueCode,
    model_feature_columns_outside_allowlist,
    require_allowed_model_features,
    validate_decision_session,
)
from app.pipeline import SessionKey

SESSION_KEY = SessionKey(
    season=2024,
    round_number=1,
    session_type="R",
)


def _default_value(
    pandas_dtype: str,
) -> object:
    """Return one non-null placeholder for a contract dtype."""
    if pandas_dtype in {"string", "object"}:
        return "VALUE"

    if pandas_dtype in {"bool", "boolean"}:
        return False

    if pandas_dtype in {"int64", "Int64"}:
        return 1

    if pandas_dtype == "float64":
        return 1.0

    raise AssertionError(
        f"unsupported test dtype: {pandas_dtype}"
    )


def _contract_table(
    contract: TableContract,
    *,
    rows: int,
) -> pd.DataFrame:
    """Create a populated table in exact contract order and dtypes."""
    return pd.DataFrame(
        {
            column.name: pd.Series(
                [
                    _default_value(
                        column.pandas_dtype
                    )
                ]
                * rows,
                dtype=column.pandas_dtype,
            )
            for column in contract.columns
        }
    )


def _cast_to_contract(
    table: pd.DataFrame,
    contract: TableContract,
) -> pd.DataFrame:
    """Restore exact extension and NumPy dtypes after mutation."""
    result = table.copy(deep=True)

    for column in contract.columns:
        result[column.name] = result[
            column.name
        ].astype(column.pandas_dtype)

    return result[
        [
            column.name
            for column in contract.columns
        ]
    ]


def make_decision_session() -> DecisionSessionData:
    """Create four internally consistent candidate decisions."""
    decision_rows = _contract_table(
        DECISION_ROWS_CONTRACT,
        rows=4,
    )
    decision_labels = _contract_table(
        DECISION_LABELS_CONTRACT,
        rows=4,
    )

    decision_laps = [2, 3, 4, 5]
    decision_ids = [
        f"{SESSION_KEY.identifier}-HAM-{lap:03d}"
        for lap in decision_laps
    ]

    shared_identity: dict[str, object] = {
        "decision_id": decision_ids,
        "session_id": [
            SESSION_KEY.identifier
        ]
        * 4,
        "season": [SESSION_KEY.season] * 4,
        "round_number": [
            SESSION_KEY.round_number
        ]
        * 4,
        "session_type": [
            SESSION_KEY.session_type
        ]
        * 4,
        "driver": ["HAM"] * 4,
        "decision_lap": decision_laps,
    }

    for column, values in shared_identity.items():
        decision_rows[column] = values
        decision_labels[column] = values

    decision_rows["event_name"] = (
        "Bahrain Grand Prix"
    )
    decision_rows["driver_number"] = "44"
    decision_rows["team"] = "Mercedes"
    decision_rows["decision_time_seconds"] = [
        100.0,
        200.0,
        300.0,
        400.0,
    ]
    decision_rows["source_row_number"] = [
        2,
        3,
        4,
        5,
    ]
    decision_rows["dataset_contract_version"] = (
        DATASET_CONTRACT_VERSION
    )
    decision_rows["cleaning_rule_version"] = (
        SOURCE_CLEANING_RULE_VERSION
    )
    decision_rows["processed_contract_version"] = (
        SOURCE_PROCESSED_CONTRACT_VERSION
    )
    decision_rows["current_compound"] = "MEDIUM"
    decision_rows["tyre_age_laps"] = [
        1,
        2,
        3,
        4,
    ]
    decision_rows["current_stint_number"] = 1
    decision_rows["current_stint_laps_completed"] = [
        1,
        2,
        3,
        4,
    ]
    decision_rows["completed_pit_stops"] = 0
    decision_rows["previous_position"] = 1.0
    decision_rows[
        "previous_lap_was_target_eligible"
    ] = True
    decision_rows["previous_lap_time_seconds"] = [
        100.0,
        101.0,
        102.0,
        103.0,
    ]
    decision_rows["previous_sector1_time_seconds"] = [
        30.0,
        30.1,
        30.2,
        30.3,
    ]
    decision_rows["previous_sector2_time_seconds"] = [
        40.0,
        40.1,
        40.2,
        40.3,
    ]
    decision_rows["previous_sector3_time_seconds"] = [
        30.0,
        30.8,
        31.6,
        32.4,
    ]
    decision_rows["eligible_laps_completed"] = [
        1,
        2,
        3,
        4,
    ]
    decision_rows["rolling_lap_time_median_3"] = [
        np.nan,
        np.nan,
        101.0,
        102.0,
    ]
    decision_rows["rolling_lap_time_median_5"] = [
        np.nan,
        np.nan,
        101.0,
        101.5,
    ]
    decision_rows["rolling_lap_time_std_5"] = [
        np.nan,
        np.nan,
        float(np.std([100.0, 101.0, 102.0])),
        float(
            np.std(
                [100.0, 101.0, 102.0, 103.0]
            )
        ),
    ]
    decision_rows["rolling_lap_time_trend_5"] = [
        np.nan,
        np.nan,
        1.0,
        1.0,
    ]
    decision_rows["weather_observation_time_seconds"] = [
        99.0,
        199.0,
        299.0,
        399.0,
    ]
    decision_rows["weather_age_seconds"] = 1.0
    decision_rows["air_temperature_celsius"] = 25.0
    decision_rows["humidity_percent"] = 50.0
    decision_rows["pressure_mbar"] = 1010.0
    decision_rows["track_temperature_celsius"] = 35.0
    decision_rows["wind_direction_degrees"] = 180
    decision_rows["wind_speed_mps"] = 2.0
    decision_rows["rainfall"] = False

    audit_columns = (
        "has_consecutive_previous_lap",
        "weather_available_by_decision",
        "previous_lap_not_pit_commitment",
        "state_reconstruction_consistent",
        "supported_dry_compound",
        "valid_current_tyre_age",
        "current_stint_identified",
        "dry_at_decision",
        "previous_lap_green",
        "minimum_history_available",
        "previous_position_available",
    )

    for column in audit_columns:
        decision_rows[column] = True

    decision_rows["minimum_history_available"] = [
        False,
        False,
        True,
        True,
    ]
    decision_rows["is_decision_eligible"] = [
        False,
        False,
        True,
        True,
    ]
    decision_rows["decision_exclusion_count"] = [
        1,
        1,
        0,
        0,
    ]
    decision_rows["decision_exclusion_reasons"] = [
        "INSUFFICIENT_ELIGIBLE_HISTORY",
        "INSUFFICIENT_ELIGIBLE_HISTORY",
        "",
        "",
    ]

    decision_labels["historical_action"] = "STAY_OUT"
    decision_labels["did_pit"] = False
    decision_labels["pit_event_id"] = pd.NA
    decision_labels["is_lap_time_target_eligible"] = True
    decision_labels["lap_time_target_seconds"] = [
        101.0,
        102.0,
        103.0,
        104.0,
    ]
    decision_labels["lap_target_exclusion_count"] = 0
    decision_labels["lap_target_exclusion_reasons"] = ""
    decision_labels["dataset_contract_version"] = (
        DATASET_CONTRACT_VERSION
    )

    return DecisionSessionData(
        session_key=SESSION_KEY,
        event_name="Bahrain Grand Prix",
        decision_rows=_cast_to_contract(
            decision_rows,
            DECISION_ROWS_CONTRACT,
        ),
        decision_labels=_cast_to_contract(
            decision_labels,
            DECISION_LABELS_CONTRACT,
        ),
    )


def _codes(
    data: DecisionSessionData,
) -> set[DecisionValidationIssueCode]:
    """Return issue codes produced for one fixture mutation."""
    return {
        issue.code
        for issue in validate_decision_session(
            data
        ).issues
    }


def test_valid_session_passes_independent_validation() -> None:
    """A contract-compliant fixture has no integrity issues."""
    report = validate_decision_session(
        make_decision_session()
    )

    assert report.is_valid
    assert report.issue_count == 0
    assert report.decision_rows == 4
    assert report.label_rows == 4
    assert report.eligible_decisions == 2
    assert report.ineligible_decisions == 2
    assert report.future_weather_matches == 0
    assert report.evaluation_season_rows == 0
    assert report.current_lap_timing_features == ()
    assert report.current_lap_quality_features == ()
    assert report.feature_columns_outside_allowlist == ()
    report.raise_for_errors()


def test_validator_rejects_wrong_input_type() -> None:
    """Only constructed decision-session objects are accepted."""
    with pytest.raises(
        TypeError,
        match="DecisionSessionData",
    ):
        validate_decision_session(  # type: ignore[arg-type]
            object()
        )


def test_report_raises_concise_fail_closed_error() -> None:
    """Invalid reports expose their stable issue code."""
    data = make_decision_session()
    rows = data.decision_rows.copy(deep=True)
    rows.loc[0, "weather_age_seconds"] = -1.0
    invalid = replace(
        data,
        decision_rows=rows,
    )
    report = validate_decision_session(invalid)

    with pytest.raises(
        DecisionDatasetValidationError,
        match="NEGATIVE_WEATHER_AGE",
    ):
        report.raise_for_errors()


def test_explicit_allowlisted_feature_selection_passes() -> None:
    """The frozen feature tuple can be selected explicitly."""
    selected = require_allowed_model_features(
        DECISION_MODEL_FEATURE_COLUMNS
    )

    assert selected == DECISION_MODEL_FEATURE_COLUMNS
    assert (
        model_feature_columns_outside_allowlist(
            selected
        )
        == ()
    )


@pytest.mark.parametrize(
    "selection",
    [
        (),
        (
            DECISION_MODEL_FEATURE_COLUMNS[0],
            DECISION_MODEL_FEATURE_COLUMNS[0],
        ),
        ("lap_time_target_seconds",),
        ("IsEligible",),
    ],
)
def test_invalid_model_feature_selection_fails_closed(
    selection: tuple[str, ...],
) -> None:
    """Empty, duplicate, target and quality selections fail."""
    with pytest.raises(
        DecisionDatasetValidationError
    ):
        require_allowed_model_features(selection)


def test_feature_helpers_reject_string_iterables() -> None:
    """A single string cannot be mistaken for many columns."""
    with pytest.raises(TypeError):
        require_allowed_model_features("driver")

    with pytest.raises(TypeError):
        model_feature_columns_outside_allowlist(
            "driver"
        )


def test_feature_helpers_reject_non_string_names() -> None:
    """Feature column names must all be strings."""
    with pytest.raises(TypeError):
        model_feature_columns_outside_allowlist(
            ["driver", 44]  # type: ignore[list-item]
        )


def test_future_weather_is_detected() -> None:
    """Weather after the start-of-lap decision is forbidden."""
    data = make_decision_session()
    rows = data.decision_rows.copy(deep=True)
    rows.loc[
        0,
        "weather_observation_time_seconds",
    ] = 101.0
    invalid = replace(data, decision_rows=rows)
    report = validate_decision_session(invalid)

    assert report.future_weather_matches == 1
    assert (
        DecisionValidationIssueCode.FUTURE_WEATHER_DETECTED
        in _codes(invalid)
    )


def test_negative_weather_age_is_detected() -> None:
    """Negative weather age is another future-data signal."""
    data = make_decision_session()
    rows = data.decision_rows.copy(deep=True)
    rows.loc[0, "weather_age_seconds"] = -0.1
    invalid = replace(data, decision_rows=rows)

    assert (
        DecisionValidationIssueCode.NEGATIVE_WEATHER_AGE
        in _codes(invalid)
    )


def test_duplicate_decision_id_is_reported_without_crashing() -> None:
    """Duplicate rows produce issues instead of a merge error."""
    data = make_decision_session()
    rows = data.decision_rows.copy(deep=True)
    rows.loc[1, "decision_id"] = rows.loc[
        0,
        "decision_id",
    ]
    invalid = replace(data, decision_rows=rows)
    codes = _codes(invalid)

    assert (
        DecisionValidationIssueCode.DUPLICATE_DECISION_ID
        in codes
    )
    assert (
        DecisionValidationIssueCode.IDENTITY_SET_MISMATCH
        in codes
    )


def test_duplicate_label_id_is_reported_without_crashing() -> None:
    """Duplicate labels also remain a reportable failure."""
    data = make_decision_session()
    labels = data.decision_labels.copy(deep=True)
    labels.loc[1, "decision_id"] = labels.loc[
        0,
        "decision_id",
    ]
    invalid = replace(data, decision_labels=labels)

    assert (
        DecisionValidationIssueCode.DUPLICATE_LABEL_ID
        in _codes(invalid)
    )


def test_missing_label_identity_is_detected() -> None:
    """Decision and label identity sets must be identical."""
    data = make_decision_session()
    labels = data.decision_labels.iloc[:-1].copy()
    invalid = replace(data, decision_labels=labels)

    assert (
        DecisionValidationIssueCode.IDENTITY_SET_MISMATCH
        in _codes(invalid)
    )


def test_joined_identity_value_disagreement_is_detected() -> None:
    """Matching IDs cannot hide disagreement in identity fields."""
    data = make_decision_session()
    labels = data.decision_labels.copy(deep=True)
    labels.loc[0, "driver"] = "RUS"
    invalid = replace(data, decision_labels=labels)

    assert (
        DecisionValidationIssueCode.IDENTITY_VALUE_MISMATCH
        in _codes(invalid)
    )


def test_non_deterministic_decision_id_is_detected() -> None:
    """Decision IDs must be reproducible from their identity."""
    data = make_decision_session()
    rows = data.decision_rows.copy(deep=True)
    labels = data.decision_labels.copy(deep=True)
    rows.loc[0, "decision_id"] = "arbitrary"
    labels.loc[0, "decision_id"] = "arbitrary"
    invalid = replace(
        data,
        decision_rows=rows,
        decision_labels=labels,
    )

    assert (
        DecisionValidationIssueCode.NON_DETERMINISTIC_DECISION_ID
        in _codes(invalid)
    )


def test_contract_version_mismatch_is_detected() -> None:
    """Unsupported dataset versions fail closed."""
    data = make_decision_session()
    rows = data.decision_rows.copy(deep=True)
    rows.loc[0, "dataset_contract_version"] = "999.0"
    invalid = replace(data, decision_rows=rows)

    assert (
        DecisionValidationIssueCode.CONTRACT_VERSION_MISMATCH
        in _codes(invalid)
    )


def test_protected_session_key_is_detected() -> None:
    """The protected 2025 season cannot enter development."""
    data = replace(
        make_decision_session(),
        session_key=SessionKey(
            season=2025,
            round_number=1,
            session_type="R",
        ),
    )

    assert (
        DecisionValidationIssueCode.EVALUATION_SEASON_DETECTED
        in _codes(data)
    )


def test_protected_row_is_counted() -> None:
    """Evaluation rows are reported even under a development key."""
    data = make_decision_session()
    rows = data.decision_rows.copy(deep=True)
    rows.loc[0, "season"] = 2025
    invalid = replace(data, decision_rows=rows)
    report = validate_decision_session(invalid)

    assert report.evaluation_season_rows == 1
    assert (
        DecisionValidationIssueCode.EVALUATION_SEASON_DETECTED
        in _codes(invalid)
    )


def test_unsupported_season_is_detected() -> None:
    """Seasons outside development and evaluation also fail."""
    data = make_decision_session()
    rows = data.decision_rows.copy(deep=True)
    rows.loc[0, "season"] = 2021
    invalid = replace(data, decision_rows=rows)

    assert (
        DecisionValidationIssueCode.UNSUPPORTED_SEASON_DETECTED
        in _codes(invalid)
    )


def test_exclusion_reason_encoding_is_recomputed() -> None:
    """Stored exclusion strings cannot conceal failed flags."""
    data = make_decision_session()
    rows = data.decision_rows.copy(deep=True)
    rows.loc[2, "previous_lap_green"] = False
    invalid = replace(data, decision_rows=rows)

    assert (
        DecisionValidationIssueCode.EXCLUSION_ENCODING_MISMATCH
        in _codes(invalid)
    )


def test_decision_eligibility_is_recomputed() -> None:
    """Eligibility must equal the conjunction of audit flags."""
    data = make_decision_session()
    rows = data.decision_rows.copy(deep=True)
    rows.loc[0, "is_decision_eligible"] = True
    invalid = replace(data, decision_rows=rows)

    assert (
        DecisionValidationIssueCode.DECISION_ELIGIBILITY_MISMATCH
        in _codes(invalid)
    )


def test_historical_action_is_recomputed() -> None:
    """Historical action must agree with the pit marker."""
    data = make_decision_session()
    labels = data.decision_labels.copy(deep=True)
    labels.loc[0, "historical_action"] = "PIT_NOW"
    invalid = replace(data, decision_labels=labels)

    assert (
        DecisionValidationIssueCode.HISTORICAL_ACTION_MISMATCH
        in _codes(invalid)
    )


def test_pit_event_lineage_is_recomputed() -> None:
    """A PIT_NOW label requires its reconstructed pit-event ID."""
    data = make_decision_session()
    labels = data.decision_labels.copy(deep=True)
    labels.loc[0, "did_pit"] = True
    labels.loc[0, "historical_action"] = "PIT_NOW"
    invalid = replace(data, decision_labels=labels)

    assert (
        DecisionValidationIssueCode.PIT_EVENT_LINEAGE_MISMATCH
        in _codes(invalid)
    )


def test_target_nullability_is_recomputed() -> None:
    """Eligible lap targets must contain a target value."""
    data = make_decision_session()
    labels = data.decision_labels.copy(deep=True)
    labels.loc[0, "lap_time_target_seconds"] = np.nan
    invalid = replace(data, decision_labels=labels)

    assert (
        DecisionValidationIssueCode.TARGET_NULLABILITY_MISMATCH
        in _codes(invalid)
    )


def test_target_exclusion_encoding_is_recomputed() -> None:
    """Eligible targets cannot carry an exclusion reason."""
    data = make_decision_session()
    labels = data.decision_labels.copy(deep=True)
    labels.loc[0, "lap_target_exclusion_count"] = 1
    labels.loc[
        0,
        "lap_target_exclusion_reasons",
    ] = "PIT_IN_LAP"
    invalid = replace(data, decision_labels=labels)

    assert (
        DecisionValidationIssueCode.TARGET_EXCLUSION_MISMATCH
        in _codes(invalid)
    )


def test_immediate_history_nullability_is_checked() -> None:
    """Ineligible previous laps cannot expose performance data."""
    data = make_decision_session()
    rows = data.decision_rows.copy(deep=True)
    rows.loc[
        0,
        "previous_lap_was_target_eligible",
    ] = False
    invalid = replace(data, decision_rows=rows)

    assert (
        DecisionValidationIssueCode.IMMEDIATE_HISTORY_MISMATCH
        in _codes(invalid)
    )


def test_rolling_history_nullability_is_checked() -> None:
    """Sufficient history requires every rolling statistic."""
    data = make_decision_session()
    rows = data.decision_rows.copy(deep=True)
    rows.loc[2, "rolling_lap_time_std_5"] = np.nan
    invalid = replace(data, decision_rows=rows)

    assert (
        DecisionValidationIssueCode.ROLLING_HISTORY_MISMATCH
        in _codes(invalid)
    )


def test_rolling_values_are_recomputed_from_earlier_labels() -> None:
    """A leaked current target cannot enter a rolling feature."""
    data = make_decision_session()
    rows = data.decision_rows.copy(deep=True)
    rows.loc[2, "rolling_lap_time_median_3"] = 102.0
    invalid = replace(data, decision_rows=rows)

    assert (
        DecisionValidationIssueCode.HISTORICAL_VALUE_MISMATCH
        in _codes(invalid)
    )


def test_immediate_lap_time_is_recomputed_from_previous_label() -> None:
    """The immediate lap feature must equal lap t-minus-one."""
    data = make_decision_session()
    rows = data.decision_rows.copy(deep=True)
    rows.loc[2, "previous_lap_time_seconds"] = 999.0
    invalid = replace(data, decision_rows=rows)

    assert (
        DecisionValidationIssueCode.HISTORICAL_VALUE_MISMATCH
        in _codes(invalid)
    )


def test_current_lap_timing_column_is_detected() -> None:
    """Current timing cannot be smuggled into decision rows."""
    data = make_decision_session()
    rows = data.decision_rows.copy(deep=True)
    rows["LapTimeSeconds"] = 90.0
    invalid = replace(data, decision_rows=rows)
    report = validate_decision_session(invalid)

    assert report.current_lap_timing_features == (
        "LapTimeSeconds",
    )
    assert (
        DecisionValidationIssueCode.CURRENT_LAP_TIMING_FEATURE
        in _codes(invalid)
    )


def test_current_lap_quality_column_is_detected() -> None:
    """Current target quality cannot be smuggled into features."""
    data = make_decision_session()
    rows = data.decision_rows.copy(deep=True)
    rows["IsEligible"] = True
    invalid = replace(data, decision_rows=rows)
    report = validate_decision_session(invalid)

    assert report.current_lap_quality_features == (
        "IsEligible",
    )
    assert (
        DecisionValidationIssueCode.CURRENT_LAP_QUALITY_FEATURE
        in _codes(invalid)
    )


def test_unknown_feature_column_is_detected() -> None:
    """Generic all-except-target matrices cannot add columns."""
    data = make_decision_session()
    rows = data.decision_rows.copy(deep=True)
    rows["secret_future_feature"] = 1.0
    invalid = replace(data, decision_rows=rows)
    report = validate_decision_session(invalid)

    assert report.feature_columns_outside_allowlist == (
        "secret_future_feature",
    )
    assert (
        DecisionValidationIssueCode.FEATURE_OUTSIDE_ALLOWLIST
        in _codes(invalid)
    )


def test_schema_dtype_mismatch_is_detected() -> None:
    """Schema validation checks exact pandas dtypes."""
    data = make_decision_session()
    rows = data.decision_rows.copy(deep=True)
    rows["season"] = rows["season"].astype("string")
    invalid = replace(data, decision_rows=rows)

    assert (
        DecisionValidationIssueCode.DECISION_SCHEMA_MISMATCH
        in _codes(invalid)
    )


def test_validation_does_not_mutate_inputs() -> None:
    """Independent validation preserves both authoritative tables."""
    data = make_decision_session()
    original_rows = data.decision_rows.copy(deep=True)
    original_labels = data.decision_labels.copy(deep=True)

    validate_decision_session(data)

    pd.testing.assert_frame_equal(
        data.decision_rows,
        original_rows,
    )
    pd.testing.assert_frame_equal(
        data.decision_labels,
        original_labels,
    )
