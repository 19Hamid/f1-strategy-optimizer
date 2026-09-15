"""Tests for immutable Phase 6 selection and diagnostic reports."""

import json

import pandas as pd
import pytest

from app.ml import (
    DEGRADATION_CURVE_COLUMNS,
    FOLD_METRIC_COLUMNS,
    IDENTITY_DIAGNOSTIC_COLUMNS,
    MODEL_CONTRACT_VERSION,
    MODEL_SPECS,
    POOLED_METRIC_COLUMNS,
    SELECTION_COLUMNS,
    SLICE_METRIC_COLUMNS,
    ModelFamily,
    PredictionFormulation,
    SelectedModelDiagnostics,
    SelectedPrimaryCandidate,
    TemporalSelectionReport,
)
from app.ml.reports import (
    MODEL_EVALUATION_FILES,
    MODEL_EVALUATION_FORMAT_VERSION,
    ModelEvaluationProvenance,
    ModelReportError,
    ModelReportPaths,
    verify_model_report,
    write_model_report,
)


def _candidate_records() -> list[tuple[ModelFamily, str, str]]:
    """Return every frozen candidate identity."""
    records = []
    for specification in MODEL_SPECS:
        for index, parameters in enumerate(specification.parameter_grid, start=1):
            records.append(
                (
                    specification.family,
                    f"{specification.family.value}_{index:02d}",
                    json.dumps(parameters, sort_keys=True, separators=(",", ":")),
                )
            )
    return records


def _selection_report() -> TemporalSelectionReport:
    """Build exact-sized synthetic temporal selection evidence."""
    candidates = _candidate_records()
    fold_rows = []
    for formulation in PredictionFormulation:
        for fold_id in ("development_fold_1", "development_fold_2"):
            for family, candidate_id, parameters in candidates:
                for feature_set_id in ("full", "without_driver_team"):
                    fold_rows.append(
                        {
                            "fold_id": fold_id,
                            "target": "LAP_TIME",
                            "formulation": formulation.value,
                            "model_family": family.value,
                            "candidate_id": candidate_id,
                            "feature_set_id": feature_set_id,
                            "parameters": parameters,
                            "eligible_targets": 10,
                            "scored_predictions": 10,
                            "coverage_rate": 1.0,
                            "mean_absolute_error_seconds": 0.2,
                            "root_mean_squared_error_seconds": 0.25,
                            "median_absolute_error_seconds": 0.2,
                            "p90_absolute_error_seconds": 0.3,
                            "mean_signed_error_seconds": 0.0,
                            "common_rows": 10,
                            "common_mean_absolute_error_seconds": 0.2,
                            "common_root_mean_squared_error_seconds": 0.25,
                            "common_median_absolute_error_seconds": 0.2,
                            "common_p90_absolute_error_seconds": 0.3,
                            "common_mean_signed_error_seconds": 0.0,
                            "baseline_common_mean_absolute_error_seconds": 0.5,
                        }
                    )
    pooled_rows = []
    for formulation in PredictionFormulation:
        for family, candidate_id, parameters in candidates:
            for feature_set_id in ("full", "without_driver_team"):
                record = {
                    "target": "LAP_TIME",
                    "formulation": formulation.value,
                    "model_family": family.value,
                    "candidate_id": candidate_id,
                    "feature_set_id": feature_set_id,
                    "parameters": parameters,
                    "fold_count": 2,
                    "eligible_targets": 20,
                    "scored_predictions": 20,
                    "coverage_rate": 1.0,
                    "mean_absolute_error_seconds": 0.2,
                    "root_mean_squared_error_seconds": 0.25,
                    "median_absolute_error_seconds": 0.2,
                    "p90_absolute_error_seconds": 0.3,
                    "mean_signed_error_seconds": 0.0,
                    "common_rows": 20,
                    "common_mean_absolute_error_seconds": 0.2,
                    "common_root_mean_squared_error_seconds": 0.25,
                    "common_median_absolute_error_seconds": 0.2,
                    "common_p90_absolute_error_seconds": 0.3,
                    "common_mean_signed_error_seconds": 0.0,
                    "baseline_common_mean_absolute_error_seconds": 0.5,
                }
                pooled_rows.append(record)
    selection_rows = []
    for formulation in PredictionFormulation:
        for ordinal, (family, candidate_id, parameters) in enumerate(candidates):
            selection_rows.append(
                {
                    "formulation": formulation.value,
                    "model_family": family.value,
                    "candidate_id": candidate_id,
                    "parameters": parameters,
                    "full_mean_absolute_error_seconds": 0.2 + ordinal / 100,
                    "full_common_mean_absolute_error_seconds": 0.2,
                    "ablated_common_mean_absolute_error_seconds": 0.25,
                    "baseline_common_mean_absolute_error_seconds": 0.5,
                    "coverage_rate": 1.0,
                    "fold_count": 2,
                    "beats_frozen_baseline": True,
                    "beats_comparable_baseline": True,
                    "ablation_passes": True,
                    "minimum_coverage_passes": True,
                    "both_folds_present": True,
                    "meets_selection_contract": True,
                    "selected": (
                        formulation == PredictionFormulation.DIRECT_ABSOLUTE
                        and ordinal == 0
                    ),
                }
            )
    family, candidate_id, parameters = candidates[0]
    return TemporalSelectionReport(
        fold_metrics=pd.DataFrame.from_records(
            fold_rows,
            columns=FOLD_METRIC_COLUMNS,
        ),
        pooled_metrics=pd.DataFrame.from_records(
            pooled_rows,
            columns=POOLED_METRIC_COLUMNS,
        ),
        selection=pd.DataFrame.from_records(
            selection_rows,
            columns=SELECTION_COLUMNS,
        ),
        selected_candidate=SelectedPrimaryCandidate(
            formulation=PredictionFormulation.DIRECT_ABSOLUTE,
            family=family,
            candidate_id=candidate_id,
            parameters=parameters,
            pooled_mean_absolute_error_seconds=0.2,
            common_mean_absolute_error_seconds=0.2,
            ablated_common_mean_absolute_error_seconds=0.25,
            coverage_rate=1.0,
        ),
    )


def _diagnostics() -> SelectedModelDiagnostics:
    """Build one valid record for every diagnostic table."""
    return SelectedModelDiagnostics(
        slice_metrics=pd.DataFrame.from_records(
            [
                {
                    "target": "LAP_TIME",
                    "fold_id": "development_fold_1",
                    "feature_set_id": "full",
                    "dimension": "event_name",
                    "value": "Test GP",
                    "rows": 10,
                    "mean_absolute_error_seconds": 0.2,
                    "root_mean_squared_error_seconds": 0.25,
                    "median_absolute_error_seconds": 0.2,
                    "p90_absolute_error_seconds": 0.3,
                    "mean_signed_error_seconds": 0.0,
                }
            ],
            columns=SLICE_METRIC_COLUMNS,
        ),
        degradation_curve=pd.DataFrame.from_records(
            [
                {
                    "fold_id": "development_fold_1",
                    "current_compound": "MEDIUM",
                    "tyre_age_band": "USED_6_15",
                    "rows": 10,
                    "mean_tyre_age_laps": 10.0,
                    "mean_observed_lap_time_delta_seconds": 0.1,
                    "mean_predicted_lap_time_delta_seconds": 0.08,
                    "mean_absolute_error_seconds": 0.2,
                    "mean_signed_error_seconds": -0.02,
                }
            ],
            columns=DEGRADATION_CURVE_COLUMNS,
        ),
        identity_dependence=pd.DataFrame.from_records(
            [
                {
                    "feature_set_id": "full",
                    "rows": 20,
                    "mean_absolute_error_seconds": 0.2,
                    "root_mean_squared_error_seconds": 0.25,
                    "median_absolute_error_seconds": 0.2,
                    "p90_absolute_error_seconds": 0.3,
                    "mean_signed_error_seconds": 0.0,
                    "mae_increase_from_full_seconds": 0.0,
                }
            ],
            columns=IDENTITY_DIAGNOSTIC_COLUMNS,
        ),
    )


def _provenance() -> ModelEvaluationProvenance:
    """Build complete synthetic final-audit provenance."""
    selected = _selection_report().selected_candidate
    assert selected is not None
    return ModelEvaluationProvenance(
        model_contract_version=MODEL_CONTRACT_VERSION,
        dataset_contract_version="1.0",
        dataset_build_identifier="unit-test-build",
        development_sessions=68,
        contributing_training_sessions=67,
        primary_target_rows=52483,
        auxiliary_target_rows=50000,
        protected_evaluation_rows=0,
        selected_formulation=selected.formulation,
        selected_family=selected.family,
        selected_candidate_id=selected.candidate_id,
        selected_parameters=selected.parameters,
        final_model_artifact_id="phase-6-final-audit-lap-time",
        execution_device="cpu",
        random_seed=42,
        dependency_versions=(
            ("joblib", "1"),
            ("numpy", "2"),
            ("pandas", "2"),
            ("python", "3"),
            ("scikit-learn", "1"),
            ("xgboost", "3"),
        ),
        evaluation_duration_seconds=2.0,
        final_fit_duration_seconds=1.0,
    )


def test_report_round_trip_verifies_every_artifact(tmp_path) -> None:
    """Store and read back exact selection and diagnostic evidence."""
    paths = ModelReportPaths(tmp_path, "phase-6-audit")

    manifest = write_model_report(
        paths=paths,
        selection=_selection_report(),
        diagnostics=_diagnostics(),
        provenance=_provenance(),
    )
    verification = verify_model_report(paths)

    assert manifest["format_version"] == MODEL_EVALUATION_FORMAT_VERSION
    assert set(manifest["artifacts"]) == set(MODEL_EVALUATION_FILES)
    assert verification.valid is True
    assert verification.artifact_count == 7
    assert verification.issues == ()


def test_report_hash_tampering_is_detected(tmp_path) -> None:
    """Fail closed when a metric table changes after publication."""
    paths = ModelReportPaths(tmp_path, "tampered")
    write_model_report(
        paths=paths,
        selection=_selection_report(),
        diagnostics=_diagnostics(),
        provenance=_provenance(),
    )
    with (paths.root / "selection.parquet").open("ab") as stream:
        stream.write(b"tampered")

    verification = verify_model_report(paths)

    assert verification.valid is False
    assert any("selection.parquet" in issue for issue in verification.issues)


def test_report_is_immutable(tmp_path) -> None:
    """Reject silent replacement of an existing run identity."""
    paths = ModelReportPaths(tmp_path, "immutable")
    arguments = {
        "paths": paths,
        "selection": _selection_report(),
        "diagnostics": _diagnostics(),
        "provenance": _provenance(),
    }
    write_model_report(**arguments)

    with pytest.raises(ModelReportError, match="already exists"):
        write_model_report(**arguments)


@pytest.mark.parametrize("run_id", ("", ".", "../escape", "a/b"))
def test_report_identity_rejects_unsafe_paths(tmp_path, run_id: str) -> None:
    """Keep generated reports inside their canonical artifact root."""
    with pytest.raises(ModelReportError, match="safe path segment"):
        ModelReportPaths(tmp_path, run_id)


def test_provenance_rejects_protected_evaluation_rows() -> None:
    """Record the Phase 6 zero-2025 boundary as executable evidence."""
    values = _provenance()
    with pytest.raises(ModelReportError, match="protected"):
        ModelEvaluationProvenance(
            **{
                name: getattr(values, name)
                for name in values.__dataclass_fields__
                if name != "protected_evaluation_rows"
            },
            protected_evaluation_rows=1,
        )


def test_report_rejects_selection_provenance_mismatch(tmp_path) -> None:
    """Require the stored winner to match the final model identity."""
    provenance = _provenance()
    invalid = ModelEvaluationProvenance(
        **{
            name: getattr(provenance, name)
            for name in provenance.__dataclass_fields__
            if name not in {"selected_candidate_id", "selected_parameters"}
        },
        selected_candidate_id="ridge_02",
        selected_parameters=json.dumps(
            MODEL_SPECS[0].parameter_grid[1],
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    with pytest.raises(ModelReportError, match="candidate differ"):
        write_model_report(
            paths=ModelReportPaths(tmp_path, "mismatch"),
            selection=_selection_report(),
            diagnostics=_diagnostics(),
            provenance=invalid,
        )
