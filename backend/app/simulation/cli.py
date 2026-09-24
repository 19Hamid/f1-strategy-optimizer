"""Command-line interface for the Phase 7 development simulation audit."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import cast

from app.simulation.audit import run_development_simulation_audit
from app.simulation.storage import (
    SimulationReportPaths,
    verify_simulation_report,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASETS_ROOT = PROJECT_ROOT / "data" / "datasets"
DEFAULT_PROCESSED_ROOT = PROJECT_ROOT / "data" / "processed" / "fastf1"
DEFAULT_ARTIFACTS_ROOT = PROJECT_ROOT / "artifacts"
DEFAULT_RUN_ID = "phase-7-final-audit"
DEFAULT_MODEL_ARTIFACT_ID = "phase-6-final-audit-lap-time"


def build_parser() -> argparse.ArgumentParser:
    """Build the final simulation-audit command parser."""
    parser = argparse.ArgumentParser(
        prog="python -m app.simulation.cli",
        description="Replay and audit Phase 7 on verified development races.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser(
        "audit",
        help="run and store the complete Phase 7 development audit",
    )
    verify = subparsers.add_parser(
        "verify",
        help="verify one stored Phase 7 simulation report",
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
    audit.set_defaults(handler=_run_audit)
    verify.set_defaults(handler=_run_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one Phase 7 audit command."""
    arguments = build_parser().parse_args(argv)
    handler = cast(object, arguments.handler)
    return handler(arguments)  # type: ignore[operator]


def _run_audit(arguments: argparse.Namespace) -> int:
    """Run the real-data audit and print complete population evidence."""
    result = run_development_simulation_audit(
        datasets_root=arguments.datasets_root,
        processed_root=arguments.processed_root,
        artifacts_root=arguments.artifacts_root,
        run_id=arguments.run_id,
        model_artifact_id=arguments.model_artifact_id,
        progress=lambda message: print(f"[Phase 7] {message}...", flush=True),
    )
    lap_metrics = result.evaluation.lap_metrics
    remaining_metrics = result.evaluation.remaining_time_metrics
    print()
    print("PHASE 7 DEVELOPMENT SIMULATION AUDIT")
    print("====================================")
    print("Status: valid")
    print(f"Audited development sessions: {result.audited_development_sessions}")
    print(f"Sessions contributing valid replays: {result.replay_development_sessions}")
    print(f"Candidate horizon slots: {result.candidate_slots}")
    print(f"Selected observed replays: {result.selected_replays}")
    print(f"Excluded horizon slots: {result.excluded_candidate_slots}")
    for horizon, count in result.horizon_counts:
        print(f"{horizon.value}: {count}")
    print(f"Aligned trajectory laps: {result.evaluation.lap_count}")
    print(f"Deterministic executions per replay: {result.deterministic_replay_passes}")
    print(f"Pooled lap MAE: {lap_metrics.mean_absolute_error_seconds:.6f}s")
    print(f"Remaining-time MAE: {remaining_metrics.mean_absolute_error_seconds:.6f}s")
    print(f"Report: {result.report_paths.root}")
    print(f"Report artifacts: {result.report_verification.artifact_count}")
    print(f"Protected 2025 rows: {result.protected_evaluation_rows}")
    return 0


def _run_verify(arguments: argparse.Namespace) -> int:
    """Verify one immutable Phase 7 report."""
    verification = verify_simulation_report(
        SimulationReportPaths(arguments.artifacts_root, arguments.run_id)
    )
    print("PHASE 7 SIMULATION AUDIT INTEGRITY")
    print("==================================")
    print(f"Status: {'valid' if verification.valid else 'invalid'}")
    print(f"Report artifacts: {verification.artifact_count}")
    print(f"Issues: {len(verification.issues)}")
    for issue in verification.issues:
        print(f"  {issue}")
    return 0 if verification.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
