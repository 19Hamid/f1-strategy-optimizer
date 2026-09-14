"""Tests for whole-race temporal baseline evaluation."""

import pandas as pd
import pytest

from app.baselines import BaselineId, BaselineTask
from app.baselines.evaluation import (
    TemporalEvaluationError,
    evaluate_development_folds,
)


def _splits() -> pd.DataFrame:
    """Build exact roles for one race per development season."""
    roles = {
        "development_fold_1": {
            2022: "TRAIN",
            2023: "VALIDATION",
            2024: "EXCLUDED",
        },
        "development_fold_2": {
            2022: "TRAIN",
            2023: "TRAIN",
            2024: "VALIDATION",
        },
    }
    return pd.DataFrame.from_records(
        [
            {
                "fold_id": fold_id,
                "session_id": f"{season}-01-R",
                "season": season,
                "round_number": 1,
                "session_type": "R",
                "role": role,
            }
            for fold_id, season_roles in roles.items()
            for season, role in season_roles.items()
        ]
    )


def _lap_rows() -> pd.DataFrame:
    """Build one complete eligible decision per synthetic race."""
    return pd.DataFrame(
        {
            "decision_id": ["d22", "d23", "d24"],
            "session_id": ["2022-01-R", "2023-01-R", "2024-01-R"],
            "season": [2022, 2023, 2024],
            "event_name": ["Bahrain GP"] * 3,
            "current_compound": ["MEDIUM"] * 3,
            "driver": ["HAM"] * 3,
            "team": ["Team"] * 3,
            "previous_lap_was_target_eligible": [True] * 3,
            "previous_lap_time_seconds": [90.0, 91.0, 92.0],
            "rolling_lap_time_median_3": [89.5, 90.5, 91.5],
            "rolling_lap_time_trend_5": [0.2, 0.3, 0.4],
            "is_decision_eligible": [True] * 3,
            "is_lap_time_target_eligible": [True] * 3,
            "lap_time_target_seconds": [90.5, 91.5, 92.5],
        }
    )


def _pit_rows() -> pd.DataFrame:
    """Build one eligible pit observation per synthetic race."""
    return pd.DataFrame(
        {
            "pit_event_id": ["p22", "p23", "p24"],
            "session_id": ["2022-01-R", "2023-01-R", "2024-01-R"],
            "season": [2022, 2023, 2024],
            "event_name": ["Bahrain GP"] * 3,
            "compound_before": ["SOFT"] * 3,
            "compound_after": ["HARD"] * 3,
            "is_pit_duration_target_eligible": [True] * 3,
            "pit_duration_target_seconds": [24.0, 26.0, 28.0],
        }
    )


def test_evaluation_produces_every_fold_baseline_combination() -> None:
    """Score four lap and three pit baselines on both temporal folds."""
    report = evaluate_development_folds(
        lap_rows=_lap_rows(),
        pit_rows=_pit_rows(),
        splits=_splits(),
    )
    assert len(report.evaluations) == 14
    assert len(report.lap_time_evaluations) == 8
    assert len(report.pit_duration_evaluations) == 6
    assert {
        result.fold_id for result in report.evaluations
    } == {"development_fold_1", "development_fold_2"}


def test_fold_sessions_are_whole_and_chronological() -> None:
    """Record complete training and held-out race identities."""
    report = evaluate_development_folds(
        lap_rows=_lap_rows(),
        pit_rows=_pit_rows(),
        splits=_splits(),
    )
    fold_one = report.evaluations[0]
    fold_two = next(
        result
        for result in report.evaluations
        if result.fold_id == "development_fold_2"
    )
    assert fold_one.training_sessions == ("2022-01-R",)
    assert fold_one.validation_sessions == ("2023-01-R",)
    assert fold_two.training_sessions == ("2022-01-R", "2023-01-R")
    assert fold_two.validation_sessions == ("2024-01-R",)


def test_historical_lap_median_uses_training_fold_only() -> None:
    """Do not let a held-out target contribute to its own estimate."""
    laps = _lap_rows()
    laps.loc[laps["season"].eq(2023), "lap_time_target_seconds"] = 999.0
    report = evaluate_development_folds(
        lap_rows=laps,
        pit_rows=_pit_rows(),
        splits=_splits(),
    )
    result = next(
        item
        for item in report.lap_time_evaluations
        if item.fold_id == "development_fold_1"
        and item.baseline_id == BaselineId.CIRCUIT_COMPOUND_MEDIAN
    )
    assert result.scored.rows.loc[0, "prediction_seconds"] == 90.5
    assert result.scored.rows.loc[0, "target_seconds"] == 999.0


def test_historical_pit_median_uses_training_fold_only() -> None:
    """Fit duration estimates before observing the validation event."""
    pits = _pit_rows()
    pits.loc[pits["season"].eq(2023), "pit_duration_target_seconds"] = 999.0
    report = evaluate_development_folds(
        lap_rows=_lap_rows(),
        pit_rows=pits,
        splits=_splits(),
    )
    result = next(
        item
        for item in report.pit_duration_evaluations
        if item.fold_id == "development_fold_1"
        and item.baseline_id == BaselineId.PIT_GLOBAL_MEDIAN
    )
    assert result.scored.rows.loc[0, "prediction_seconds"] == 24.0
    assert result.scored.rows.loc[0, "target_seconds"] == 999.0


def test_results_preserve_task_and_fallback_counts() -> None:
    """Keep coverage and prediction provenance beside every metric."""
    report = evaluate_development_folds(
        lap_rows=_lap_rows(),
        pit_rows=_pit_rows(),
        splits=_splits(),
    )
    assert {
        result.task for result in report.evaluations
    } == {BaselineTask.LAP_TIME, BaselineTask.PIT_DURATION}
    assert all(
        result.scored.coverage.eligible_targets == 1
        for result in report.evaluations
    )
    assert all(result.fallback_counts for result in report.evaluations)


def test_protected_2025_rows_are_rejected_before_folds() -> None:
    """Keep the final holdout outside all Phase 5 interfaces."""
    laps = _lap_rows()
    laps.loc[0, "season"] = 2025
    with pytest.raises(TemporalEvaluationError, match="protected 2025"):
        evaluate_development_folds(
            lap_rows=laps,
            pit_rows=_pit_rows(),
            splits=_splits(),
        )


def test_modified_temporal_role_is_rejected() -> None:
    """Refuse a split that moves validation evidence into training."""
    splits = _splits()
    splits.loc[
        splits["fold_id"].eq("development_fold_1")
        & splits["season"].eq(2023),
        "role",
    ] = "TRAIN"
    with pytest.raises(TemporalEvaluationError, match="roles differ"):
        evaluate_development_folds(
            lap_rows=_lap_rows(),
            pit_rows=_pit_rows(),
            splits=splits,
        )


def test_missing_assigned_race_is_rejected() -> None:
    """Require complete source coverage before target filtering."""
    laps = _lap_rows().loc[lambda frame: ~frame["season"].eq(2023)]
    with pytest.raises(TemporalEvaluationError, match="missing assigned"):
        evaluate_development_folds(
            lap_rows=laps,
            pit_rows=_pit_rows(),
            splits=_splits(),
        )
