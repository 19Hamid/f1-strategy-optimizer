"""Tests for preparing verified artifacts before database access."""

from pathlib import Path

import pandas as pd
import pytest

import app.db.artifacts as database_artifacts
from app.cleaning import ProcessedDataPaths
from app.datasets import DatasetPaths
from app.db.artifacts import (
    DatabaseArtifactError,
    prepare_session_artifacts,
)
from app.pipeline import RawDataPaths, SessionKey


class _IntegrityReport:
    """Minimal successful raw or processed integrity result."""

    def __init__(self, manifest: dict[str, object] | None = None) -> None:
        self.manifest = manifest

    def raise_for_errors(self) -> None:
        """Represent successful integrity validation."""


def _session_document() -> dict[str, object]:
    """Return one shared session identity."""
    return {
        "identifier": "2024-03-R",
        "season": 2024,
        "round_number": 3,
        "session_type": "R",
        "event_name": "Australian Grand Prix",
    }


def _artifact_documents() -> dict[str, dict[str, object]]:
    """Build a complete minimal provenance chain."""
    artifact_record = {"sha256": "artifact-hash"}
    processed_files = {
        "laps.parquet": artifact_record,
        "stints.parquet": artifact_record,
        "pit_events.parquet": artifact_record,
        "quality_report.json": artifact_record,
    }
    return {
        "raw_manifest": {
            "contract_version": "1.0",
            "session": _session_document(),
            "files": {
                "laps.parquet": artifact_record,
                "weather.parquet": artifact_record,
                "results.parquet": artifact_record,
                "metadata.json": artifact_record,
            },
        },
        "raw_metadata": {
            "season": 2024,
            "round_number": 3,
            "session_type": "R",
            "event_name": "Australian Grand Prix",
            "official_event_name": "Formula 1 Australian Grand Prix 2024",
            "country": "Australia",
            "location": "Melbourne",
            "event_format": "conventional",
            "event_date": "2024-03-24",
        },
        "processed_manifest": {
            "source_contract_version": "1.0",
            "processed_contract_version": "1.0",
            "cleaning_rule_version": "1.0",
            "session": _session_document(),
            "files": processed_files,
        },
        "processed_report": {"validation": {"status": "passed"}},
        "dataset_manifest": {
            "dataset_contract_version": "1.0",
            "session": _session_document(),
            "source": {
                "processed_contract_version": "1.0",
                "cleaning_rule_version": "1.0",
                "manifest_sha256": "processed-manifest-hash",
                "table_sha256": {
                    "laps.parquet": "artifact-hash",
                    "stints.parquet": "artifact-hash",
                    "pit_events.parquet": "artifact-hash",
                },
            },
            "files": {
                "decision_rows.parquet": artifact_record,
                "decision_labels.parquet": artifact_record,
                "pit_duration_observations.parquet": artifact_record,
                "quality_report.json": artifact_record,
            },
        },
        "dataset_report": {"validation": {"status": "passed"}},
    }


def _patch_artifact_sources(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path,
    documents: dict[str, dict[str, object]],
    calls: list[str],
) -> tuple[RawDataPaths, ProcessedDataPaths, DatasetPaths, SessionKey]:
    """Replace storage reads while keeping real deterministic paths."""
    session_key = SessionKey(2024, 3, "R")
    raw_paths = RawDataPaths(tmp_path / "raw")
    processed_paths = ProcessedDataPaths(tmp_path / "processed")
    dataset_paths = DatasetPaths(tmp_path / "datasets")
    raw_session = raw_paths.for_session(session_key)
    processed_session = processed_paths.for_session(session_key)
    dataset_session = dataset_paths.for_session(session_key)

    def verify_raw(*args: object) -> _IntegrityReport:
        calls.append("raw-verify")
        return _IntegrityReport()

    def verify_processed(*args: object) -> _IntegrityReport:
        calls.append("processed-verify")
        return _IntegrityReport(documents["processed_manifest"])

    def verify_dataset(*args: object) -> tuple[dict, dict]:
        calls.append("dataset-verify")
        return documents["dataset_manifest"], documents["dataset_report"]

    def read_json(path: Path) -> dict[str, object]:
        calls.append("read")
        if path == raw_session.manifest:
            return documents["raw_manifest"]
        if path == raw_session.metadata:
            return documents["raw_metadata"]
        if path == processed_session.quality_report:
            return documents["processed_report"]
        if path == processed_session.manifest:
            return documents["processed_manifest"]
        if path == dataset_session.manifest:
            return documents["dataset_manifest"]
        raise AssertionError(f"unexpected JSON path: {path}")

    monkeypatch.setattr(database_artifacts, "verify_session_partition", verify_raw)
    monkeypatch.setattr(
        database_artifacts,
        "verify_processed_partition",
        verify_processed,
    )
    monkeypatch.setattr(
        database_artifacts,
        "validate_dataset_session_partition",
        verify_dataset,
    )
    monkeypatch.setattr(database_artifacts, "read_json_document", read_json)
    monkeypatch.setattr(
        database_artifacts,
        "read_parquet_table",
        lambda path: pd.DataFrame(),
    )
    monkeypatch.setattr(
        database_artifacts,
        "sha256_file",
        lambda path: (
            "processed-manifest-hash"
            if path == processed_session.manifest
            else "artifact-hash"
        ),
    )
    return raw_paths, processed_paths, dataset_paths, session_key


def test_prepare_session_artifacts_verifies_before_reading(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Complete all filesystem integrity gates before loading any table."""
    calls: list[str] = []
    paths = _patch_artifact_sources(
        monkeypatch,
        tmp_path=tmp_path,
        documents=_artifact_documents(),
        calls=calls,
    )

    prepared = prepare_session_artifacts(
        raw_paths=paths[0],
        processed_paths=paths[1],
        dataset_paths=paths[2],
        session_key=paths[3],
    )

    assert prepared.session_key == paths[3]
    assert calls[:3] == [
        "raw-verify",
        "processed-verify",
        "dataset-verify",
    ]
    assert len(prepared.processed_laps) == 0
    assert len(prepared.decision_rows) == 0


def test_prepare_session_artifacts_rejects_broken_provenance_chain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject dataset hashes that do not identify the processed source."""
    documents = _artifact_documents()
    dataset_source = documents["dataset_manifest"]["source"]
    assert isinstance(dataset_source, dict)
    table_hashes = dataset_source["table_sha256"]
    assert isinstance(table_hashes, dict)
    table_hashes["laps.parquet"] = "different-hash"
    paths = _patch_artifact_sources(
        monkeypatch,
        tmp_path=tmp_path,
        documents=documents,
        calls=[],
    )

    with pytest.raises(
        DatabaseArtifactError,
        match="source hash differs for laps.parquet",
    ):
        prepare_session_artifacts(
            raw_paths=paths[0],
            processed_paths=paths[1],
            dataset_paths=paths[2],
            session_key=paths[3],
        )


def test_prepare_session_artifacts_rejects_2025_before_verification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Protect the evaluation season before any artifact is accessed."""
    verification_attempted = False

    def verify_raw(*args: object) -> _IntegrityReport:
        nonlocal verification_attempted
        verification_attempted = True
        return _IntegrityReport()

    monkeypatch.setattr(database_artifacts, "verify_session_partition", verify_raw)

    with pytest.raises(DatabaseArtifactError, match="development seasons"):
        prepare_session_artifacts(
            raw_paths=RawDataPaths(tmp_path / "raw"),
            processed_paths=ProcessedDataPaths(tmp_path / "processed"),
            dataset_paths=DatasetPaths(tmp_path / "datasets"),
            session_key=SessionKey(2025, 1, "R"),
        )

    assert verification_attempted is False
