"""Command-line interface for the Phase 9 development audit."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import cast

from app.concurrent_simulation.audit import (
    run_development_concurrent_simulation_audit,
)
from app.concurrent_simulation.benchmark import BenchmarkExecutionMode
from app.concurrent_simulation.storage import (
    ConcurrentSimulationReportPaths,
    verify_concurrent_simulation_report,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASETS_ROOT = PROJECT_ROOT / "data" / "datasets"
DEFAULT_PROCESSED_ROOT = PROJECT_ROOT / "data" / "processed" / "fastf1"
DEFAULT_ARTIFACTS_ROOT = PROJECT_ROOT / "artifacts"
DEFAULT_RUN_ID = "phase-9-final-audit"
DEFAULT_MODEL_ARTIFACT_ID = "phase-6-final-audit-lap-time"
DEFAULT_SIMULATION_RUN_ID = "phase-7-final-audit"
DEFAULT_OPTIMIZER_RUN_ID = "phase-8-final-audit"


def build_parser() -> argparse.ArgumentParser:
    """Build the final concurrent-simulation audit command parser."""
    parser = argparse.ArgumentParser(
        prog="python -m app.concurrent_simulation.cli",
        description=(
            "Calibrate, benchmark and audit Phase 9 on verified "
            "development evidence."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser(
        "audit",
        help="run and store the complete Phase 9 development audit",
    )
    verify = subparsers.add_parser(
        "verify",
        help="verify one stored Phase 9 concurrent simulation report",
    )
    for command in (audit, verify):
        command.add_argument(
            "--artifacts-root",
            type=Path,
            default=DEFAULT_ARTIFACTS_ROOT,
        )
        command.add_argument("--run-id", default=DEFAULT_RUN_ID)
    audit.add_argument(
        "--datasets-root",
        type=Path,
        default=DEFAULT_DATASETS_ROOT,
    )
    audit.add_argument(
        "--processed-root",
        type=Path,
        default=DEFAULT_PROCESSED_ROOT,
    )
    audit.add_argument(
        "--model-artifact-id",
        default=DEFAULT_MODEL_ARTIFACT_ID,
    )
    audit.add_argument(
        "--simulation-run-id",
        default=DEFAULT_SIMULATION_RUN_ID,
    )
    audit.add_argument(
        "--optimizer-run-id",
        default=DEFAULT_OPTIMIZER_RUN_ID,
    )
    audit.set_defaults(handler=_run_audit)
    verify.set_defaults(handler=_run_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one Phase 9 audit command."""
    arguments = build_parser().parse_args(argv)
    handler = cast(object, arguments.handler)
    return handler(arguments)  # type: ignore[operator]


def _run_audit(arguments: argparse.Namespace) -> int:
    result = run_development_concurrent_simulation_audit(
        datasets_root=arguments.datasets_root,
        processed_root=arguments.processed_root,
        artifacts_root=arguments.artifacts_root,
        run_id=arguments.run_id,
        model_artifact_id=arguments.model_artifact_id,
        simulation_run_id=arguments.simulation_run_id,
        optimizer_run_id=arguments.optimizer_run_id,
        progress=lambda message: print(f"[Phase 9] {message}...", flush=True),
    )
    calibration = result.calibration
    coverage = result.coverage
    evaluation = result.evaluation
    advantage = evaluation.advantage_distribution
    print()
    print("PHASE 9 DEVELOPMENT CONCURRENT SIMULATION AUDIT")
    print("===============================================")
    print("Status: valid")
    print(f"Audited development sessions: {result.audited_development_sessions}")
    print(
        "Sessions contributing Phase 8 decisions: "
        f"{result.candidate_development_sessions}"
    )
    print(
        "Reconciled historical decisions: "
        f"{result.reconciled_historical_decisions}"
    )
    print(
        "Representative decision: "
        + "/".join(str(value) for value in result.representative_decision_key)
    )
    print(
        "Representative remaining laps: "
        f"{result.representative_remaining_laps}"
    )
    print(f"Calibration replays: {calibration.replay_count}")
    print(f"Calibration laps: {calibration.lap_count}")
    print(
        "Calibration pit-loss profiles: "
        f"{calibration.pit_loss_profile_count}"
    )
    print(
        "Shared-pace scale: "
        f"{calibration.shared_pace_scale_seconds:.6f}s"
    )
    print(f"Pit-loss scale: {calibration.pit_loss_scale_seconds:.6f}s")
    print(
        "Lap-residual scale: "
        f"{calibration.lap_time_residual_scale_seconds:.6f}s"
    )
    print(
        "Development replay-mean central-90% coverage: "
        f"{coverage.replay_mean_covered}/{coverage.replay_mean_count} "
        f"({coverage.replay_mean_coverage_rate:.2%})"
    )
    print(
        "Development lap-residual central-90% coverage: "
        f"{coverage.lap_residual_covered}/{coverage.lap_residual_count} "
        f"({coverage.lap_residual_coverage_rate:.2%})"
    )
    print(
        "Coverage scope: in-sample perturbation diagnostic; "
        "not strategy-correctness probability"
    )
    print(f"Stored scenarios: {evaluation.scenario_count}")
    print(f"Recommendation: {evaluation.recommendation.value}")
    print(f"PIT_NOW scenario share: {evaluation.pit_now_scenario_share:.2%}")
    print(f"STAY_OUT scenario share: {evaluation.stay_out_scenario_share:.2%}")
    print(f"Tie scenario share: {evaluation.tie_scenario_share:.2%}")
    print(
        "Advantage central 90% interval: "
        f"[{advantage.p05:.6f}s, {advantage.p95:.6f}s]"
    )
    print()
    print("SCALING BENCHMARK")
    for benchmark in result.benchmark.results:
        for measurement in benchmark.measurements:
            mode = measurement.execution_mode.value
            workers = (
                "-"
                if measurement.execution_mode
                is BenchmarkExecutionMode.SEQUENTIAL
                else str(measurement.max_workers)
            )
            print(
                f"{measurement.scenario_count:>5} scenarios | "
                f"{mode:<10} | workers={workers:<2} | "
                f"{measurement.median_duration_seconds:.6f}s | "
                f"{measurement.scenarios_per_second:.2f}/s | "
                f"speedup={measurement.speedup_vs_sequential:.3f}x"
            )
    print(f"Report: {result.report_paths.root}")
    print(f"Report artifacts: {result.report_verification.artifact_count}")
    print(f"Protected 2025 rows: {result.protected_evaluation_rows}")
    return 0


def _run_verify(arguments: argparse.Namespace) -> int:
    verification = verify_concurrent_simulation_report(
        ConcurrentSimulationReportPaths(
            arguments.artifacts_root,
            arguments.run_id,
        )
    )
    print("PHASE 9 CONCURRENT SIMULATION AUDIT INTEGRITY")
    print("=============================================")
    print(f"Status: {'valid' if verification.valid else 'invalid'}")
    print(f"Report artifacts: {verification.artifact_count}")
    print(f"Issues: {len(verification.issues)}")
    for issue in verification.issues:
        print(f"  {issue}")
    return 0 if verification.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())

