"""Tests for fitting the selected model on all development races."""

import json

import pandas as pd
import pytest

from app.ml import (
    APPROVED_FEATURE_COLUMNS,
    NUMERIC_FEATURE_COLUMNS,
    FoldTrainingMatrix,
    ModelFamily,
    ModelTarget,
    SelectedPrimaryCandidate,
    TrainingMatrixPartition,
    model_spec,
)
from app.ml.final_fit import (
    FINAL_DEVELOPMENT_FIT_ID,
    FinalModelFitError,
    build_final_development_partition,
    fit_final_development_model,
)


def _partition(
    rows: int,
    *,
    season: int,
    session: str,
    offset: int,
) -> TrainingMatrixPartition:
    """Build one exact synthetic primary-target partition."""
    records: list[dict[str, object]] = []
    for index in range(rows):
        value = offset + index
        record: dict[str, object] = {
            column: float(value + column_index + 1)
            for column_index, column in enumerate(NUMERIC_FEATURE_COLUMNS)
        }
        record.update(
            {
                "event_name": f"Event {season}",
                "driver": ("HAM", "LEC")[value % 2],
                "team": ("Mercedes", "Ferrari")[value % 2],
                "current_compound": ("SOFT", "MEDIUM")[value % 2],
                "previous_lap_was_target_eligible": True,
            }
        )
        records.append(record)
    features = pd.DataFrame.from_records(
        records,
        columns=APPROVED_FEATURE_COLUMNS,
    )
    target = (
        70.0
        + features["decision_lap"] * 0.1
        + features["tyre_age_laps"] * 0.02
    )
    return TrainingMatrixPartition(
        identities=pd.DataFrame(
            {
                "decision_id": [f"{session}-{index}" for index in range(rows)],
                "session_id": [session] * rows,
                "season": [season] * rows,
            }
        ),
        features=features,
        target=target.rename("lap_time_target_seconds"),
    )


def _matrices() -> tuple[FoldTrainingMatrix, ...]:
    """Build both chronological folds with complete development coverage."""
    season_2022 = _partition(
        5,
        season=2022,
        session="2022-01-R",
        offset=0,
    )
    season_2023 = _partition(
        4,
        season=2023,
        session="2023-01-R",
        offset=20,
    )
    season_2024 = _partition(
        3,
        season=2024,
        session="2024-01-R",
        offset=40,
    )
    fold_2_training = TrainingMatrixPartition(
        identities=pd.concat(
            [season_2022.identities, season_2023.identities],
            ignore_index=True,
        ),
        features=pd.concat(
            [season_2022.features, season_2023.features],
            ignore_index=True,
        ),
        target=pd.concat(
            [season_2022.target, season_2023.target],
            ignore_index=True,
        ),
    )
    return (
        FoldTrainingMatrix(
            fold_id="development_fold_1",
            target=ModelTarget.LAP_TIME,
            training=season_2022,
            validation=season_2023,
        ),
        FoldTrainingMatrix(
            fold_id="development_fold_2",
            target=ModelTarget.LAP_TIME,
            training=fold_2_training,
            validation=season_2024,
        ),
    )


def _selected() -> SelectedPrimaryCandidate:
    """Return a valid selected Ridge candidate."""
    parameters = model_spec(ModelFamily.RIDGE).parameter_grid[0]
    return SelectedPrimaryCandidate(
        family=ModelFamily.RIDGE,
        candidate_id="ridge_01",
        parameters=json.dumps(parameters, sort_keys=True, separators=(",", ":")),
        pooled_mean_absolute_error_seconds=0.2,
        common_mean_absolute_error_seconds=0.2,
        ablated_common_mean_absolute_error_seconds=0.25,
        coverage_rate=1.0,
    )


def test_final_partition_contains_every_development_row_once() -> None:
    """Use fold two's expanding train and validation roles exactly once."""
    partition = build_final_development_partition(_matrices())

    assert partition.row_count == 12
    assert tuple(sorted(partition.identities["season"].unique())) == (
        2022,
        2023,
        2024,
    )
    assert not partition.identities["decision_id"].duplicated().any()


def test_final_fit_preserves_the_temporally_selected_identity() -> None:
    """Refit the approved grid member without retuning on all data."""
    result = fit_final_development_model(
        matrices=_matrices(),
        selected_candidate=_selected(),
    )

    assert result.model.fold_id == FINAL_DEVELOPMENT_FIT_ID
    assert result.model.candidate_id == "ridge_01"
    assert result.training.row_count == 12
    assert len(result.model.predict(result.training.features)) == 12
    assert result.fit_duration_seconds >= 0


def test_final_partition_requires_both_frozen_folds() -> None:
    """Reject an incomplete temporal history before refitting."""
    with pytest.raises(FinalModelFitError, match="both frozen"):
        build_final_development_partition(_matrices()[:1])


def test_final_partition_rejects_non_primary_target() -> None:
    """Keep the final production bundle on the primary lap-time target."""
    first = _matrices()[0]
    invalid = (
        FoldTrainingMatrix(
            fold_id=first.fold_id,
            target=ModelTarget.LAP_TIME_DELTA,
            training=first.training,
            validation=first.validation,
        ),
        _matrices()[1],
    )
    with pytest.raises(FinalModelFitError, match="LAP_TIME"):
        build_final_development_partition(invalid)


def test_final_fit_rejects_parameters_outside_json_object() -> None:
    """Reject malformed selected-candidate evidence."""
    selected = _selected()
    invalid = SelectedPrimaryCandidate(
        family=selected.family,
        candidate_id=selected.candidate_id,
        parameters="[]",
        pooled_mean_absolute_error_seconds=selected.pooled_mean_absolute_error_seconds,
        common_mean_absolute_error_seconds=selected.common_mean_absolute_error_seconds,
        ablated_common_mean_absolute_error_seconds=(
            selected.ablated_common_mean_absolute_error_seconds
        ),
        coverage_rate=selected.coverage_rate,
    )
    with pytest.raises(FinalModelFitError, match="JSON object"):
        fit_final_development_model(
            matrices=_matrices(),
            selected_candidate=invalid,
        )
