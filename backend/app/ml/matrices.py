"""Build leakage-safe model matrices from Phase 4 decision artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from app.datasets.contracts import DEVELOPMENT_SEASONS, temporal_fold
from app.ml.contracts import (
    APPROVED_FEATURE_COLUMNS,
    AUXILIARY_TARGET_COLUMN,
    DEVELOPMENT_FOLDS,
    FORBIDDEN_MODEL_COLUMNS,
    PRIMARY_TARGET_COLUMN,
    PROTECTED_EVALUATION_SEASON,
    ModelTarget,
)

MATRIX_IDENTITY_COLUMNS: Final = (
    "decision_id",
    "session_id",
    "season",
)
_REQUIRED_DECISION_COLUMNS: Final = (
    *MATRIX_IDENTITY_COLUMNS,
    "decision_lap",
    "is_decision_eligible",
    *APPROVED_FEATURE_COLUMNS,
)
_REQUIRED_LABEL_COLUMNS: Final = (
    *MATRIX_IDENTITY_COLUMNS,
    "is_lap_time_target_eligible",
    PRIMARY_TARGET_COLUMN,
)
_REQUIRED_SPLIT_COLUMNS: Final = (
    "fold_id",
    "session_id",
    "season",
    "round_number",
    "session_type",
    "role",
)


class TrainingMatrixError(ValueError):
    """Raised when source data cannot form a leakage-safe model matrix."""


@dataclass(frozen=True, slots=True)
class TrainingMatrixPartition:
    """Features, target and audit identities for one temporal role."""

    identities: pd.DataFrame
    features: pd.DataFrame
    target: pd.Series

    def __post_init__(self) -> None:
        """Require aligned rows and the exact approved feature order."""
        row_count = len(self.identities)
        if row_count == 0:
            raise TrainingMatrixError("matrix partition must not be empty")
        if len(self.features) != row_count or len(self.target) != row_count:
            raise TrainingMatrixError("matrix partition rows are not aligned")
        if tuple(self.identities.columns) != MATRIX_IDENTITY_COLUMNS:
            raise TrainingMatrixError("matrix identity columns differ from contract")
        if tuple(self.features.columns) != APPROVED_FEATURE_COLUMNS:
            raise TrainingMatrixError("matrix features differ from contract")
        if set(self.features.columns) & FORBIDDEN_MODEL_COLUMNS:
            raise TrainingMatrixError("forbidden columns entered matrix features")
        expected_index = pd.RangeIndex(row_count)
        if (
            not self.identities.index.equals(expected_index)
            or not self.features.index.equals(expected_index)
            or not self.target.index.equals(expected_index)
        ):
            raise TrainingMatrixError("matrix partition index is not canonical")

    @property
    def row_count(self) -> int:
        """Return the number of examples in this partition."""
        return len(self.target)


@dataclass(frozen=True, slots=True)
class FoldTrainingMatrix:
    """Training and validation matrices for one whole-race temporal fold."""

    fold_id: str
    target: ModelTarget
    training: TrainingMatrixPartition
    validation: TrainingMatrixPartition

    def __post_init__(self) -> None:
        """Prevent a race from entering both sides of a fold."""
        training_sessions = set(self.training.identities["session_id"])
        validation_sessions = set(self.validation.identities["session_id"])
        if training_sessions & validation_sessions:
            raise TrainingMatrixError(
                f"{self.fold_id} training and validation sessions overlap"
            )


def build_development_training_matrices(
    *,
    decision_rows: pd.DataFrame,
    decision_labels: pd.DataFrame,
    splits: pd.DataFrame,
    target: ModelTarget | str,
) -> tuple[FoldTrainingMatrix, ...]:
    """Build deterministic matrices for both frozen development folds."""
    _require_frame(decision_rows, source="decision_rows")
    _require_frame(decision_labels, source="decision_labels")
    _require_frame(splits, source="splits")
    normalized_target = _normalize_target(target)
    _require_columns(
        decision_rows,
        _REQUIRED_DECISION_COLUMNS,
        source="decision_rows",
    )
    _require_columns(
        decision_labels,
        _REQUIRED_LABEL_COLUMNS,
        source="decision_labels",
    )
    _require_columns(splits, _REQUIRED_SPLIT_COLUMNS, source="splits")
    _reject_protected_or_unknown_seasons(decision_rows, source="decision_rows")
    _reject_protected_or_unknown_seasons(
        decision_labels,
        source="decision_labels",
    )
    _reject_protected_or_unknown_seasons(splits, source="splits")

    assignments = _validate_splits(splits)
    joined = _join_decisions_and_targets(decision_rows, decision_labels)
    _require_assigned_session_coverage(joined, assignments)
    eligible = _eligible_target_rows(joined, target=normalized_target)

    matrices = tuple(
        _build_fold_matrix(
            eligible,
            assignments=assignments,
            fold_id=fold_id,
            target=normalized_target,
        )
        for fold_id in DEVELOPMENT_FOLDS
    )
    if len(matrices) != len(DEVELOPMENT_FOLDS):
        raise TrainingMatrixError("not every development fold was built")
    return matrices


def _normalize_target(target: ModelTarget | str) -> ModelTarget:
    """Return one frozen target identity."""
    try:
        return ModelTarget(target)
    except (TypeError, ValueError) as error:
        raise TrainingMatrixError(f"unknown model target: {target!r}") from error


def _join_decisions_and_targets(
    decisions: pd.DataFrame,
    labels: pd.DataFrame,
) -> pd.DataFrame:
    """Join target fields only after reconciling source identities."""
    if decisions["decision_id"].duplicated().any():
        raise TrainingMatrixError("decision_rows contain duplicate decision_id")
    if labels["decision_id"].duplicated().any():
        raise TrainingMatrixError("decision_labels contain duplicate decision_id")

    identities = decisions.loc[:, MATRIX_IDENTITY_COLUMNS].merge(
        labels.loc[:, MATRIX_IDENTITY_COLUMNS],
        on="decision_id",
        how="outer",
        suffixes=("_decision", "_label"),
        indicator=True,
        validate="one_to_one",
    )
    if not identities["_merge"].eq("both").all():
        raise TrainingMatrixError("decision rows and labels do not reconcile")
    for column in ("session_id", "season"):
        if not identities[f"{column}_decision"].eq(
            identities[f"{column}_label"]
        ).all():
            raise TrainingMatrixError(
                f"decision rows and labels disagree on {column}"
            )

    target_columns = (
        "decision_id",
        "is_lap_time_target_eligible",
        PRIMARY_TARGET_COLUMN,
    )
    return decisions.merge(
        labels.loc[:, target_columns],
        on="decision_id",
        how="inner",
        validate="one_to_one",
    )


def _eligible_target_rows(
    rows: pd.DataFrame,
    *,
    target: ModelTarget,
) -> pd.DataFrame:
    """Select eligible rows and derive the approved auxiliary target."""
    _require_boolean(rows, "is_decision_eligible")
    _require_boolean(rows, "is_lap_time_target_eligible")
    eligible = rows.loc[
        rows["is_decision_eligible"].eq(True)
        & rows["is_lap_time_target_eligible"].eq(True)
    ].copy()
    if eligible.empty:
        raise TrainingMatrixError("no eligible lap-time targets")

    primary = pd.to_numeric(eligible[PRIMARY_TARGET_COLUMN], errors="coerce")
    invalid_primary = (
        primary.isna().any()
        or (~np.isfinite(primary)).any()
        or primary.le(0).any()
    )
    if invalid_primary:
        raise TrainingMatrixError(
            "eligible lap-time targets must be finite and positive"
        )
    eligible[PRIMARY_TARGET_COLUMN] = primary.astype("float64")

    if target == ModelTarget.LAP_TIME:
        return _canonical_sort(eligible)

    previous = pd.to_numeric(
        eligible["previous_lap_time_seconds"],
        errors="coerce",
    )
    auxiliary_mask = (
        eligible["previous_lap_was_target_eligible"].eq(True)
        & previous.notna()
        & np.isfinite(previous)
        & previous.gt(0)
    )
    eligible = eligible.loc[auxiliary_mask].copy()
    if eligible.empty:
        raise TrainingMatrixError("no eligible lap-time delta targets")
    previous = previous.loc[auxiliary_mask]
    eligible[AUXILIARY_TARGET_COLUMN] = (
        eligible[PRIMARY_TARGET_COLUMN] - previous
    ).astype("float64")
    if (~np.isfinite(eligible[AUXILIARY_TARGET_COLUMN])).any():
        raise TrainingMatrixError("lap-time delta targets must be finite")
    return _canonical_sort(eligible)


def _canonical_sort(rows: pd.DataFrame) -> pd.DataFrame:
    """Return deterministic chronological and driver ordering."""
    return rows.sort_values(
        [
            "season",
            "session_id",
            "decision_lap",
            "driver",
            "decision_id",
        ],
        kind="stable",
    ).reset_index(drop=True)


def _build_fold_matrix(
    rows: pd.DataFrame,
    *,
    assignments: pd.DataFrame,
    fold_id: str,
    target: ModelTarget,
) -> FoldTrainingMatrix:
    """Slice one target population by frozen whole-race assignments."""
    fold_rows = assignments.loc[assignments["fold_id"].eq(fold_id)]
    training_sessions = frozenset(
        fold_rows.loc[fold_rows["role"].eq("TRAIN"), "session_id"].astype(str)
    )
    validation_sessions = frozenset(
        fold_rows.loc[
            fold_rows["role"].eq("VALIDATION"),
            "session_id",
        ].astype(str)
    )
    if not training_sessions or not validation_sessions:
        raise TrainingMatrixError(
            f"{fold_id} requires training and validation sessions"
        )
    target_column = (
        PRIMARY_TARGET_COLUMN
        if target == ModelTarget.LAP_TIME
        else AUXILIARY_TARGET_COLUMN
    )
    training_rows = rows.loc[
        rows["session_id"].astype(str).isin(training_sessions)
    ].copy()
    validation_rows = rows.loc[
        rows["session_id"].astype(str).isin(validation_sessions)
    ].copy()
    return FoldTrainingMatrix(
        fold_id=fold_id,
        target=target,
        training=_partition(training_rows, target_column=target_column),
        validation=_partition(validation_rows, target_column=target_column),
    )


def _partition(
    rows: pd.DataFrame,
    *,
    target_column: str,
) -> TrainingMatrixPartition:
    """Separate audit identities from model inputs and target values."""
    canonical = _canonical_sort(rows)
    identities = canonical.loc[:, MATRIX_IDENTITY_COLUMNS].reset_index(drop=True)
    features = canonical.loc[:, APPROVED_FEATURE_COLUMNS].reset_index(drop=True)
    target = canonical[target_column].rename(target_column).reset_index(drop=True)
    return TrainingMatrixPartition(
        identities=identities,
        features=features,
        target=target,
    )


def _validate_splits(splits: pd.DataFrame) -> pd.DataFrame:
    """Require exact roles for every frozen development fold."""
    selected = splits.loc[
        splits["fold_id"].isin(DEVELOPMENT_FOLDS),
        _REQUIRED_SPLIT_COLUMNS,
    ].copy()
    if set(selected["fold_id"].astype(str)) != set(DEVELOPMENT_FOLDS):
        raise TrainingMatrixError("splits do not contain every development fold")
    if selected.loc[:, ["fold_id", "session_id"]].duplicated().any():
        raise TrainingMatrixError("splits contain duplicate fold-session rows")
    if not selected["session_type"].eq("R").all():
        raise TrainingMatrixError("splits contain non-race sessions")

    for row in selected.itertuples(index=False):
        try:
            expected = temporal_fold(str(row.fold_id)).role_for_season(
                int(row.season)
            )
        except ValueError as error:
            raise TrainingMatrixError("splits contain an invalid season") from error
        if str(row.role) != expected.value:
            raise TrainingMatrixError(
                f"{row.fold_id} roles differ from the temporal contract"
            )

    session_sets = tuple(
        frozenset(group["session_id"].astype(str))
        for _, group in selected.groupby("fold_id", sort=True)
    )
    if (
        len(session_sets) != len(DEVELOPMENT_FOLDS)
        or len(set(session_sets)) != 1
    ):
        raise TrainingMatrixError(
            "development folds cover different session sets"
        )
    return selected


def _require_assigned_session_coverage(
    rows: pd.DataFrame,
    assignments: pd.DataFrame,
) -> None:
    """Require every assigned race to exist before eligibility filtering."""
    expected = set(assignments["session_id"].astype(str))
    actual = set(rows["session_id"].astype(str))
    missing = sorted(expected.difference(actual))
    unexpected = sorted(actual.difference(expected))
    if missing or unexpected:
        raise TrainingMatrixError(
            "source and split sessions differ; "
            f"missing={missing}, unexpected={unexpected}"
        )


def _reject_protected_or_unknown_seasons(
    rows: pd.DataFrame,
    *,
    source: str,
) -> None:
    """Fail before filtering if protected or unknown seasons are present."""
    seasons = pd.to_numeric(rows["season"], errors="coerce")
    if seasons.isna().any():
        raise TrainingMatrixError(f"{source} contains invalid seasons")
    if seasons.eq(PROTECTED_EVALUATION_SEASON).any():
        raise TrainingMatrixError(
            f"{source} contains protected {PROTECTED_EVALUATION_SEASON} rows"
        )
    unknown = sorted(set(seasons.astype(int)).difference(DEVELOPMENT_SEASONS))
    if unknown:
        raise TrainingMatrixError(
            f"{source} contains non-development seasons: {unknown}"
        )


def _require_boolean(rows: pd.DataFrame, column: str) -> None:
    """Require an explicit non-null boolean eligibility field."""
    if rows[column].isna().any() or not rows[column].isin([True, False]).all():
        raise TrainingMatrixError(f"{column} must contain only booleans")


def _require_frame(value: object, *, source: str) -> None:
    """Require explicit DataFrame inputs."""
    if not isinstance(value, pd.DataFrame):
        raise TypeError(f"{source} must be a pandas DataFrame")


def _require_columns(
    rows: pd.DataFrame,
    required: tuple[str, ...],
    *,
    source: str,
) -> None:
    """Require every declared matrix dependency."""
    missing = sorted(set(required).difference(rows.columns))
    if missing:
        raise TrainingMatrixError(
            f"{source} missing required columns: {', '.join(missing)}"
        )
