"""Tests for the verified raw-data catalog."""

from pathlib import Path

import pytest

from app.pipeline.catalog import (
    CATALOG_COLUMNS,
    CatalogBuildError,
    RawCatalogBuilder,
)
from app.pipeline.integrity import (
    EXPECTED_SESSION_FILES,
    SessionIntegrityError,
)
from app.pipeline.models import SessionKey
from app.pipeline.paths import RawDataPaths
from app.pipeline.serialization import (
    read_parquet_table,
    sha256_file,
    write_json_document,
)


def create_complete_partition(
    raw_paths: RawDataPaths,
    session_key: SessionKey,
    event_name: str,
) -> None:
    """Create a lightweight but integrity-valid session partition."""
    session_paths = raw_paths.for_session(
        session_key
    )
    session_paths.directory.mkdir(
        parents=True,
    )

    file_records: dict[str, object] = {}

    for filename in EXPECTED_SESSION_FILES:
        path = session_paths.directory / filename

        if filename == "metadata.json":
            write_json_document(
                {
                    "season": session_key.season,
                    "round_number": session_key.round_number,
                    "session_type": session_key.session_type,
                    "event_name": event_name,
                    "telemetry_loaded": False,
                },
                path,
            )
        else:
            path.write_bytes(
                f"test data for {filename}".encode()
            )

        record: dict[str, object] = {
            "path": filename,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }

        if filename.endswith(".parquet"):
            record["rows"] = 10

        file_records[filename] = record

    manifest: dict[str, object] = {
        "contract_version": "1.0",
        "created_at_utc": "2026-08-29T12:00:00Z",
        "session": {
            "identifier": session_key.identifier,
            "season": session_key.season,
            "round_number": session_key.round_number,
            "session_type": session_key.session_type,
            "event_name": event_name,
        },
        "source": {
            "name": "FastF1",
            "version": "3.8.3",
        },
        "validation": {
            "status": "passed",
            "issue_count": 0,
        },
        "files": file_records,
    }

    write_json_document(
        manifest,
        session_paths.manifest,
    )


def test_builds_sorted_catalog_from_verified_sessions(
    tmp_path: Path,
) -> None:
    raw_paths = RawDataPaths(tmp_path / "raw")

    create_complete_partition(
        raw_paths,
        SessionKey(2024, 2),
        "Saudi Arabian Grand Prix",
    )
    create_complete_partition(
        raw_paths,
        SessionKey(2024, 1),
        "Bahrain Grand Prix",
    )

    result = RawCatalogBuilder(raw_paths).build()
    catalog = read_parquet_table(result.path)

    assert result.session_count == 2
    assert result.sha256 == sha256_file(result.path)
    assert tuple(catalog.columns) == CATALOG_COLUMNS
    assert catalog["session_id"].tolist() == [
        "2024-01-R",
        "2024-02-R",
    ]
    assert catalog["event_name"].tolist() == [
        "Bahrain Grand Prix",
        "Saudi Arabian Grand Prix",
    ]


def test_rejects_corrupted_session(
    tmp_path: Path,
) -> None:
    raw_paths = RawDataPaths(tmp_path / "raw")
    session_key = SessionKey(2024, 1)

    create_complete_partition(
        raw_paths,
        session_key,
        "Bahrain Grand Prix",
    )

    session_paths = raw_paths.for_session(session_key)
    session_paths.laps.write_bytes(b"corrupted")

    with pytest.raises(
        SessionIntegrityError,
        match="checksum_mismatch",
    ):
        RawCatalogBuilder(raw_paths).build()


def test_rejects_empty_raw_dataset(
    tmp_path: Path,
) -> None:
    raw_paths = RawDataPaths(tmp_path / "raw")

    with pytest.raises(
        CatalogBuildError,
        match="no completed session manifests",
    ):
        RawCatalogBuilder(raw_paths).build()


def test_rebuilds_catalog_without_duplicate_rows(
    tmp_path: Path,
) -> None:
    raw_paths = RawDataPaths(tmp_path / "raw")

    create_complete_partition(
        raw_paths,
        SessionKey(2024, 1),
        "Bahrain Grand Prix",
    )

    RawCatalogBuilder(raw_paths).build()

    create_complete_partition(
        raw_paths,
        SessionKey(2024, 2),
        "Saudi Arabian Grand Prix",
    )

    result = RawCatalogBuilder(raw_paths).build()
    catalog = read_parquet_table(result.path)

    assert result.session_count == 2
    assert catalog["session_id"].is_unique