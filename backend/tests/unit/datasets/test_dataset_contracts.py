"""Tests for the executable Phase 4 dataset contract."""

from __future__ import annotations

import pytest

from app.cleaning import (
    CLEANING_RULE_VERSION,
    PROCESSED_CONTRACT_VERSION,
)
from app.datasets import (
    CATALOG_CONTRACT,
    DATASET_CONTRACT_VERSION,
    DATASET_DIRECTORY_NAME,
    DATASET_VERSION_DIRECTORY,
    DECISION_EXCLUSION_REASON_ORDER,
    DECISION_LABELS_CONTRACT,
    DECISION_MODEL_FEATURE_COLUMNS,
    DECISION_ROWS_CONTRACT,
    DEVELOPMENT_SEASONS,
    EXPECTED_DEVELOPMENT_TOTALS,
    EXPECTED_SEASON_TOTALS,
    PIT_DURATION_OBSERVATIONS_CONTRACT,
    PIT_EVENT_NULLABLE_BOOLEAN_COLUMNS,
    PIT_EVENT_NULLABLE_INTEGER_COLUMNS,
    PROTECTED_EVALUATION_SEASON,
    SOURCE_CLEANING_RULE_VERSION,
    SOURCE_PROCESSED_CONTRACT_VERSION,
    SPLITS_CONTRACT,
    TABLE_CONTRACTS,
    TEMPORAL_FOLDS,
    ColumnRole,
    ColumnSpec,
    DatasetContractError,
    HistoricalAction,
    SplitRole,
    TableContract,
    TemporalFold,
    temporal_fold,
)


def test_dataset_contract_version_is_frozen() -> None:
    """Phase 4 starts with dataset contract version 1.0."""
    assert DATASET_CONTRACT_VERSION == "1.0"


def test_source_contract_versions_match_phase_3() -> None:
    """Declared inputs must match the implemented source versions."""
    assert (
        SOURCE_CLEANING_RULE_VERSION
        == CLEANING_RULE_VERSION
    )
    assert (
        SOURCE_PROCESSED_CONTRACT_VERSION
        == PROCESSED_CONTRACT_VERSION
    )


def test_table_column_counts_match_documentation() -> None:
    """Every executable table must have its documented width."""
    expected_counts = {
        "decision_rows": 55,
        "decision_labels": 15,
        "pit_duration_observations": 28,
        "splits": 6,
        "catalog": 20,
    }

    actual_counts = {
        contract.name: len(contract.columns)
        for contract in TABLE_CONTRACTS
    }

    assert actual_counts == expected_counts


def test_table_columns_are_unique() -> None:
    """No stored schema may contain duplicate column names."""
    for contract in TABLE_CONTRACTS:
        assert len(
            contract.column_names
        ) == len(
            set(contract.column_names)
        )


def test_table_file_names_are_canonical() -> None:
    """Contract files must use their frozen Parquet names."""
    expected_files = {
        "decision_rows": "decision_rows.parquet",
        "decision_labels": (
            "decision_labels.parquet"
        ),
        "pit_duration_observations": (
            "pit_duration_observations.parquet"
        ),
        "splits": "splits.parquet",
        "catalog": "catalog.parquet",
    }

    actual_files = {
        contract.name: contract.file_name
        for contract in TABLE_CONTRACTS
    }

    assert actual_files == expected_files


def test_exact_column_orders_are_accepted() -> None:
    """Every declared order must validate without an error."""
    for contract in TABLE_CONTRACTS:
        contract.validate_column_order(
            contract.column_names
        )


def test_missing_column_is_rejected() -> None:
    """A table missing one required column must fail closed."""
    actual = (
        DECISION_ROWS_CONTRACT.column_names[:-1]
    )

    with pytest.raises(
        DatasetContractError,
        match="columns do not match contract",
    ):
        DECISION_ROWS_CONTRACT.validate_column_order(
            actual
        )


def test_reordered_columns_are_rejected() -> None:
    """Correct columns in the wrong order still violate contract."""
    expected = list(
        DECISION_LABELS_CONTRACT.column_names
    )

    expected[0], expected[1] = (
        expected[1],
        expected[0],
    )

    with pytest.raises(
        DatasetContractError,
        match="order_matches=True",
    ):
        DECISION_LABELS_CONTRACT.validate_column_order(
            expected
        )


def test_column_lookup_returns_declared_spec() -> None:
    """Column lookup must expose dtype and semantic role."""
    column = DECISION_ROWS_CONTRACT.column(
        "rolling_lap_time_median_3"
    )

    assert column.pandas_dtype == "float64"
    assert column.nullable
    assert column.role is ColumnRole.FEATURE


def test_unknown_column_lookup_is_rejected() -> None:
    """Undeclared columns must not be accepted silently."""
    with pytest.raises(
        DatasetContractError,
        match="has no column",
    ):
        DECISION_ROWS_CONTRACT.column(
            "future_race_result"
        )


def test_model_feature_allowlist_is_valid() -> None:
    """Allowed model features must be unique and declared."""
    assert len(
        DECISION_MODEL_FEATURE_COLUMNS
    ) == len(
        set(DECISION_MODEL_FEATURE_COLUMNS)
    )

    for name in DECISION_MODEL_FEATURE_COLUMNS:
        column = DECISION_ROWS_CONTRACT.column(
            name
        )

        assert column.role in {
            ColumnRole.CONTEXT,
            ColumnRole.FEATURE,
        }


def test_forbidden_fields_are_not_model_features() -> None:
    """Labels, targets and audit outcomes must stay excluded."""
    forbidden = {
        "historical_action",
        "did_pit",
        "lap_time_target_seconds",
        "is_lap_time_target_eligible",
        "is_decision_eligible",
        "decision_exclusion_reasons",
        "previous_track_status",
        "rainfall",
    }

    assert forbidden.isdisjoint(
        DECISION_MODEL_FEATURE_COLUMNS
    )


def test_decision_rows_contain_no_labels_or_targets() -> None:
    """The physical feature table must remain label-free."""
    forbidden_roles = {
        ColumnRole.LABEL,
        ColumnRole.TARGET,
        ColumnRole.QUALITY,
    }

    assert all(
        column.role not in forbidden_roles
        for column in DECISION_ROWS_CONTRACT.columns
    )


def test_decision_labels_declare_action_and_target() -> None:
    """The label table must contain its diagnostic and target."""
    historical_action = (
        DECISION_LABELS_CONTRACT.column(
            "historical_action"
        )
    )
    lap_target = (
        DECISION_LABELS_CONTRACT.column(
            "lap_time_target_seconds"
        )
    )

    assert (
        historical_action.role
        is ColumnRole.LABEL
    )
    assert lap_target.role is ColumnRole.TARGET
    assert lap_target.nullable


def test_decision_exclusion_order_is_frozen() -> None:
    """Multiple decision reasons need deterministic ordering."""
    assert [
        reason.value
        for reason in DECISION_EXCLUSION_REASON_ORDER
    ] == [
        "NON_CONSECUTIVE_PREVIOUS_LAP",
        "WEATHER_NOT_AVAILABLE_BY_DECISION",
        "PREVIOUS_LAP_PIT_COMMITMENT",
        "STATE_RECONSTRUCTION_CONFLICT",
        "UNSUPPORTED_CURRENT_COMPOUND",
        "INVALID_CURRENT_TYRE_AGE",
        "MISSING_CURRENT_STINT",
        "WET_AT_DECISION",
        "PREVIOUS_LAP_NOT_GREEN",
        "INSUFFICIENT_ELIGIBLE_HISTORY",
        "MISSING_PREVIOUS_POSITION",
    ]


def test_historical_action_values_are_explicit() -> None:
    """Historical action is diagnostic, not optimality."""
    assert {
        action.value
        for action in HistoricalAction
    } == {
        "PIT_NOW",
        "STAY_OUT",
    }


def test_pit_normalization_columns_are_nullable() -> None:
    """Drifting pit fields must have canonical nullable types."""
    for name in PIT_EVENT_NULLABLE_INTEGER_COLUMNS:
        column = (
            PIT_DURATION_OBSERVATIONS_CONTRACT
            .column(name)
        )

        assert column.pandas_dtype == "Int64"
        assert column.nullable

    for name in PIT_EVENT_NULLABLE_BOOLEAN_COLUMNS:
        column = (
            PIT_DURATION_OBSERVATIONS_CONTRACT
            .column(name)
        )

        assert column.pandas_dtype == "boolean"
        assert column.nullable


def test_temporal_fold_roles_are_frozen() -> None:
    """Each season must receive its documented fold role."""
    expected = {
        "development_fold_1": {
            2022: SplitRole.TRAIN,
            2023: SplitRole.VALIDATION,
            2024: SplitRole.EXCLUDED,
        },
        "development_fold_2": {
            2022: SplitRole.TRAIN,
            2023: SplitRole.TRAIN,
            2024: SplitRole.VALIDATION,
        },
        "final_development_fit": {
            2022: SplitRole.TRAIN,
            2023: SplitRole.TRAIN,
            2024: SplitRole.TRAIN,
        },
    }

    actual = {
        fold.fold_id: {
            season: fold.role_for_season(
                season
            )
            for season in DEVELOPMENT_SEASONS
        }
        for fold in TEMPORAL_FOLDS
    }

    assert actual == expected


def test_temporal_fold_ids_are_unique_and_complete() -> None:
    """All three folds must cover all development seasons."""
    assert len(TEMPORAL_FOLDS) == 3

    fold_ids = tuple(
        fold.fold_id
        for fold in TEMPORAL_FOLDS
    )

    assert len(fold_ids) == len(set(fold_ids))

    for fold in TEMPORAL_FOLDS:
        assigned = (
            set(fold.train_seasons)
            | set(fold.validation_seasons)
            | set(fold.excluded_seasons)
        )

        assert assigned == set(
            DEVELOPMENT_SEASONS
        )


def test_protected_season_has_no_fold_role() -> None:
    """Development folds must reject protected 2025."""
    for fold in TEMPORAL_FOLDS:
        with pytest.raises(
            DatasetContractError,
            match="outside",
        ):
            fold.role_for_season(
                PROTECTED_EVALUATION_SEASON
            )


def test_unknown_temporal_fold_is_rejected() -> None:
    """Callers cannot invent unregistered split names."""
    with pytest.raises(
        DatasetContractError,
        match="unknown temporal fold",
    ):
        temporal_fold("random_lap_split")


def test_expected_development_totals_reconcile() -> None:
    """Frozen real-data counts must be internally consistent."""
    totals = EXPECTED_DEVELOPMENT_TOTALS

    assert (
        totals.source_laps
        - totals.omitted_first_laps
        == totals.candidate_decisions
    )
    assert (
        totals.eligible_decisions
        + totals.ineligible_decisions
        == totals.candidate_decisions
    )
    assert (
        totals.eligible_pit_now
        + totals.eligible_stay_out
        == totals.eligible_decisions
    )
    assert (
        totals.eligible_lap_targets
        + totals.ineligible_lap_targets
        == totals.eligible_decisions
    )
    assert totals.split_rows == (
        totals.sessions
        * len(TEMPORAL_FOLDS)
    )


def test_expected_season_totals_reconcile() -> None:
    """Per-season audited totals must equal dataset totals."""
    totals = EXPECTED_DEVELOPMENT_TOTALS

    assert {
        item.season
        for item in EXPECTED_SEASON_TOTALS
    } == set(DEVELOPMENT_SEASONS)

    assert sum(
        item.sessions
        for item in EXPECTED_SEASON_TOTALS
    ) == totals.sessions

    assert sum(
        item.eligible_decisions
        for item in EXPECTED_SEASON_TOTALS
    ) == totals.eligible_decisions

    assert sum(
        item.eligible_pit_now
        for item in EXPECTED_SEASON_TOTALS
    ) == totals.eligible_pit_now


def test_dataset_directory_names_are_versioned() -> None:
    """Stored artifacts must live below a version root."""
    assert DATASET_DIRECTORY_NAME == "f1_strategy"
    assert DATASET_VERSION_DIRECTORY == (
        "dataset_contract_version=1.0"
    )


def test_catalog_column_order_is_frozen() -> None:
    """Global catalog columns must match the document exactly."""
    assert CATALOG_CONTRACT.column_names == (
        "session_id",
        "season",
        "round_number",
        "session_type",
        "event_name",
        "dataset_contract_version",
        "cleaning_rule_version",
        "processed_contract_version",
        "created_at_utc",
        "decision_rows",
        "eligible_decisions",
        "ineligible_decisions",
        "decision_label_rows",
        "lap_time_target_eligible_rows",
        "pit_now_rows",
        "stay_out_rows",
        "pit_duration_rows",
        "pit_duration_target_eligible_rows",
        "total_size_bytes",
        "session_directory",
    )


def test_split_column_order_is_frozen() -> None:
    """Global split assignments need a stable schema."""
    assert SPLITS_CONTRACT.column_names == (
        "fold_id",
        "session_id",
        "season",
        "round_number",
        "session_type",
        "role",
    )


def test_table_contract_names_are_unique() -> None:
    """Registered stored-table identities must not collide."""
    names = tuple(
        contract.name
        for contract in TABLE_CONTRACTS
    )

    assert len(names) == len(set(names))


def test_empty_column_name_is_rejected() -> None:
    """A stored column must always have an identity."""
    with pytest.raises(
        DatasetContractError,
        match="column name",
    ):
        ColumnSpec(
            name="",
            pandas_dtype="int64",
            nullable=False,
            role=ColumnRole.IDENTITY,
        )


def test_empty_column_dtype_is_rejected() -> None:
    """Every stored column must declare its pandas dtype."""
    with pytest.raises(
        DatasetContractError,
        match="pandas dtype",
    ):
        ColumnSpec(
            name="identifier",
            pandas_dtype="",
            nullable=False,
            role=ColumnRole.IDENTITY,
        )


def test_duplicate_table_columns_are_rejected() -> None:
    """Malformed declarative schemas must fail immediately."""
    duplicate = ColumnSpec(
        name="identifier",
        pandas_dtype="string",
        nullable=False,
        role=ColumnRole.IDENTITY,
    )

    with pytest.raises(
        DatasetContractError,
        match="duplicate columns",
    ):
        TableContract(
            name="invalid",
            file_name="invalid.parquet",
            columns=(
                duplicate,
                duplicate,
            ),
        )


def test_overlapping_temporal_fold_is_rejected() -> None:
    """One season cannot hold multiple roles in one fold."""
    with pytest.raises(
        DatasetContractError,
        match="train and validation overlap",
    ):
        TemporalFold(
            fold_id="invalid",
            train_seasons=(2022,),
            validation_seasons=(
                2022,
                2023,
            ),
            excluded_seasons=(2024,),
        )