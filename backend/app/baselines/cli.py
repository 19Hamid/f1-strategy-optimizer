"""Command-line interface for the Phase 5 development baseline audit."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import cast

from app.baselines.audit import run_development_baseline_audit
from app.baselines.storage import BaselineReportPaths, verify_baseline_report
from app.datasets.paths import DatasetPaths
from app.pipeline.serialization import sha256_file

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASETS_ROOT = PROJECT_ROOT / "data" / "datasets"
DEFAULT_ARTIFACTS_ROOT = PROJECT_ROOT / "artifacts"
DEFAULT_RUN_ID = "phase-5-development-audit"


def build_parser() -> argparse.ArgumentParser:
    """Build the baseline-audit command parser."""
    parser = argparse.ArgumentParser(
        prog="python -m app.baselines.cli",
        description="Evaluate Phase 5 baselines on verified development folds.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser(
        "audit",
        help="run and store the complete development baseline evaluation",
    )
    verify = subparsers.add_parser(
        "verify",
        help="verify one previously stored baseline report",
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
    audit.set_defaults(handler=_run_audit)
    verify.set_defaults(handler=_run_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one baseline reporting command."""
    arguments = build_parser().parse_args(argv)
    handler = cast(object, arguments.handler)
    return handler(arguments)  # type: ignore[operator]


def _run_audit(arguments: argparse.Namespace) -> int:
    """Run the real-data audit and print its selection evidence."""
    dataset_paths = DatasetPaths(arguments.datasets_root)
    dataset_build_identifier = sha256_file(dataset_paths.catalog)
    result = run_development_baseline_audit(
        datasets_root=arguments.datasets_root,
        artifacts_root=arguments.artifacts_root,
        run_id=arguments.run_id,
        dataset_build_identifier=dataset_build_identifier,
    )
    print("PHASE 5 DEVELOPMENT BASELINE AUDIT")
    print("==================================")
    print("Status: valid")
    print(f"Development sessions: {result.development_sessions}")
    print(f"Eligible lap targets: {result.lap_target_rows}")
    print(f"Eligible pit-duration targets: {result.pit_target_rows}")
    print(f"Report: {result.report_paths.root}")
    print()
    print("SELECTED BASELINES")
    for selected in result.selected_baselines:
        print(
            f"  {selected.task.value}: {selected.baseline_id} "
            f"MAE={selected.pooled_mean_absolute_error_seconds:.6f}s "
            f"coverage={selected.coverage_rate:.6f} "
            f"rows={selected.pooled_rows}"
        )
    print()
    print("Protected 2025 rows: 0")
    return 0


def _run_verify(arguments: argparse.Namespace) -> int:
    """Verify one immutable stored report."""
    paths = BaselineReportPaths(
        artifacts_root=arguments.artifacts_root,
        run_id=arguments.run_id,
    )
    report = verify_baseline_report(paths)
    print("PHASE 5 BASELINE REPORT INTEGRITY")
    print("=================================")
    print(f"Status: {'valid' if report.valid else 'invalid'}")
    print(f"Artifacts: {report.artifact_count}")
    print(f"Issues: {len(report.issues)}")
    for issue in report.issues:
        print(f"  {issue}")
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
