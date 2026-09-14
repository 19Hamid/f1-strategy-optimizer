"""Tests for reproducible Phase 5 reporting and artifact storage."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from app.baselines.contracts import BaselineId, BaselineTask
from app.baselines.evaluation import (
    FoldBaselineEvaluation,
    TemporalEvaluationReport,
)
from app.baselines.metrics import (
    PredictionCoverage,
    ScoredPredictions,
    regression_metrics,
)
from app.baselines.reporting import (
    BaselineEvaluationTables,
    BaselineExperimentProvenance,
    BaselineReportingError,
    build_evaluation_tables,
    provenance_document,
)
from app.baselines.storage import (
    BaselineReportPaths,
    BaselineStorageError,
    verify_baseline_report,
    write_baseline_report,
)

_LAP_IDS = (
    BaselineId.PREVIOUS_VALID_LAP,
    BaselineId.ROLLING_MEDIAN_3,
    BaselineId.STINT_LINEAR_TREND,
    BaselineId.CIRCUIT_COMPOUND_MEDIAN,
)
_PIT_IDS = (
    BaselineId.PIT_GLOBAL_MEDIAN,
    BaselineId.PIT_CIRCUIT_MEDIAN,
    BaselineId.PIT_CIRCUIT_TRANSITION_MEDIAN,
)


def _provenance() -> BaselineExperimentProvenance:
    return BaselineExperimentProvenance(
        dataset_contract_version="1.0",
        dataset_build_identifier="development-build",
        execution_time_seconds=1.25,
        dependency_versions={"numpy": "2", "pandas": "2", "pyarrow": "25"},
    )


def _scored(row_id: str, target: float, prediction: float) -> ScoredPredictions:
    signed = prediction - target
    rows = pd.DataFrame(
        {
            "row_id": [row_id],
            "target_seconds": [target],
            "prediction_seconds": [prediction],
            "signed_error_seconds": [signed],
            "absolute_error_seconds": [abs(signed)],
            "squared_error_seconds": [signed**2],
            "prediction_source": ["synthetic"],
        }
    )
    return ScoredPredictions(
        metrics=regression_metrics(
            rows["target_seconds"],
            rows["prediction_seconds"],
        ),
        coverage=PredictionCoverage(
            eligible_targets=1,
            available_predictions=1,
            scored_predictions=1,
        ),
        rows=rows,
    )


def _report() -> TemporalEvaluationReport:
    evaluations = []
    for fold_id in ("development_fold_1", "development_fold_2"):
        evaluations.extend(
            FoldBaselineEvaluation(
                fold_id=fold_id,
                task=BaselineTask.LAP_TIME,
                baseline_id=baseline_id,
                training_sessions=("2022-01-R",),
                validation_sessions=("2023-01-R",),
                fallback_counts={"synthetic": 1},
                scored=_scored("d23", 91.0, 90.0),
            )
            for baseline_id in _LAP_IDS
        )
        evaluations.extend(
            FoldBaselineEvaluation(
                fold_id=fold_id,
                task=BaselineTask.PIT_DURATION,
                baseline_id=baseline_id,
                training_sessions=("2022-01-R",),
                validation_sessions=("2023-01-R",),
                fallback_counts={"synthetic": 1},
                scored=_scored("p23", 25.0, 24.0),
            )
            for baseline_id in _PIT_IDS
        )
    return TemporalEvaluationReport(evaluations=tuple(evaluations))


def _lap_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "decision_id": ["d23"],
            "session_id": ["2023-01-R"],
            "event_name": ["Bahrain GP"],
            "current_compound": ["MEDIUM"],
            "tyre_age_band": ["MID"],
            "driver": ["HAM"],
            "team": ["Team"],
            "race_progress_band": ["MIDDLE"],
        }
    )


def _pit_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "pit_event_id": ["p23"],
            "session_id": ["2023-01-R"],
            "event_name": ["Bahrain GP"],
            "season": [2023],
            "compound_before": ["SOFT"],
            "compound_after": ["HARD"],
        }
    )


def _tables() -> BaselineEvaluationTables:
    return build_evaluation_tables(
        report=_report(),
        lap_rows=_lap_rows(),
        pit_rows=_pit_rows(),
        provenance=_provenance(),
    )


def test_reporting_builds_exact_aggregate_and_required_slices() -> None:
    tables = _tables()
    assert len(tables.summary) == 14
    assert set(tables.summary["task"]) == {"LAP_TIME", "PIT_DURATION"}
    assert tables.summary["coverage_rate"].eq(1.0).all()
    assert tables.summary["training_sessions"].str.startswith("[").all()
    assert tables.summary["validation_sessions"].str.startswith("[").all()
    assert tables.summary["fallback_counts"].str.startswith("{").all()
    assert set(tables.summary["target_name"]) == {
        "lap_time_target_seconds",
        "pit_duration_target_seconds",
    }
    assert set(tables.summary["target_eligibility_rule"]) == {
        (
            "is_decision_eligible == true AND "
            "is_lap_time_target_eligible == true"
        ),
        "is_pit_duration_target_eligible == true",
    }
    assert tables.summary["parameters"].eq("{}").all()
    lap_dimensions = set(
        tables.slices.loc[
            tables.slices["task"].eq("LAP_TIME"),
            "dimension",
        ]
    )
    pit_dimensions = set(
        tables.slices.loc[
            tables.slices["task"].eq("PIT_DURATION"),
            "dimension",
        ]
    )
    assert lap_dimensions == {
        "session_id",
        "event_name",
        "current_compound",
        "tyre_age_band",
        "driver",
        "team",
        "race_progress_band",
    }
    assert pit_dimensions == {
        "session_id",
        "event_name",
        "season",
        "compound_transition",
    }
    assert set(
        tables.slices.loc[
            tables.slices["dimension"].eq("compound_transition"),
            "value",
        ]
    ) == {"SOFT->HARD"}


def test_reporting_preserves_row_level_residual_evidence() -> None:
    tables = _tables()
    assert len(tables.predictions) == 14
    assert tables.predictions["absolute_error_seconds"].eq(1.0).all()
    assert tables.predictions.loc[
        :,
        ["fold_id", "task", "baseline_id", "row_id"],
    ].duplicated().sum() == 0


def test_reporting_rejects_missing_required_slice_dimension() -> None:
    with pytest.raises(
        BaselineReportingError,
        match="missing required slice dimension",
    ):
        build_evaluation_tables(
            report=_report(),
            lap_rows=_lap_rows().drop(columns="team"),
            pit_rows=_pit_rows(),
            provenance=_provenance(),
        )


def test_provenance_document_reconciles_table_counts() -> None:
    document = provenance_document(_tables())
    assert document["baseline_contract_version"] == "1.0"
    assert document["dataset_build_identifier"] == "development-build"
    assert document["summary_rows"] == 14
    assert document["prediction_rows"] == 14


@pytest.mark.parametrize("run_id", ["", ".", "..", "../escape", "a/b", "a\\b"])
def test_paths_reject_unsafe_run_identity(tmp_path, run_id: str) -> None:
    with pytest.raises(BaselineStorageError, match="safe path segment"):
        BaselineReportPaths(tmp_path, run_id)


def test_storage_writes_and_verifies_immutable_report(tmp_path) -> None:
    paths = BaselineReportPaths(tmp_path, "phase-5-test")
    manifest = write_baseline_report(paths=paths, tables=_tables())
    assert manifest["run_id"] == "phase-5-test"
    assert set(manifest["artifacts"]) == {
        "summary.parquet",
        "slices.parquet",
        "predictions.parquet",
        "provenance.json",
    }
    verification = verify_baseline_report(paths)
    assert verification.valid
    assert verification.artifact_count == 4
    assert verification.issues == ()


def test_storage_refuses_to_overwrite_completed_run(tmp_path) -> None:
    paths = BaselineReportPaths(tmp_path, "phase-5-test")
    write_baseline_report(paths=paths, tables=_tables())
    with pytest.raises(BaselineStorageError, match="already exists"):
        write_baseline_report(paths=paths, tables=_tables())


def test_verification_detects_corrupted_artifact(tmp_path) -> None:
    paths = BaselineReportPaths(tmp_path, "phase-5-test")
    write_baseline_report(paths=paths, tables=_tables())
    with (paths.root / "provenance.json").open("a", encoding="utf-8") as stream:
        stream.write("corruption")
    verification = verify_baseline_report(paths)
    assert not verification.valid
    assert any("mismatch: provenance.json" in issue for issue in verification.issues)
    with pytest.raises(BaselineStorageError, match="verification failed"):
        verification.raise_for_errors()


def test_provenance_rejects_negative_execution_time() -> None:
    with pytest.raises(BaselineReportingError, match="non-negative"):
        replace(_provenance(), execution_time_seconds=-1.0)
