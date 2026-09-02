"""Tests for complete whole-session temporal splits."""

from __future__ import annotations

from collections import Counter

import pandas as pd
import pytest

from app.datasets.contracts import (
    EXPECTED_DEVELOPMENT_TOTALS,
    SPLITS_CONTRACT,
    TEMPORAL_FOLDS,
    DatasetContractError,
    SplitRole,
)
from app.datasets.splits import (
    TEMPORAL_SPLIT_FOLD_IDS,
    TemporalSplitError,
    TemporalSplitIssueCode,
    build_temporal_splits,
    session_ids_for_fold_role,
    validate_temporal_splits,
)
from app.pipeline import SessionKey


@pytest.fixture
def development_session_keys() -> tuple[SessionKey, ...]:
    """Return the frozen 22/22/24 development schedule."""
    season_rounds = {
        2022: 22,
        2023: 22,
        2024: 24,
    }

    return tuple(
        SessionKey(
            season=season,
            round_number=round_number,
            session_type="R",
        )
        for season, rounds in season_rounds.items()
        for round_number in range(1, rounds + 1)
    )


@pytest.fixture
def valid_splits(
    development_session_keys: tuple[SessionKey, ...],
) -> pd.DataFrame:
    """Return one complete validated split table."""
    return build_temporal_splits(
        development_session_keys
    ).splits


def _codes(
    splits: pd.DataFrame,
    session_keys: tuple[SessionKey, ...],
) -> set[TemporalSplitIssueCode]:
    """Return issue codes for one mutated split table."""
    return {
        issue.code
        for issue in validate_temporal_splits(
            splits,
            session_keys,
        ).issues
    }


def test_builder_creates_complete_split_contract(
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """Three folds assign all 68 sessions exactly once."""
    result = build_temporal_splits(
        development_session_keys
    )

    assert result.validation.is_valid
    assert result.validation.issue_count == 0
    assert result.session_count == 68
    assert result.fold_count == 3
    assert result.row_count == 204
    assert result.row_count == (
        EXPECTED_DEVELOPMENT_TOTALS.split_rows
    )
    result.validation.raise_for_errors()


def test_split_table_matches_exact_schema_and_dtypes(
    valid_splits: pd.DataFrame,
) -> None:
    """Stored assignments implement all six contract columns."""
    expected_columns = tuple(
        column.name
        for column in SPLITS_CONTRACT.columns
    )
    expected_dtypes = {
        column.name: column.pandas_dtype
        for column in SPLITS_CONTRACT.columns
    }

    assert tuple(valid_splits.columns) == (
        expected_columns
    )
    assert {
        column: str(dtype)
        for column, dtype in valid_splits.dtypes.items()
    } == expected_dtypes
    assert not valid_splits.isna().any().any()


def test_fold_identifiers_have_frozen_order() -> None:
    """The public identifier tuple mirrors the contract."""
    assert TEMPORAL_SPLIT_FOLD_IDS == (
        "development_fold_1",
        "development_fold_2",
        "final_development_fit",
    )
    assert TEMPORAL_SPLIT_FOLD_IDS == tuple(
        fold.fold_id
        for fold in TEMPORAL_FOLDS
    )


def test_role_counts_match_whole_season_assignments(
    valid_splits: pd.DataFrame,
) -> None:
    """Each fold contains its frozen train/validation roles."""
    actual = Counter(
        zip(
            valid_splits["fold_id"].astype(str),
            valid_splits["role"].astype(str),
            strict=True,
        )
    )

    assert actual == Counter(
        {
            (
                "development_fold_1",
                "TRAIN",
            ): 22,
            (
                "development_fold_1",
                "VALIDATION",
            ): 22,
            (
                "development_fold_1",
                "EXCLUDED",
            ): 24,
            (
                "development_fold_2",
                "TRAIN",
            ): 44,
            (
                "development_fold_2",
                "VALIDATION",
            ): 24,
            (
                "final_development_fit",
                "TRAIN",
            ): 68,
        }
    )


def test_every_session_appears_once_in_every_fold(
    valid_splits: pd.DataFrame,
) -> None:
    """No session is randomly fragmented or omitted."""
    assignment_counts = valid_splits.groupby(
        "session_id"
    )["fold_id"].nunique()

    assert assignment_counts.eq(3).all()
    assert not valid_splits.duplicated(
        subset=[
            "fold_id",
            "session_id",
        ]
    ).any()


def test_roles_are_constant_within_each_fold_season(
    valid_splits: pd.DataFrame,
) -> None:
    """A season cannot be split across train and validation."""
    roles_per_season = valid_splits.groupby(
        [
            "fold_id",
            "season",
        ]
    )["role"].nunique()

    assert roles_per_season.eq(1).all()


def test_assignments_are_deterministically_ordered(
    valid_splits: pd.DataFrame,
) -> None:
    """Fold order and chronological session order are stable."""
    assert valid_splits.iloc[0][
        "fold_id"
    ] == "development_fold_1"
    assert valid_splits.iloc[0][
        "session_id"
    ] == "2022-01-R"
    assert valid_splits.iloc[67][
        "session_id"
    ] == "2024-24-R"
    assert valid_splits.iloc[-1][
        "fold_id"
    ] == "final_development_fit"
    assert valid_splits.iloc[-1][
        "session_id"
    ] == "2024-24-R"


def test_builder_accepts_one_pass_iterable(
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """Session schedules may be provided as generators."""
    result = build_temporal_splits(
        key
        for key in development_session_keys
    )

    assert result.row_count == 204


@pytest.mark.parametrize(
    "bad_value",
    [
        "2022-01-R",
        68,
        None,
    ],
)
def test_builder_rejects_non_iterable_session_key_inputs(
    bad_value: object,
) -> None:
    """The source schedule must be an iterable of keys."""
    with pytest.raises(TypeError):
        build_temporal_splits(  # type: ignore[arg-type]
            bad_value
        )


def test_builder_rejects_non_session_key_members() -> None:
    """A malformed member cannot enter the source schedule."""
    with pytest.raises(TypeError):
        build_temporal_splits(
            ["2022-01-R"]  # type: ignore[list-item]
        )


def test_builder_rejects_empty_source() -> None:
    """A partial dataset cannot claim complete split status."""
    with pytest.raises(
        TemporalSplitError,
        match="SOURCE_COVERAGE_MISMATCH",
    ):
        build_temporal_splits(())


def test_builder_rejects_missing_development_session(
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """The frozen 68-session population is mandatory."""
    with pytest.raises(
        TemporalSplitError,
        match="SOURCE_COVERAGE_MISMATCH",
    ):
        build_temporal_splits(
            development_session_keys[:-1]
        )


def test_builder_rejects_duplicate_source_session(
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """Duplicate catalog sessions fail before assignment."""
    duplicated = (
        *development_session_keys,
        development_session_keys[0],
    )

    with pytest.raises(
        TemporalSplitError,
        match="DUPLICATE_SOURCE_SESSION",
    ):
        build_temporal_splits(duplicated)


def test_builder_rejects_protected_evaluation_season(
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """A 2025 source session is rejected before role lookup."""
    protected = (
        *development_session_keys[:-1],
        SessionKey(
            season=2025,
            round_number=1,
            session_type="R",
        ),
    )

    with pytest.raises(
        TemporalSplitError,
        match="EVALUATION_SEASON_DETECTED",
    ):
        build_temporal_splits(protected)


def test_builder_rejects_unsupported_season(
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """Seasons outside the frozen study period fail closed."""
    unsupported = (
        *development_session_keys[:-1],
        SessionKey(
            season=2021,
            round_number=1,
            session_type="R",
        ),
    )

    with pytest.raises(
        TemporalSplitError,
        match="UNSUPPORTED_SEASON_DETECTED",
    ):
        build_temporal_splits(unsupported)


def test_session_key_rejects_non_race_split_input() -> None:
    """Qualifying is rejected at the identity boundary."""
    with pytest.raises(
        ValueError,
        match="unsupported session_type",
    ):
        SessionKey(
            season=2024,
            round_number=24,
            session_type="Q",
        )


def test_valid_table_passes_independent_validation(
    valid_splits: pd.DataFrame,
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """A complete builder output has no validation issue."""
    report = validate_temporal_splits(
        valid_splits,
        development_session_keys,
    )

    assert report.is_valid
    assert report.issue_count == 0
    assert report.rows == 204
    assert report.source_sessions == 68
    assert report.stored_sessions == 68
    assert report.stored_folds == 3
    assert report.evaluation_season_rows == 0
    report.raise_for_errors()


def test_validator_rejects_non_dataframe(
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """Split validation requires a pandas table."""
    with pytest.raises(TypeError):
        validate_temporal_splits(  # type: ignore[arg-type]
            [],
            development_session_keys,
        )


def test_report_raises_fail_closed_error(
    valid_splits: pd.DataFrame,
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """Invalid reports include stable issue codes."""
    damaged = valid_splits.iloc[:-1].copy()
    report = validate_temporal_splits(
        damaged,
        development_session_keys,
    )

    with pytest.raises(
        TemporalSplitError,
        match="ROW_COUNT_MISMATCH",
    ):
        report.raise_for_errors()


def test_schema_column_mismatch_is_detected(
    valid_splits: pd.DataFrame,
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """Missing contract columns are reported."""
    damaged = valid_splits.drop(
        columns="role"
    )

    assert (
        TemporalSplitIssueCode.SCHEMA_MISMATCH
        in _codes(
            damaged,
            development_session_keys,
        )
    )


def test_schema_dtype_mismatch_is_detected(
    valid_splits: pd.DataFrame,
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """Exact pandas dtypes are part of the contract."""
    damaged = valid_splits.copy(deep=True)
    damaged["season"] = damaged[
        "season"
    ].astype("string")

    assert (
        TemporalSplitIssueCode.SCHEMA_MISMATCH
        in _codes(
            damaged,
            development_session_keys,
        )
    )


def test_missing_required_value_is_detected(
    valid_splits: pd.DataFrame,
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """Every split identity and role value is required."""
    damaged = valid_splits.copy(deep=True)
    damaged["role"] = damaged[
        "role"
    ].astype("string")
    damaged.loc[0, "role"] = pd.NA

    assert (
        TemporalSplitIssueCode.REQUIRED_VALUE_MISSING
        in _codes(
            damaged,
            development_session_keys,
        )
    )


def test_removed_assignment_is_detected(
    valid_splits: pd.DataFrame,
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """Every fold must retain all 68 sessions."""
    damaged = valid_splits.iloc[:-1].copy()
    codes = _codes(
        damaged,
        development_session_keys,
    )

    assert (
        TemporalSplitIssueCode.ROW_COUNT_MISMATCH
        in codes
    )
    assert (
        TemporalSplitIssueCode.FOLD_COVERAGE_MISMATCH
        in codes
    )
    assert (
        TemporalSplitIssueCode.SESSION_COVERAGE_MISMATCH
        in codes
    )


def test_duplicate_assignment_is_detected(
    valid_splits: pd.DataFrame,
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """A repeated fold-session pair fails closed."""
    damaged = pd.concat(
        [
            valid_splits,
            valid_splits.iloc[[0]],
        ],
        ignore_index=True,
    )

    assert (
        TemporalSplitIssueCode.DUPLICATE_ASSIGNMENT
        in _codes(
            damaged,
            development_session_keys,
        )
    )


def test_unknown_session_identity_is_detected(
    valid_splits: pd.DataFrame,
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """Stored sessions must equal the source catalog set."""
    damaged = valid_splits.copy(deep=True)
    damaged.loc[0, "session_id"] = (
        "2022-99-R"
    )

    assert (
        TemporalSplitIssueCode.SESSION_SET_MISMATCH
        in _codes(
            damaged,
            development_session_keys,
        )
    )


def test_unknown_fold_identity_is_detected(
    valid_splits: pd.DataFrame,
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """Ad hoc fold identities are forbidden."""
    damaged = valid_splits.copy(deep=True)
    damaged.loc[0, "fold_id"] = "random_fold"

    assert (
        TemporalSplitIssueCode.FOLD_SET_MISMATCH
        in _codes(
            damaged,
            development_session_keys,
        )
    )


def test_invalid_role_value_is_detected(
    valid_splits: pd.DataFrame,
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """Only TRAIN, VALIDATION and EXCLUDED are valid."""
    damaged = valid_splits.copy(deep=True)
    damaged.loc[0, "role"] = "TEST"

    assert (
        TemporalSplitIssueCode.INVALID_ROLE
        in _codes(
            damaged,
            development_session_keys,
        )
    )


def test_wrong_frozen_role_is_detected(
    valid_splits: pd.DataFrame,
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """A valid role string can still violate its season fold."""
    damaged = valid_splits.copy(deep=True)
    damaged.loc[0, "role"] = "VALIDATION"

    assert (
        TemporalSplitIssueCode.ROLE_ASSIGNMENT_MISMATCH
        in _codes(
            damaged,
            development_session_keys,
        )
    )


def test_source_identity_disagreement_is_detected(
    valid_splits: pd.DataFrame,
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """Session ID metadata must agree with the source key."""
    damaged = valid_splits.copy(deep=True)
    damaged.loc[0, "round_number"] = 99

    assert (
        TemporalSplitIssueCode.SOURCE_IDENTITY_MISMATCH
        in _codes(
            damaged,
            development_session_keys,
        )
    )


def test_protected_stored_row_is_detected(
    valid_splits: pd.DataFrame,
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """A stored 2025 assignment is counted explicitly."""
    damaged = valid_splits.copy(deep=True)
    damaged.loc[0, "season"] = 2025
    report = validate_temporal_splits(
        damaged,
        development_session_keys,
    )

    assert report.evaluation_season_rows == 1
    assert (
        TemporalSplitIssueCode.EVALUATION_SEASON_DETECTED
        in {
            issue.code
            for issue in report.issues
        }
    )


def test_unsupported_stored_season_is_detected(
    valid_splits: pd.DataFrame,
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """Unsupported historical seasons cannot enter splits."""
    damaged = valid_splits.copy(deep=True)
    damaged.loc[0, "season"] = 2021

    assert (
        TemporalSplitIssueCode.UNSUPPORTED_SEASON_DETECTED
        in _codes(
            damaged,
            development_session_keys,
        )
    )


@pytest.mark.parametrize(
    ("fold_id", "role", "expected_count"),
    [
        (
            "development_fold_1",
            SplitRole.TRAIN,
            22,
        ),
        (
            "development_fold_1",
            SplitRole.VALIDATION,
            22,
        ),
        (
            "development_fold_1",
            SplitRole.EXCLUDED,
            24,
        ),
        (
            "development_fold_2",
            SplitRole.TRAIN,
            44,
        ),
        (
            "development_fold_2",
            SplitRole.VALIDATION,
            24,
        ),
        (
            "final_development_fit",
            SplitRole.TRAIN,
            68,
        ),
    ],
)
def test_explicit_fold_role_selection(
    valid_splits: pd.DataFrame,
    fold_id: str,
    role: SplitRole,
    expected_count: int,
) -> None:
    """Consumers must explicitly select one fold and role."""
    session_ids = session_ids_for_fold_role(
        valid_splits,
        fold_id=fold_id,
        role=role,
    )

    assert len(session_ids) == expected_count
    assert len(set(session_ids)) == expected_count


def test_fold_role_selection_is_chronological(
    valid_splits: pd.DataFrame,
) -> None:
    """Selected session IDs retain chronological ordering."""
    session_ids = session_ids_for_fold_role(
        valid_splits,
        fold_id="development_fold_2",
        role=SplitRole.TRAIN,
    )

    assert session_ids[0] == "2022-01-R"
    assert session_ids[21] == "2022-22-R"
    assert session_ids[22] == "2023-01-R"
    assert session_ids[-1] == "2023-22-R"


def test_fold_role_selection_requires_explicit_types(
    valid_splits: pd.DataFrame,
) -> None:
    """Stringly typed role selection is rejected."""
    with pytest.raises(TypeError):
        session_ids_for_fold_role(
            valid_splits,
            fold_id="development_fold_1",
            role="TRAIN",  # type: ignore[arg-type]
        )

    with pytest.raises(TypeError):
        session_ids_for_fold_role(
            valid_splits,
            fold_id=1,  # type: ignore[arg-type]
            role=SplitRole.TRAIN,
        )


def test_fold_role_selection_rejects_unknown_fold(
    valid_splits: pd.DataFrame,
) -> None:
    """Consumers cannot invent a fourth fold."""
    with pytest.raises(DatasetContractError):
        session_ids_for_fold_role(
            valid_splits,
            fold_id="random_fold",
            role=SplitRole.TRAIN,
        )


def test_fold_role_selection_rejects_missing_columns(
    valid_splits: pd.DataFrame,
) -> None:
    """Selection fails closed on an incomplete table."""
    with pytest.raises(
        TemporalSplitError,
        match="missing columns",
    ):
        session_ids_for_fold_role(
            valid_splits.drop(
                columns="season"
            ),
            fold_id="development_fold_1",
            role=SplitRole.TRAIN,
        )


def test_fold_role_selection_rejects_duplicates(
    valid_splits: pd.DataFrame,
) -> None:
    """A duplicated selected session cannot reach training."""
    damaged = pd.concat(
        [
            valid_splits,
            valid_splits.iloc[[0]],
        ],
        ignore_index=True,
    )

    with pytest.raises(
        TemporalSplitError,
        match="duplicate sessions",
    ):
        session_ids_for_fold_role(
            damaged,
            fold_id="development_fold_1",
            role=SplitRole.TRAIN,
        )


def test_builder_and_validator_do_not_mutate_inputs(
    development_session_keys: tuple[SessionKey, ...],
) -> None:
    """Construction and validation preserve caller-owned data."""
    result = build_temporal_splits(
        development_session_keys
    )
    original = result.splits.copy(deep=True)

    validate_temporal_splits(
        result.splits,
        development_session_keys,
    )

    pd.testing.assert_frame_equal(
        result.splits,
        original,
    )