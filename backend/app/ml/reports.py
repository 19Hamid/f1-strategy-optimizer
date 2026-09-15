"""Immutable selection and diagnostic reports for Phase 6."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

import pandas as pd

from app.ml.contracts import (
    DEVELOPMENT_FOLDS,
    MODEL_CONTRACT_VERSION,
    MODEL_RANDOM_SEED,
    ModelFamily,
    PredictionFormulation,
    model_spec,
)
from app.ml.diagnostics import (
    DEGRADATION_CURVE_COLUMNS,
    IDENTITY_DIAGNOSTIC_COLUMNS,
    SLICE_METRIC_COLUMNS,
    SelectedModelDiagnostics,
)
from app.ml.selection import (
    FOLD_METRIC_COLUMNS,
    POOLED_METRIC_COLUMNS,
    SELECTION_COLUMNS,
    TemporalSelectionReport,
)

MODEL_EVALUATION_DIRECTORY_NAME: Final = "model_evaluation"
MODEL_EVALUATION_FORMAT_VERSION: Final = "1.1"
MODEL_EVALUATION_FILES: Final = (
    "fold_metrics.parquet",
    "pooled_metrics.parquet",
    "selection.parquet",
    "slice_metrics.parquet",
    "degradation_curve.parquet",
    "identity_dependence.parquet",
    "provenance.json",
)
_TABLE_SPECS: Final = (
    ("fold_metrics.parquet", "fold_metrics", FOLD_METRIC_COLUMNS),
    ("pooled_metrics.parquet", "pooled_metrics", POOLED_METRIC_COLUMNS),
    ("selection.parquet", "selection", SELECTION_COLUMNS),
    ("slice_metrics.parquet", "slice_metrics", SLICE_METRIC_COLUMNS),
    (
        "degradation_curve.parquet",
        "degradation_curve",
        DEGRADATION_CURVE_COLUMNS,
    ),
    (
        "identity_dependence.parquet",
        "identity_dependence",
        IDENTITY_DIAGNOSTIC_COLUMNS,
    ),
)
_REQUIRED_DEPENDENCIES: Final = frozenset(
    {"joblib", "numpy", "pandas", "python", "scikit-learn"}
)


class ModelReportError(RuntimeError):
    """Raised when Phase 6 evaluation evidence is incomplete or altered."""


@dataclass(frozen=True, slots=True)
class ModelReportPaths:
    """Canonical location for one immutable Phase 6 evaluation report."""

    artifacts_root: Path
    run_id: str

    def __post_init__(self) -> None:
        """Normalize the root and reject path traversal through run IDs."""
        object.__setattr__(self, "artifacts_root", Path(self.artifacts_root))
        normalized = self.run_id.strip()
        if (
            not normalized
            or normalized in {".", ".."}
            or Path(normalized).name != normalized
            or "/" in normalized
            or "\\" in normalized
        ):
            raise ModelReportError("run_id must be one safe path segment")
        object.__setattr__(self, "run_id", normalized)

    @property
    def root(self) -> Path:
        """Return the immutable evaluation directory."""
        return (
            self.artifacts_root
            / MODEL_EVALUATION_DIRECTORY_NAME
            / f"contract_version={MODEL_EVALUATION_FORMAT_VERSION}"
            / f"run_id={self.run_id}"
        )

    @property
    def manifest(self) -> Path:
        """Return the integrity manifest path."""
        return self.root / "manifest.json"


@dataclass(frozen=True, slots=True)
class ModelEvaluationProvenance:
    """Data, selection, artifact and runtime identity for one audit."""

    model_contract_version: str
    dataset_contract_version: str
    dataset_build_identifier: str
    development_sessions: int
    contributing_training_sessions: int
    primary_target_rows: int
    auxiliary_target_rows: int
    protected_evaluation_rows: int
    selected_formulation: PredictionFormulation
    selected_family: ModelFamily
    selected_candidate_id: str
    selected_parameters: str
    final_model_artifact_id: str
    random_seed: int
    dependency_versions: tuple[tuple[str, str], ...]
    evaluation_duration_seconds: float
    final_fit_duration_seconds: float

    def __post_init__(self) -> None:
        """Reject incomplete, protected or non-canonical audit evidence."""
        if self.model_contract_version != MODEL_CONTRACT_VERSION:
            raise ModelReportError("unexpected model contract version")
        if not self.dataset_contract_version.strip():
            raise ModelReportError("dataset contract version must not be blank")
        if not self.dataset_build_identifier.strip():
            raise ModelReportError("dataset build identifier must not be blank")
        if self.development_sessions <= 0:
            raise ModelReportError("development session count must be positive")
        if not (0 < self.contributing_training_sessions <= self.development_sessions):
            raise ModelReportError(
                "contributing training sessions must be within the audit catalog"
            )
        if self.primary_target_rows <= 0 or self.auxiliary_target_rows <= 0:
            raise ModelReportError("target row counts must be positive")
        if self.protected_evaluation_rows != 0:
            raise ModelReportError("protected evaluation rows entered Phase 6")
        if not isinstance(self.selected_formulation, PredictionFormulation):
            raise ModelReportError("selected formulation is outside the model contract")
        _validate_selected_candidate(self)
        if not self.final_model_artifact_id.strip():
            raise ModelReportError("final model artifact ID must not be blank")
        if self.random_seed != MODEL_RANDOM_SEED:
            raise ModelReportError("random seed differs from the model contract")
        if tuple(sorted(self.dependency_versions)) != self.dependency_versions:
            raise ModelReportError("dependency versions must be canonical")
        names = {name for name, _ in self.dependency_versions}
        if names != _REQUIRED_DEPENDENCIES:
            raise ModelReportError("dependency version evidence is incomplete")
        if any(not name or not value for name, value in self.dependency_versions):
            raise ModelReportError("dependency versions must not be blank")
        for name, value in (
            ("evaluation_duration_seconds", self.evaluation_duration_seconds),
            ("final_fit_duration_seconds", self.final_fit_duration_seconds),
        ):
            if not math.isfinite(value) or value < 0:
                raise ModelReportError(f"{name} must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class ModelReportVerification:
    """Integrity result for one stored Phase 6 evaluation report."""

    valid: bool
    artifact_count: int
    issues: tuple[str, ...]

    def raise_for_errors(self) -> None:
        """Fail closed when stored evaluation evidence is invalid."""
        if self.issues:
            raise ModelReportError(
                "model report verification failed: " + "; ".join(self.issues)
            )


def write_model_report(
    *,
    paths: ModelReportPaths,
    selection: TemporalSelectionReport,
    diagnostics: SelectedModelDiagnostics,
    provenance: ModelEvaluationProvenance,
) -> dict[str, object]:
    """Atomically publish selection, diagnostics and provenance."""
    _validate_report_sources(selection, diagnostics, provenance)
    if paths.root.exists():
        raise ModelReportError(f"model report already exists: {paths.root}")
    paths.root.parent.mkdir(parents=True, exist_ok=True)
    temporary = paths.root.parent / f".tmp-{paths.run_id}-{uuid4().hex}"
    temporary.mkdir()
    try:
        frames = _report_frames(selection, diagnostics)
        for file_name, frame_name, _ in _TABLE_SPECS:
            frames[frame_name].to_parquet(temporary / file_name, index=False)
        _write_json(temporary / "provenance.json", _provenance_document(provenance))
        artifacts = {
            name: {
                "sha256": _sha256(temporary / name),
                "size_bytes": (temporary / name).stat().st_size,
            }
            for name in MODEL_EVALUATION_FILES
        }
        manifest: dict[str, object] = {
            "format_version": MODEL_EVALUATION_FORMAT_VERSION,
            "model_contract_version": MODEL_CONTRACT_VERSION,
            "run_id": paths.run_id,
            "artifacts": artifacts,
        }
        _write_json(temporary / "manifest.json", manifest)
        os.replace(temporary, paths.root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    verification = verify_model_report(paths)
    if verification.issues:
        shutil.rmtree(paths.root, ignore_errors=True)
        verification.raise_for_errors()
    return manifest


def verify_model_report(paths: ModelReportPaths) -> ModelReportVerification:
    """Verify exact files, hashes, schemas, counts and selected identity."""
    issues: list[str] = []
    if not paths.manifest.is_file():
        return ModelReportVerification(
            valid=False,
            artifact_count=0,
            issues=("missing manifest.json",),
        )
    try:
        manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return ModelReportVerification(
            valid=False,
            artifact_count=0,
            issues=(f"invalid manifest: {error}",),
        )
    if not isinstance(manifest, dict):
        return ModelReportVerification(
            valid=False,
            artifact_count=0,
            issues=("manifest must be a JSON object",),
        )
    if manifest.get("format_version") != MODEL_EVALUATION_FORMAT_VERSION:
        issues.append("unexpected format_version")
    if manifest.get("model_contract_version") != MODEL_CONTRACT_VERSION:
        issues.append("unexpected model_contract_version")
    if manifest.get("run_id") != paths.run_id:
        issues.append("manifest run_id mismatch")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(MODEL_EVALUATION_FILES):
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
            provenance = _read_provenance(paths.root / "provenance.json")
            _validate_stored_report(frames, provenance=provenance)
        except Exception as error:  # noqa: BLE001
            issues.append(f"artifact readback failed: {type(error).__name__}: {error}")
    return ModelReportVerification(
        valid=not issues,
        artifact_count=len(artifacts),
        issues=tuple(issues),
    )


def _report_frames(
    selection: TemporalSelectionReport,
    diagnostics: SelectedModelDiagnostics,
) -> dict[str, pd.DataFrame]:
    """Return the six named tables stored by the report contract."""
    return {
        "fold_metrics": selection.fold_metrics,
        "pooled_metrics": selection.pooled_metrics,
        "selection": selection.selection,
        "slice_metrics": diagnostics.slice_metrics,
        "degradation_curve": diagnostics.degradation_curve,
        "identity_dependence": diagnostics.identity_dependence,
    }


def _validate_report_sources(
    selection: TemporalSelectionReport,
    diagnostics: SelectedModelDiagnostics,
    provenance: ModelEvaluationProvenance,
) -> None:
    """Reconcile in-memory evidence before any file is written."""
    if not isinstance(selection, TemporalSelectionReport):
        raise TypeError("selection must be a TemporalSelectionReport")
    if not isinstance(diagnostics, SelectedModelDiagnostics):
        raise TypeError("diagnostics must be SelectedModelDiagnostics")
    if not isinstance(provenance, ModelEvaluationProvenance):
        raise TypeError("provenance must be ModelEvaluationProvenance")
    if selection.selected_candidate is None:
        raise ModelReportError("selection has no qualifying candidate")
    selected = selection.selected_candidate
    if (
        selected.family != provenance.selected_family
        or selected.formulation != provenance.selected_formulation
        or selected.candidate_id != provenance.selected_candidate_id
        or selected.parameters != provenance.selected_parameters
    ):
        raise ModelReportError("selection and provenance candidate differ")
    frames = _report_frames(selection, diagnostics)
    _validate_stored_report(frames, provenance=provenance)


def _validate_stored_report(
    frames: dict[str, pd.DataFrame],
    *,
    provenance: ModelEvaluationProvenance,
) -> None:
    """Require exact schemas and complete selection evidence."""
    for _, frame_name, columns in _TABLE_SPECS:
        frame = frames[frame_name]
        if tuple(frame.columns) != columns:
            raise ModelReportError(f"{frame_name} columns differ from contract")
        if frame.empty:
            raise ModelReportError(f"{frame_name} must not be empty")
    if len(frames["fold_metrics"]) != 120:
        raise ModelReportError("fold_metrics must contain 120 rows")
    if len(frames["pooled_metrics"]) != 60:
        raise ModelReportError("pooled_metrics must contain 60 rows")
    if len(frames["selection"]) != 30:
        raise ModelReportError("selection must contain 30 rows")
    formulations = {
        PredictionFormulation(str(value))
        for value in frames["selection"]["formulation"]
    }
    if formulations != set(PredictionFormulation):
        raise ModelReportError("selection must compare both approved formulations")
    fold_ids = set(frames["fold_metrics"]["fold_id"].astype(str))
    if fold_ids != set(DEVELOPMENT_FOLDS):
        raise ModelReportError("fold_metrics differ from frozen folds")
    selected = frames["selection"].loc[frames["selection"]["selected"].eq(True)]
    if len(selected) != 1:
        raise ModelReportError("selection must identify exactly one winner")
    winner = selected.iloc[0]
    if (
        str(winner["formulation"]) != provenance.selected_formulation.value
        or str(winner["model_family"]) != provenance.selected_family.value
        or str(winner["candidate_id"]) != provenance.selected_candidate_id
        or str(winner["parameters"]) != provenance.selected_parameters
    ):
        raise ModelReportError("stored winner differs from provenance")


def _validate_selected_candidate(provenance: ModelEvaluationProvenance) -> None:
    """Require a declared family, grid member and matching candidate ID."""
    if not isinstance(provenance.selected_family, ModelFamily):
        raise ModelReportError("selected family is outside the model contract")
    try:
        parameters = json.loads(provenance.selected_parameters)
    except json.JSONDecodeError as error:
        raise ModelReportError("selected parameters are invalid JSON") from error
    if not isinstance(parameters, dict):
        raise ModelReportError("selected parameters must be a JSON object")
    specification = model_spec(provenance.selected_family)
    for index, candidate in enumerate(specification.parameter_grid, start=1):
        if candidate == parameters:
            expected = f"{provenance.selected_family.value}_{index:02d}"
            if provenance.selected_candidate_id != expected:
                raise ModelReportError("selected candidate ID differs from parameters")
            return
    raise ModelReportError("selected parameters are outside the approved grid")


def _verify_file_set(paths: ModelReportPaths, *, issues: list[str]) -> None:
    """Reject missing, extra or nested stored artifacts."""
    expected = {*MODEL_EVALUATION_FILES, "manifest.json"}
    try:
        actual = {item.name for item in paths.root.iterdir() if item.is_file()}
        if actual != expected:
            issues.append("stored artifact file set mismatch")
        if any(item.is_dir() for item in paths.root.iterdir()):
            issues.append("stored report contains an unexpected directory")
    except OSError as error:
        issues.append(f"report directory read failed: {error}")


def _verify_hashes(
    paths: ModelReportPaths,
    *,
    artifacts: dict[str, Any],
    issues: list[str],
) -> None:
    """Verify every payload size and SHA-256 digest."""
    for name in MODEL_EVALUATION_FILES:
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


def _provenance_document(
    provenance: ModelEvaluationProvenance,
) -> dict[str, object]:
    """Return deterministic JSON-compatible provenance."""
    document = asdict(provenance)
    document["selected_formulation"] = provenance.selected_formulation.value
    document["selected_family"] = provenance.selected_family.value
    return document


def _read_provenance(path: Path) -> ModelEvaluationProvenance:
    """Read and validate exact stored report provenance."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ModelReportError("provenance must be a JSON object")
    expected = set(ModelEvaluationProvenance.__dataclass_fields__)
    if set(document) != expected:
        raise ModelReportError("provenance fields differ from contract")
    return ModelEvaluationProvenance(
        model_contract_version=str(document["model_contract_version"]),
        dataset_contract_version=str(document["dataset_contract_version"]),
        dataset_build_identifier=str(document["dataset_build_identifier"]),
        development_sessions=int(document["development_sessions"]),
        contributing_training_sessions=int(document["contributing_training_sessions"]),
        primary_target_rows=int(document["primary_target_rows"]),
        auxiliary_target_rows=int(document["auxiliary_target_rows"]),
        protected_evaluation_rows=int(document["protected_evaluation_rows"]),
        selected_formulation=PredictionFormulation(
            str(document["selected_formulation"])
        ),
        selected_family=ModelFamily(str(document["selected_family"])),
        selected_candidate_id=str(document["selected_candidate_id"]),
        selected_parameters=str(document["selected_parameters"]),
        final_model_artifact_id=str(document["final_model_artifact_id"]),
        random_seed=int(document["random_seed"]),
        dependency_versions=tuple(
            (str(name), str(value)) for name, value in document["dependency_versions"]
        ),
        evaluation_duration_seconds=float(document["evaluation_duration_seconds"]),
        final_fit_duration_seconds=float(document["final_fit_duration_seconds"]),
    )


def _write_json(path: Path, document: object) -> None:
    """Write deterministic UTF-8 JSON."""
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
