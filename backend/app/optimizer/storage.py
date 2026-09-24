"""Atomic, integrity-checked storage for Phase 8 optimizer reports."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from uuid import uuid4

import pandas as pd

from app.optimizer.contracts import OPTIMIZER_CONTRACT_VERSION
from app.optimizer.reporting import (
    OPTIMIZER_CASE_COLUMNS,
    OPTIMIZER_DECISION_COLUMNS,
    OPTIMIZER_SUMMARY_COLUMNS,
    OptimizerReportProvenance,
    OptimizerReportTables,
    optimizer_provenance_document,
    validate_optimizer_report_tables,
)

OPTIMIZER_REPORT_DIRECTORY_NAME: Final = "optimizer_evaluation"
OPTIMIZER_REPORT_FORMAT_VERSION: Final = "1.0"
OPTIMIZER_REPORT_FILES: Final = (
    "decisions.parquet",
    "cases.parquet",
    "summaries.parquet",
    "provenance.json",
)
_TABLE_SPECS: Final = (
    ("decisions.parquet", "decisions", OPTIMIZER_DECISION_COLUMNS),
    ("cases.parquet", "cases", OPTIMIZER_CASE_COLUMNS),
    ("summaries.parquet", "summaries", OPTIMIZER_SUMMARY_COLUMNS),
)


class OptimizerStorageError(RuntimeError):
    """Raised when an optimizer report cannot be stored or verified."""


@dataclass(frozen=True, slots=True)
class OptimizerReportPaths:
    """Canonical paths for one immutable Phase 8 optimizer report."""

    artifacts_root: Path
    run_id: str

    def __post_init__(self) -> None:
        """Normalize paths and reject traversal through run identities."""
        object.__setattr__(self, "artifacts_root", Path(self.artifacts_root))
        normalized = self.run_id.strip()
        if (
            not normalized
            or normalized in {".", ".."}
            or Path(normalized).name != normalized
            or "/" in normalized
            or "\\" in normalized
        ):
            raise OptimizerStorageError("run_id must be one safe path segment")
        object.__setattr__(self, "run_id", normalized)

    @property
    def root(self) -> Path:
        """Return the immutable run directory."""
        return (
            self.artifacts_root
            / OPTIMIZER_REPORT_DIRECTORY_NAME
            / f"format_version={OPTIMIZER_REPORT_FORMAT_VERSION}"
            / f"run_id={self.run_id}"
        )

    @property
    def manifest(self) -> Path:
        """Return the integrity manifest path."""
        return self.root / "manifest.json"


@dataclass(frozen=True, slots=True)
class OptimizerReportVerification:
    """Integrity result for one stored Phase 8 optimizer report."""

    valid: bool
    artifact_count: int
    issues: tuple[str, ...]

    def raise_for_errors(self) -> None:
        """Fail closed when stored evidence is invalid."""
        if self.issues:
            raise OptimizerStorageError(
                "optimizer report verification failed: " + "; ".join(self.issues)
            )


def write_optimizer_report(
    *,
    paths: OptimizerReportPaths,
    tables: OptimizerReportTables,
) -> dict[str, object]:
    """Atomically publish comparisons, cases, summaries and provenance."""
    if not isinstance(paths, OptimizerReportPaths):
        raise TypeError("paths must be an OptimizerReportPaths")
    if not isinstance(tables, OptimizerReportTables):
        raise TypeError("tables must be an OptimizerReportTables")
    validate_optimizer_report_tables(tables)
    if paths.root.exists():
        raise OptimizerStorageError(f"optimizer report already exists: {paths.root}")
    paths.root.parent.mkdir(parents=True, exist_ok=True)
    temporary = paths.root.parent / f".tmp-{paths.run_id}-{uuid4().hex}"
    temporary.mkdir()
    try:
        for file_name, frame_name, _ in _TABLE_SPECS:
            frame = getattr(tables, frame_name)
            frame.to_parquet(temporary / file_name, index=False)
        _write_json(
            temporary / "provenance.json",
            optimizer_provenance_document(tables),
        )
        artifacts = {
            name: {
                "sha256": _sha256(temporary / name),
                "size_bytes": (temporary / name).stat().st_size,
            }
            for name in OPTIMIZER_REPORT_FILES
        }
        manifest: dict[str, object] = {
            "format_version": OPTIMIZER_REPORT_FORMAT_VERSION,
            "optimizer_contract_version": OPTIMIZER_CONTRACT_VERSION,
            "run_id": paths.run_id,
            "artifacts": artifacts,
        }
        _write_json(temporary / "manifest.json", manifest)
        os.replace(temporary, paths.root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    verification = verify_optimizer_report(paths)
    if verification.issues:
        shutil.rmtree(paths.root, ignore_errors=True)
        verification.raise_for_errors()
    return manifest


def verify_optimizer_report(
    paths: OptimizerReportPaths,
) -> OptimizerReportVerification:
    """Verify exact files, hashes, schemas, counts and arithmetic."""
    if not isinstance(paths, OptimizerReportPaths):
        raise TypeError("paths must be an OptimizerReportPaths")
    issues: list[str] = []
    if not paths.manifest.is_file():
        return OptimizerReportVerification(
            valid=False,
            artifact_count=0,
            issues=("missing manifest.json",),
        )
    try:
        manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return OptimizerReportVerification(
            valid=False,
            artifact_count=0,
            issues=(f"invalid manifest: {error}",),
        )
    if not isinstance(manifest, dict):
        return OptimizerReportVerification(
            valid=False,
            artifact_count=0,
            issues=("manifest must be a JSON object",),
        )
    if manifest.get("format_version") != OPTIMIZER_REPORT_FORMAT_VERSION:
        issues.append("unexpected format_version")
    if manifest.get("optimizer_contract_version") != OPTIMIZER_CONTRACT_VERSION:
        issues.append("unexpected optimizer_contract_version")
    if manifest.get("run_id") != paths.run_id:
        issues.append("manifest run_id mismatch")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(OPTIMIZER_REPORT_FILES):
        issues.append("manifest artifact set mismatch")
        artifacts = {}
    _verify_file_set(paths, issues=issues)
    _verify_hashes(paths, artifacts=artifacts, issues=issues)

    if not issues:
        try:
            frames = {
                frame_name: pd.read_parquet(paths.root / file_name)
                for file_name, frame_name, _ in _TABLE_SPECS
            }
            document = json.loads(
                (paths.root / "provenance.json").read_text(encoding="utf-8")
            )
            provenance = _read_provenance(document)
            expected_counts = {
                "decision_rows": len(frames["decisions"]),
                "case_rows": len(frames["cases"]),
                "summary_rows": len(frames["summaries"]),
            }
            for name, expected in expected_counts.items():
                if document.get(name) != expected:
                    raise OptimizerStorageError(f"provenance {name} mismatch")
            tables = OptimizerReportTables(
                decisions=frames["decisions"],
                cases=frames["cases"],
                summaries=frames["summaries"],
                provenance=provenance,
            )
            validate_optimizer_report_tables(tables)
        except Exception as error:  # noqa: BLE001
            issues.append(f"artifact readback failed: {type(error).__name__}: {error}")
    return OptimizerReportVerification(
        valid=not issues,
        artifact_count=len(artifacts),
        issues=tuple(issues),
    )


def _read_provenance(document: object) -> OptimizerReportProvenance:
    if not isinstance(document, dict):
        raise OptimizerStorageError("provenance must be a JSON object")
    count_fields = {"decision_rows", "case_rows", "summary_rows"}
    expected = {
        *OptimizerReportProvenance.__dataclass_fields__,
        *count_fields,
    }
    if set(document) != expected:
        raise OptimizerStorageError("provenance fields differ from the report contract")
    dependency_versions = document["dependency_versions"]
    if not isinstance(dependency_versions, list):
        raise OptimizerStorageError("dependency_versions must be a JSON array")
    return OptimizerReportProvenance(
        optimizer_contract_version=str(document["optimizer_contract_version"]),
        simulation_contract_version=str(document["simulation_contract_version"]),
        model_contract_version=str(document["model_contract_version"]),
        model_artifact_id=str(document["model_artifact_id"]),
        dataset_contract_version=str(document["dataset_contract_version"]),
        dataset_build_identifier=str(document["dataset_build_identifier"]),
        development_sessions=int(document["development_sessions"]),
        protected_evaluation_rows=int(document["protected_evaluation_rows"]),
        random_seed=int(document["random_seed"]),
        dependency_versions=tuple(
            (str(name), str(value)) for name, value in dependency_versions
        ),
        execution_duration_seconds=float(document["execution_duration_seconds"]),
    )


def _verify_file_set(
    paths: OptimizerReportPaths,
    *,
    issues: list[str],
) -> None:
    expected = {*OPTIMIZER_REPORT_FILES, "manifest.json"}
    try:
        actual = {item.name for item in paths.root.iterdir() if item.is_file()}
        if actual != expected:
            issues.append("stored artifact file set mismatch")
        if any(item.is_dir() for item in paths.root.iterdir()):
            issues.append("stored report contains an unexpected directory")
    except OSError as error:
        issues.append(f"report directory read failed: {error}")


def _verify_hashes(
    paths: OptimizerReportPaths,
    *,
    artifacts: dict[str, object],
    issues: list[str],
) -> None:
    for name in OPTIMIZER_REPORT_FILES:
        artifact = paths.root / name
        expected = artifacts.get(name)
        if not artifact.is_file():
            issues.append(f"missing artifact: {name}")
            continue
        if not isinstance(expected, dict):
            continue
        if artifact.stat().st_size != expected.get("size_bytes"):
            issues.append(f"size mismatch: {name}")
        if _sha256(artifact) != expected.get("sha256"):
            issues.append(f"hash mismatch: {name}")


def _write_json(path: Path, document: object) -> None:
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
