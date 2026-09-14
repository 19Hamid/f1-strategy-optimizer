"""Prepare verified immutable artifacts before database transactions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from app.cleaning import (
    ProcessedDataPaths,
    verify_processed_partition,
)
from app.datasets import (
    DEVELOPMENT_SEASONS,
    DatasetPaths,
    validate_dataset_session_partition,
)
from app.pipeline import (
    RawDataPaths,
    SessionKey,
    verify_session_partition,
)
from app.pipeline.serialization import (
    read_json_document,
    read_parquet_table,
    sha256_file,
)


class DatabaseArtifactError(RuntimeError):
    """Raised when verified artifacts do not form one provenance chain."""


@dataclass(frozen=True, slots=True)
class PreparedSessionArtifacts:
    """Hold one fully verified session outside a write transaction."""

    session_key: SessionKey
    raw_directory: Path
    raw_manifest_path: Path
    raw_manifest_sha256: str
    raw_manifest: dict[str, object]
    raw_metadata: dict[str, object]
    processed_directory: Path
    processed_manifest_path: Path
    processed_manifest_sha256: str
    processed_manifest: dict[str, object]
    processed_quality_report: dict[str, object]
    processed_laps: pd.DataFrame
    reconstructed_stints: pd.DataFrame
    reconstructed_pit_events: pd.DataFrame
    dataset_directory: Path
    dataset_manifest_path: Path
    dataset_manifest_sha256: str
    dataset_manifest: dict[str, object]
    dataset_quality_report: dict[str, object]
    decision_rows: pd.DataFrame
    decision_labels: pd.DataFrame
    pit_duration_observations: pd.DataFrame


def prepare_session_artifacts(
    *,
    raw_paths: RawDataPaths,
    processed_paths: ProcessedDataPaths,
    dataset_paths: DatasetPaths,
    session_key: SessionKey,
) -> PreparedSessionArtifacts:
    """Verify and read one session completely before database access."""
    _require_development_session(session_key)
    if not isinstance(raw_paths, RawDataPaths):
        raise TypeError("raw_paths must be RawDataPaths")

    if not isinstance(processed_paths, ProcessedDataPaths):
        raise TypeError("processed_paths must be ProcessedDataPaths")

    if not isinstance(dataset_paths, DatasetPaths):
        raise TypeError("dataset_paths must be DatasetPaths")

    raw_report = verify_session_partition(raw_paths, session_key)
    raw_report.raise_for_errors()

    processed_report = verify_processed_partition(
        processed_paths,
        session_key,
    )
    processed_report.raise_for_errors()
    if processed_report.manifest is None:
        raise DatabaseArtifactError(
            "processed integrity passed without a manifest"
        )

    dataset_manifest, dataset_quality_report = (
        validate_dataset_session_partition(
            dataset_paths,
            session_key,
        )
    )
    raw_session_paths = raw_paths.for_session(session_key)
    processed_session_paths = processed_paths.for_session(session_key)
    dataset_session_paths = dataset_paths.for_session(session_key)
    raw_manifest = read_json_document(raw_session_paths.manifest)
    raw_metadata = read_json_document(raw_session_paths.metadata)
    processed_quality_report = read_json_document(
        processed_session_paths.quality_report
    )
    processed_tables = {
        name: read_parquet_table(path)
        for name, path in processed_session_paths.table_paths.items()
    }
    dataset_tables = {
        name: read_parquet_table(path)
        for name, path in dataset_session_paths.table_paths.items()
    }
    stored_processed_manifest = read_json_document(
        processed_session_paths.manifest
    )
    if stored_processed_manifest != processed_report.manifest:
        raise DatabaseArtifactError(
            "processed manifest changed after integrity validation"
        )

    stored_dataset_manifest = read_json_document(
        dataset_session_paths.manifest
    )
    if stored_dataset_manifest != dataset_manifest:
        raise DatabaseArtifactError(
            "dataset manifest changed after integrity validation"
        )

    _validate_manifest_file_hashes(
        manifest=raw_manifest,
        directory=raw_session_paths.directory,
        source="raw manifest",
    )
    _validate_manifest_file_hashes(
        manifest=processed_report.manifest,
        directory=processed_session_paths.directory,
        source="processed manifest",
    )
    _validate_manifest_file_hashes(
        manifest=dataset_manifest,
        directory=dataset_session_paths.directory,
        source="dataset manifest",
    )

    prepared = PreparedSessionArtifacts(
        session_key=session_key,
        raw_directory=raw_session_paths.directory,
        raw_manifest_path=raw_session_paths.manifest,
        raw_manifest_sha256=sha256_file(raw_session_paths.manifest),
        raw_manifest=raw_manifest,
        raw_metadata=raw_metadata,
        processed_directory=processed_session_paths.directory,
        processed_manifest_path=processed_session_paths.manifest,
        processed_manifest_sha256=sha256_file(
            processed_session_paths.manifest
        ),
        processed_manifest=processed_report.manifest,
        processed_quality_report=processed_quality_report,
        processed_laps=processed_tables["laps"],
        reconstructed_stints=processed_tables["stints"],
        reconstructed_pit_events=processed_tables["pit_events"],
        dataset_directory=dataset_session_paths.directory,
        dataset_manifest_path=dataset_session_paths.manifest,
        dataset_manifest_sha256=sha256_file(
            dataset_session_paths.manifest
        ),
        dataset_manifest=dataset_manifest,
        dataset_quality_report=dataset_quality_report,
        decision_rows=dataset_tables["decision_rows"],
        decision_labels=dataset_tables["decision_labels"],
        pit_duration_observations=(
            dataset_tables["pit_duration_observations"]
        ),
    )
    _validate_artifact_chain(prepared)
    return prepared


def _validate_manifest_file_hashes(
    *,
    manifest: dict[str, object],
    directory: Path,
    source: str,
) -> None:
    """Recheck every described file after all preparation reads."""
    files = _require_mapping(manifest, "files", source=source)
    for filename, value in files.items():
        if not isinstance(filename, str) or not isinstance(value, dict):
            raise DatabaseArtifactError(
                f"{source} contains an invalid file record"
            )

        expected = _require_text(
            value,
            "sha256",
            source=f"{source} {filename}",
        )
        if sha256_file(directory / filename) != expected:
            raise DatabaseArtifactError(
                f"{source} checksum changed for {filename}"
            )


def _require_development_session(session_key: SessionKey) -> None:
    """Reject protected or unsupported sessions before artifact access."""
    if not isinstance(session_key, SessionKey):
        raise TypeError("session_key must be a SessionKey")

    if session_key.season not in DEVELOPMENT_SEASONS:
        raise DatabaseArtifactError(
            f"{session_key.identifier} is outside the development seasons"
        )

    if session_key.session_type != "R":
        raise DatabaseArtifactError(
            f"{session_key.identifier} is not a race session"
        )


def _validate_artifact_chain(
    prepared: PreparedSessionArtifacts,
) -> None:
    """Require raw, processed and dataset provenance to agree exactly."""
    session_key = prepared.session_key
    raw_contract_version = _require_text(
        prepared.raw_manifest,
        "contract_version",
        source="raw manifest",
    )
    processed_source_version = _require_text(
        prepared.processed_manifest,
        "source_contract_version",
        source="processed manifest",
    )
    if raw_contract_version != processed_source_version:
        raise DatabaseArtifactError(
            "raw and processed source contract versions differ"
        )

    processed_contract_version = _require_text(
        prepared.processed_manifest,
        "processed_contract_version",
        source="processed manifest",
    )
    cleaning_rule_version = _require_text(
        prepared.processed_manifest,
        "cleaning_rule_version",
        source="processed manifest",
    )
    dataset_source = _require_mapping(
        prepared.dataset_manifest,
        "source",
        source="dataset manifest",
    )
    if (
        dataset_source.get("processed_contract_version")
        != processed_contract_version
        or dataset_source.get("cleaning_rule_version")
        != cleaning_rule_version
    ):
        raise DatabaseArtifactError(
            "dataset source versions differ from the processed manifest"
        )

    recorded_manifest_hash = _require_text(
        dataset_source,
        "manifest_sha256",
        source="dataset source",
    )
    actual_manifest_hash = sha256_file(prepared.processed_manifest_path)
    if recorded_manifest_hash != actual_manifest_hash:
        raise DatabaseArtifactError(
            "dataset source processed-manifest SHA-256 differs"
        )

    source_table_hashes = _require_mapping(
        dataset_source,
        "table_sha256",
        source="dataset source",
    )
    processed_files = _require_mapping(
        prepared.processed_manifest,
        "files",
        source="processed manifest",
    )
    for filename in (
        "laps.parquet",
        "stints.parquet",
        "pit_events.parquet",
    ):
        file_record = _require_mapping(
            processed_files,
            filename,
            source="processed manifest files",
        )
        processed_hash = _require_text(
            file_record,
            "sha256",
            source=f"processed {filename}",
        )
        if source_table_hashes.get(filename) != processed_hash:
            raise DatabaseArtifactError(
                f"dataset source hash differs for {filename}"
            )

    _require_identity(
        prepared.raw_metadata,
        session_key=session_key,
        source="raw metadata",
    )
    _require_identity(
        _require_mapping(
            prepared.raw_manifest,
            "session",
            source="raw manifest",
        ),
        session_key=session_key,
        source="raw manifest session",
    )
    _require_identity(
        _require_mapping(
            prepared.processed_manifest,
            "session",
            source="processed manifest",
        ),
        session_key=session_key,
        source="processed manifest session",
    )
    dataset_session = _require_mapping(
        prepared.dataset_manifest,
        "session",
        source="dataset manifest",
    )
    _require_identity(
        dataset_session,
        session_key=session_key,
        source="dataset manifest session",
    )

    event_name = _require_text(
        prepared.raw_metadata,
        "event_name",
        source="raw metadata",
    )
    if dataset_session.get("event_name") != event_name:
        raise DatabaseArtifactError(
            "raw and dataset event names differ"
        )

    for field in (
        "country",
        "location",
        "official_event_name",
        "event_format",
        "event_date",
    ):
        _require_text(prepared.raw_metadata, field, source="raw metadata")


def _require_identity(
    document: dict[str, object],
    *,
    session_key: SessionKey,
    source: str,
) -> None:
    """Require one document to identify the requested session."""
    expected = {
        "season": session_key.season,
        "round_number": session_key.round_number,
        "session_type": session_key.session_type,
    }
    if "identifier" in document:
        expected["identifier"] = session_key.identifier

    for field, expected_value in expected.items():
        if document.get(field) != expected_value:
            raise DatabaseArtifactError(
                f"{source} {field} differs from the requested session"
            )


def _require_mapping(
    document: dict[str, object],
    field: str,
    *,
    source: str,
) -> dict[str, object]:
    """Return one required nested object."""
    value = document.get(field)
    if not isinstance(value, dict):
        raise DatabaseArtifactError(f"{source} {field} must be an object")

    return value


def _require_text(
    document: dict[str, object],
    field: str,
    *,
    source: str,
) -> str:
    """Return one required, non-blank source string without mutation."""
    value = document.get(field)
    if not isinstance(value, str) or not value or value != value.strip():
        raise DatabaseArtifactError(
            f"{source} {field} must be non-blank canonical text"
        )

    return value
