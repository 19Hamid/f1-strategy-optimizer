"""Fail-closed access to verified Phase 6-9 development evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol

from app.concurrent_simulation.storage import (
    ConcurrentSimulationReportPaths,
    ConcurrentSimulationStorageError,
    verify_concurrent_simulation_report,
)
from app.ml.artifacts import (
    ModelArtifactError,
    ModelArtifactPaths,
    verify_model_artifact,
)
from app.optimizer.storage import (
    OptimizerReportPaths,
    OptimizerStorageError,
    verify_optimizer_report,
)
from app.simulation.storage import (
    SimulationReportPaths,
    SimulationStorageError,
    verify_simulation_report,
)

PROJECT_ROOT: Final = Path(__file__).resolve().parents[3]
DEFAULT_ARTIFACTS_ROOT: Final = PROJECT_ROOT / "artifacts"
DEFAULT_MODEL_ARTIFACT_ID: Final = "phase-6-final-audit-lap-time"
DEFAULT_SIMULATION_RUN_ID: Final = "phase-7-final-audit"
DEFAULT_OPTIMIZER_RUN_ID: Final = "phase-8-final-audit"
DEFAULT_CONCURRENT_SIMULATION_RUN_ID: Final = "phase-9-final-audit"


class ApiEvidenceError(RuntimeError):
    """Raised when API evidence is missing, invalid or unsafe to expose."""


class EvidenceArtifactKind(StrEnum):
    """Verified upstream evidence categories required by the V1 API."""

    MODEL = "MODEL"
    SIMULATION = "SIMULATION"
    OPTIMIZER = "OPTIMIZER"
    CONCURRENT_SIMULATION = "CONCURRENT_SIMULATION"


class _VerificationResult(Protocol):
    valid: bool
    artifact_count: int
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VerifiedEvidenceArtifact:
    """Compact identity and integrity result for one upstream artifact."""

    kind: EvidenceArtifactKind
    identifier: str
    artifact_count: int
    verification_rows: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EvidenceArtifactKind):
            raise TypeError("kind must be an EvidenceArtifactKind")
        if not self.identifier.strip():
            raise ApiEvidenceError("evidence identifier must not be blank")
        if self.artifact_count < 1:
            raise ApiEvidenceError("verified evidence must contain artifacts")
        if self.verification_rows is not None and self.verification_rows < 1:
            raise ApiEvidenceError(
                "model evidence must contain verification rows"
            )


@dataclass(frozen=True, slots=True)
class DevelopmentEvidenceBundle:
    """All verified Phase 6-9 evidence required by public API services."""

    artifacts_root: Path
    artifacts: tuple[VerifiedEvidenceArtifact, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifacts_root", Path(self.artifacts_root))
        expected = tuple(EvidenceArtifactKind)
        actual = tuple(artifact.kind for artifact in self.artifacts)
        if actual != expected:
            raise ApiEvidenceError(
                "development evidence bundle is incomplete or unordered"
            )

    def artifact_for(
        self,
        kind: EvidenceArtifactKind,
    ) -> VerifiedEvidenceArtifact:
        """Return one verified artifact by its stable category."""
        normalized = EvidenceArtifactKind(kind)
        for artifact in self.artifacts:
            if artifact.kind is normalized:
                return artifact
        raise ApiEvidenceError(f"verified evidence is unavailable: {normalized}")


def verify_development_evidence_bundle(
    *,
    artifacts_root: Path = DEFAULT_ARTIFACTS_ROOT,
    model_artifact_id: str = DEFAULT_MODEL_ARTIFACT_ID,
    simulation_run_id: str = DEFAULT_SIMULATION_RUN_ID,
    optimizer_run_id: str = DEFAULT_OPTIMIZER_RUN_ID,
    concurrent_simulation_run_id: str = (
        DEFAULT_CONCURRENT_SIMULATION_RUN_ID
    ),
) -> DevelopmentEvidenceBundle:
    """Verify every upstream artifact before the API reads any evidence."""
    root = Path(artifacts_root)
    try:
        model = verify_model_artifact(
            ModelArtifactPaths(root, model_artifact_id)
        )
        simulation = verify_simulation_report(
            SimulationReportPaths(root, simulation_run_id)
        )
        optimizer = verify_optimizer_report(
            OptimizerReportPaths(root, optimizer_run_id)
        )
        concurrent = verify_concurrent_simulation_report(
            ConcurrentSimulationReportPaths(
                root,
                concurrent_simulation_run_id,
            )
        )
    except (
        ModelArtifactError,
        SimulationStorageError,
        OptimizerStorageError,
        ConcurrentSimulationStorageError,
    ) as error:
        raise ApiEvidenceError(
            f"development evidence verification failed: {error}"
        ) from error

    artifacts = (
        _verified_artifact(
            EvidenceArtifactKind.MODEL,
            model_artifact_id,
            model,
            verification_rows=model.verification_rows,
        ),
        _verified_artifact(
            EvidenceArtifactKind.SIMULATION,
            simulation_run_id,
            simulation,
        ),
        _verified_artifact(
            EvidenceArtifactKind.OPTIMIZER,
            optimizer_run_id,
            optimizer,
        ),
        _verified_artifact(
            EvidenceArtifactKind.CONCURRENT_SIMULATION,
            concurrent_simulation_run_id,
            concurrent,
        ),
    )
    return DevelopmentEvidenceBundle(
        artifacts_root=root,
        artifacts=artifacts,
    )


def _verified_artifact(
    kind: EvidenceArtifactKind,
    identifier: str,
    verification: _VerificationResult,
    *,
    verification_rows: int | None = None,
) -> VerifiedEvidenceArtifact:
    issues = tuple(verification.issues)
    if not verification.valid or issues:
        detail = "; ".join(issues) if issues else "verification returned invalid"
        raise ApiEvidenceError(
            f"{kind.value} evidence {identifier!r} is invalid: {detail}"
        )
    return VerifiedEvidenceArtifact(
        kind=kind,
        identifier=identifier,
        artifact_count=verification.artifact_count,
        verification_rows=verification_rows,
    )
