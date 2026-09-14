"""Whole-race temporal evaluation for Phase 5 baselines."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.baselines.contracts import (
    DEVELOPMENT_EVALUATION_FOLDS,
    LAP_TIME_BASELINES,
    PIT_DURATION_BASELINES,
    BaselineId,
    BaselineTask,
)
from app.baselines.lap_times import fit_lap_time_baseline
from app.baselines.metrics import ScoredPredictions, score_prediction_frame
from app.baselines.pit_durations import fit_pit_duration_baseline

_EXPECTED_ROLES = {
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


class TemporalEvaluationError(ValueError):
    """Raised when fold evaluation could leak or misstate results."""


@dataclass(frozen=True, slots=True)
class FoldBaselineEvaluation:
    """One baseline scored on one held-out whole-race fold."""

    fold_id: str
    task: BaselineTask
    baseline_id: BaselineId
    training_sessions: tuple[str, ...]
    validation_sessions: tuple[str, ...]
    fallback_counts: dict[str, int]
    scored: ScoredPredictions


@dataclass(frozen=True, slots=True)
class TemporalEvaluationReport:
    """All lap-time and pit-duration development-fold results."""

    evaluations: tuple[FoldBaselineEvaluation, ...]

    @property
    def lap_time_evaluations(self) -> tuple[FoldBaselineEvaluation, ...]:
        """Return the eight lap-time fold-baseline combinations."""
        return tuple(
            result
            for result in self.evaluations
            if result.task == BaselineTask.LAP_TIME
        )

    @property
    def pit_duration_evaluations(self) -> tuple[FoldBaselineEvaluation, ...]:
        """Return the six pit-duration fold-baseline combinations."""
        return tuple(
            result
            for result in self.evaluations
            if result.task == BaselineTask.PIT_DURATION
        )


def evaluate_development_folds(
    *,
    lap_rows: pd.DataFrame,
    pit_rows: pd.DataFrame,
    splits: pd.DataFrame,
) -> TemporalEvaluationReport:
    """Fit on TRAIN races and score complete VALIDATION races."""
    _require_frame(lap_rows, source="lap_rows")
    _require_frame(pit_rows, source="pit_rows")
    _require_frame(splits, source="splits")
    _reject_protected_season(lap_rows, source="lap_rows")
    _reject_protected_season(pit_rows, source="pit_rows")
    assignments = _validate_splits(splits)

    results: list[FoldBaselineEvaluation] = []
    for fold_id in DEVELOPMENT_EVALUATION_FOLDS:
        fold_rows = assignments.loc[assignments["fold_id"].eq(fold_id)]
        training_sessions = _session_ids(fold_rows, "TRAIN")
        validation_sessions = _session_ids(fold_rows, "VALIDATION")
        results.extend(
            _evaluate_lap_baselines(
                fold_id=fold_id,
                training_sessions=training_sessions,
                validation_sessions=validation_sessions,
                rows=lap_rows,
            )
        )
        results.extend(
            _evaluate_pit_baselines(
                fold_id=fold_id,
                training_sessions=training_sessions,
                validation_sessions=validation_sessions,
                rows=pit_rows,
            )
        )
    report = TemporalEvaluationReport(evaluations=tuple(results))
    if len(report.lap_time_evaluations) != 8:
        raise TemporalEvaluationError(
            "expected eight lap-time fold evaluations"
        )
    if len(report.pit_duration_evaluations) != 6:
        raise TemporalEvaluationError(
            "expected six pit-duration fold evaluations"
        )
    return report


def _evaluate_lap_baselines(
    *,
    fold_id: str,
    training_sessions: tuple[str, ...],
    validation_sessions: tuple[str, ...],
    rows: pd.DataFrame,
) -> list[FoldBaselineEvaluation]:
    """Fit and score all lap-time baselines for one fold."""
    required = (
        "decision_id",
        "session_id",
        "season",
        "is_decision_eligible",
        "is_lap_time_target_eligible",
        "lap_time_target_seconds",
    )
    _require_columns(rows, required, source="lap_rows")
    training = rows.loc[rows["session_id"].isin(training_sessions)].copy()
    validation_source = rows.loc[
        rows["session_id"].isin(validation_sessions)
    ].copy()
    _require_complete_session_coverage(
        training,
        training_sessions,
        source=f"{fold_id} lap training",
    )
    _require_complete_session_coverage(
        validation_source,
        validation_sessions,
        source=f"{fold_id} lap validation",
    )
    validation = validation_source.loc[
        validation_source["is_decision_eligible"].eq(True)
        & validation_source["is_lap_time_target_eligible"].eq(True)
    ].copy()
    _require_positive_targets(
        validation,
        "lap_time_target_seconds",
        source=f"{fold_id} lap validation",
    )

    results: list[FoldBaselineEvaluation] = []
    for specification in LAP_TIME_BASELINES:
        fit_rows = training if specification.fit_required else None
        model = fit_lap_time_baseline(
            specification.baseline_id,
            fit_rows,
        )
        predictions = model.predict(validation)
        scored = score_prediction_frame(
            targets=validation,
            predictions=predictions,
            identity_column="decision_id",
            target_column="lap_time_target_seconds",
        )
        results.append(
            _result(
                fold_id=fold_id,
                task=BaselineTask.LAP_TIME,
                baseline_id=specification.baseline_id,
                training_sessions=training_sessions,
                validation_sessions=validation_sessions,
                predictions=predictions,
                scored=scored,
            )
        )
    return results


def _evaluate_pit_baselines(
    *,
    fold_id: str,
    training_sessions: tuple[str, ...],
    validation_sessions: tuple[str, ...],
    rows: pd.DataFrame,
) -> list[FoldBaselineEvaluation]:
    """Fit and score all pit-duration baselines for one fold."""
    required = (
        "pit_event_id",
        "session_id",
        "season",
        "is_pit_duration_target_eligible",
        "pit_duration_target_seconds",
    )
    _require_columns(rows, required, source="pit_rows")
    training = rows.loc[rows["session_id"].isin(training_sessions)].copy()
    validation_source = rows.loc[
        rows["session_id"].isin(validation_sessions)
    ].copy()
    _require_complete_session_coverage(
        training,
        training_sessions,
        source=f"{fold_id} pit training",
    )
    _require_complete_session_coverage(
        validation_source,
        validation_sessions,
        source=f"{fold_id} pit validation",
    )
    validation = validation_source.loc[
        validation_source["is_pit_duration_target_eligible"].eq(True)
    ].copy()
    _require_positive_targets(
        validation,
        "pit_duration_target_seconds",
        source=f"{fold_id} pit validation",
    )

    results: list[FoldBaselineEvaluation] = []
    for specification in PIT_DURATION_BASELINES:
        model = fit_pit_duration_baseline(
            specification.baseline_id,
            training,
        )
        predictions = model.predict(validation)
        scored = score_prediction_frame(
            targets=validation,
            predictions=predictions,
            identity_column="pit_event_id",
            target_column="pit_duration_target_seconds",
        )
        results.append(
            _result(
                fold_id=fold_id,
                task=BaselineTask.PIT_DURATION,
                baseline_id=specification.baseline_id,
                training_sessions=training_sessions,
                validation_sessions=validation_sessions,
                predictions=predictions,
                scored=scored,
            )
        )
    return results


def _result(
    *,
    fold_id: str,
    task: BaselineTask,
    baseline_id: BaselineId,
    training_sessions: tuple[str, ...],
    validation_sessions: tuple[str, ...],
    predictions: pd.DataFrame,
    scored: ScoredPredictions,
) -> FoldBaselineEvaluation:
    """Build one immutable result with prediction-source counts."""
    counts = Counter(predictions["prediction_source"].astype(str))
    return FoldBaselineEvaluation(
        fold_id=fold_id,
        task=task,
        baseline_id=baseline_id,
        training_sessions=training_sessions,
        validation_sessions=validation_sessions,
        fallback_counts=dict(sorted(counts.items())),
        scored=scored,
    )


def _validate_splits(splits: pd.DataFrame) -> pd.DataFrame:
    """Require exact development roles and whole-session identities."""
    required = (
        "fold_id",
        "session_id",
        "season",
        "round_number",
        "session_type",
        "role",
    )
    _require_columns(splits, required, source="splits")
    rows = splits.loc[
        splits["fold_id"].isin(DEVELOPMENT_EVALUATION_FOLDS),
        list(required),
    ].copy()
    if rows.empty:
        raise TemporalEvaluationError(
            "splits contain no development evaluation folds"
        )
    if rows.loc[:, ["fold_id", "session_id"]].duplicated().any():
        raise TemporalEvaluationError(
            "splits contain duplicate fold-session assignments"
        )
    if set(rows["fold_id"]) != set(DEVELOPMENT_EVALUATION_FOLDS):
        raise TemporalEvaluationError(
            "splits do not contain both development folds"
        )
    if rows["season"].eq(2025).any():
        raise TemporalEvaluationError(
            "splits contain protected 2025 assignments"
        )
    if not rows["session_type"].eq("R").all():
        raise TemporalEvaluationError("splits contain non-race sessions")

    expected_roles = rows.apply(
        lambda row: _EXPECTED_ROLES.get(str(row["fold_id"]), {}).get(
            int(row["season"])
        ),
        axis=1,
    )
    if expected_roles.isna().any() or not rows["role"].eq(
        expected_roles
    ).all():
        raise TemporalEvaluationError(
            "split roles differ from the frozen temporal contract"
        )
    session_sets = [
        set(group["session_id"].astype(str))
        for _, group in rows.groupby("fold_id", sort=True)
    ]
    if len(session_sets) != 2 or session_sets[0] != session_sets[1]:
        raise TemporalEvaluationError(
            "development folds cover different session sets"
        )
    return rows


def _session_ids(
    fold_rows: pd.DataFrame,
    role: str,
) -> tuple[str, ...]:
    """Return canonical sorted whole-session identities for one role."""
    identities = tuple(
        sorted(fold_rows.loc[fold_rows["role"].eq(role), "session_id"].astype(str))
    )
    if not identities:
        raise TemporalEvaluationError(
            f"fold contains no {role} sessions"
        )
    return identities


def _require_complete_session_coverage(
    rows: pd.DataFrame,
    expected_sessions: tuple[str, ...],
    *,
    source: str,
) -> None:
    """Require every assigned race to contribute to its population."""
    actual = set(rows["session_id"].astype(str))
    missing = sorted(set(expected_sessions).difference(actual))
    if missing:
        raise TemporalEvaluationError(
            f"{source} missing assigned sessions: {', '.join(missing)}"
        )


def _require_positive_targets(
    rows: pd.DataFrame,
    target_column: str,
    *,
    source: str,
) -> None:
    """Require a non-empty finite positive held-out population."""
    if rows.empty:
        raise TemporalEvaluationError(f"{source} contains no eligible targets")
    targets = pd.to_numeric(rows[target_column], errors="coerce")
    if (
        targets.isna().any()
        or (~np.isfinite(targets)).any()
        or targets.le(0).any()
    ):
        raise TemporalEvaluationError(
            f"{source} contains invalid eligible targets"
        )


def _reject_protected_season(rows: pd.DataFrame, *, source: str) -> None:
    """Reject protected rows before constructing any fold."""
    _require_columns(rows, ("season",), source=source)
    if rows["season"].eq(2025).any():
        raise TemporalEvaluationError(
            f"{source} contains protected 2025 rows"
        )


def _require_frame(value: object, *, source: str) -> None:
    """Require an explicit DataFrame."""
    if not isinstance(value, pd.DataFrame):
        raise TypeError(f"{source} must be a pandas DataFrame")


def _require_columns(
    rows: pd.DataFrame,
    required: tuple[str, ...],
    *,
    source: str,
) -> None:
    """Require every temporal evaluation dependency."""
    missing = sorted(set(required).difference(rows.columns))
    if missing:
        raise TemporalEvaluationError(
            f"{source} missing required columns: {', '.join(missing)}"
        )
