"""Atomic, integrity-checked storage for Phase 7 simulation reports."""

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

from app.simulation.contracts import SIMULATION_CONTRACT_VERSION
from app.simulation.reporting import (
    SIMULATION_METRIC_COLUMNS,
    SIMULATION_REPLAY_COLUMNS,
    SIMULATION_TRAJECTORY_COLUMNS,
    SimulationReportProvenance,
    SimulationReportTables,
    simulation_provenance_document,
    validate_simulation_report_tables,
)

SIMULATION_REPORT_DIRECTORY_NAME: Final = "simulation_evaluation"
SIMULATION_REPORT_FORMAT_VERSION: Final = "1.0"
SIMULATION_REPORT_FILES: Final = (
    "metrics.parquet",
    "replays.parquet",
    "trajectories.parquet",
    "provenance.json",
)
_TABLE_SPECS: Final = (
    ("metrics.parquet", "metrics", SIMULATION_METRIC_COLUMNS),
    ("replays.parquet", "replays", SIMULATION_REPLAY_COLUMNS),
    (
        "trajectories.parquet",
        "trajectories",
        SIMULATION_TRAJECTORY_COLUMNS,
    ),
)


class SimulationStorageError(RuntimeError):
    """Raised when a simulation report cannot be stored or verified."""


@dataclass(frozen=True, slots=True)
class SimulationReportPaths:
    """Canonical paths for one immutable Phase 7 report."""

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
            raise SimulationStorageError("run_id must be one safe path segment")
        object.__setattr__(self, "run_id", normalized)

    @property
    def root(self) -> Path:
        """Return the immutable run directory."""
        return (
            self.artifacts_root
            / SIMULATION_REPORT_DIRECTORY_NAME
            / f"format_version={SIMULATION_REPORT_FORMAT_VERSION}"
            / f"run_id={self.run_id}"
        )

    @property
    def manifest(self) -> Path:
        """Return the integrity manifest path."""
        return self.root / "manifest.json"


@dataclass(frozen=True, slots=True)
class SimulationReportVerification:
    """Integrity result for one stored Phase 7 report."""

    valid: bool
    artifact_count: int
    issues: tuple[str, ...]

    def raise_for_errors(self) -> None:
        """Fail closed when stored evidence is invalid."""
        if self.issues:
            raise SimulationStorageError(
                "simulation report verification failed: " + "; ".join(self.issues)
            )


def write_simulation_report(
    *,
    paths: SimulationReportPaths,
    tables: SimulationReportTables,
) -> dict[str, object]:
    """Atomically publish trajectories, metrics and provenance."""
    if not isinstance(paths, SimulationReportPaths):
        raise TypeError("paths must be a SimulationReportPaths")
    if not isinstance(tables, SimulationReportTables):
        raise TypeError("tables must be a SimulationReportTables")
    validate_simulation_report_tables(tables)
    if paths.root.exists():
        raise SimulationStorageError(f"simulation report already exists: {paths.root}")
    paths.root.parent.mkdir(parents=True, exist_ok=True)
    temporary = paths.root.parent / f".tmp-{paths.run_id}-{uuid4().hex}"
    temporary.mkdir()
    try:
        for file_name, frame_name, _ in _TABLE_SPECS:
            frame = getattr(tables, frame_name)
            frame.to_parquet(temporary / file_name, index=False)
        _write_json(
            temporary / "provenance.json",
            simulation_provenance_document(tables),
        )
        artifacts = {
            name: {
                "sha256": _sha256(temporary / name),
                "size_bytes": (temporary / name).stat().st_size,
            }
            for name in SIMULATION_REPORT_FILES
        }
        manifest: dict[str, object] = {
            "format_version": SIMULATION_REPORT_FORMAT_VERSION,
            "simulation_contract_version": SIMULATION_CONTRACT_VERSION,
            "run_id": paths.run_id,
            "artifacts": artifacts,
        }
        _write_json(temporary / "manifest.json", manifest)
        os.replace(temporary, paths.root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    verification = verify_simulation_report(paths)
    if verification.issues:
        shutil.rmtree(paths.root, ignore_errors=True)
        verification.raise_for_errors()
    return manifest


def verify_simulation_report(
    paths: SimulationReportPaths,
) -> SimulationReportVerification:
    """Verify exact files, hashes, schemas, counts and arithmetic."""
    if not isinstance(paths, SimulationReportPaths):
        raise TypeError("paths must be a SimulationReportPaths")
    issues: list[str] = []
    if not paths.manifest.is_file():
        return SimulationReportVerification(
            valid=False,
            artifact_count=0,
            issues=("missing manifest.json",),
        )
    try:
        manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return SimulationReportVerification(
            valid=False,
            artifact_count=0,
            issues=(f"invalid manifest: {error}",),
        )
    if not isinstance(manifest, dict):
        return SimulationReportVerification(
            valid=False,
            artifact_count=0,
            issues=("manifest must be a JSON object",),
        )
    if manifest.get("format_version") != SIMULATION_REPORT_FORMAT_VERSION:
        issues.append("unexpected format_version")
    if manifest.get("simulation_contract_version") != SIMULATION_CONTRACT_VERSION:
        issues.append("unexpected simulation_contract_version")
    if manifest.get("run_id") != paths.run_id:
        issues.append("manifest run_id mismatch")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(
        SIMULATION_REPORT_FILES
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
                "metric_rows": len(frames["metrics"]),
                "replay_rows": len(frames["replays"]),
                "trajectory_rows": len(frames["trajectories"]),
            }
            for name, expected in expected_counts.items():
                if document.get(name) != expected:
                    raise SimulationStorageError(f"provenance {name} mismatch")
            tables = SimulationReportTables(
                metrics=frames["metrics"],
                replays=frames["replays"],
                trajectories=frames["trajectories"],
                provenance=provenance,
            )
            validate_simulation_report_tables(tables)
        except Exception as error:  # noqa: BLE001
            issues.append(f"artifact readback failed: {type(error).__name__}: {error}")
    return SimulationReportVerification(
        valid=not issues,
        artifact_count=len(artifacts),
        issues=tuple(issues),
    )


def _read_provenance(document: object) -> SimulationReportProvenance:
    if not isinstance(document, dict):
        raise SimulationStorageError("provenance must be a JSON object")
    count_fields = {"metric_rows", "replay_rows", "trajectory_rows"}
    expected = {
        *SimulationReportProvenance.__dataclass_fields__,
        *count_fields,
    }
    if set(document) != expected:
        raise SimulationStorageError(
            "provenance fields differ from the report contract"
        )
    return SimulationReportProvenance(
        simulation_contract_version=str(document["simulation_contract_version"]),
        model_contract_version=str(document["model_contract_version"]),
        model_artifact_id=str(document["model_artifact_id"]),
        dataset_contract_version=str(document["dataset_contract_version"]),
        dataset_build_identifier=str(document["dataset_build_identifier"]),
        development_sessions=int(document["development_sessions"]),
        protected_evaluation_rows=int(document["protected_evaluation_rows"]),
        random_seed=int(document["random_seed"]),
        dependency_versions=tuple(
            (str(name), str(value)) for name, value in document["dependency_versions"]
        ),
        execution_duration_seconds=float(document["execution_duration_seconds"]),
    )


def _verify_file_set(
    paths: SimulationReportPaths,
    *,
    issues: list[str],
) -> None:
    expected = {*SIMULATION_REPORT_FILES, "manifest.json"}
    try:
        actual = {item.name for item in paths.root.iterdir() if item.is_file()}
        if actual != expected:
            issues.append("stored artifact file set mismatch")
        if any(item.is_dir() for item in paths.root.iterdir()):
            issues.append("stored report contains an unexpected directory")
    except OSError as error:
        issues.append(f"report directory read failed: {error}")


def _verify_hashes(
    paths: SimulationReportPaths,
    *,
    artifacts: dict[str, object],
    issues: list[str],
) -> None:
    for name in SIMULATION_REPORT_FILES:
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
