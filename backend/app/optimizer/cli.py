"""Command-line interface for the Phase 8 development optimizer audit."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import cast

from app.optimizer.audit import run_development_optimizer_audit
from app.optimizer.storage import (
    OptimizerReportPaths,
    verify_optimizer_report,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASETS_ROOT = PROJECT_ROOT / "data" / "datasets"
DEFAULT_PROCESSED_ROOT = PROJECT_ROOT / "data" / "processed" / "fastf1"
DEFAULT_ARTIFACTS_ROOT = PROJECT_ROOT / "artifacts"
DEFAULT_RUN_ID = "phase-8-final-audit"
DEFAULT_MODEL_ARTIFACT_ID = "phase-6-final-audit-lap-time"
DEFAULT_SIMULATION_RUN_ID = "phase-7-final-audit"


def build_parser() -> argparse.ArgumentParser:
    """Build the final optimizer-audit command parser."""
    parser = argparse.ArgumentParser(
        prog="python -m app.optimizer.cli",
        description="Compare and audit Phase 8 on verified development races.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser(
        "audit",
        help="run and store the complete Phase 8 development audit",
    )
    verify = subparsers.add_parser(
        "verify",
        help="verify one stored Phase 8 optimizer report",
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
    audit.set_defaults(handler=_run_audit)
    verify.set_defaults(handler=_run_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one Phase 8 audit command."""
    arguments = build_parser().parse_args(argv)
    handler = cast(object, arguments.handler)
    return handler(arguments)  # type: ignore[operator]


def _run_audit(arguments: argparse.Namespace) -> int:
    """Run the real-data audit and print complete population evidence."""
    result = run_development_optimizer_audit(
        datasets_root=arguments.datasets_root,
        processed_root=arguments.processed_root,
        artifacts_root=arguments.artifacts_root,
        run_id=arguments.run_id,
        model_artifact_id=arguments.model_artifact_id,
        simulation_run_id=arguments.simulation_run_id,
        progress=lambda message: print(f"[Phase 8] {message}...", flush=True),
    )
    summary = result.diagnostics.overall
    alignment = summary.observed_action_alignment_rate
    print()
    print("PHASE 8 DEVELOPMENT OPTIMIZER AUDIT")
    print("===================================")
    print("Status: valid")
    print(f"Audited development sessions: {result.audited_development_sessions}")
    print(
        "Sessions contributing decision pairs: "
        f"{result.decision_development_sessions}"
    )
    print(f"Candidate pair slots: {result.candidate_pair_slots}")
    print(f"Selected decision pairs: {result.selected_decision_pairs}")
    print(f"Excluded pair slots: {result.excluded_pair_slots}")
    print(f"Selected historical decisions: {result.selected_decisions}")
    print(f"Observed PIT_NOW: {result.observed_pit_now}")
    print(f"Observed STAY_OUT: {result.observed_stay_out}")
    print(f"Stable PIT_NOW: {summary.stable_pit_now}")
    print(f"Stable STAY_OUT: {summary.stable_stay_out}")
    print(f"NO_CLEAR_ADVANTAGE: {summary.no_clear_advantage}")
    print(
        "Comparable observed actions: "
        f"{summary.comparable_observed_action_rows}"
    )
    print(f"Aligned observed actions: {summary.aligned_observed_actions}")
    print(
        "Observed-action alignment rate: "
        + ("n/a" if alignment is None else f"{alignment:.6f}")
    )
    print(
        "Action-time uncertainty margin: "
        f"{result.action_time_margin_seconds:.6f}s"
    )
    print(
        "Deterministic executions per decision: "
        f"{result.deterministic_decision_passes}"
    )
    print(f"Report: {result.report_paths.root}")
    print(f"Report artifacts: {result.report_verification.artifact_count}")
    print(f"Protected 2025 rows: {result.protected_evaluation_rows}")
    return 0


def _run_verify(arguments: argparse.Namespace) -> int:
    """Verify one immutable Phase 8 report."""
    verification = verify_optimizer_report(
        OptimizerReportPaths(arguments.artifacts_root, arguments.run_id)
    )
    print("PHASE 8 OPTIMIZER AUDIT INTEGRITY")
    print("=================================")
    print(f"Status: {'valid' if verification.valid else 'invalid'}")
    print(f"Report artifacts: {verification.artifact_count}")
    print(f"Issues: {len(verification.issues)}")
    for issue in verification.issues:
        print(f"  {issue}")
    return 0 if verification.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
