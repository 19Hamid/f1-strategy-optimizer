from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import main
from app.api.evidence import (
    ApiEvidenceError,
    DevelopmentEvidenceBundle,
    EvidenceArtifactKind,
    VerifiedEvidenceArtifact,
)
from app.api.main import app
from app.api.reporting import (
    ConcurrentBenchmarkSummary,
    ConcurrentSimulationSummary,
)
from app.optimizer.contracts import PitDecisionRecommendation

client = TestClient(app)


@pytest.fixture
def evidence_bundle(tmp_path) -> DevelopmentEvidenceBundle:
    return DevelopmentEvidenceBundle(
        artifacts_root=tmp_path,
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
                "phase-9-final-audit",
                4,
            ),
        ),
    )


@pytest.fixture
def concurrent_summary() -> ConcurrentSimulationSummary:
    return ConcurrentSimulationSummary(
        run_id="phase-9-final-audit",
        decision_id="2024/2024-04-R/HAM/38/MEDIUM",
        season=2024,
        session_id="2024-04-R",
        event_name="Japanese Grand Prix",
        driver="HAM",
        team="Mercedes",
        decision_lap=38,
        total_laps=53,
        remaining_laps=16,
        current_compound="MEDIUM",
        target_compound="HARD",
        pit_loss_seconds=22.0,
        scenario_count=10_000,
        root_seed=20250308,
        shared_pace_scale_seconds=0.439048,
        pit_loss_scale_seconds=5.0,
        lap_time_residual_scale_seconds=3.523793,
        pit_now_mean_seconds=1500.0,
        stay_out_mean_seconds=1501.5,
        advantage_mean_seconds=1.5,
        advantage_p05_seconds=-44.462827,
        advantage_median_seconds=1.2,
        advantage_p95_seconds=71.892230,
        pit_now_scenario_share=0.595,
        stay_out_scenario_share=0.405,
        tie_scenario_share=0.0,
        recommendation=PitDecisionRecommendation.NO_CLEAR_ADVANTAGE,
        recommendation_is_stable=False,
        protected_evaluation_rows=0,
        fastest_concurrent_benchmark=ConcurrentBenchmarkSummary(
            scenario_count=10_000,
            workers=4,
            median_duration_seconds=7075.189679,
            scenarios_per_second=1.41,
            speedup_vs_sequential=1.642,
            worker_efficiency=0.4105,
        ),
    )


def test_development_evidence_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    evidence_bundle: DevelopmentEvidenceBundle,
) -> None:
    monkeypatch.setattr(
        main,
        "verify_development_evidence_bundle",
        lambda: evidence_bundle,
    )

    response = client.get("/api/v1/evidence/development")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "valid"
    assert payload["protected_evaluation_rows"] == 0
    assert [item["kind"] for item in payload["artifacts"]] == [
        "MODEL",
        "SIMULATION",
        "OPTIMIZER",
        "CONCURRENT_SIMULATION",
    ]
    assert payload["artifacts"][0]["verification_rows"] == 128


def test_concurrent_report_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    concurrent_summary: ConcurrentSimulationSummary,
) -> None:
    monkeypatch.setattr(
        main,
        "load_concurrent_simulation_summary",
        lambda **kwargs: concurrent_summary,
    )

    response = client.get(
        "/api/v1/reports/concurrent-simulation/phase-9-final-audit"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["recommendation"] == "NO_CLEAR_ADVANTAGE"
    assert payload["scenario_count"] == 10_000
    assert payload["pit_now_scenario_share"] == pytest.approx(0.595)
    assert payload["advantage_p05_seconds"] == pytest.approx(-44.462827)
    assert payload["advantage_p95_seconds"] == pytest.approx(71.892230)
    assert payload["fastest_concurrent_benchmark"]["workers"] == 4
    assert payload["scenario_shares_are_correctness_probabilities"] is False


def test_concurrent_report_rejects_unsafe_run_id() -> None:
    response = client.get(
        "/api/v1/reports/concurrent-simulation/../protected"
    )

    assert response.status_code in {404, 422}


def test_evidence_failure_returns_stable_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main,
        "verify_development_evidence_bundle",
        lambda: (_ for _ in ()).throw(
            ApiEvidenceError("/private/path/manifest hash mismatch")
        ),
    )

    response = client.get("/api/v1/evidence/development")

    assert response.status_code == 503
    assert response.json() == {
        "code": "EVIDENCE_UNAVAILABLE",
        "message": "Verified development evidence is unavailable.",
    }
    assert "/private/path" not in response.text


def test_read_only_routes_are_documented_in_openapi() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/evidence/development" in paths
    assert "/api/v1/reports/concurrent-simulation/{run_id}" in paths
    assert (
        paths["/api/v1/evidence/development"]["get"]["summary"]
        == "Verify complete development evidence"
    )
