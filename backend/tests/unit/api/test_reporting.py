from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from app.api import reporting
from app.api.evidence import (
    ApiEvidenceError,
    DevelopmentEvidenceBundle,
    EvidenceArtifactKind,
    VerifiedEvidenceArtifact,
)
from app.api.reporting import load_concurrent_simulation_summary
from app.concurrent_simulation.storage import (
    ConcurrentSimulationReportPaths,
)


def _bundle(root: Path, run_id: str) -> DevelopmentEvidenceBundle:
    return DevelopmentEvidenceBundle(
        artifacts_root=root,
        artifacts=(
            VerifiedEvidenceArtifact(
                EvidenceArtifactKind.MODEL,
                "phase-6-final-audit-lap-time",
                3,
                128,
            ),
            VerifiedEvidenceArtifact(
                EvidenceArtifactKind.SIMULATION,
                "phase-7-final-audit",
                4,
            ),
            VerifiedEvidenceArtifact(
                EvidenceArtifactKind.OPTIMIZER,
                "phase-8-final-audit",
                4,
            ),
            VerifiedEvidenceArtifact(
                EvidenceArtifactKind.CONCURRENT_SIMULATION,
                run_id,
                4,
            ),
        ),
    )


def _write_summary_files(
    root: Path,
    *,
    run_id: str,
    protected_evaluation_rows: int = 0,
) -> None:
    paths = ConcurrentSimulationReportPaths(root, run_id)
    paths.root.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "decision_id": "2024/2024-04-R/HAM/38/MEDIUM",
                "season": 2024,
                "session_id": "2024-04-R",
                "event_name": "Japanese Grand Prix",
                "driver": "HAM",
                "team": "Mercedes",
                "decision_lap": 38,
                "total_laps": 53,
                "remaining_laps": 16,
                "current_compound": "MEDIUM",
                "target_compound": "HARD",
                "pit_loss_seconds": 22.0,
                "scenario_count": 10_000,
                "root_seed": 20250308,
                "shared_pace_scale_seconds": 0.439048,
                "pit_loss_scale_seconds": 5.0,
                "lap_time_residual_scale_seconds": 3.523793,
                "pit_now_mean_seconds": 1500.0,
                "stay_out_mean_seconds": 1501.5,
                "advantage_mean_seconds": 1.5,
                "advantage_p05_seconds": -44.462827,
                "advantage_median_seconds": 1.2,
                "advantage_p95_seconds": 71.892230,
                "pit_now_scenario_share": 0.595,
                "stay_out_scenario_share": 0.405,
                "tie_scenario_share": 0.0,
                "recommendation": "NO_CLEAR_ADVANTAGE",
                "recommendation_is_stable": False,
            }
        ]
    ).to_parquet(paths.root / "decision.parquet", index=False)
    pd.DataFrame(
        [
            {
                "scenario_count": 10_000,
                "execution_mode": "CONCURRENT",
                "max_workers": 2,
                "median_duration_seconds": 7329.651890,
                "scenarios_per_second": 1.36,
                "speedup_vs_sequential": 1.585,
                "worker_efficiency": 0.7925,
            },
            {
                "scenario_count": 10_000,
                "execution_mode": "CONCURRENT",
                "max_workers": 4,
                "median_duration_seconds": 7075.189679,
                "scenarios_per_second": 1.41,
                "speedup_vs_sequential": 1.642,
                "worker_efficiency": 0.4105,
            },
            {
                "scenario_count": 10_000,
                "execution_mode": "CONCURRENT",
                "max_workers": 8,
                "median_duration_seconds": 7209.080433,
                "scenarios_per_second": 1.39,
                "speedup_vs_sequential": 1.611,
                "worker_efficiency": 0.201375,
            },
        ]
    ).to_parquet(paths.root / "benchmarks.parquet", index=False)
    (paths.root / "provenance.json").write_text(
        json.dumps(
            {"protected_evaluation_rows": protected_evaluation_rows}
        ),
        encoding="utf-8",
    )


def test_load_summary_uses_verified_report_and_fastest_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_id = "phase-9-final-audit"
    _write_summary_files(tmp_path, run_id=run_id)
    monkeypatch.setattr(
        reporting,
        "verify_development_evidence_bundle",
        lambda **kwargs: _bundle(tmp_path, run_id),
    )

    summary = load_concurrent_simulation_summary(
        artifacts_root=tmp_path,
        run_id=run_id,
    )

    assert summary.decision_id == "2024/2024-04-R/HAM/38/MEDIUM"
    assert summary.scenario_count == 10_000
    assert summary.recommendation.value == "NO_CLEAR_ADVANTAGE"
    assert summary.advantage_p05_seconds == pytest.approx(-44.462827)
    assert summary.advantage_p95_seconds == pytest.approx(71.892230)
    assert summary.fastest_concurrent_benchmark.workers == 4
    assert (
        summary.fastest_concurrent_benchmark.median_duration_seconds
        == pytest.approx(7075.189679)
    )


def test_load_summary_rejects_protected_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_id = "phase-9-final-audit"
    _write_summary_files(
        tmp_path,
        run_id=run_id,
        protected_evaluation_rows=1,
    )
    monkeypatch.setattr(
        reporting,
        "verify_development_evidence_bundle",
        lambda **kwargs: _bundle(tmp_path, run_id),
    )

    with pytest.raises(
        ApiEvidenceError,
        match="protected evaluation rows",
    ):
        load_concurrent_simulation_summary(
            artifacts_root=tmp_path,
            run_id=run_id,
        )


def test_load_summary_fails_closed_when_files_disappear(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_id = "phase-9-final-audit"
    monkeypatch.setattr(
        reporting,
        "verify_development_evidence_bundle",
        lambda **kwargs: _bundle(tmp_path, run_id),
    )

    with pytest.raises(
        ApiEvidenceError,
        match="summary could not be read",
    ):
        load_concurrent_simulation_summary(
            artifacts_root=tmp_path,
            run_id=run_id,
        )
