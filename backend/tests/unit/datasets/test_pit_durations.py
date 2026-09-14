"""Tests for leakage-safe pit-duration target construction."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from app.datasets.contracts import (
    DATASET_CONTRACT_VERSION,
    PIT_DURATION_OBSERVATIONS_CONTRACT,
)
from app.datasets.normalization import (
    NormalizedProcessedSession,
)
from app.datasets.pit_durations import (
    PIT_DURATION_EXCLUSION_REASON_ORDER,
    PitDurationConstructionError,
    PitDurationExclusionReason,
    PitDurationIssueCode,
    PitDurationSessionData,
    build_pit_duration_observations,
    validate_pit_duration_session,
)
from app.pipeline import SessionKey


def _event(
    pit_event_id: str,
    *,
    compound_before: str | None = "MEDIUM",
    compound_after: str | None = "HARD",
    entry_rainfall: bool | None = False,
    exit_rainfall: bool | None = False,
    is_stint_change: bool | None = True,
    is_compound_change: bool | None = True,
    is_complete: bool = True,
    is_green_flag_pair: bool = True,
    is_interrupted_duration: bool = False,
    duration_seconds: float | None = 23.5,
) -> dict[str, object]:
    """Return one internally consistent normalized pit event."""
    is_dry_compound_pair = bool(
        compound_before in {"SOFT", "MEDIUM", "HARD"}
        and compound_after in {"SOFT", "MEDIUM", "HARD"}
    )
    is_dry_weather_pair = bool(
        entry_rainfall is False
        and exit_rainfall is False
    )
    is_candidate = bool(
        is_complete
        and is_stint_change is True
        and is_green_flag_pair
        and is_dry_compound_pair
        and is_dry_weather_pair
        and not is_interrupted_duration
    )

    return {
        "pit_event_id": pit_event_id,
        "season": 2024,
        "round_number": 1,
        "session_type": "R",
        "event_name": "Bahrain Grand Prix",
        "driver": "HAM",
        "team": "Mercedes",
        "event_type": "MATCHED",
        "pit_in_lap": 20,
        "pit_out_lap": 21,
        "stint_before": 1,
        "stint_after": 2,
        "compound_before": compound_before,
        "compound_after": compound_after,
        "tyre_life_before": 20.0,
        "tyre_life_after": 1.0,
        "pit_in_time_seconds": 1800.0,
        "pit_out_time_seconds": 1823.5,
        "observed_pit_lane_duration_seconds": (
            duration_seconds
        ),
        "entry_track_status": "1",
        "exit_track_status": "1",
        "is_stint_change": is_stint_change,
        "is_compound_change": is_compound_change,
        "is_green_flag_pair": is_green_flag_pair,
        "is_dry_compound_pair": is_dry_compound_pair,
        "is_interrupted_duration": (
            is_interrupted_duration
        ),
        "is_complete": is_complete,
        "is_duration_analysis_candidate": is_candidate,
        "warning_count": 0,
        "warnings": "",
        "entry_rainfall": entry_rainfall,
        "exit_rainfall": exit_rainfall,
        "is_dry_weather_pair": is_dry_weather_pair,
    }


def _pit_events(
    records: list[dict[str, object]],
) -> pd.DataFrame:
    """Return synthetic events with normalized source dtypes."""
    table = pd.DataFrame.from_records(records)

    string_columns = (
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
    )

    for column in string_columns:
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


@pytest.fixture
def normalized_source() -> NormalizedProcessedSession:
    """Return one source containing every eligibility outcome."""
    records = [
        _event("2024-01-R-HAM-020-021"),
        _event(
            "2024-01-R-HAM-022-023",
            is_complete=False,
        ),
        _event(
            "2024-01-R-HAM-024-025",
            is_stint_change=False,
            is_compound_change=False,
        ),
        _event(
            "2024-01-R-HAM-026-027",
            is_green_flag_pair=False,
        ),
        _event(
            "2024-01-R-HAM-028-029",
            compound_after="INTERMEDIATE",
        ),
        _event(
            "2024-01-R-HAM-030-031",
            entry_rainfall=True,
        ),
        _event(
            "2024-01-R-HAM-032-033",
            is_interrupted_duration=True,
            duration_seconds=180.0,
        ),
    ]

    return NormalizedProcessedSession(
        session_key=SessionKey(
            season=2024,
            round_number=1,
            session_type="R",
        ),
        event_name="Bahrain Grand Prix",
        laps=pd.DataFrame(),
        stints=pd.DataFrame(),
        pit_events=_pit_events(records),
    )


@pytest.fixture
def built_data(
    normalized_source: NormalizedProcessedSession,
) -> PitDurationSessionData:
    """Return valid constructed observations."""
    return build_pit_duration_observations(
        normalized_source
    )


def _issue_codes(
    data: PitDurationSessionData,
) -> set[PitDurationIssueCode]:
    """Return validation issue codes for one dataset."""
    return {
        issue.code
        for issue in validate_pit_duration_session(
            data
        ).issues
    }


def test_exclusion_reason_order_is_frozen() -> None:
    """Exclusion encoding remains deterministic."""
    assert PIT_DURATION_EXCLUSION_REASON_ORDER == (
        PitDurationExclusionReason.INCOMPLETE_EVENT,
        PitDurationExclusionReason.NO_STINT_CHANGE,
        PitDurationExclusionReason.NON_GREEN_FLAG_PAIR,
        PitDurationExclusionReason
        .UNSUPPORTED_DRY_COMPOUND_PAIR,
        PitDurationExclusionReason.NON_DRY_WEATHER_PAIR,
        PitDurationExclusionReason.INTERRUPTED_DURATION,
    )


def test_builder_preserves_one_row_per_source_event(
    normalized_source: NormalizedProcessedSession,
    built_data: PitDurationSessionData,
) -> None:
    """No pit event is silently removed from the target table."""
    assert built_data.source_pit_event_count == 7
    assert len(built_data.observations) == 7
    assert (
        built_data.observations["pit_event_id"].tolist()
        == normalized_source.pit_events[
            "pit_event_id"
        ].tolist()
    )


def test_builder_uses_exact_contract_schema(
    built_data: PitDurationSessionData,
) -> None:
    """Columns, order and dtypes match the executable contract."""
    expected_columns = [
        column.name
        for column in (
            PIT_DURATION_OBSERVATIONS_CONTRACT.columns
        )
    ]

    assert (
        built_data.observations.columns.tolist()
        == expected_columns
    )

    for column in (
        PIT_DURATION_OBSERVATIONS_CONTRACT.columns
    ):
        assert str(
            built_data.observations[
                column.name
            ].dtype
        ) == column.pandas_dtype


def test_builder_separates_target_from_ineligible_events(
    built_data: PitDurationSessionData,
) -> None:
    """Only eligible events expose observed duration as a target."""
    observations = built_data.observations
    eligible = observations[
        "is_pit_duration_target_eligible"
    ]

    assert built_data.eligible_target_count == 1
    assert built_data.ineligible_target_count == 6
    assert observations.loc[
        eligible,
        "pit_duration_target_seconds",
    ].tolist() == [23.5]
    assert observations.loc[
        ~eligible,
        "pit_duration_target_seconds",
    ].isna().all()


@pytest.mark.parametrize(
    ("row_number", "expected_reason"),
    [
        (
            1,
            PitDurationExclusionReason.INCOMPLETE_EVENT,
        ),
        (
            2,
            PitDurationExclusionReason.NO_STINT_CHANGE,
        ),
        (
            3,
            PitDurationExclusionReason.NON_GREEN_FLAG_PAIR,
        ),
        (
            4,
            PitDurationExclusionReason
            .UNSUPPORTED_DRY_COMPOUND_PAIR,
        ),
        (
            5,
            PitDurationExclusionReason.NON_DRY_WEATHER_PAIR,
        ),
        (
            6,
            PitDurationExclusionReason.INTERRUPTED_DURATION,
        ),
    ],
)
def test_builder_records_each_exclusion_reason(
    built_data: PitDurationSessionData,
    row_number: int,
    expected_reason: PitDurationExclusionReason,
) -> None:
    """Every frozen eligibility condition has an audit reason."""
    row = built_data.observations.iloc[row_number]

    assert row[
        "pit_duration_exclusion_reasons"
    ] == expected_reason.value
    assert row[
        "pit_duration_exclusion_count"
    ] == 1


def test_builder_records_empty_reason_for_eligible_event(
    built_data: PitDurationSessionData,
) -> None:
    """Eligible observations have no fabricated exclusion."""
    row = built_data.observations.iloc[0]

    assert row["pit_duration_exclusion_count"] == 0
    assert row["pit_duration_exclusion_reasons"] == ""


def test_builder_adds_identity_and_contract_provenance(
    built_data: PitDurationSessionData,
) -> None:
    """Every row remains traceable to one source session."""
    observations = built_data.observations

    assert set(observations["session_id"]) == {
        "2024-01-R"
    }
    assert set(observations["season"]) == {2024}
    assert set(observations["round_number"]) == {1}
    assert set(observations["session_type"]) == {"R"}
    assert set(observations["event_name"]) == {
        "Bahrain Grand Prix"
    }
    assert set(
        observations["dataset_contract_version"]
    ) == {DATASET_CONTRACT_VERSION}


def test_builder_does_not_mutate_source(
    normalized_source: NormalizedProcessedSession,
) -> None:
    """Construction leaves normalized processed events immutable."""
    original = normalized_source.pit_events.copy(
        deep=True
    )

    build_pit_duration_observations(
        normalized_source
    )

    pd.testing.assert_frame_equal(
        normalized_source.pit_events,
        original,
    )


def test_builder_supports_empty_pit_event_table(
    normalized_source: NormalizedProcessedSession,
) -> None:
    """A session without events still has a typed empty table."""
    empty_source = replace(
        normalized_source,
        pit_events=(
            normalized_source.pit_events.iloc[
                0:0
            ].copy()
        ),
    )

    result = build_pit_duration_observations(
        empty_source
    )

    assert result.observations.empty
    assert result.eligible_target_count == 0
    assert result.ineligible_target_count == 0

    for column in (
        PIT_DURATION_OBSERVATIONS_CONTRACT.columns
    ):
        assert str(
            result.observations[column.name].dtype
        ) == column.pandas_dtype


def test_builder_rejects_wrong_input_type() -> None:
    """Raw mappings cannot bypass source normalization."""
    with pytest.raises(
        TypeError,
        match="NormalizedProcessedSession",
    ):
        build_pit_duration_observations(  # type: ignore[arg-type]
            {}
        )


def test_builder_rejects_protected_evaluation_season(
    normalized_source: NormalizedProcessedSession,
) -> None:
    """Protected 2025 data cannot enter development targets."""
    protected = replace(
        normalized_source,
        session_key=SessionKey(
            season=2025,
            round_number=1,
            session_type="R",
        ),
    )

    with pytest.raises(
        PitDurationConstructionError,
        match="protected evaluation season",
    ):
        build_pit_duration_observations(
            protected
        )


def test_builder_rejects_unsupported_development_season(
    normalized_source: NormalizedProcessedSession,
) -> None:
    """Undeclared seasons cannot alter the frozen population."""
    unsupported = replace(
        normalized_source,
        session_key=SessionKey(
            season=2021,
            round_number=1,
            session_type="R",
        ),
    )

    with pytest.raises(
        PitDurationConstructionError,
        match="outside the development seasons",
    ):
        build_pit_duration_observations(
            unsupported
        )


def test_builder_rejects_duplicate_pit_event_ids(
    normalized_source: NormalizedProcessedSession,
) -> None:
    """Target identities must be unique inside each session."""
    corrupted = normalized_source.pit_events.copy(
        deep=True
    )
    corrupted.loc[
        corrupted.index[1],
        "pit_event_id",
    ] = corrupted.loc[
        corrupted.index[0],
        "pit_event_id",
    ]

    with pytest.raises(
        PitDurationConstructionError,
        match="duplicate pit-event IDs",
    ):
        build_pit_duration_observations(
            replace(
                normalized_source,
                pit_events=corrupted,
            )
        )


def test_builder_rejects_inconsistent_dry_compound_flag(
    normalized_source: NormalizedProcessedSession,
) -> None:
    """Stored convenience flags cannot override source compounds."""
    corrupted = normalized_source.pit_events.copy(
        deep=True
    )
    corrupted.loc[
        corrupted.index[0],
        "is_dry_compound_pair",
    ] = False

    with pytest.raises(
        PitDurationConstructionError,
        match="dry-compound flags",
    ):
        build_pit_duration_observations(
            replace(
                normalized_source,
                pit_events=corrupted,
            )
        )


def test_builder_rejects_inconsistent_dry_weather_flag(
    normalized_source: NormalizedProcessedSession,
) -> None:
    """Rain observations remain authoritative for dry context."""
    corrupted = normalized_source.pit_events.copy(
        deep=True
    )
    corrupted.loc[
        corrupted.index[0],
        "is_dry_weather_pair",
    ] = False

    with pytest.raises(
        PitDurationConstructionError,
        match="dry-weather flags",
    ):
        build_pit_duration_observations(
            replace(
                normalized_source,
                pit_events=corrupted,
            )
        )


@pytest.mark.parametrize(
    "invalid_duration",
    [None, 0.0, -1.0],
)
def test_builder_rejects_complete_event_without_positive_duration(
    normalized_source: NormalizedProcessedSession,
    invalid_duration: float | None,
) -> None:
    """Complete events require a positive observed interval."""
    corrupted = normalized_source.pit_events.copy(
        deep=True
    )
    corrupted.loc[
        corrupted.index[0],
        "observed_pit_lane_duration_seconds",
    ] = invalid_duration

    with pytest.raises(
        PitDurationConstructionError,
        match="without positive observed durations",
    ):
        build_pit_duration_observations(
            replace(
                normalized_source,
                pit_events=corrupted,
            )
        )


def test_builder_rejects_inconsistent_candidate_flag(
    normalized_source: NormalizedProcessedSession,
) -> None:
    """Phase 3 candidate flags are independently recomputed."""
    corrupted = normalized_source.pit_events.copy(
        deep=True
    )
    corrupted.loc[
        corrupted.index[0],
        "is_duration_analysis_candidate",
    ] = False

    with pytest.raises(
        PitDurationConstructionError,
        match="candidate flags",
    ):
        build_pit_duration_observations(
            replace(
                normalized_source,
                pit_events=corrupted,
            )
        )


def test_valid_observations_pass_independent_validation(
    built_data: PitDurationSessionData,
) -> None:
    """A constructed session produces a clean validation report."""
    report = validate_pit_duration_session(
        built_data
    )

    assert report.is_valid
    assert report.issue_count == 0
    assert report.rows == 7
    assert report.eligible_targets == 1
    assert report.ineligible_targets == 6
    assert report.evaluation_season_rows == 0
    report.raise_for_errors()


def test_validator_rejects_wrong_input_type() -> None:
    """Validation requires the typed session container."""
    with pytest.raises(
        TypeError,
        match="PitDurationSessionData",
    ):
        validate_pit_duration_session(  # type: ignore[arg-type]
            pd.DataFrame()
        )


def test_validator_detects_schema_change(
    built_data: PitDurationSessionData,
) -> None:
    """Stored tables cannot add or remove contract columns."""
    corrupted = built_data.observations.drop(
        columns=["driver"]
    )
    corrupted["unexpected"] = 1
    data = replace(
        built_data,
        observations=corrupted,
    )

    assert PitDurationIssueCode.SCHEMA_MISMATCH in (
        _issue_codes(data)
    )


def test_validator_detects_required_missing_value(
    built_data: PitDurationSessionData,
) -> None:
    """Required identity values cannot become null."""
    corrupted = built_data.observations.copy(
        deep=True
    )
    corrupted["driver"] = corrupted[
        "driver"
    ].astype("string")
    corrupted.loc[
        corrupted.index[0],
        "driver",
    ] = pd.NA
    data = replace(
        built_data,
        observations=corrupted,
    )

    assert PitDurationIssueCode.REQUIRED_VALUE_MISSING in (
        _issue_codes(data)
    )


def test_validator_detects_source_row_count_mismatch(
    built_data: PitDurationSessionData,
) -> None:
    """Every normalized pit event must retain one target row."""
    data = replace(
        built_data,
        source_pit_event_count=8,
    )

    assert PitDurationIssueCode.ROW_COUNT_MISMATCH in (
        _issue_codes(data)
    )


def test_validator_detects_duplicate_identity(
    built_data: PitDurationSessionData,
) -> None:
    """Duplicate target identities fail independent validation."""
    corrupted = built_data.observations.copy(
        deep=True
    )
    corrupted.loc[
        corrupted.index[1],
        "pit_event_id",
    ] = corrupted.loc[
        corrupted.index[0],
        "pit_event_id",
    ]
    data = replace(
        built_data,
        observations=corrupted,
    )

    assert PitDurationIssueCode.DUPLICATE_PIT_EVENT_ID in (
        _issue_codes(data)
    )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("session_id", "2024-02-R"),
        ("season", 2023),
        ("round_number", 2),
        ("session_type", "X"),
        ("event_name", "Wrong Grand Prix"),
    ],
)
def test_validator_detects_identity_mismatch(
    built_data: PitDurationSessionData,
    column: str,
    value: object,
) -> None:
    """Partition identity must match every observation row."""
    corrupted = built_data.observations.copy(
        deep=True
    )
    corrupted.loc[
        corrupted.index[0],
        column,
    ] = value
    data = replace(
        built_data,
        observations=corrupted,
    )

    assert PitDurationIssueCode.IDENTITY_MISMATCH in (
        _issue_codes(data)
    )


def test_validator_detects_contract_version_mismatch(
    built_data: PitDurationSessionData,
) -> None:
    """Every row must retain dataset contract provenance."""
    corrupted = built_data.observations.copy(
        deep=True
    )
    corrupted.loc[
        corrupted.index[0],
        "dataset_contract_version",
    ] = "9.9"
    data = replace(
        built_data,
        observations=corrupted,
    )

    assert (
        PitDurationIssueCode.CONTRACT_VERSION_MISMATCH
        in _issue_codes(data)
    )


def test_validator_detects_evaluation_season_row(
    built_data: PitDurationSessionData,
) -> None:
    """A protected 2025 row is reported explicitly."""
    corrupted = built_data.observations.copy(
        deep=True
    )
    corrupted.loc[
        corrupted.index[0],
        "season",
    ] = 2025
    data = replace(
        built_data,
        observations=corrupted,
    )
    report = validate_pit_duration_session(
        data
    )

    assert report.evaluation_season_rows == 1
    assert PitDurationIssueCode.EVALUATION_SEASON_DETECTED in {
        issue.code
        for issue in report.issues
    }


def test_validator_detects_eligibility_mismatch(
    built_data: PitDurationSessionData,
) -> None:
    """Stored eligibility cannot contradict event context."""
    corrupted = built_data.observations.copy(
        deep=True
    )
    corrupted.loc[
        corrupted.index[0],
        "is_pit_duration_target_eligible",
    ] = False
    data = replace(
        built_data,
        observations=corrupted,
    )

    assert PitDurationIssueCode.ELIGIBILITY_MISMATCH in (
        _issue_codes(data)
    )


@pytest.mark.parametrize(
    ("row_number", "target"),
    [
        (0, None),
        (1, 23.5),
    ],
)
def test_validator_detects_target_nullability_mismatch(
    built_data: PitDurationSessionData,
    row_number: int,
    target: float | None,
) -> None:
    """Targets exist exactly when observations are eligible."""
    corrupted = built_data.observations.copy(
        deep=True
    )
    corrupted.loc[
        corrupted.index[row_number],
        "pit_duration_target_seconds",
    ] = target
    data = replace(
        built_data,
        observations=corrupted,
    )

    assert (
        PitDurationIssueCode.TARGET_NULLABILITY_MISMATCH
        in _issue_codes(data)
    )


@pytest.mark.parametrize(
    "invalid_target",
    [0.0, -1.0, float("inf")],
)
def test_validator_detects_invalid_eligible_target(
    built_data: PitDurationSessionData,
    invalid_target: float,
) -> None:
    """Eligible duration targets must be finite and positive."""
    corrupted = built_data.observations.copy(
        deep=True
    )
    corrupted.loc[
        corrupted.index[0],
        "pit_duration_target_seconds",
    ] = invalid_target
    data = replace(
        built_data,
        observations=corrupted,
    )

    assert PitDurationIssueCode.TARGET_VALUE_MISMATCH in (
        _issue_codes(data)
    )


@pytest.mark.parametrize(
    "column",
    [
        "pit_duration_exclusion_count",
        "pit_duration_exclusion_reasons",
    ],
)
def test_validator_detects_exclusion_encoding_mismatch(
    built_data: PitDurationSessionData,
    column: str,
) -> None:
    """Reason text and counts must remain deterministic."""
    corrupted = built_data.observations.copy(
        deep=True
    )
    value: object = (
        99
        if column == "pit_duration_exclusion_count"
        else "MADE_UP_REASON"
    )
    corrupted.loc[
        corrupted.index[1],
        column,
    ] = value
    data = replace(
        built_data,
        observations=corrupted,
    )

    assert (
        PitDurationIssueCode.EXCLUSION_ENCODING_MISMATCH
        in _issue_codes(data)
    )


def test_invalid_report_raises_construction_error(
    built_data: PitDurationSessionData,
) -> None:
    """Callers can fail closed from a validation report."""
    corrupted = built_data.observations.copy(
        deep=True
    )
    corrupted.loc[
        corrupted.index[0],
        "dataset_contract_version",
    ] = "9.9"
    report = validate_pit_duration_session(
        replace(
            built_data,
            observations=corrupted,
        )
    )

    with pytest.raises(
        PitDurationConstructionError,
        match="CONTRACT_VERSION_MISMATCH",
    ):
        report.raise_for_errors()