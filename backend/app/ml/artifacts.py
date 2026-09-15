"""Atomic, integrity-checked storage for fitted Phase 6 models."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import shutil
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

import joblib
import numpy as np
import pandas as pd

from app.ml.contracts import (
    APPROVED_FEATURE_COLUMNS,
    IDENTITY_ABLATION_FEATURE_COLUMNS,
    MODEL_CONTRACT_VERSION,
    MODEL_RANDOM_SEED,
    PROTECTED_EVALUATION_SEASON,
    ModelFamily,
    ModelTarget,
    model_spec,
)
from app.ml.training import (
    FULL_FEATURE_SET_ID,
    IDENTITY_ABLATION_FEATURE_SET_ID,
    TrainedCandidateModel,
)

MODEL_ARTIFACT_DIRECTORY_NAME: Final = "models"
MODEL_ARTIFACT_FORMAT_VERSION: Final = "1.0"
MODEL_ARTIFACT_MAX_VERIFICATION_ROWS: Final = 128
MODEL_ARTIFACT_FILES: Final = (
    "model.joblib",
    "provenance.json",
    "verification.parquet",
)
_VERIFICATION_PREDICTION_COLUMN: Final = "expected_prediction_seconds"
_REQUIRED_DEPENDENCIES: Final = frozenset(
    {"joblib", "numpy", "pandas", "python", "scikit-learn"}
)


class ModelArtifactError(RuntimeError):
    """Raised when a fitted model artifact is invalid or unsafe to load."""


@dataclass(frozen=True, slots=True)
class ModelArtifactPaths:
    """Canonical paths for one immutable fitted-model artifact."""

    artifacts_root: Path
    artifact_id: str

    def __post_init__(self) -> None:
        """Normalize the root and reject traversal through the identity."""
        object.__setattr__(self, "artifacts_root", Path(self.artifacts_root))
        normalized = self.artifact_id.strip()
        if (
            not normalized
            or normalized in {".", ".."}
            or Path(normalized).name != normalized
            or "/" in normalized
            or "\\" in normalized
        ):
            raise ModelArtifactError(
                "artifact_id must be one safe path segment"
            )
        object.__setattr__(self, "artifact_id", normalized)

    @property
    def root(self) -> Path:
        """Return the immutable artifact directory."""
        return (
            self.artifacts_root
            / MODEL_ARTIFACT_DIRECTORY_NAME
            / f"contract_version={MODEL_CONTRACT_VERSION}"
            / f"artifact_id={self.artifact_id}"
        )

    @property
    def manifest(self) -> Path:
        """Return the integrity manifest path."""
        return self.root / "manifest.json"


@dataclass(frozen=True, slots=True)
class ModelArtifactProvenance:
    """Frozen training, model and runtime identity for one fitted model."""

    model_contract_version: str
    dataset_contract_version: str
    dataset_build_identifier: str
    fold_id: str
    target: ModelTarget
    family: ModelFamily
    candidate_id: str
    feature_set_id: str
    parameters: tuple[tuple[str, object], ...]
    feature_columns: tuple[str, ...]
    training_session_ids: tuple[str, ...]
    training_seasons: tuple[int, ...]
    validation_session_ids: tuple[str, ...]
    random_seed: int
    dependency_versions: tuple[tuple[str, str], ...]
    fit_duration_seconds: float

    def __post_init__(self) -> None:
        """Fail closed on incomplete, protected or non-canonical evidence."""
        if self.model_contract_version != MODEL_CONTRACT_VERSION:
            raise ModelArtifactError("unexpected model contract version")
        if not self.dataset_contract_version.strip():
            raise ModelArtifactError("dataset_contract_version must not be blank")
        if not self.dataset_build_identifier.strip():
            raise ModelArtifactError("dataset_build_identifier must not be blank")
        if not self.fold_id.strip():
            raise ModelArtifactError("fold_id must not be blank")
        if not isinstance(self.target, ModelTarget):
            raise ModelArtifactError("target is outside the model contract")
        if not isinstance(self.family, ModelFamily):
            raise ModelArtifactError("family is outside the model contract")
        _validate_candidate_identity(self)
        _validate_feature_identity(self)
        _validate_session_identity(self)
        dependency_names = {name for name, _ in self.dependency_versions}
        if tuple(sorted(self.dependency_versions)) != self.dependency_versions:
            raise ModelArtifactError("dependency versions must be canonical")
        if dependency_names != _REQUIRED_DEPENDENCIES:
            raise ModelArtifactError("dependency version evidence is incomplete")
        if any(not name or not value for name, value in self.dependency_versions):
            raise ModelArtifactError("dependency versions must not be blank")
        if self.random_seed != MODEL_RANDOM_SEED:
            raise ModelArtifactError("random seed differs from the model contract")
        if (
            not math.isfinite(self.fit_duration_seconds)
            or self.fit_duration_seconds < 0
        ):
            raise ModelArtifactError(
                "fit_duration_seconds must be finite and non-negative"
            )


@dataclass(frozen=True, slots=True)
class ModelArtifactVerificationReport:
    """Integrity and inference-reproduction result for one artifact."""

    valid: bool
    artifact_count: int
    verification_rows: int
    issues: tuple[str, ...]

    def raise_for_errors(self) -> None:
        """Fail closed before an invalid model reaches inference."""
        if self.issues:
            raise ModelArtifactError(
                "model artifact verification failed: "
                + "; ".join(self.issues)
            )


@dataclass(frozen=True, slots=True)
class LoadedModelArtifact:
    """A verified fitted model and its immutable provenance."""

    model: TrainedCandidateModel
    provenance: ModelArtifactProvenance

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        """Run inference through the stored training-only preprocessor."""
        return self.model.predict(features)


def runtime_model_dependency_versions() -> tuple[tuple[str, str], ...]:
    """Capture versions capable of changing fit or inference behaviour."""
    dependencies = {"python": platform.python_version()}
    for package in ("joblib", "numpy", "pandas", "scikit-learn"):
        try:
            dependencies[package] = version(package)
        except PackageNotFoundError as error:
            raise ModelArtifactError(
                f"required dependency is not installed: {package}"
            ) from error
    return tuple(sorted(dependencies.items()))


def model_artifact_provenance(
    model: TrainedCandidateModel,
    *,
    dataset_contract_version: str,
    dataset_build_identifier: str,
    training_session_ids: tuple[str, ...],
    training_seasons: tuple[int, ...],
    validation_session_ids: tuple[str, ...] = (),
    fit_duration_seconds: float = 0.0,
    dependency_versions: tuple[tuple[str, str], ...] | None = None,
) -> ModelArtifactProvenance:
    """Build canonical provenance directly from a fitted model."""
    if not isinstance(model, TrainedCandidateModel):
        raise TypeError("model must be a TrainedCandidateModel")
    return ModelArtifactProvenance(
        model_contract_version=MODEL_CONTRACT_VERSION,
        dataset_contract_version=dataset_contract_version.strip(),
        dataset_build_identifier=dataset_build_identifier.strip(),
        fold_id=model.fold_id,
        target=model.target,
        family=model.family,
        candidate_id=model.candidate_id,
        feature_set_id=model.feature_set_id,
        parameters=model.parameters,
        feature_columns=model.preprocessor.feature_columns,
        training_session_ids=tuple(sorted(set(training_session_ids))),
        training_seasons=tuple(sorted(set(training_seasons))),
        validation_session_ids=tuple(sorted(set(validation_session_ids))),
        random_seed=MODEL_RANDOM_SEED,
        dependency_versions=(
            runtime_model_dependency_versions()
            if dependency_versions is None
            else tuple(sorted(dependency_versions))
        ),
        fit_duration_seconds=float(fit_duration_seconds),
    )


def write_model_artifact(
    *,
    paths: ModelArtifactPaths,
    model: TrainedCandidateModel,
    provenance: ModelArtifactProvenance,
    verification_features: pd.DataFrame,
) -> dict[str, object]:
    """Publish one immutable bundle through a sibling temporary directory."""
    _validate_model_provenance(model, provenance)
    verification = _verification_table(model, verification_features)
    if paths.root.exists():
        raise ModelArtifactError(f"model artifact already exists: {paths.root}")
    paths.root.parent.mkdir(parents=True, exist_ok=True)
    temporary = paths.root.parent / f".tmp-{paths.artifact_id}-{uuid4().hex}"
    temporary.mkdir()
    try:
        joblib.dump(model, temporary / "model.joblib", compress=3)
        _write_json(
            temporary / "provenance.json",
            _provenance_document(provenance),
        )
        verification.to_parquet(
            temporary / "verification.parquet",
            index=False,
        )
        artifacts = {
            name: {
                "sha256": _sha256(temporary / name),
                "size_bytes": (temporary / name).stat().st_size,
            }
            for name in MODEL_ARTIFACT_FILES
        }
        manifest: dict[str, object] = {
            "artifact_id": paths.artifact_id,
            "format_version": MODEL_ARTIFACT_FORMAT_VERSION,
            "model_contract_version": MODEL_CONTRACT_VERSION,
            "artifacts": artifacts,
        }
        _write_json(temporary / "manifest.json", manifest)
        os.replace(temporary, paths.root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    report = verify_model_artifact(paths)
    if report.issues:
        shutil.rmtree(paths.root, ignore_errors=True)
        report.raise_for_errors()
    return manifest


def verify_model_artifact(
    paths: ModelArtifactPaths,
) -> ModelArtifactVerificationReport:
    """Verify file identity, hashes, metadata and reloaded predictions."""
    issues: list[str] = []
    verification_rows = 0
    if not paths.manifest.is_file():
        return ModelArtifactVerificationReport(
            valid=False,
            artifact_count=0,
            verification_rows=0,
            issues=("missing manifest.json",),
        )
    try:
        manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return ModelArtifactVerificationReport(
            valid=False,
            artifact_count=0,
            verification_rows=0,
            issues=(f"invalid manifest: {error}",),
        )
    if not isinstance(manifest, dict):
        return ModelArtifactVerificationReport(
            valid=False,
            artifact_count=0,
            verification_rows=0,
            issues=("manifest must be a JSON object",),
        )

    _verify_manifest_identity(manifest, paths=paths, issues=issues)
    artifacts = manifest.get("artifacts")
    if (
        not isinstance(artifacts, dict)
        or set(artifacts) != set(MODEL_ARTIFACT_FILES)
    ):
        issues.append("manifest artifact set mismatch")
        artifacts = {}
    expected_files = {*MODEL_ARTIFACT_FILES, "manifest.json"}
    try:
        actual_files = {
            item.name for item in paths.root.iterdir() if item.is_file()
        }
        if actual_files != expected_files:
            issues.append("stored artifact file set mismatch")
        if any(item.is_dir() for item in paths.root.iterdir()):
            issues.append("stored artifact contains an unexpected directory")
    except OSError as error:
        issues.append(f"artifact directory read failed: {error}")

    for name in MODEL_ARTIFACT_FILES:
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
            provenance = _read_provenance(paths.root / "provenance.json")
            verification = pd.read_parquet(
                paths.root / "verification.parquet"
            )
            verification_rows = len(verification)
            _validate_verification_table(verification)
            model = joblib.load(paths.root / "model.joblib")
            if not isinstance(model, TrainedCandidateModel):
                raise ModelArtifactError(
                    "model.joblib does not contain a trained candidate"
                )
            _validate_model_provenance(model, provenance)
            predictions = model.predict(
                verification.loc[:, APPROVED_FEATURE_COLUMNS]
            )
            expected_predictions = verification[
                _VERIFICATION_PREDICTION_COLUMN
            ].to_numpy(dtype="float64")
            if not np.array_equal(predictions, expected_predictions):
                raise ModelArtifactError(
                    "reloaded model predictions differ from stored evidence"
                )
        except Exception as error:  # noqa: BLE001
            issues.append(
                "artifact readback failed: "
                f"{type(error).__name__}: {error}"
            )

    return ModelArtifactVerificationReport(
        valid=not issues,
        artifact_count=len(artifacts),
        verification_rows=verification_rows,
        issues=tuple(issues),
    )


def load_model_artifact(paths: ModelArtifactPaths) -> LoadedModelArtifact:
    """Return a model only after complete integrity and inference checks."""
    report = verify_model_artifact(paths)
    report.raise_for_errors()
    model = joblib.load(paths.root / "model.joblib")
    provenance = _read_provenance(paths.root / "provenance.json")
    return LoadedModelArtifact(model=model, provenance=provenance)


def _validate_candidate_identity(provenance: ModelArtifactProvenance) -> None:
    """Require an exact family grid member and its stable candidate ID."""
    parameters = dict(provenance.parameters)
    if tuple(sorted(provenance.parameters)) != provenance.parameters:
        raise ModelArtifactError("model parameters must be canonical")
    specification = model_spec(provenance.family)
    for index, candidate in enumerate(specification.parameter_grid, start=1):
        if candidate == parameters:
            expected_id = f"{provenance.family.value}_{index:02d}"
            if provenance.candidate_id != expected_id:
                raise ModelArtifactError("candidate_id differs from parameters")
            return
    raise ModelArtifactError("parameters are outside the approved model grid")


def _validate_feature_identity(provenance: ModelArtifactProvenance) -> None:
    """Require either the full or approved identity-ablation schema."""
    if provenance.feature_columns == APPROVED_FEATURE_COLUMNS:
        expected = FULL_FEATURE_SET_ID
    elif provenance.feature_columns == IDENTITY_ABLATION_FEATURE_COLUMNS:
        expected = IDENTITY_ABLATION_FEATURE_SET_ID
    else:
        raise ModelArtifactError("feature columns are outside the model contract")
    if provenance.feature_set_id != expected:
        raise ModelArtifactError("feature_set_id differs from feature columns")


def _validate_session_identity(provenance: ModelArtifactProvenance) -> None:
    """Require canonical development-only session evidence."""
    if not provenance.training_session_ids:
        raise ModelArtifactError("training_session_ids must not be empty")
    for label, values in (
        ("training_session_ids", provenance.training_session_ids),
        ("validation_session_ids", provenance.validation_session_ids),
    ):
        if tuple(sorted(set(values))) != values or any(not value for value in values):
            raise ModelArtifactError(f"{label} must be canonical")
    if set(provenance.training_session_ids) & set(
        provenance.validation_session_ids
    ):
        raise ModelArtifactError("training and validation sessions overlap")
    if not provenance.training_seasons:
        raise ModelArtifactError("training_seasons must not be empty")
    if tuple(sorted(set(provenance.training_seasons))) != (
        provenance.training_seasons
    ):
        raise ModelArtifactError("training_seasons must be canonical")
    if PROTECTED_EVALUATION_SEASON in provenance.training_seasons:
        raise ModelArtifactError(
            f"protected {PROTECTED_EVALUATION_SEASON} entered training provenance"
        )
    unknown = set(provenance.training_seasons).difference({2022, 2023, 2024})
    if unknown:
        raise ModelArtifactError(
            f"training provenance contains unknown seasons: {sorted(unknown)}"
        )


def _validate_model_provenance(
    model: TrainedCandidateModel,
    provenance: ModelArtifactProvenance,
) -> None:
    """Reconcile serialized estimator identity with JSON evidence."""
    if not isinstance(model, TrainedCandidateModel):
        raise TypeError("model must be a TrainedCandidateModel")
    comparisons = {
        "fold_id": (model.fold_id, provenance.fold_id),
        "target": (model.target, provenance.target),
        "family": (model.family, provenance.family),
        "candidate_id": (model.candidate_id, provenance.candidate_id),
        "feature_set_id": (
            model.feature_set_id,
            provenance.feature_set_id,
        ),
        "parameters": (model.parameters, provenance.parameters),
        "feature_columns": (
            model.preprocessor.feature_columns,
            provenance.feature_columns,
        ),
    }
    mismatches = [
        name for name, (actual, expected) in comparisons.items()
        if actual != expected
    ]
    if mismatches:
        raise ModelArtifactError(
            "model and provenance differ: " + ", ".join(mismatches)
        )


def _verification_table(
    model: TrainedCandidateModel,
    features: pd.DataFrame,
) -> pd.DataFrame:
    """Store bounded raw inputs and their exact pre-serialization output."""
    if not isinstance(features, pd.DataFrame):
        raise TypeError("verification_features must be a pandas DataFrame")
    if tuple(features.columns) != APPROVED_FEATURE_COLUMNS:
        raise ModelArtifactError(
            "verification features differ from the approved source schema"
        )
    if len(features) == 0 or len(features) > MODEL_ARTIFACT_MAX_VERIFICATION_ROWS:
        raise ModelArtifactError(
            "verification features must contain between 1 and "
            f"{MODEL_ARTIFACT_MAX_VERIFICATION_ROWS} rows"
        )
    table = features.reset_index(drop=True).copy()
    table[_VERIFICATION_PREDICTION_COLUMN] = model.predict(table)
    return table


def _validate_verification_table(table: pd.DataFrame) -> None:
    """Require the exact bounded inference-fingerprint schema."""
    expected_columns = (
        *APPROVED_FEATURE_COLUMNS,
        _VERIFICATION_PREDICTION_COLUMN,
    )
    if tuple(table.columns) != expected_columns:
        raise ModelArtifactError("verification table schema differs from contract")
    if len(table) == 0 or len(table) > MODEL_ARTIFACT_MAX_VERIFICATION_ROWS:
        raise ModelArtifactError("verification table row count is invalid")
    expected = pd.to_numeric(
        table[_VERIFICATION_PREDICTION_COLUMN],
        errors="coerce",
    ).to_numpy(dtype="float64")
    if not np.isfinite(expected).all():
        raise ModelArtifactError("verification predictions are non-finite")


def _verify_manifest_identity(
    manifest: dict[str, Any],
    *,
    paths: ModelArtifactPaths,
    issues: list[str],
) -> None:
    """Check the unhashed envelope before reading payload files."""
    if manifest.get("artifact_id") != paths.artifact_id:
        issues.append("manifest artifact_id mismatch")
    if manifest.get("format_version") != MODEL_ARTIFACT_FORMAT_VERSION:
        issues.append("unexpected format_version")
    if manifest.get("model_contract_version") != MODEL_CONTRACT_VERSION:
        issues.append("unexpected model_contract_version")


def _provenance_document(
    provenance: ModelArtifactProvenance,
) -> dict[str, object]:
    """Return stable JSON-compatible provenance."""
    document = asdict(provenance)
    document["target"] = provenance.target.value
    document["family"] = provenance.family.value
    return document


def _read_provenance(path: Path) -> ModelArtifactProvenance:
    """Read and validate the exact stored provenance schema."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ModelArtifactError("provenance must be a JSON object")
    expected_fields = set(ModelArtifactProvenance.__dataclass_fields__)
    if set(document) != expected_fields:
        raise ModelArtifactError("provenance fields differ from contract")
    return ModelArtifactProvenance(
        model_contract_version=str(document["model_contract_version"]),
        dataset_contract_version=str(document["dataset_contract_version"]),
        dataset_build_identifier=str(document["dataset_build_identifier"]),
        fold_id=str(document["fold_id"]),
        target=ModelTarget(str(document["target"])),
        family=ModelFamily(str(document["family"])),
        candidate_id=str(document["candidate_id"]),
        feature_set_id=str(document["feature_set_id"]),
        parameters=tuple(
            (str(name), value) for name, value in document["parameters"]
        ),
        feature_columns=tuple(str(value) for value in document["feature_columns"]),
        training_session_ids=tuple(
            str(value) for value in document["training_session_ids"]
        ),
        training_seasons=tuple(
            int(value) for value in document["training_seasons"]
        ),
        validation_session_ids=tuple(
            str(value) for value in document["validation_session_ids"]
        ),
        random_seed=int(document["random_seed"]),
        dependency_versions=tuple(
            (str(name), str(value))
            for name, value in document["dependency_versions"]
        ),
        fit_duration_seconds=float(document["fit_duration_seconds"]),
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
