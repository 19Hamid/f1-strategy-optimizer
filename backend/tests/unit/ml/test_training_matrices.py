"""Tests for leakage-safe Phase 6 training matrix construction."""

import pandas as pd
import pytest

from app.ml import (
    APPROVED_FEATURE_COLUMNS,
    AUXILIARY_TARGET_COLUMN,
    FORBIDDEN_MODEL_COLUMNS,
    MATRIX_IDENTITY_COLUMNS,
    PRIMARY_TARGET_COLUMN,
    ModelTarget,
    TrainingMatrixError,
    build_development_training_matrices,
)

_SEASONS = (2022, 2023, 2024)


def _decision_rows() -> pd.DataFrame:
    """Build two deterministic eligible decisions per development season."""
    records: list[dict[str, object]] = []
    for season_index, season in enumerate(_SEASONS):
        for lap in (2, 3):
            previous_lap = 90.0 + season_index + (lap - 2) * 0.2
            features: dict[str, object] = {
                column: float(season_index + lap)
                for column in APPROVED_FEATURE_COLUMNS
            }
            features.update(
                {
                    "event_name": f"Event {season}",
                    "driver": f"D{season_index}",
                    "team": f"Team {season_index}",
                    "decision_lap": lap,
                    "current_compound": "MEDIUM",
                    "previous_lap_was_target_eligible": True,
                    "previous_lap_time_seconds": previous_lap,
                }
            )
            records.append(
                {
                    "decision_id": f"d{season}-{lap}",
                    "session_id": f"{season}-01-R",
                    "season": season,
                    **features,
                    "is_decision_eligible": True,
                }
            )
    return pd.DataFrame.from_records(records)


def _decision_labels() -> pd.DataFrame:
    """Build matching positive next-lap targets."""
    decisions = _decision_rows()
    return pd.DataFrame.from_records(
        [
            {
                "decision_id": row.decision_id,
                "session_id": row.session_id,
                "season": row.season,
                "is_lap_time_target_eligible": True,
                "lap_time_target_seconds": (
                    float(row.previous_lap_time_seconds) + 0.5
                ),
            }
            for row in decisions.itertuples(index=False)
        ]
    )


def _splits() -> pd.DataFrame:
    """Build exact whole-race roles for the two development folds."""
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


def _build(
    *,
    decisions: pd.DataFrame | None = None,
    labels: pd.DataFrame | None = None,
    splits: pd.DataFrame | None = None,
    target: ModelTarget | str = ModelTarget.LAP_TIME,
):
    """Build matrices with optional source overrides."""
    return build_development_training_matrices(
        decision_rows=_decision_rows() if decisions is None else decisions,
        decision_labels=_decision_labels() if labels is None else labels,
        splits=_splits() if splits is None else splits,
        target=target,
    )


def test_primary_matrices_follow_whole_race_temporal_folds() -> None:
    """Use 2022→2023 and 2022–2023→2024 without row-level splitting."""
    fold_one, fold_two = _build()
    assert fold_one.fold_id == "development_fold_1"
    assert fold_one.target == ModelTarget.LAP_TIME
    assert set(fold_one.training.identities["session_id"]) == {"2022-01-R"}
    assert set(fold_one.validation.identities["session_id"]) == {"2023-01-R"}
    assert set(fold_two.training.identities["session_id"]) == {
        "2022-01-R",
        "2023-01-R",
    }
    assert set(fold_two.validation.identities["session_id"]) == {"2024-01-R"}


def test_matrix_separates_identities_features_and_target() -> None:
    """Expose audit identity without allowing it into model inputs."""
    fold_one = _build()[0]
    partition = fold_one.training
    assert tuple(partition.identities.columns) == MATRIX_IDENTITY_COLUMNS
    assert tuple(partition.features.columns) == APPROVED_FEATURE_COLUMNS
    assert partition.target.name == PRIMARY_TARGET_COLUMN
    assert partition.row_count == 2
    assert not set(partition.features.columns) & FORBIDDEN_MODEL_COLUMNS


def test_auxiliary_matrix_derives_change_from_previous_valid_lap() -> None:
    """Build lap-time change only where the previous lap is target-valid."""
    decisions = _decision_rows()
    decisions.loc[
        decisions["decision_lap"].eq(2),
        "previous_lap_was_target_eligible",
    ] = False
    matrices = _build(
        decisions=decisions,
        target=ModelTarget.LAP_TIME_DELTA,
    )
    assert all(
        matrix.training.target.name == AUXILIARY_TARGET_COLUMN
        for matrix in matrices
    )
    assert all(
        matrix.validation.target.name == AUXILIARY_TARGET_COLUMN
        for matrix in matrices
    )
    assert all(
        partition.target.eq(0.5).all()
        for matrix in matrices
        for partition in (matrix.training, matrix.validation)
    )


def test_ineligible_target_rows_are_removed_before_partitioning() -> None:
    """Never train on a post-lap target rejected by Phase 4."""
    labels = _decision_labels()
    labels.loc[labels["decision_id"].eq("d2022-2"), "is_lap_time_target_eligible"] = (
        False
    )
    fold_one = _build(labels=labels)[0]
    assert tuple(fold_one.training.identities["decision_id"]) == ("d2022-3",)


def test_source_order_does_not_change_canonical_matrix_order() -> None:
    """Return the same chronological identities from shuffled inputs."""
    decisions = _decision_rows().sample(frac=1, random_state=7)
    labels = _decision_labels().sample(frac=1, random_state=8)
    fold_two = _build(decisions=decisions, labels=labels)[1]
    assert tuple(fold_two.training.identities["decision_id"]) == (
        "d2022-2",
        "d2022-3",
        "d2023-2",
        "d2023-3",
    )


def test_protected_2025_rows_fail_before_matrix_filtering() -> None:
    """Do not let the final holdout touch a development interface."""
    decisions = _decision_rows()
    decisions.loc[0, "season"] = 2025
    with pytest.raises(TrainingMatrixError, match="protected 2025"):
        _build(decisions=decisions)


def test_decision_and_label_identity_disagreement_is_rejected() -> None:
    """Refuse targets attached to the wrong race."""
    labels = _decision_labels()
    labels.loc[0, "session_id"] = "2022-99-R"
    with pytest.raises(TrainingMatrixError, match="disagree on session_id"):
        _build(labels=labels)


def test_duplicate_decision_identity_is_rejected() -> None:
    """Preserve the one-decision-to-one-target relationship."""
    decisions = pd.concat(
        [_decision_rows(), _decision_rows().iloc[[0]]],
        ignore_index=True,
    )
    with pytest.raises(TrainingMatrixError, match="duplicate decision_id"):
        _build(decisions=decisions)


def test_invalid_eligible_primary_target_is_rejected() -> None:
    """Require real finite positive lap-time targets."""
    labels = _decision_labels()
    labels.loc[0, PRIMARY_TARGET_COLUMN] = -1.0
    with pytest.raises(TrainingMatrixError, match="finite and positive"):
        _build(labels=labels)


def test_modified_temporal_role_is_rejected() -> None:
    """Fail if a validation season is silently moved into training."""
    splits = _splits()
    splits.loc[
        splits["fold_id"].eq("development_fold_1")
        & splits["season"].eq(2023),
        "role",
    ] = "TRAIN"
    with pytest.raises(TrainingMatrixError, match="roles differ"):
        _build(splits=splits)


def test_missing_approved_feature_is_rejected() -> None:
    """Require the full user-approved safe feature set."""
    decisions = _decision_rows().drop(columns=["tyre_age_laps"])
    with pytest.raises(TrainingMatrixError, match="tyre_age_laps"):
        _build(decisions=decisions)


def test_unknown_target_is_rejected() -> None:
    """Restrict construction to the two frozen supervised targets."""
    with pytest.raises(TrainingMatrixError, match="unknown model target"):
        _build(target="fastest_lap")
