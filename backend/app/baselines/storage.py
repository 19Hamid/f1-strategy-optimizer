"""Atomic, integrity-checked storage for Phase 5 evaluation artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pandas as pd

from app.baselines.reporting import (
    BaselineEvaluationTables,
    provenance_document,
)

BASELINE_REPORT_DIRECTORY_NAME = "baseline_evaluation"
BASELINE_REPORT_FORMAT_VERSION = "1.1"
_ARTIFACT_NAMES = (
    "summary.parquet",
    "slices.parquet",
    "predictions.parquet",
    "provenance.json",
)


class BaselineStorageError(RuntimeError):
    """Raised when a baseline report cannot be stored or verified."""


@dataclass(frozen=True, slots=True)
class BaselineReportPaths:
    """Canonical paths for one immutable evaluation run."""

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
            raise BaselineStorageError("run_id must be one safe path segment")
        object.__setattr__(self, "run_id", normalized)

    @property
    def root(self) -> Path:
        """Return the immutable run directory."""
        return (
            self.artifacts_root
            / BASELINE_REPORT_DIRECTORY_NAME
            / f"contract_version={BASELINE_REPORT_FORMAT_VERSION}"
            / f"run_id={self.run_id}"
        )

    @property
    def manifest(self) -> Path:
        """Return the integrity manifest path."""
        return self.root / "manifest.json"


@dataclass(frozen=True, slots=True)
class BaselineVerificationReport:
    """Integrity result for one stored evaluation report."""

    valid: bool
    artifact_count: int
    issues: tuple[str, ...]

    def raise_for_errors(self) -> None:
        """Fail closed when any artifact differs from its manifest."""
        if self.issues:
            raise BaselineStorageError(
                "baseline report verification failed: "
                + "; ".join(self.issues)
            )


def write_baseline_report(
    *,
    paths: BaselineReportPaths,
    tables: BaselineEvaluationTables,
) -> dict[str, object]:
    """Write one immutable report through a sibling temporary directory."""
    if paths.root.exists():
        raise BaselineStorageError(
            f"baseline report already exists: {paths.root}"
        )
    paths.root.parent.mkdir(parents=True, exist_ok=True)
    temporary = paths.root.parent / f".tmp-{paths.run_id}-{uuid4().hex}"
    temporary.mkdir()
    try:
        tables.summary.to_parquet(temporary / "summary.parquet", index=False)
        tables.slices.to_parquet(temporary / "slices.parquet", index=False)
        tables.predictions.to_parquet(
            temporary / "predictions.parquet",
            index=False,
        )
        _write_json(
            temporary / "provenance.json",
            provenance_document(tables),
        )
        artifacts = {
            name: {
                "sha256": _sha256(temporary / name),
                "size_bytes": (temporary / name).stat().st_size,
            }
            for name in _ARTIFACT_NAMES
        }
        manifest: dict[str, object] = {
            "format_version": BASELINE_REPORT_FORMAT_VERSION,
            "run_id": paths.run_id,
            "artifacts": artifacts,
        }
        _write_json(temporary / "manifest.json", manifest)
        os.replace(temporary, paths.root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    verification = verify_baseline_report(paths)
    verification.raise_for_errors()
    return manifest


def verify_baseline_report(
    paths: BaselineReportPaths,
) -> BaselineVerificationReport:
    """Verify identity, file set, sizes, hashes and readable tables."""
    issues: list[str] = []
    if not paths.manifest.is_file():
        return BaselineVerificationReport(
            valid=False,
            artifact_count=0,
            issues=("missing manifest.json",),
        )
    try:
        manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return BaselineVerificationReport(
            valid=False,
            artifact_count=0,
            issues=(f"invalid manifest: {error}",),
        )
    if manifest.get("format_version") != BASELINE_REPORT_FORMAT_VERSION:
        issues.append("unexpected format_version")
    if manifest.get("run_id") != paths.run_id:
        issues.append("manifest run_id mismatch")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(_ARTIFACT_NAMES):
        issues.append("manifest artifact set mismatch")
        artifacts = {}

    for name in _ARTIFACT_NAMES:
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

    if not issues:
        try:
            summary = pd.read_parquet(paths.root / "summary.parquet")
            slices = pd.read_parquet(paths.root / "slices.parquet")
            predictions = pd.read_parquet(paths.root / "predictions.parquet")
            provenance = json.loads(
                (paths.root / "provenance.json").read_text(encoding="utf-8")
            )
            if len(summary) != 14:
                issues.append("summary must contain 14 results")
            if summary.loc[:, ["fold_id", "baseline_id"]].duplicated().any():
                issues.append("summary identities are not unique")
            if slices.empty:
                issues.append("slice report is empty")
            if predictions.empty:
                issues.append("prediction evidence is empty")
            if provenance.get("summary_rows") != len(summary):
                issues.append("provenance summary_rows mismatch")
            if provenance.get("slice_rows") != len(slices):
                issues.append("provenance slice_rows mismatch")
            if provenance.get("prediction_rows") != len(predictions):
                issues.append("provenance prediction_rows mismatch")
        except Exception as error:  # noqa: BLE001
            issues.append(f"artifact readback failed: {type(error).__name__}: {error}")

    return BaselineVerificationReport(
        valid=not issues,
        artifact_count=len(artifacts),
        issues=tuple(issues),
    )


def _write_json(path: Path, document: object) -> None:
    """Write stable UTF-8 JSON."""
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest of one stored artifact."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
