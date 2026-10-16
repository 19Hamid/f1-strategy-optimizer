"""Atomic, integrity-checked storage for Phase 9 reports."""

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

from app.concurrent_simulation.contracts import (
    CONCURRENT_SIMULATION_CONTRACT_VERSION,
)
from app.concurrent_simulation.reporting import (
    CONCURRENT_BENCHMARK_COLUMNS,
    CONCURRENT_DECISION_COLUMNS,
    CONCURRENT_SCENARIO_COLUMNS,
    ConcurrentSimulationReportProvenance,
    ConcurrentSimulationReportTables,
    concurrent_simulation_provenance_document,
    validate_concurrent_simulation_report_tables,
)

CONCURRENT_SIMULATION_REPORT_DIRECTORY_NAME: Final = (
    "concurrent_simulation_evaluation"
)
CONCURRENT_SIMULATION_REPORT_FORMAT_VERSION: Final = "1.0"
CONCURRENT_SIMULATION_REPORT_FILES: Final = (
    "scenarios.parquet",
    "decision.parquet",
    "benchmarks.parquet",
    "provenance.json",
)
_TABLE_SPECS: Final = (
    ("scenarios.parquet", "scenarios", CONCURRENT_SCENARIO_COLUMNS),
    ("decision.parquet", "decision", CONCURRENT_DECISION_COLUMNS),
    ("benchmarks.parquet", "benchmarks", CONCURRENT_BENCHMARK_COLUMNS),
)


class ConcurrentSimulationStorageError(RuntimeError):
    """Raised when a Phase 9 report cannot be stored or verified."""


@dataclass(frozen=True, slots=True)
class ConcurrentSimulationReportPaths:
    """Canonical paths for one immutable Phase 9 report."""

    artifacts_root: Path
    run_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifacts_root", Path(self.artifacts_root))
        normalized = self.run_id.strip()
        if (
            not normalized
            or normalized in {".", ".."}
            or Path(normalized).name != normalized
            or "/" in normalized
            or "\\" in normalized
        ):
            raise ConcurrentSimulationStorageError(
                "run_id must be one safe path segment"
            )
        object.__setattr__(self, "run_id", normalized)

    @property
    def root(self) -> Path:
        """Return the immutable run directory."""
        return (
            self.artifacts_root
            / CONCURRENT_SIMULATION_REPORT_DIRECTORY_NAME
            / f"format_version={CONCURRENT_SIMULATION_REPORT_FORMAT_VERSION}"
            / f"run_id={self.run_id}"
        )

    @property
    def manifest(self) -> Path:
        """Return the integrity manifest path."""
        return self.root / "manifest.json"


@dataclass(frozen=True, slots=True)
class ConcurrentSimulationReportVerification:
    """Integrity result for one stored Phase 9 report."""

    valid: bool
    artifact_count: int
    issues: tuple[str, ...]

    def raise_for_errors(self) -> None:
        """Fail closed when stored evidence is invalid."""
        if self.issues:
            raise ConcurrentSimulationStorageError(
                "concurrent simulation report verification failed: "
                + "; ".join(self.issues)
            )


def write_concurrent_simulation_report(
    *,
    paths: ConcurrentSimulationReportPaths,
    tables: ConcurrentSimulationReportTables,
) -> dict[str, object]:
    """Atomically publish scenario, decision, benchmark and provenance evidence."""
    if not isinstance(paths, ConcurrentSimulationReportPaths):
        raise TypeError("paths must be a ConcurrentSimulationReportPaths")
    if not isinstance(tables, ConcurrentSimulationReportTables):
        raise TypeError("tables must be a ConcurrentSimulationReportTables")
    validate_concurrent_simulation_report_tables(tables)
    if paths.root.exists():
        raise ConcurrentSimulationStorageError(
            f"concurrent simulation report already exists: {paths.root}"
        )
    paths.root.parent.mkdir(parents=True, exist_ok=True)
    temporary = paths.root.parent / f".tmp-{paths.run_id}-{uuid4().hex}"
    temporary.mkdir()
    try:
        for file_name, frame_name, _ in _TABLE_SPECS:
            frame = getattr(tables, frame_name)
            frame.to_parquet(temporary / file_name, index=False)
        _write_json(
            temporary / "provenance.json",
            concurrent_simulation_provenance_document(tables),
        )
        artifacts = {
            name: {
                "sha256": _sha256(temporary / name),
                "size_bytes": (temporary / name).stat().st_size,
            }
            for name in CONCURRENT_SIMULATION_REPORT_FILES
        }
        manifest: dict[str, object] = {
            "format_version": CONCURRENT_SIMULATION_REPORT_FORMAT_VERSION,
            "concurrent_simulation_contract_version": (
                CONCURRENT_SIMULATION_CONTRACT_VERSION
            ),
            "run_id": paths.run_id,
            "artifacts": artifacts,
        }
        _write_json(temporary / "manifest.json", manifest)
        os.replace(temporary, paths.root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    verification = verify_concurrent_simulation_report(paths)
    if verification.issues:
        shutil.rmtree(paths.root, ignore_errors=True)
        verification.raise_for_errors()
    return manifest


def verify_concurrent_simulation_report(
    paths: ConcurrentSimulationReportPaths,
) -> ConcurrentSimulationReportVerification:
    """Verify exact files, hashes, schemas, counts and arithmetic."""
    if not isinstance(paths, ConcurrentSimulationReportPaths):
        raise TypeError("paths must be a ConcurrentSimulationReportPaths")
    issues: list[str] = []
    if not paths.manifest.is_file():
        return ConcurrentSimulationReportVerification(
            valid=False,
            artifact_count=0,
            issues=("missing manifest.json",),
        )
    try:
        manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return ConcurrentSimulationReportVerification(
            valid=False,
            artifact_count=0,
            issues=(f"invalid manifest: {error}",),
        )
    if not isinstance(manifest, dict):
        return ConcurrentSimulationReportVerification(
            valid=False,
            artifact_count=0,
            issues=("manifest must be a JSON object",),
        )
    if manifest.get("format_version") != CONCURRENT_SIMULATION_REPORT_FORMAT_VERSION:
        issues.append("unexpected format_version")
    if (
        manifest.get("concurrent_simulation_contract_version")
        != CONCURRENT_SIMULATION_CONTRACT_VERSION
    ):
        issues.append("unexpected concurrent_simulation_contract_version")
    if manifest.get("run_id") != paths.run_id:
        issues.append("manifest run_id mismatch")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(
        CONCURRENT_SIMULATION_REPORT_FILES
    ):
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
                "scenario_rows": len(frames["scenarios"]),
                "decision_rows": len(frames["decision"]),
                "benchmark_rows": len(frames["benchmarks"]),
            }
            for name, expected in expected_counts.items():
                if document.get(name) != expected:
                    raise ConcurrentSimulationStorageError(
                        f"provenance {name} mismatch"
                    )
            tables = ConcurrentSimulationReportTables(
                scenarios=frames["scenarios"],
                decision=frames["decision"],
                benchmarks=frames["benchmarks"],
                provenance=provenance,
            )
            validate_concurrent_simulation_report_tables(tables)
        except Exception as error:  # noqa: BLE001
            issues.append(
                f"artifact readback failed: {type(error).__name__}: {error}"
            )
    return ConcurrentSimulationReportVerification(
        valid=not issues,
        artifact_count=len(artifacts),
        issues=tuple(issues),
    )


def _read_provenance(
    document: object,
) -> ConcurrentSimulationReportProvenance:
    if not isinstance(document, dict):
        raise ConcurrentSimulationStorageError(
            "provenance must be a JSON object"
        )
    count_fields = {"scenario_rows", "decision_rows", "benchmark_rows"}
    expected = {
        *ConcurrentSimulationReportProvenance.__dataclass_fields__,
        *count_fields,
    }
    if set(document) != expected:
        raise ConcurrentSimulationStorageError(
            "provenance fields differ from the report contract"
        )
    dependency_versions = document["dependency_versions"]
    scenario_counts = document["scenario_counts"]
    worker_counts = document["worker_counts"]
    if not isinstance(dependency_versions, list):
        raise ConcurrentSimulationStorageError(
            "dependency_versions must be a JSON array"
        )
    if not isinstance(scenario_counts, list) or not isinstance(
        worker_counts,
        list,
    ):
        raise ConcurrentSimulationStorageError(
            "scenario_counts and worker_counts must be JSON arrays"
        )
    return ConcurrentSimulationReportProvenance(
        concurrent_simulation_contract_version=str(
            document["concurrent_simulation_contract_version"]
        ),
        optimizer_contract_version=str(document["optimizer_contract_version"]),
        simulation_contract_version=str(document["simulation_contract_version"]),
        model_contract_version=str(document["model_contract_version"]),
        model_artifact_id=str(document["model_artifact_id"]),
        dataset_contract_version=str(document["dataset_contract_version"]),
        dataset_build_identifier=str(document["dataset_build_identifier"]),
        calibration_id=str(document["calibration_id"]),
        calibration_method_id=str(document["calibration_method_id"]),
        scenario_generator_id=str(document["scenario_generator_id"]),
        sequential_aggregator_id=str(document["sequential_aggregator_id"]),
        concurrent_executor_id=str(document["concurrent_executor_id"]),
        benchmark_id=str(document["benchmark_id"]),
        development_sessions=int(document["development_sessions"]),
        protected_evaluation_rows=int(document["protected_evaluation_rows"]),
        root_seed=int(document["root_seed"]),
        scenario_counts=tuple(int(value) for value in scenario_counts),
        worker_counts=tuple(int(value) for value in worker_counts),
        repetitions=int(document["repetitions"]),
        dependency_versions=tuple(
            (str(name), str(value)) for name, value in dependency_versions
        ),
        runtime_platform=str(document["runtime_platform"]),
        runtime_machine=str(document["runtime_machine"]),
        runtime_processor=str(document["runtime_processor"]),
        logical_cpu_count=int(document["logical_cpu_count"]),
        execution_duration_seconds=float(document["execution_duration_seconds"]),
    )


def _verify_file_set(
    paths: ConcurrentSimulationReportPaths,
    *,
    issues: list[str],
) -> None:
    expected = {*CONCURRENT_SIMULATION_REPORT_FILES, "manifest.json"}
    try:
        actual = {item.name for item in paths.root.iterdir() if item.is_file()}
        if actual != expected:
            issues.append("stored artifact file set mismatch")
        if any(item.is_dir() for item in paths.root.iterdir()):
            issues.append("stored report contains an unexpected directory")
    except OSError as error:
        issues.append(f"report directory read failed: {error}")


def _verify_hashes(
    paths: ConcurrentSimulationReportPaths,
    *,
    artifacts: dict[str, object],
    issues: list[str],
) -> None:
    for name in CONCURRENT_SIMULATION_REPORT_FILES:
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
