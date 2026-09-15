"""Tests for selected-model degradation diagnostics."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from app.ml import diagnostics
from app.ml.contracts import (
    APPROVED_FEATURE_COLUMNS,
    NUMERIC_FEATURE_COLUMNS,
    ModelFamily,
    ModelTarget,
    PredictionFormulation,
)
from app.ml.diagnostics import (
    DEGRADATION_CURVE_COLUMNS,
    DIAGNOSTIC_DIMENSIONS,
    IDENTITY_DIAGNOSTIC_COLUMNS,
    SLICE_METRIC_COLUMNS,
    DegradationDiagnosticError,
    SelectedModelDiagnostics,
    build_selected_model_diagnostics,
)
from app.ml.matrices import (
    FoldTrainingMatrix,
    TrainingMatrixPartition,
)
from app.ml.selection import SelectedPrimaryCandidate
from app.ml.training import (
    FULL_FEATURE_SET_ID,
    IDENTITY_ABLATION_FEATURE_SET_ID,
    PREDICTION_COLUMNS,
)


def _features(rows: int, *, offset: int = 0) -> pd.DataFrame:
    """Build exact features spanning compounds and tyre-age bands."""
    tyre_ages = (2.0, 7.0, 18.0, 3.0, 12.0, 20.0)
    records: list[dict[str, object]] = []
    for index in range(rows):
        value = index + offset
        record: dict[str, object] = {
            column: float(value + column_index + 1)
            for column_index, column in enumerate(NUMERIC_FEATURE_COLUMNS)
        }
        record.update(
            {
                "event_name": f"Event {offset}",
                "driver": ("HAM", "LEC", "RUS")[index % 3],
                "team": ("Ferrari", "Mercedes")[index % 2],
                "current_compound": ("SOFT", "MEDIUM", "HARD")[index % 3],
                "decision_lap": index + 2,
                "tyre_age_laps": tyre_ages[index % len(tyre_ages)],
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
    target: ModelTarget,
    offset: int,
) -> TrainingMatrixPartition:
    """Build one diagnostic partition for the requested target."""
    features = _features(rows, offset=offset)
    identities = pd.DataFrame(
        {
            "decision_id": [f"{prefix}-decision-{index}" for index in range(rows)],
            "session_id": [f"{season}-01-R"] * rows,
            "season": [season] * rows,
        }
    )
    if target == ModelTarget.LAP_TIME:
        values = features["previous_lap_time_seconds"] + 0.5
        name = "lap_time_target_seconds"
    else:
        values = pd.Series(
            [(-0.3 + index * 0.15) for index in range(rows)],
            dtype="float64",
        )
        name = "lap_time_delta_seconds"
    return TrainingMatrixPartition(
        identities=identities,
        features=features,
        target=values.rename(name).reset_index(drop=True),
    )


def _matrices(
    target: ModelTarget,
) -> tuple[FoldTrainingMatrix, ...]:
    """Build both chronological diagnostic folds."""
    return (
        FoldTrainingMatrix(
            fold_id="development_fold_1",
            target=target,
            training=_partition(
                6,
                season=2022,
                prefix=f"{target.value}-f1-train",
                target=target,
                offset=0,
            ),
            validation=_partition(
                6,
                season=2023,
                prefix=f"{target.value}-f1-validation",
                target=target,
                offset=10,
            ),
        ),
        FoldTrainingMatrix(
            fold_id="development_fold_2",
            target=target,
            training=_partition(
                8,
                season=2023,
                prefix=f"{target.value}-f2-train",
                target=target,
                offset=20,
            ),
            validation=_partition(
                6,
                season=2024,
                prefix=f"{target.value}-f2-validation",
                target=target,
                offset=30,
            ),
        ),
    )


def _selected() -> SelectedPrimaryCandidate:
    """Return a valid frozen Ridge selection."""
    return SelectedPrimaryCandidate(
        family=ModelFamily.RIDGE,
        candidate_id="ridge_02",
        parameters='{"alpha":1.0}',
        pooled_mean_absolute_error_seconds=0.2,
        common_mean_absolute_error_seconds=0.2,
        ablated_common_mean_absolute_error_seconds=0.3,
        coverage_rate=1.0,
    )


def _fake_train_candidate_model(
    matrix: FoldTrainingMatrix,
    *,
    family: ModelFamily,
    parameters: dict[str, object],
    feature_columns: tuple[str, ...] = APPROVED_FEATURE_COLUMNS,
) -> SimpleNamespace:
    """Return deterministic selected-model predictions."""
    del parameters
    feature_set_id = (
        FULL_FEATURE_SET_ID
        if feature_columns == APPROVED_FEATURE_COLUMNS
        else IDENTITY_ABLATION_FEATURE_SET_ID
    )
    if matrix.target == ModelTarget.LAP_TIME_DELTA:
        error = 0.1
    elif feature_set_id == FULL_FEATURE_SET_ID:
        error = 0.2
    else:
        error = 0.3
    targets = matrix.validation.target.to_numpy(dtype="float64")
    predicted = targets + error
    rows = matrix.validation.identities.copy()
    rows["fold_id"] = matrix.fold_id
    rows["target"] = matrix.target.value
    rows["model_family"] = family.value
    rows["candidate_id"] = "ridge_02"
    rows["feature_set_id"] = feature_set_id
    rows["target_seconds"] = targets
    rows["prediction_seconds"] = predicted
    rows["absolute_error_seconds"] = np.abs(predicted - targets)
    rows = rows.loc[:, PREDICTION_COLUMNS]
    model = SimpleNamespace(
        family=family,
        candidate_id="ridge_02",
        feature_set_id=feature_set_id,
    )
    return SimpleNamespace(
        model=model,
        validation_predictions=rows,
    )


def _build(
    monkeypatch: pytest.MonkeyPatch,
) -> SelectedModelDiagnostics:
    """Build diagnostics with deterministic lightweight predictions."""
    monkeypatch.setattr(
        diagnostics,
        "train_candidate_model",
        _fake_train_candidate_model,
    )
    return build_selected_model_diagnostics(
        primary_matrices=_matrices(ModelTarget.LAP_TIME),
        auxiliary_matrices=_matrices(ModelTarget.LAP_TIME_DELTA),
        selected_candidate=_selected(),
    )


def test_diagnostics_publish_exact_non_empty_schemas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Build all three required evidence tables."""
    report = _build(monkeypatch)
    assert tuple(report.slice_metrics.columns) == SLICE_METRIC_COLUMNS
    assert tuple(report.degradation_curve.columns) == (DEGRADATION_CURVE_COLUMNS)
    assert tuple(report.identity_dependence.columns) == (IDENTITY_DIAGNOSTIC_COLUMNS)
    assert not report.slice_metrics.empty
    assert not report.degradation_curve.empty
    assert len(report.identity_dependence) == 2


def test_slices_cover_both_targets_and_required_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report race, tyre, progress and identity stability."""
    slices = _build(monkeypatch).slice_metrics
    assert set(slices["target"]) == {
        ModelTarget.LAP_TIME.value,
        ModelTarget.LAP_TIME_DELTA.value,
    }
    assert set(slices["dimension"]) == set(DIAGNOSTIC_DIMENSIONS)
    assert set(slices["fold_id"]) == {
        "development_fold_1",
        "development_fold_2",
    }


def test_degradation_curve_uses_auxiliary_lap_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Summarize observed and predicted change by tyre state."""
    curve = _build(monkeypatch).degradation_curve
    assert set(curve["current_compound"]) == {"SOFT", "MEDIUM", "HARD"}
    assert set(curve["tyre_age_band"]) == {
        "NEW_0_5",
        "USED_6_15",
        "OLD_16_PLUS",
    }
    assert np.allclose(
        curve["mean_absolute_error_seconds"],
        0.1,
    )


def test_identity_dependence_reports_ablation_penalty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quantify the cost of removing driver and team."""
    identity = _build(monkeypatch).identity_dependence
    full = identity.loc[identity["feature_set_id"].eq(FULL_FEATURE_SET_ID)].iloc[0]
    ablated = identity.loc[
        identity["feature_set_id"].eq(IDENTITY_ABLATION_FEATURE_SET_ID)
    ].iloc[0]
    assert full["mean_absolute_error_seconds"] == pytest.approx(0.2)
    assert full["mae_increase_from_full_seconds"] == pytest.approx(0.0)
    assert ablated["mean_absolute_error_seconds"] == pytest.approx(0.3)
    assert ablated["mae_increase_from_full_seconds"] == pytest.approx(0.1)


def test_hybrid_winner_diagnostics_score_absolute_and_delta_models() -> None:
    """Diagnose a selected hybrid without losing either target view."""
    selected = replace(
        _selected(),
        formulation=PredictionFormulation.RESIDUAL_HYBRID,
    )

    report = build_selected_model_diagnostics(
        primary_matrices=_matrices(ModelTarget.LAP_TIME),
        auxiliary_matrices=_matrices(ModelTarget.LAP_TIME_DELTA),
        selected_candidate=selected,
    )

    assert set(report.slice_metrics["target"]) == {
        ModelTarget.LAP_TIME.value,
        ModelTarget.LAP_TIME_DELTA.value,
    }
    assert set(report.identity_dependence["feature_set_id"]) == {
        FULL_FEATURE_SET_ID,
        IDENTITY_ABLATION_FEATURE_SET_ID,
    }


def test_diagnostics_do_not_mutate_source_matrices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the verified model matrices authoritative."""
    monkeypatch.setattr(
        diagnostics,
        "train_candidate_model",
        _fake_train_candidate_model,
    )
    primary = _matrices(ModelTarget.LAP_TIME)
    before = primary[0].validation.features.copy(deep=True)
    build_selected_model_diagnostics(
        primary_matrices=primary,
        auxiliary_matrices=_matrices(ModelTarget.LAP_TIME_DELTA),
        selected_candidate=_selected(),
    )
    assert_frame_equal(primary[0].validation.features, before)


def test_invalid_selected_parameter_document_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require deterministic JSON hyperparameter provenance."""
    monkeypatch.setattr(
        diagnostics,
        "train_candidate_model",
        _fake_train_candidate_model,
    )
    selected = SelectedPrimaryCandidate(
        family=ModelFamily.RIDGE,
        candidate_id="ridge_02",
        parameters="not-json",
        pooled_mean_absolute_error_seconds=0.2,
        common_mean_absolute_error_seconds=0.2,
        ablated_common_mean_absolute_error_seconds=0.3,
        coverage_rate=1.0,
    )
    with pytest.raises(
        DegradationDiagnosticError,
        match="not valid JSON",
    ):
        build_selected_model_diagnostics(
            primary_matrices=_matrices(ModelTarget.LAP_TIME),
            auxiliary_matrices=_matrices(ModelTarget.LAP_TIME_DELTA),
            selected_candidate=selected,
        )


def test_auxiliary_matrices_must_use_delta_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not label primary lap-time predictions as degradation evidence."""
    monkeypatch.setattr(
        diagnostics,
        "train_candidate_model",
        _fake_train_candidate_model,
    )
    with pytest.raises(
        DegradationDiagnosticError,
        match="expected LAP_TIME_DELTA",
    ):
        build_selected_model_diagnostics(
            primary_matrices=_matrices(ModelTarget.LAP_TIME),
            auxiliary_matrices=_matrices(ModelTarget.LAP_TIME),
            selected_candidate=_selected(),
        )


def test_protected_2025_rows_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the final evaluation season outside all diagnostics."""
    monkeypatch.setattr(
        diagnostics,
        "train_candidate_model",
        _fake_train_candidate_model,
    )
    primary = list(_matrices(ModelTarget.LAP_TIME))
    primary[0].validation.identities.loc[:, "season"] = 2025
    with pytest.raises(
        DegradationDiagnosticError,
        match="protected 2025",
    ):
        build_selected_model_diagnostics(
            primary_matrices=tuple(primary),
            auxiliary_matrices=_matrices(ModelTarget.LAP_TIME_DELTA),
            selected_candidate=_selected(),
        )


def test_retrained_candidate_must_match_selected_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refuse diagnostics accidentally produced by another grid member."""

    def wrong_candidate(
        *args: object,
        **kwargs: object,
    ) -> SimpleNamespace:
        result = _fake_train_candidate_model(*args, **kwargs)
        result.model.candidate_id = "ridge_01"
        return result

    monkeypatch.setattr(
        diagnostics,
        "train_candidate_model",
        wrong_candidate,
    )
    with pytest.raises(
        DegradationDiagnosticError,
        match="differs from selected",
    ):
        build_selected_model_diagnostics(
            primary_matrices=_matrices(ModelTarget.LAP_TIME),
            auxiliary_matrices=_matrices(ModelTarget.LAP_TIME_DELTA),
            selected_candidate=_selected(),
        )
