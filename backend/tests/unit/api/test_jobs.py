"""Bounded job, cancellation and public status semantics."""

from __future__ import annotations

from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import jobs, main
from app.api.evidence import ApiEvidenceError
from app.api.historical import HistoricalDecisionKey
from app.api.jobs import (
    AnalysisJobManager,
    JobNotFoundError,
    JobQueueFullError,
    JobSnapshot,
    JobStatus,
    PairedAnalysisSummary,
    PairedJobRequest,
)
from app.api.main import app


def _request() -> PairedJobRequest:
    return PairedJobRequest(
        HistoricalDecisionKey(2024, "2024-04-R", "HAM", 38, "MEDIUM")
    )


def _payload() -> dict[str, object]:
    return {
        "season": 2024,
        "session_id": "2024-04-R",
        "driver": "HAM",
        "decision_lap": 38,
        "target_compound": "MEDIUM",
        "scenario_count": 100,
        "root_seed": 42,
        "max_workers": 4,
    }


def _snapshot(
    status: JobStatus,
    *,
    result: PairedAnalysisSummary | None = None,
) -> JobSnapshot:
    return JobSnapshot(
        job_id="a" * 32,
        status=status,
        season=2024,
        session_id="2024-04-R",
        driver="HAM",
        decision_lap=38,
        target_compound="MEDIUM",
        scenario_count=100,
        root_seed=42,
        max_workers=4,
        completed_scenarios=100 if result is not None else 0,
        result=result,
        error_code=None,
    )


def _summary() -> PairedAnalysisSummary:
    return PairedAnalysisSummary(
        season=2024,
        session_id="2024-04-R",
        driver="HAM",
        decision_lap=38,
        target_compound="MEDIUM",
        scenario_count=100,
        root_seed=42,
        calibration_id="verified-development-calibration",
        point_advantage_seconds=1.75,
        pit_now_mean_seconds=1500.0,
        stay_out_mean_seconds=1501.0,
        advantage_mean_seconds=1.0,
        advantage_p05_seconds=-5.0,
        advantage_median_seconds=1.0,
        advantage_p95_seconds=6.0,
        pit_now_scenario_share=0.6,
        stay_out_scenario_share=0.4,
        tie_scenario_share=0.0,
        recommendation="NO_CLEAR_ADVANTAGE",
        recommendation_is_stable=False,
    )


def test_manager_bounds_queue_and_cancels_waiting_and_running_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = AnalysisJobManager()
    started, released = Event(), Event()

    def blocking_run(record) -> None:
        with manager._lock:
            record.status = JobStatus.RUNNING
        started.set()
        assert released.wait(5)
        with manager._lock:
            record.status = JobStatus.CANCELLED

    monkeypatch.setattr(manager, "_run", blocking_run)
    try:
        running = manager.submit(_request())
        assert started.wait(5)
        waiting = manager.submit(_request())
        with pytest.raises(JobQueueFullError):
            manager.submit(_request())
        assert manager.cancel(waiting.job_id).status is JobStatus.CANCELLED
        assert manager.cancel(running.job_id).status is JobStatus.CANCEL_REQUESTED
        released.set()
        assert manager._jobs[running.job_id].future is not None
        manager._jobs[running.job_id].future.result(timeout=5)
        assert manager.status(running.job_id).status is JobStatus.CANCELLED
        assert manager.status(running.job_id).result is None
    finally:
        released.set()
        manager.close()


def test_background_evidence_failure_does_not_expose_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = AnalysisJobManager()

    def unavailable(key: HistoricalDecisionKey) -> None:
        raise ApiEvidenceError("/private/model/path")

    monkeypatch.setattr(jobs, "load_verified_historical_analysis", unavailable)
    try:
        snapshot = manager.submit(_request())
        future = manager._jobs[snapshot.job_id].future
        assert future is not None
        future.result(timeout=5)
        failed = manager.status(snapshot.job_id)
        assert failed.status is JobStatus.FAILED
        assert failed.error_code == "EVIDENCE_UNAVAILABLE"
        assert failed.result is None
    finally:
        manager.close()


def test_job_routes_hide_partial_results_and_label_completed_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queued = _snapshot(JobStatus.QUEUED)
    completed = _snapshot(JobStatus.COMPLETED, result=_summary())
    manager = SimpleNamespace(
        submit=lambda request: queued,
        status=lambda job_id: completed,
        cancel=lambda job_id: _snapshot(JobStatus.CANCELLED),
    )
    monkeypatch.setattr(main, "get_job_manager", lambda: manager)
    client = TestClient(app)

    created = client.post("/api/v1/analysis/paired/jobs", json=_payload())
    assert created.status_code == 202
    assert created.json()["status"] == "QUEUED"
    assert created.json()["result"] is None

    polled = client.get("/api/v1/analysis/paired/jobs/" + "a" * 32)
    assert polled.status_code == 200
    result = polled.json()["result"]
    assert result["recommendation"] == "NO_CLEAR_ADVANTAGE"
    assert result["advantage_p05_seconds"] == -5.0
    assert result["scenario_shares_are_correctness_probabilities"] is False
    assert result["counterfactual_strategy_accuracy_is_proven"] is False

    cancelled = client.delete("/api/v1/analysis/paired/jobs/" + "a" * 32)
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["result"] is None


@pytest.mark.parametrize(
    "override",
    [
        {"season": 2025},
        {"scenario_count": 99},
        {"scenario_count": 1001},
        {"max_workers": 5},
        {"scenario_count": True},
        {"base_features": {"future_lap": 999}},
    ],
)
def test_job_request_rejects_unsupported_input_before_queue_access(
    monkeypatch: pytest.MonkeyPatch,
    override: dict[str, object],
) -> None:
    monkeypatch.setattr(
        main,
        "get_job_manager",
        lambda: pytest.fail("invalid input reached the job queue"),
    )
    response = TestClient(app).post(
        "/api/v1/analysis/paired/jobs",
        json={**_payload(), **override},
    )
    assert response.status_code == 422


def test_queue_full_and_unknown_job_return_stable_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def full(request: PairedJobRequest) -> JobSnapshot:
        raise JobQueueFullError("/internal/queue/path")

    def missing(job_id: str) -> JobSnapshot:
        raise JobNotFoundError("/internal/job/path")

    monkeypatch.setattr(
        main,
        "get_job_manager",
        lambda: SimpleNamespace(submit=full, status=missing),
    )
    client = TestClient(app)
    full_response = client.post("/api/v1/analysis/paired/jobs", json=_payload())
    assert full_response.status_code == 429
    assert full_response.json()["code"] == "ANALYSIS_QUEUE_FULL"
    assert "/internal/" not in full_response.text
    missing_response = client.get("/api/v1/analysis/paired/jobs/" + "b" * 32)
    assert missing_response.status_code == 404
    assert missing_response.json()["code"] == "JOB_NOT_FOUND"
    assert "/internal/" not in missing_response.text
