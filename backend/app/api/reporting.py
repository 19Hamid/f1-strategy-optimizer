"""Read-only summaries built from verified immutable Phase 9 evidence."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from app.api.evidence import (
    DEFAULT_ARTIFACTS_ROOT,
    DEFAULT_CONCURRENT_SIMULATION_RUN_ID,
    ApiEvidenceError,
    DevelopmentEvidenceBundle,
    EvidenceArtifactKind,
    verify_development_evidence_bundle,
)
from app.concurrent_simulation.storage import (
    ConcurrentSimulationReportPaths,
)
from app.datasets.contracts import DEVELOPMENT_SEASONS
from app.optimizer.contracts import PitDecisionRecommendation


@dataclass(frozen=True, slots=True)
class ConcurrentBenchmarkSummary:
    """Fastest measured concurrent path for the stored scenario population."""

    scenario_count: int
    workers: int
    median_duration_seconds: float
    scenarios_per_second: float
    speedup_vs_sequential: float
    worker_efficiency: float

    def __post_init__(self) -> None:
        for name in ("scenario_count", "workers"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ApiEvidenceError(f"{name} must be a positive integer")
        for name in (
            "median_duration_seconds",
            "scenarios_per_second",
            "speedup_vs_sequential",
            "worker_efficiency",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0:
                raise ApiEvidenceError(f"{name} must be finite and positive")


@dataclass(frozen=True, slots=True)
class ConcurrentSimulationSummary:
    """Dashboard-safe view of one verified Phase 9 decision report."""

    run_id: str
    decision_id: str
    season: int
    session_id: str
    event_name: str
    driver: str
    team: str
    decision_lap: int
    total_laps: int
    remaining_laps: int
    current_compound: str
    target_compound: str
    pit_loss_seconds: float
    scenario_count: int
    root_seed: int
    shared_pace_scale_seconds: float
    pit_loss_scale_seconds: float
    lap_time_residual_scale_seconds: float
    pit_now_mean_seconds: float
    stay_out_mean_seconds: float
    advantage_mean_seconds: float
    advantage_p05_seconds: float
    advantage_median_seconds: float
    advantage_p95_seconds: float
    pit_now_scenario_share: float
    stay_out_scenario_share: float
    tie_scenario_share: float
    recommendation: PitDecisionRecommendation
    recommendation_is_stable: bool
    protected_evaluation_rows: int
    fastest_concurrent_benchmark: ConcurrentBenchmarkSummary

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "decision_id",
            "session_id",
            "event_name",
            "driver",
            "team",
            "current_compound",
            "target_compound",
        ):
            if not str(getattr(self, name)).strip():
                raise ApiEvidenceError(f"{name} must not be blank")
        if self.season not in DEVELOPMENT_SEASONS:
            raise ApiEvidenceError("summary decision is outside development")
        for name in (
            "decision_lap",
            "total_laps",
            "remaining_laps",
            "scenario_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ApiEvidenceError(f"{name} must be a positive integer")
        if self.root_seed < 0:
            raise ApiEvidenceError("root_seed must be non-negative")
        for name in (
            "pit_loss_seconds",
            "shared_pace_scale_seconds",
            "pit_loss_scale_seconds",
            "lap_time_residual_scale_seconds",
            "pit_now_mean_seconds",
            "stay_out_mean_seconds",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0:
                raise ApiEvidenceError(f"{name} must be finite and positive")
        interval = (
            float(self.advantage_p05_seconds),
            float(self.advantage_median_seconds),
            float(self.advantage_p95_seconds),
        )
        if any(not math.isfinite(value) for value in interval):
            raise ApiEvidenceError("advantage interval must be finite")
        if not interval[0] <= interval[1] <= interval[2]:
            raise ApiEvidenceError("advantage interval must be ordered")
        if not math.isfinite(float(self.advantage_mean_seconds)):
            raise ApiEvidenceError("advantage mean must be finite")
        shares = (
            float(self.pit_now_scenario_share),
            float(self.stay_out_scenario_share),
            float(self.tie_scenario_share),
        )
        if any(value < 0 or value > 1 for value in shares):
            raise ApiEvidenceError("scenario shares must be between zero and one")
        if not math.isclose(sum(shares), 1.0, rel_tol=0.0, abs_tol=1e-12):
            raise ApiEvidenceError("scenario shares must sum to one")
        try:
            recommendation = PitDecisionRecommendation(self.recommendation)
        except (TypeError, ValueError) as error:
            raise ApiEvidenceError("unsupported recommendation") from error
        object.__setattr__(self, "recommendation", recommendation)
        expected_stability = (
            recommendation
            is not PitDecisionRecommendation.NO_CLEAR_ADVANTAGE
        )
        if self.recommendation_is_stable is not expected_stability:
            raise ApiEvidenceError(
                "recommendation stability differs from recommendation"
            )
        if self.protected_evaluation_rows != 0:
            raise ApiEvidenceError(
                "protected evaluation rows entered the API summary"
            )
        if (
            self.fastest_concurrent_benchmark.scenario_count
            != self.scenario_count
        ):
            raise ApiEvidenceError(
                "benchmark population differs from the stored decision"
            )


def load_concurrent_simulation_summary(
    *,
    artifacts_root: Path = DEFAULT_ARTIFACTS_ROOT,
    run_id: str = DEFAULT_CONCURRENT_SIMULATION_RUN_ID,
) -> ConcurrentSimulationSummary:
    """Verify Phase 6-9, then load one compact Phase 9 decision summary."""
    root = Path(artifacts_root)
    bundle = verify_development_evidence_bundle(
        artifacts_root=root,
        concurrent_simulation_run_id=run_id,
    )
    _require_matching_concurrent_artifact(bundle, run_id=run_id)
    paths = ConcurrentSimulationReportPaths(root, run_id)
    try:
        decision_frame = pd.read_parquet(paths.root / "decision.parquet")
        benchmark_frame = pd.read_parquet(paths.root / "benchmarks.parquet")
        provenance = json.loads(
            (paths.root / "provenance.json").read_text(encoding="utf-8")
        )
        if len(decision_frame) != 1:
            raise ApiEvidenceError(
                "verified concurrent decision table must contain one row"
            )
        if not isinstance(provenance, dict):
            raise ApiEvidenceError("verified provenance must be an object")
        decision = decision_frame.iloc[0]
        scenario_count = int(decision["scenario_count"])
        benchmark = _fastest_concurrent_benchmark(
            benchmark_frame,
            scenario_count=scenario_count,
        )
        return ConcurrentSimulationSummary(
            run_id=run_id,
            decision_id=str(decision["decision_id"]),
            season=int(decision["season"]),
            session_id=str(decision["session_id"]),
            event_name=str(decision["event_name"]),
            driver=str(decision["driver"]),
            team=str(decision["team"]),
            decision_lap=int(decision["decision_lap"]),
            total_laps=int(decision["total_laps"]),
            remaining_laps=int(decision["remaining_laps"]),
            current_compound=str(decision["current_compound"]),
            target_compound=str(decision["target_compound"]),
            pit_loss_seconds=float(decision["pit_loss_seconds"]),
            scenario_count=scenario_count,
            root_seed=int(decision["root_seed"]),
            shared_pace_scale_seconds=float(
                decision["shared_pace_scale_seconds"]
            ),
            pit_loss_scale_seconds=float(
                decision["pit_loss_scale_seconds"]
            ),
            lap_time_residual_scale_seconds=float(
                decision["lap_time_residual_scale_seconds"]
            ),
            pit_now_mean_seconds=float(decision["pit_now_mean_seconds"]),
            stay_out_mean_seconds=float(decision["stay_out_mean_seconds"]),
            advantage_mean_seconds=float(
                decision["advantage_mean_seconds"]
            ),
            advantage_p05_seconds=float(
                decision["advantage_p05_seconds"]
            ),
            advantage_median_seconds=float(
                decision["advantage_median_seconds"]
            ),
            advantage_p95_seconds=float(
                decision["advantage_p95_seconds"]
            ),
            pit_now_scenario_share=float(
                decision["pit_now_scenario_share"]
            ),
            stay_out_scenario_share=float(
                decision["stay_out_scenario_share"]
            ),
            tie_scenario_share=float(decision["tie_scenario_share"]),
            recommendation=PitDecisionRecommendation(
                str(decision["recommendation"])
            ),
            recommendation_is_stable=bool(
                decision["recommendation_is_stable"]
            ),
            protected_evaluation_rows=int(
                provenance["protected_evaluation_rows"]
            ),
            fastest_concurrent_benchmark=benchmark,
        )
    except ApiEvidenceError:
        raise
    except Exception as error:
        raise ApiEvidenceError(
            "verified concurrent simulation summary could not be read: "
            f"{type(error).__name__}: {error}"
        ) from error


def _require_matching_concurrent_artifact(
    bundle: DevelopmentEvidenceBundle,
    *,
    run_id: str,
) -> None:
    artifact = bundle.artifact_for(
        EvidenceArtifactKind.CONCURRENT_SIMULATION
    )
    if artifact.identifier != run_id:
        raise ApiEvidenceError(
            "verified concurrent artifact identity differs from the request"
        )


def _fastest_concurrent_benchmark(
    frame: pd.DataFrame,
    *,
    scenario_count: int,
) -> ConcurrentBenchmarkSummary:
    candidates = frame.loc[
        (frame["scenario_count"].astype(int) == scenario_count)
        & (frame["execution_mode"].astype(str) == "CONCURRENT")
    ].copy()
    if candidates.empty:
        raise ApiEvidenceError(
            "verified report has no concurrent benchmark for its population"
        )
    candidates = candidates.sort_values(
        ["median_duration_seconds", "max_workers"],
        kind="stable",
    )
    fastest = candidates.iloc[0]
    return ConcurrentBenchmarkSummary(
        scenario_count=scenario_count,
        workers=int(fastest["max_workers"]),
        median_duration_seconds=float(
            fastest["median_duration_seconds"]
        ),
        scenarios_per_second=float(fastest["scenarios_per_second"]),
        speedup_vs_sequential=float(fastest["speedup_vs_sequential"]),
        worker_efficiency=float(fastest["worker_efficiency"]),
    )
