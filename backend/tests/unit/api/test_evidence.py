from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from app.api import evidence
from app.api.evidence import (
    ApiEvidenceError,
    EvidenceArtifactKind,
    verify_development_evidence_bundle,
)


@dataclass(frozen=True)
class _Verification:
    valid: bool
    artifact_count: int
    issues: tuple[str, ...] = ()
    verification_rows: int = 128


def _install_valid_verifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        evidence,
        "verify_model_artifact",
        lambda paths: _Verification(valid=True, artifact_count=3),
    )
    monkeypatch.setattr(
        evidence,
        "verify_simulation_report",
        lambda paths: _Verification(valid=True, artifact_count=4),
    )
    monkeypatch.setattr(
        evidence,
        "verify_optimizer_report",
        lambda paths: _Verification(valid=True, artifact_count=4),
    )
    monkeypatch.setattr(
        evidence,
        "verify_concurrent_simulation_report",
        lambda paths: _Verification(valid=True, artifact_count=4),
    )


def test_evidence_bundle_verifies_every_phase(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_valid_verifiers(monkeypatch)

    bundle = verify_development_evidence_bundle(artifacts_root=tmp_path)

    assert bundle.artifacts_root == tmp_path
    assert tuple(item.kind for item in bundle.artifacts) == tuple(
        EvidenceArtifactKind
    )
    assert tuple(item.artifact_count for item in bundle.artifacts) == (
        3,
        4,
        4,
        4,
    )
    model = bundle.artifact_for(EvidenceArtifactKind.MODEL)
    assert model.identifier == "phase-6-final-audit-lap-time"
    assert model.verification_rows == 128


def test_evidence_bundle_passes_canonical_paths_to_verifiers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[EvidenceArtifactKind, object] = {}

    def capture(kind: EvidenceArtifactKind, result: _Verification):
        def verify(paths: object) -> _Verification:
            captured[kind] = paths
            return result

        return verify

    monkeypatch.setattr(
        evidence,
        "verify_model_artifact",
        capture(
            EvidenceArtifactKind.MODEL,
            _Verification(valid=True, artifact_count=3),
        ),
    )
    monkeypatch.setattr(
        evidence,
        "verify_simulation_report",
        capture(
            EvidenceArtifactKind.SIMULATION,
            _Verification(valid=True, artifact_count=4),
        ),
    )
    monkeypatch.setattr(
        evidence,
        "verify_optimizer_report",
        capture(
            EvidenceArtifactKind.OPTIMIZER,
            _Verification(valid=True, artifact_count=4),
        ),
    )
    monkeypatch.setattr(
        evidence,
        "verify_concurrent_simulation_report",
        capture(
            EvidenceArtifactKind.CONCURRENT_SIMULATION,
            _Verification(valid=True, artifact_count=4),
        ),
    )

    verify_development_evidence_bundle(artifacts_root=tmp_path)

    assert captured[EvidenceArtifactKind.MODEL].artifacts_root == tmp_path
    assert captured[EvidenceArtifactKind.SIMULATION].artifacts_root == tmp_path
    assert captured[EvidenceArtifactKind.OPTIMIZER].artifacts_root == tmp_path
    assert (
        captured[EvidenceArtifactKind.CONCURRENT_SIMULATION].artifacts_root
        == tmp_path
    )


def test_evidence_bundle_fails_closed_on_invalid_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_valid_verifiers(monkeypatch)
    monkeypatch.setattr(
        evidence,
        "verify_optimizer_report",
        lambda paths: _Verification(
            valid=False,
            artifact_count=0,
            issues=("manifest hash mismatch",),
        ),
    )

    with pytest.raises(
        ApiEvidenceError,
        match="OPTIMIZER evidence.*manifest hash mismatch",
    ):
        verify_development_evidence_bundle(artifacts_root=tmp_path)


def test_evidence_bundle_rejects_missing_real_artifacts(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ApiEvidenceError,
        match="MODEL evidence.*missing manifest.json",
    ):
        verify_development_evidence_bundle(artifacts_root=tmp_path)


def test_evidence_bundle_rejects_unsafe_identity(tmp_path: Path) -> None:
    with pytest.raises(
        ApiEvidenceError,
        match="development evidence verification failed",
    ):
        verify_development_evidence_bundle(
            artifacts_root=tmp_path,
            model_artifact_id="../model",
        )
