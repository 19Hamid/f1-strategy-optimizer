"""Tests for the complete Phase 6 development audit orchestration."""

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from app.ml import (
    APPROVED_FEATURE_COLUMNS,
    NUMERIC_FEATURE_COLUMNS,
    FoldTrainingMatrix,
    ModelFamily,
    ModelTarget,
    PredictionFormulation,
    SelectedPrimaryCandidate,
    TrainingMatrixPartition,
    audit,
    model_spec,
)
from app.ml.audit import (
    ModelAuditError,
    _selection_failure_messages,
    run_model_audit_from_frames,
)
from app.ml.reports import ModelReportVerification


def _partition(
    rows: int,
    *,
    season: int,
    session: str,
    offset: int,
) -> TrainingMatrixPartition:
    """Build one exact synthetic primary matrix partition."""
    records = []
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
    return TrainingMatrixPartition(
        identities=pd.DataFrame(
            {
                "decision_id": [f"{session}-{index}" for index in range(rows)],
                "session_id": [session] * rows,
                "season": [season] * rows,
            }
        ),
        features=features,
        target=(70.0 + features["decision_lap"] * 0.1).rename(
            "lap_time_target_seconds"
        ),
    )


def _matrices() -> tuple[FoldTrainingMatrix, ...]:
    """Build both frozen folds across three synthetic sessions."""
    first = _partition(5, season=2022, session="2022-01-R", offset=0)
    second = _partition(4, season=2023, session="2023-01-R", offset=20)
    third = _partition(3, season=2024, session="2024-01-R", offset=40)
    combined = TrainingMatrixPartition(
        identities=pd.concat(
            [first.identities, second.identities],
            ignore_index=True,
        ),
        features=pd.concat(
            [first.features, second.features],
            ignore_index=True,
        ),
        target=pd.concat([first.target, second.target], ignore_index=True),
    )
    return (
        FoldTrainingMatrix(
            fold_id="development_fold_1",
            target=ModelTarget.LAP_TIME,
            training=first,
            validation=second,
        ),
        FoldTrainingMatrix(
            fold_id="development_fold_2",
            target=ModelTarget.LAP_TIME,
            training=combined,
            validation=third,
        ),
    )


def _selected() -> SelectedPrimaryCandidate:
    """Return one qualifying candidate identity."""
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


def _frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Include one audited race with no eligible model targets."""
    frame = pd.DataFrame(
        {
            "season": [2022, 2023, 2024, 2024],
            "session_id": [
                "2022-01-R",
                "2023-01-R",
                "2024-01-R",
                "2024-02-R",
            ],
        }
    )
    return (
        frame.copy(),
        frame.copy(),
        frame.copy(),
    )


def _patch_fast_audit(
    monkeypatch: pytest.MonkeyPatch,
    *,
    selected: SelectedPrimaryCandidate | None,
) -> None:
    """Replace expensive selection and report storage with exact test doubles."""
    matrices = _matrices()
    selection_table = pd.DataFrame(
        {
            "formulation": [PredictionFormulation.DIRECT_ABSOLUTE.value],
            "candidate_id": ["ridge_01"],
            "full_mean_absolute_error_seconds": [0.5],
            "full_common_mean_absolute_error_seconds": [0.48],
            "ablated_common_mean_absolute_error_seconds": [0.47],
            "coverage_rate": [1.0],
            "beats_frozen_baseline": [False],
            "beats_comparable_baseline": [False],
            "ablation_passes": [False],
            "minimum_coverage_passes": [True],
            "both_folds_present": [True],
        }
    )
    monkeypatch.setattr(
        audit,
        "build_development_training_matrices",
        lambda **_: matrices,
    )
    monkeypatch.setattr(
        audit,
        "evaluate_primary_temporal_candidates",
        lambda *_, **__: SimpleNamespace(
            selected_candidate=selected,
            selection=selection_table,
        ),
    )
    monkeypatch.setattr(
        audit,
        "build_selected_model_diagnostics",
        lambda **_: SimpleNamespace(),
    )
    monkeypatch.setattr(audit, "write_model_report", lambda **_: {})
    monkeypatch.setattr(
        audit,
        "verify_model_report",
        lambda _: ModelReportVerification(True, 7, ()),
    )


def test_audit_refits_and_verifies_the_selected_model(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Complete the orchestration with deterministic progress evidence."""
    _patch_fast_audit(monkeypatch, selected=_selected())
    decision_rows, decision_labels, splits = _frames()
    messages: list[str] = []

    result = run_model_audit_from_frames(
        decision_rows=decision_rows,
        decision_labels=decision_labels,
        splits=splits,
        development_sessions=4,
        artifacts_root=tmp_path,
        run_id="unit-audit",
        dataset_build_identifier="unit-build",
        expected_primary_target_rows=12,
        progress=messages.append,
    )

    assert result.selected_candidate.candidate_id == "ridge_01"
    assert result.primary_target_rows == 12
    assert result.auxiliary_target_rows == 12
    assert result.development_sessions == 4
    assert result.contributing_training_sessions == 3
    assert result.protected_evaluation_rows == 0
    assert result.model_verification.valid is True
    assert result.model_verification.verification_rows == 12
    assert len(messages) == 5


def test_audit_rejects_protected_rows_before_matrix_building(tmp_path) -> None:
    """Fail before training when any 2025 record is present."""
    decision_rows, decision_labels, splits = _frames()
    decision_rows.loc[0, "season"] = 2025

    with pytest.raises(ModelAuditError, match="protected 2025"):
        run_model_audit_from_frames(
            decision_rows=decision_rows,
            decision_labels=decision_labels,
            splits=splits,
            development_sessions=4,
            artifacts_root=tmp_path,
            run_id="protected",
            dataset_build_identifier="unit-build",
        )


def test_audit_rejects_when_no_candidate_passes(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not produce a final model when frozen gates have no winner."""
    _patch_fast_audit(monkeypatch, selected=None)
    decision_rows, decision_labels, splits = _frames()

    with pytest.raises(ModelAuditError, match="no candidate met"):
        run_model_audit_from_frames(
            decision_rows=decision_rows,
            decision_labels=decision_labels,
            splits=splits,
            development_sessions=4,
            artifacts_root=tmp_path,
            run_id="no-winner",
            dataset_build_identifier="unit-build",
        )


def test_audit_reconciles_final_sessions_with_catalog(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a final fit population that omits a verified session."""
    _patch_fast_audit(monkeypatch, selected=_selected())
    decision_rows, decision_labels, splits = _frames()

    with pytest.raises(ModelAuditError, match="sessions differ"):
        run_model_audit_from_frames(
            decision_rows=decision_rows,
            decision_labels=decision_labels,
            splits=splits,
            development_sessions=5,
            artifacts_root=tmp_path,
            run_id="missing-session",
            dataset_build_identifier="unit-build",
        )


def test_audit_reconciles_primary_target_total(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject data drift against the frozen 52,483-row population."""
    _patch_fast_audit(monkeypatch, selected=_selected())
    decision_rows, decision_labels, splits = _frames()

    with pytest.raises(ModelAuditError, match="target rows differ"):
        run_model_audit_from_frames(
            decision_rows=decision_rows,
            decision_labels=decision_labels,
            splits=splits,
            development_sessions=4,
            artifacts_root=tmp_path,
            run_id="wrong-total",
            dataset_build_identifier="unit-build",
            expected_primary_target_rows=99,
        )


def test_failed_selection_summary_exposes_gate_counts_and_top_models() -> None:
    """Give the owner evidence for revising or retaining the contract."""
    rows = pd.DataFrame(
        {
            "formulation": [
                PredictionFormulation.DIRECT_ABSOLUTE.value,
                PredictionFormulation.RESIDUAL_HYBRID.value,
            ],
            "candidate_id": ["ridge_01", "random_forest_01"],
            "full_mean_absolute_error_seconds": [0.5, 0.4],
            "full_common_mean_absolute_error_seconds": [0.48, 0.39],
            "ablated_common_mean_absolute_error_seconds": [0.47, 0.45],
            "coverage_rate": [1.0, 1.0],
            "beats_frozen_baseline": [False, True],
            "beats_comparable_baseline": [False, True],
            "ablation_passes": [False, False],
            "minimum_coverage_passes": [True, True],
            "both_folds_present": [True, True],
        }
    )

    messages = _selection_failure_messages(rows)

    assert "ablation_passes=0/2" in messages[0]
    assert "random_forest_01" in messages[1]
    assert "failed=ablation_passes" in messages[1]
