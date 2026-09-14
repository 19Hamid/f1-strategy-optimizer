"""Tests for the real-data Phase 5 audit orchestration."""

from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest

from app.baselines import audit as baseline_audit
from app.baselines.audit import (
    BaselineAuditError,
    SelectedBaseline,
)
from app.baselines.cli import main
from app.baselines.storage import (
    BaselineReportPaths,
    BaselineVerificationReport,
)
from app.baselines.contracts import BaselineTask


def test_reporting_bands_are_deterministic_and_not_model_features() -> None:
    rows = pd.DataFrame(
        {
            "session_id": ["race"] * 4,
            "decision_lap": [1, 20, 40, 60],
            "tyre_age_laps": [1, 6, 16, pd.NA],
        }
    )
    result = baseline_audit._add_reporting_bands(rows)
    assert result["tyre_age_band"].tolist() == [
        "NEW_0_5",
        "USED_6_15",
        "OLD_16_PLUS",
        pd.NA,
    ]
    assert result["race_progress_band"].tolist() == [
        "EARLY",
        "EARLY",
        "MIDDLE",
        "LATE",
    ]
    assert "tyre_age_band" not in rows
    assert "race_progress_band" not in rows


def test_decisions_join_only_target_fields() -> None:
    decisions = pd.DataFrame(
        {
            "decision_id": ["d1"],
            "is_decision_eligible": [True],
        }
    )
    labels = pd.DataFrame(
        {
            "decision_id": ["d1"],
            "is_lap_time_target_eligible": [True],
            "lap_time_target_seconds": [90.0],
            "historical_action": ["PIT_NOW"],
        }
    )
    joined = baseline_audit._join_decisions_and_targets(decisions, labels)
    assert joined["lap_time_target_seconds"].tolist() == [90.0]
    assert "historical_action" not in joined


def test_decision_join_rejects_missing_label() -> None:
    decisions = pd.DataFrame({"decision_id": ["d1", "d2"]})
    labels = pd.DataFrame(
        {
            "decision_id": ["d1"],
            "is_lap_time_target_eligible": [True],
            "lap_time_target_seconds": [90.0],
        }
    )
    with pytest.raises(BaselineAuditError, match="do not reconcile"):
        baseline_audit._join_decisions_and_targets(decisions, labels)


def test_selection_uses_pooled_mae_with_coverage_tiebreak() -> None:
    predictions = pd.DataFrame(
        {
            "task": ["LAP_TIME"] * 5 + ["PIT_DURATION"] * 2,
            "baseline_id": ["a", "a", "b", "b", "b", "c", "d"],
            "absolute_error_seconds": [1.0, 3.0, 1.0, 1.0, 4.0, 2.0, 3.0],
        }
    )
    summary = pd.DataFrame(
        {
            "task": ["LAP_TIME", "LAP_TIME", "PIT_DURATION", "PIT_DURATION"],
            "baseline_id": ["a", "b", "c", "d"],
            "eligible_targets": [4, 4, 1, 1],
        }
    )
    selected = baseline_audit._select_baselines(predictions, summary)
    assert selected == (
        SelectedBaseline(
            task=BaselineTask.LAP_TIME,
            baseline_id="a",
            pooled_rows=2,
            pooled_mean_absolute_error_seconds=2.0,
            coverage_rate=0.5,
        ),
        SelectedBaseline(
            task=BaselineTask.PIT_DURATION,
            baseline_id="c",
            pooled_rows=1,
            pooled_mean_absolute_error_seconds=2.0,
            coverage_rate=1.0,
        ),
    )


def test_cli_audit_prints_real_data_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "datasets" / "f1_strategy" / (
        "dataset_contract_version=1.0"
    ) / "catalog.parquet"
    catalog.parent.mkdir(parents=True)
    catalog.write_bytes(b"catalog")
    selected = (
        SelectedBaseline(
            task=BaselineTask.LAP_TIME,
            baseline_id="rolling_median_3",
            pooled_rows=100,
            pooled_mean_absolute_error_seconds=1.25,
            coverage_rate=0.99,
        ),
        SelectedBaseline(
            task=BaselineTask.PIT_DURATION,
            baseline_id="pit_global_median",
            pooled_rows=20,
            pooled_mean_absolute_error_seconds=2.5,
            coverage_rate=1.0,
        ),
    )
    result = Mock(
        development_sessions=68,
        lap_target_rows=52483,
        pit_target_rows=1465,
        report_paths=BaselineReportPaths(tmp_path, "audit"),
        selected_baselines=selected,
    )
    monkeypatch.setattr(
        "app.baselines.cli.sha256_file",
        lambda _: "catalog-sha",
    )
    runner = Mock(return_value=result)
    monkeypatch.setattr(
        "app.baselines.cli.run_development_baseline_audit",
        runner,
    )
    assert main(
        [
            "audit",
            "--datasets-root",
            str(tmp_path / "datasets"),
            "--artifacts-root",
            str(tmp_path),
            "--run-id",
            "audit",
        ]
    ) == 0
    output = capsys.readouterr().out
    assert "Development sessions: 68" in output
    assert "Eligible lap targets: 52483" in output
    assert "Protected 2025 rows: 0" in output
    assert "rolling_median_3" in output
    assert runner.call_args.kwargs["dataset_build_identifier"] == "catalog-sha"


def test_cli_verify_returns_failure_for_invalid_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "app.baselines.cli.verify_baseline_report",
        lambda _: BaselineVerificationReport(
            valid=False,
            artifact_count=3,
            issues=("hash mismatch",),
        ),
    )
    assert main(
        [
            "verify",
            "--artifacts-root",
            str(tmp_path),
            "--run-id",
            "audit",
        ]
    ) == 1
    assert "Status: invalid" in capsys.readouterr().out
