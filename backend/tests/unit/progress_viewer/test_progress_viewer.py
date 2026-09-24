"""Tests for the artifact-backed development progress viewer."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from app.ml.artifacts import ModelArtifactVerificationReport
from app.ml.reports import ModelReportPaths, ModelReportVerification
from app.progress_viewer import builder
from app.progress_viewer.builder import (
    ProgressViewerError,
    ProgressViewerPaths,
    build_progress_viewer,
)
from app.progress_viewer.template import render_progress_viewer
from app.simulation.storage import (
    SimulationReportPaths,
    SimulationReportVerification,
)


def _write_inputs(tmp_path: Path) -> ProgressViewerPaths:
    """Write the minimum tables consumed after integrity verification."""
    artifacts_root = tmp_path / "artifacts"
    model_root = ModelReportPaths(artifacts_root, "model-run").root
    simulation_root = SimulationReportPaths(artifacts_root, "simulation-run").root
    model_root.mkdir(parents=True)
    simulation_root.mkdir(parents=True)
    (model_root / "provenance.json").write_text(
        json.dumps(
            {
                "development_sessions": 68,
                "contributing_training_sessions": 66,
                "primary_target_rows": 52_483,
                "auxiliary_target_rows": 50_913,
                "execution_device": "cuda",
                "protected_evaluation_rows": 0,
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame.from_records(
        [
            {
                "candidate_id": "xgboost_02",
                "model_family": "XGBOOST",
                "formulation": "RESIDUAL_HYBRID",
                "parameters": '{"max_depth":4}',
                "full_mean_absolute_error_seconds": 0.410601,
                "full_common_mean_absolute_error_seconds": 0.392725,
                "ablated_common_mean_absolute_error_seconds": 0.392716,
                "baseline_common_mean_absolute_error_seconds": 0.410049,
                "coverage_rate": 1.0,
                "meets_selection_contract": True,
                "selected": True,
            },
            {
                "candidate_id": "ridge_01",
                "model_family": "RIDGE",
                "formulation": "DIRECT_ABSOLUTE",
                "parameters": '{"alpha":1}',
                "full_mean_absolute_error_seconds": 0.7,
                "full_common_mean_absolute_error_seconds": 0.69,
                "ablated_common_mean_absolute_error_seconds": 0.7,
                "baseline_common_mean_absolute_error_seconds": 0.410049,
                "coverage_rate": 1.0,
                "meets_selection_contract": False,
                "selected": False,
            },
        ]
    ).to_parquet(model_root / "selection.parquet", index=False)
    pd.DataFrame.from_records(
        [
            {
                "current_compound": "MEDIUM",
                "tyre_age_band": "NEW_0_5",
                "rows": 10,
                "mean_tyre_age_laps": 3.0,
                "mean_observed_lap_time_delta_seconds": 0.1,
                "mean_predicted_lap_time_delta_seconds": 0.08,
                "mean_absolute_error_seconds": 0.2,
            },
            {
                "current_compound": "MEDIUM",
                "tyre_age_band": "OLD_16_PLUS",
                "rows": 8,
                "mean_tyre_age_laps": 20.0,
                "mean_observed_lap_time_delta_seconds": 0.4,
                "mean_predicted_lap_time_delta_seconds": 0.36,
                "mean_absolute_error_seconds": 0.3,
            },
        ]
    ).to_parquet(model_root / "degradation_curve.parquet", index=False)
    pd.DataFrame.from_records(
        [
            {
                "dimension": "event_name",
                "feature_set_id": "full",
                "value": "Test Grand Prix",
                "rows": 10,
                "mean_absolute_error_seconds": 0.4,
            }
        ]
    ).to_parquet(model_root / "slice_metrics.parquet", index=False)

    (simulation_root / "provenance.json").write_text(
        json.dumps(
            {
                "development_sessions": 1,
                "protected_evaluation_rows": 0,
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame.from_records(
        [
            _metric("OVERALL_LAP", "ALL", 1.1),
            _metric("OVERALL_REMAINING", "ALL", 4.5),
            _metric("HORIZON_REMAINING", "SHORT_1_TO_10_LAPS", 2.0),
            _metric("EVENT_REMAINING", "Test Grand Prix", 4.5),
        ]
    ).to_parquet(simulation_root / "metrics.parquet", index=False)
    pd.DataFrame.from_records(
        [
            {
                "replay_id": "2024-test-driver-5",
                "season": 2024,
                "event_name": "Test Grand Prix",
                "driver": "AAA",
                "team": "Test Team",
                "start_lap": 50,
                "total_laps": 50,
                "remaining_laps": 1,
                "horizon": "SHORT_1_TO_10_LAPS",
                "initial_compound": "MEDIUM",
                "planned_stops_json": "[]",
                "predicted_remaining_time_seconds": 90.0,
                "observed_remaining_time_seconds": 91.0,
                "absolute_remaining_time_error_seconds": 1.0,
            }
        ]
    ).to_parquet(simulation_root / "replays.parquet", index=False)
    pd.DataFrame.from_records(
        [
            {
                "replay_id": "2024-test-driver-5",
                "lap_number": 50,
                "predicted_total_lap_time_seconds": 90.0,
                "observed_total_lap_time_seconds": 91.0,
                "cumulative_predicted_time_seconds": 90.0,
                "cumulative_observed_time_seconds": 91.0,
                "pit_stop_after_lap": False,
                "start_compound": "MEDIUM",
                "start_tyre_age_laps": 10,
            }
        ]
    ).to_parquet(simulation_root / "trajectories.parquet", index=False)

    roadmap = tmp_path / "ROADMAP.md"
    roadmap.write_text(
        """# Roadmap

## Development roadmap

| Phase | Weight | Status | Main result |
|---|---:|---|---|
| 0. Completed work | 77% | Completed | Verified evidence |
| 1. Optimizer | 9% | In progress (75%) | Stable decision bounds |
| 2. Remaining work | 14% | Planned | Uncertainty, API and UI |
""",
        encoding="utf-8",
    )
    return ProgressViewerPaths(
        project_root=tmp_path,
        artifacts_root=artifacts_root,
        output_directory=artifacts_root / "progress_viewer",
        roadmap=roadmap,
        model_run_id="model-run",
        model_artifact_id="model-artifact",
        simulation_run_id="simulation-run",
    )


def _metric(scope: str, value: str, mae: float) -> dict[str, object]:
    return {
        "scope": scope,
        "value": value,
        "replays": 1,
        "laps": 1,
        "mean_absolute_error_seconds": mae,
        "p90_absolute_error_seconds": mae,
        "mean_signed_error_seconds": -0.25,
    }


def _accept_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        builder,
        "verify_model_report",
        lambda _: ModelReportVerification(True, 7, ()),
    )
    monkeypatch.setattr(
        builder,
        "verify_model_artifact",
        lambda _: ModelArtifactVerificationReport(True, 3, 128, ()),
    )
    monkeypatch.setattr(
        builder,
        "verify_simulation_report",
        lambda _: SimulationReportVerification(True, 4, ()),
    )


def test_build_writes_self_contained_verified_viewer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _write_inputs(tmp_path)
    _accept_verification(monkeypatch)

    output = build_progress_viewer(paths)

    document = output.read_text(encoding="utf-8")
    assert output == paths.output_file
    assert "Actual model evidence" in document
    assert '"progress_percent":83.8' in document
    assert '"status_class":"in-progress"' in document
    assert '"candidate_id":"xgboost_02"' in document
    assert '"replay_id":"2024-test-driver-5"' in document
    assert "https://" not in document


def test_build_rejects_invalid_immutable_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _write_inputs(tmp_path)
    _accept_verification(monkeypatch)
    monkeypatch.setattr(
        builder,
        "verify_simulation_report",
        lambda _: SimulationReportVerification(False, 0, ("hash mismatch",)),
    )

    with pytest.raises(ProgressViewerError, match="Phase 7 report: hash mismatch"):
        build_progress_viewer(paths)

    assert not paths.output_file.exists()


def test_render_escapes_script_termination() -> None:
    document = render_progress_viewer({"event": "</script><script>alert(1)</script>"})

    assert "</script><script>alert(1)</script>" not in document
    assert "\\u003c/script\\u003e" in document


@pytest.mark.parametrize("unsafe", ("", ".", "..", "nested/run", "nested\\run"))
def test_paths_reject_unsafe_artifact_identifiers(
    tmp_path: Path,
    unsafe: str,
) -> None:
    with pytest.raises(ProgressViewerError, match="model_run_id"):
        ProgressViewerPaths(
            project_root=tmp_path,
            artifacts_root=tmp_path / "artifacts",
            output_directory=tmp_path / "output",
            roadmap=tmp_path / "ROADMAP.md",
            model_run_id=unsafe,
        )
