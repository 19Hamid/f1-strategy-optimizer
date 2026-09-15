"""Tests for chronological Phase 6 candidate selection."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.ml import selection
from app.ml.contracts import (
    APPROVED_FEATURE_COLUMNS,
    IDENTITY_ABLATION_FEATURE_COLUMNS,
    MODEL_SPECS,
    NUMERIC_FEATURE_COLUMNS,
    ModelFamily,
    ModelTarget,
)
from app.ml.matrices import (
    FoldTrainingMatrix,
    TrainingMatrixPartition,
)
from app.ml.selection import (
    FOLD_METRIC_COLUMNS,
    POOLED_METRIC_COLUMNS,
    SELECTION_COLUMNS,
    TemporalSelectionError,
    TemporalSelectionReport,
    evaluate_primary_temporal_candidates,
    select_primary_candidate,
)
from app.ml.training import (
    FULL_FEATURE_SET_ID,
    IDENTITY_ABLATION_FEATURE_SET_ID,
    PREDICTION_COLUMNS,
)


def _features(rows: int, *, offset: int = 0) -> pd.DataFrame:
    """Build exact features with a comparable previous-lap baseline."""
    records: list[dict[str, object]] = []
    for index in range(rows):
        value = index + offset
        record: dict[str, object] = {
            column: float(value + column_index + 1)
            for column_index, column in enumerate(NUMERIC_FEATURE_COLUMNS)
        }
        record.update(
            {
                "event_name": f"Event {value % 2}",
                "driver": f"Driver {value % 3}",
                "team": f"Team {value % 2}",
                "current_compound": ("SOFT", "MEDIUM", "HARD")[value % 3],
                "previous_lap_was_target_eligible": True,
                "previous_lap_time_seconds": 90.0 + value * 0.1,
            }
        )
        records.append(record)
    return pd.DataFrame.from_records(
        records,
        columns=APPROVED_FEATURE_COLUMNS,
    )


def _partition(
    rows: int,
    *,
    season: int,
    prefix: str,
    offset: int,
) -> TrainingMatrixPartition:
    """Build aligned identities, features and primary targets."""
    features = _features(rows, offset=offset)
    identities = pd.DataFrame(
        {
            "decision_id": [
                f"{prefix}-decision-{index}"
                for index in range(rows)
            ],
            "session_id": [f"{season}-01-R"] * rows,
            "season": [season] * rows,
        }
    )
    target = (
        features["previous_lap_time_seconds"] + 0.5
    ).rename("lap_time_target_seconds")
    return TrainingMatrixPartition(
        identities=identities,
        features=features,
        target=target.reset_index(drop=True),
    )


def _matrices() -> tuple[FoldTrainingMatrix, ...]:
    """Build both frozen primary temporal folds."""
    return (
        FoldTrainingMatrix(
            fold_id="development_fold_1",
            target=ModelTarget.LAP_TIME,
            training=_partition(
                6,
                season=2022,
                prefix="fold1-train",
                offset=0,
            ),
            validation=_partition(
                3,
                season=2023,
                prefix="fold1-validation",
                offset=10,
            ),
        ),
        FoldTrainingMatrix(
            fold_id="development_fold_2",
            target=ModelTarget.LAP_TIME,
            training=_partition(
                9,
                season=2023,
                prefix="fold2-train",
                offset=20,
            ),
            validation=_partition(
                4,
                season=2024,
                prefix="fold2-validation",
                offset=40,
            ),
        ),
    )


def _fake_train_fold_candidates(
    matrix: FoldTrainingMatrix,
    *,
    feature_columns: tuple[str, ...],
) -> tuple[SimpleNamespace, ...]:
    """Return all 15 deterministic candidates without expensive fitting."""
    if feature_columns == APPROVED_FEATURE_COLUMNS:
        feature_set_id = FULL_FEATURE_SET_ID
        ablation_penalty = 0.0
    elif feature_columns == IDENTITY_ABLATION_FEATURE_COLUMNS:
        feature_set_id = IDENTITY_ABLATION_FEATURE_SET_ID
        ablation_penalty = 0.05
    else:
        raise AssertionError("unexpected feature set")

    results = []
    ordinal = 0
    for specification in MODEL_SPECS:
        for grid_index, parameters in enumerate(
            specification.parameter_grid,
            start=1,
        ):
            error = 0.20 + ordinal * 0.005 + ablation_penalty
            targets = matrix.validation.target.to_numpy(dtype="float64")
            predictions = targets + error
            rows = matrix.validation.identities.copy()
            rows["fold_id"] = matrix.fold_id
            rows["target"] = matrix.target.value
            rows["model_family"] = specification.family.value
            rows["candidate_id"] = (
                f"{specification.family.value}_{grid_index:02d}"
            )
            rows["feature_set_id"] = feature_set_id
            rows["target_seconds"] = targets
            rows["prediction_seconds"] = predictions
            rows["absolute_error_seconds"] = np.abs(
                predictions - targets
            )
            rows = rows.loc[:, PREDICTION_COLUMNS]
            model = SimpleNamespace(
                family=specification.family,
                candidate_id=(
                    f"{specification.family.value}_{grid_index:02d}"
                ),
                feature_set_id=feature_set_id,
                parameters=tuple(sorted(parameters.items())),
            )
            results.append(
                SimpleNamespace(
                    model=model,
                    validation_predictions=rows,
                )
            )
            ordinal += 1
    return tuple(results)


def _report(
    monkeypatch: pytest.MonkeyPatch,
) -> TemporalSelectionReport:
    """Evaluate synthetic candidates through the real selection logic."""
    monkeypatch.setattr(
        selection,
        "train_fold_candidates",
        _fake_train_fold_candidates,
    )
    return evaluate_primary_temporal_candidates(_matrices())


def test_temporal_evaluation_reports_every_fold_and_feature_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Produce 60 fold rows and 30 exact pooled candidate rows."""
    report = _report(monkeypatch)
    assert tuple(report.fold_metrics.columns) == FOLD_METRIC_COLUMNS
    assert tuple(report.pooled_metrics.columns) == POOLED_METRIC_COLUMNS
    assert tuple(report.selection.columns) == SELECTION_COLUMNS
    assert len(report.fold_metrics) == 60
    assert len(report.pooled_metrics) == 30
    assert len(report.selection) == 15
    assert set(report.fold_metrics["fold_id"]) == {
        "development_fold_1",
        "development_fold_2",
    }


def test_best_qualifying_candidate_is_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rank by pooled MAE after every frozen gate passes."""
    report = _report(monkeypatch)
    assert report.selected_candidate is not None
    assert report.selected_candidate.family == ModelFamily.RIDGE
    assert report.selected_candidate.candidate_id == "ridge_01"
    assert report.selection["selected"].sum() == 1
    winner = report.selection.loc[report.selection["selected"].eq(True)].iloc[0]
    assert winner["meets_selection_contract"]


def test_comparable_rows_use_previous_valid_lap_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Score model and baseline on the identical validation population."""
    report = _report(monkeypatch)
    assert report.fold_metrics[
        "baseline_common_mean_absolute_error_seconds"
    ].eq(0.5).all()
    assert report.pooled_metrics[
        "baseline_common_mean_absolute_error_seconds"
    ].eq(0.5).all()
    assert report.pooled_metrics["common_rows"].eq(7).all()


def test_ablation_must_still_beat_frozen_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Block a candidate that depends too heavily on driver and team."""
    report = _report(monkeypatch)
    pooled = report.pooled_metrics.copy()
    pooled.loc[
        pooled["feature_set_id"].eq(
            IDENTITY_ABLATION_FEATURE_SET_ID
        )
        & pooled["candidate_id"].eq("ridge_01"),
        "common_mean_absolute_error_seconds",
    ] = 0.6
    selection_table, selected = select_primary_candidate(pooled)
    first = selection_table.loc[
        selection_table["candidate_id"].eq("ridge_01")
    ].iloc[0]
    assert not first["ablation_passes"]
    assert not first["selected"]
    assert selected is not None
    assert selected.candidate_id == "ridge_02"


def test_no_winner_is_reported_when_every_candidate_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report failure honestly instead of crowning a worse complex model."""
    report = _report(monkeypatch)
    pooled = report.pooled_metrics.copy()
    pooled.loc[
        :,
        "common_mean_absolute_error_seconds",
    ] = 0.7
    selection_table, selected = select_primary_candidate(pooled)
    assert selected is None
    assert not selection_table["meets_selection_contract"].any()
    assert not selection_table["selected"].any()


def test_minimum_coverage_gate_is_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a candidate that avoids predicting difficult rows."""
    report = _report(monkeypatch)
    pooled = report.pooled_metrics.copy()
    pooled.loc[
        pooled["candidate_id"].eq("ridge_01"),
        "coverage_rate",
    ] = 0.5
    selection_table, _ = select_primary_candidate(pooled)
    first = selection_table.loc[
        selection_table["candidate_id"].eq("ridge_01")
    ].iloc[0]
    assert not first["minimum_coverage_passes"]
    assert not first["selected"]


def test_primary_ranking_uses_pooled_mae_then_stable_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use deterministic tie-breaking after equal primary metrics."""
    report = _report(monkeypatch)
    pooled = report.pooled_metrics.copy()
    for candidate_id in ("ridge_01", "ridge_02"):
        pooled.loc[
            pooled["candidate_id"].eq(candidate_id),
            "mean_absolute_error_seconds",
        ] = 0.2
        pooled.loc[
            pooled["candidate_id"].eq(candidate_id),
            "common_mean_absolute_error_seconds",
        ] = 0.2
    _, selected = select_primary_candidate(pooled)
    assert selected is not None
    assert selected.candidate_id == "ridge_01"


def test_primary_selection_rejects_auxiliary_target_matrices() -> None:
    """Keep lap-time change diagnostic out of primary model selection."""
    matrices = list(_matrices())
    first = matrices[0]
    matrices[0] = FoldTrainingMatrix(
        fold_id=first.fold_id,
        target=ModelTarget.LAP_TIME_DELTA,
        training=first.training,
        validation=first.validation,
    )
    with pytest.raises(
        TemporalSelectionError,
        match="requires LAP_TIME",
    ):
        evaluate_primary_temporal_candidates(tuple(matrices))


def test_selection_requires_both_distinct_folds() -> None:
    """Prevent selection from a single favourable validation season."""
    with pytest.raises(
        TemporalSelectionError,
        match="exactly both",
    ):
        evaluate_primary_temporal_candidates((_matrices()[0],))


def test_missing_common_baseline_rows_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require the promised apples-to-apples baseline comparison."""
    monkeypatch.setattr(
        selection,
        "train_fold_candidates",
        _fake_train_fold_candidates,
    )
    matrices = list(_matrices())
    matrices[0].validation.features.loc[
        :,
        "previous_lap_was_target_eligible",
    ] = False
    with pytest.raises(
        TemporalSelectionError,
        match="no rows comparable",
    ):
        evaluate_primary_temporal_candidates(tuple(matrices))
