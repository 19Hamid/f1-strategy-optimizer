"""Tests for browser-ready Phase 6 model-review visuals."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from app.ml.visualization import (
    MODEL_REVIEW_CHART_FILES,
    MODEL_REVIEW_PAYLOAD_FILES,
    ModelReviewData,
    ModelReviewError,
    ModelReviewPaths,
    verify_model_review,
    write_model_review,
)


def _review_data() -> ModelReviewData:
    selection = pd.DataFrame.from_records(
        [
            {
                "formulation": "RESIDUAL_HYBRID",
                "model_family": "xgboost",
                "candidate_id": "xgboost_02",
                "full_mean_absolute_error_seconds": 0.410601,
                "full_common_mean_absolute_error_seconds": 0.392725,
                "ablated_common_mean_absolute_error_seconds": 0.392716,
                "baseline_common_mean_absolute_error_seconds": 0.410049,
                "coverage_rate": 1.0,
                "meets_selection_contract": True,
                "selected": True,
            },
            {
                "formulation": "DIRECT_ABSOLUTE",
                "model_family": "random_forest",
                "candidate_id": "random_forest_02",
                "full_mean_absolute_error_seconds": 0.430772,
                "full_common_mean_absolute_error_seconds": 0.413153,
                "ablated_common_mean_absolute_error_seconds": 0.412521,
                "baseline_common_mean_absolute_error_seconds": 0.410049,
                "coverage_rate": 1.0,
                "meets_selection_contract": False,
                "selected": False,
            },
        ]
    )
    fold_metrics = pd.DataFrame.from_records(
        [
            {
                "fold_id": "development_fold_1",
                "formulation": "RESIDUAL_HYBRID",
                "model_family": "xgboost",
                "candidate_id": "xgboost_02",
                "feature_set_id": "full",
                "common_mean_absolute_error_seconds": 0.39,
                "baseline_common_mean_absolute_error_seconds": 0.41,
            },
            {
                "fold_id": "development_fold_2",
                "formulation": "RESIDUAL_HYBRID",
                "model_family": "xgboost",
                "candidate_id": "xgboost_02",
                "feature_set_id": "full",
                "common_mean_absolute_error_seconds": 0.395,
                "baseline_common_mean_absolute_error_seconds": 0.4101,
            },
        ]
    )
    slice_metrics = pd.DataFrame.from_records(
        [
            {
                "feature_set_id": "full",
                "dimension": "current_compound",
                "value": "HARD",
                "rows": 100,
                "mean_absolute_error_seconds": 0.38,
            },
            {
                "feature_set_id": "full",
                "dimension": "current_compound",
                "value": "MEDIUM",
                "rows": 200,
                "mean_absolute_error_seconds": 0.40,
            },
            {
                "feature_set_id": "full",
                "dimension": "session_id",
                "value": "2023-01-R",
                "rows": 150,
                "mean_absolute_error_seconds": 0.44,
            },
            {
                "feature_set_id": "full",
                "dimension": "session_id",
                "value": "2024-01-R",
                "rows": 150,
                "mean_absolute_error_seconds": 0.36,
            },
        ]
    )
    degradation_curve = pd.DataFrame.from_records(
        [
            {
                "current_compound": "HARD",
                "tyre_age_band": "NEW_0_5",
                "rows": 100,
                "mean_observed_lap_time_delta_seconds": -0.1,
                "mean_predicted_lap_time_delta_seconds": -0.08,
            },
            {
                "current_compound": "HARD",
                "tyre_age_band": "USED_6_15",
                "rows": 80,
                "mean_observed_lap_time_delta_seconds": 0.05,
                "mean_predicted_lap_time_delta_seconds": 0.04,
            },
            {
                "current_compound": "HARD",
                "tyre_age_band": "OLD_16_PLUS",
                "rows": 40,
                "mean_observed_lap_time_delta_seconds": 0.2,
                "mean_predicted_lap_time_delta_seconds": 0.18,
            },
        ]
    )
    identity_dependence = pd.DataFrame.from_records(
        [
            {
                "feature_set_id": "full",
                "rows": 300,
                "mean_absolute_error_seconds": 0.392725,
            },
            {
                "feature_set_id": "without_driver_team",
                "rows": 300,
                "mean_absolute_error_seconds": 0.392716,
            },
        ]
    )
    return ModelReviewData(
        selection=selection,
        fold_metrics=fold_metrics,
        slice_metrics=slice_metrics,
        degradation_curve=degradation_curve,
        identity_dependence=identity_dependence,
        provenance={
            "model_contract_version": "1.2",
            "selected_candidate_id": "xgboost_02",
            "execution_device": "cuda",
            "protected_evaluation_rows": 0,
        },
    )


def test_write_model_review_creates_browser_dashboard_and_svg_charts(
    tmp_path: Path,
) -> None:
    """Render complete human-readable evidence outside immutable sources."""
    paths = ModelReviewPaths(tmp_path, "phase-6-final-audit")

    result = write_model_review(paths=paths, data=_review_data())

    assert result == paths
    assert paths.index.is_file()
    assert set(item.name for item in paths.root.iterdir()) == {
        *MODEL_REVIEW_PAYLOAD_FILES,
        "manifest.json",
    }
    html = paths.index.read_text(encoding="utf-8")
    assert "Phase 6 <em>Model Review</em>" in html
    assert "xgboost_02" in html
    assert "4.22%" in html
    assert "Protected 2025" not in html
    for name in MODEL_REVIEW_CHART_FILES:
        chart = (paths.root / name).read_text(encoding="utf-8")
        assert chart.startswith("<?xml")
        assert "<svg" in chart


def test_generated_review_passes_hash_and_file_verification(tmp_path: Path) -> None:
    """Protect generated evidence from accidental mutation."""
    paths = ModelReviewPaths(tmp_path, "review")
    write_model_review(paths=paths, data=_review_data())

    verification = verify_model_review(paths)

    assert verification.valid
    assert verification.artifact_count == len(MODEL_REVIEW_PAYLOAD_FILES)
    assert verification.issues == ()


def test_review_verification_detects_changed_chart(tmp_path: Path) -> None:
    """Reject a graph that no longer matches its generated manifest."""
    paths = ModelReviewPaths(tmp_path, "review")
    write_model_review(paths=paths, data=_review_data())
    chart = paths.root / MODEL_REVIEW_CHART_FILES[0]
    chart.write_text("changed", encoding="utf-8")

    verification = verify_model_review(paths)

    assert not verification.valid
    assert any("mismatch" in issue for issue in verification.issues)


def test_existing_review_requires_explicit_replace(tmp_path: Path) -> None:
    """Avoid silently overwriting a review that the user may be inspecting."""
    paths = ModelReviewPaths(tmp_path, "review")
    write_model_review(paths=paths, data=_review_data())

    with pytest.raises(ModelReviewError, match="already exists"):
        write_model_review(paths=paths, data=_review_data())

    replaced = write_model_review(paths=paths, data=_review_data(), replace=True)
    assert verify_model_review(replaced).valid


@pytest.mark.parametrize("run_id", ["", "..", "nested/run", "nested\\run"])
def test_review_paths_reject_unsafe_run_ids(tmp_path: Path, run_id: str) -> None:
    """Keep generated output inside its dedicated artifact root."""
    with pytest.raises(ModelReviewError, match="safe path segment"):
        ModelReviewPaths(tmp_path, run_id)


def test_review_data_rejects_incomplete_selection() -> None:
    """Fail before rendering when required audit values are unavailable."""
    data = _review_data()
    incomplete = data.selection.drop(columns="coverage_rate")

    with pytest.raises(ModelReviewError, match="coverage_rate"):
        ModelReviewData(
            selection=incomplete,
            fold_metrics=data.fold_metrics,
            slice_metrics=data.slice_metrics,
            degradation_curve=data.degradation_curve,
            identity_dependence=data.identity_dependence,
            provenance=data.provenance,
        )


def test_manifest_records_contract_and_exact_payloads(tmp_path: Path) -> None:
    """Expose reproducible review identity in a readable JSON document."""
    paths = ModelReviewPaths(tmp_path, "review")
    write_model_review(paths=paths, data=_review_data())

    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))

    assert manifest["format_version"] == "1.0"
    assert manifest["source_model_contract_version"] == "1.2"
    assert set(manifest["artifacts"]) == set(MODEL_REVIEW_PAYLOAD_FILES)
