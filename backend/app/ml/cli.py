"""Command-line interface for the Phase 6 development model audit."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import cast

from app.ml.artifacts import ModelArtifactPaths, verify_model_artifact
from app.ml.audit import run_development_model_audit
from app.ml.reports import ModelReportPaths, verify_model_report

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASETS_ROOT = PROJECT_ROOT / "data" / "datasets"
DEFAULT_ARTIFACTS_ROOT = PROJECT_ROOT / "artifacts"
DEFAULT_RUN_ID = "phase-6-development-audit"


def build_parser() -> argparse.ArgumentParser:
    """Build the final model-audit command parser."""
    parser = argparse.ArgumentParser(
        prog="python -m app.ml.cli",
        description="Select and refit Phase 6 models on development data.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser(
        "audit",
        help="run and store the complete Phase 6 development audit",
    )
    verify = subparsers.add_parser(
        "verify",
        help="verify a stored model report and fitted model bundle",
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
    """Run one Phase 6 model reporting command."""
    arguments = build_parser().parse_args(argv)
    handler = cast(object, arguments.handler)
    return handler(arguments)  # type: ignore[operator]


def _run_audit(arguments: argparse.Namespace) -> int:
    """Run the real-data audit and print selection evidence."""
    from app.datasets.paths import DatasetPaths
    from app.pipeline.serialization import sha256_file

    dataset_paths = DatasetPaths(arguments.datasets_root)
    result = run_development_model_audit(
        datasets_root=arguments.datasets_root,
        artifacts_root=arguments.artifacts_root,
        run_id=arguments.run_id,
        dataset_build_identifier=sha256_file(dataset_paths.catalog),
        progress=lambda message: print(f"[Phase 6] {message}...", flush=True),
    )
    selected = result.selected_candidate
    print()
    print("PHASE 6 DEVELOPMENT MODEL AUDIT")
    print("=================================")
    print("Status: valid")
    print(f"Development sessions: {result.development_sessions}")
    print(
        "Sessions contributing eligible targets: "
        f"{result.contributing_training_sessions}"
    )
    print(f"Primary lap-time targets: {result.primary_target_rows}")
    print(f"Auxiliary lap-delta targets: {result.auxiliary_target_rows}")
    print(f"Selected model: {selected.candidate_id}")
    print(f"Model family: {selected.family.value}")
    print(
        "Temporal pooled MAE: "
        f"{selected.pooled_mean_absolute_error_seconds:.6f}s"
    )
    print(
        "Comparable-row MAE: "
        f"{selected.common_mean_absolute_error_seconds:.6f}s"
    )
    print(
        "Identity-ablation MAE: "
        f"{selected.ablated_common_mean_absolute_error_seconds:.6f}s"
    )
    print(f"Coverage: {selected.coverage_rate:.6f}")
    print(f"Report: {result.report_paths.root}")
    print(f"Model: {result.model_paths.root}")
    print(f"Protected 2025 rows: {result.protected_evaluation_rows}")
    return 0


def _run_verify(arguments: argparse.Namespace) -> int:
    """Verify both immutable products of one Phase 6 audit."""
    report = verify_model_report(
        ModelReportPaths(arguments.artifacts_root, arguments.run_id)
    )
    model = verify_model_artifact(
        ModelArtifactPaths(
            arguments.artifacts_root,
            f"{arguments.run_id}-lap-time",
        )
    )
    valid = report.valid and model.valid
    print("PHASE 6 MODEL AUDIT INTEGRITY")
    print("=============================")
    print(f"Status: {'valid' if valid else 'invalid'}")
    print(f"Report artifacts: {report.artifact_count}")
    print(f"Model artifacts: {model.artifact_count}")
    print(f"Model verification rows: {model.verification_rows}")
    issues = (*report.issues, *model.issues)
    print(f"Issues: {len(issues)}")
    for issue in issues:
        print(f"  {issue}")
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
