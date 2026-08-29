"""Atomically store validated raw Formula 1 session data."""

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pandas as pd

from app.pipeline.paths import RawDataPaths, SessionPaths
from app.pipeline.serialization import (
    read_json_document,
    read_parquet_table,
    sha256_file,
    write_json_document,
    write_parquet_table,
)
from app.pipeline.source import RawSessionData
from app.pipeline.validation import validate_raw_session

RAW_CONTRACT_VERSION = "1.0"


class IncompleteSessionDirectoryError(RuntimeError):
    """Raised when a final session directory has no manifest."""


class ParquetReadbackError(RuntimeError):
    """Raised when a stored Parquet table differs from its source."""


@dataclass(frozen=True, slots=True)
class SessionWriteResult:
    """Describe the outcome of storing one race session."""

    status: Literal["written", "skipped"]
    directory: Path
    manifest: dict[str, object]


@dataclass(frozen=True, slots=True)
class RawSessionWriter:
    """Write complete raw session partitions safely."""

    raw_paths: RawDataPaths

    def write(
        self,
        raw_session: RawSessionData,
        *,
        force: bool = False,
    ) -> SessionWriteResult:
        """Validate and store one raw race session."""
        if not isinstance(force, bool):
            raise TypeError("force must be a boolean")

        session_paths = self.raw_paths.for_session(
            raw_session.session_key
        )
        backup_directory = _backup_directory(session_paths)

        _recover_backup(
            session_paths,
            backup_directory,
        )

        report = validate_raw_session(raw_session)
        report.raise_for_errors()

        if session_paths.manifest.is_file() and not force:
            return SessionWriteResult(
                status="skipped",
                directory=session_paths.directory,
                manifest=read_json_document(
                    session_paths.manifest
                ),
            )

        if session_paths.directory.exists() and not force:
            raise IncompleteSessionDirectoryError(
                "session directory exists without a completed "
                f"manifest: {session_paths.directory}"
            )

        if session_paths.temporary_directory.exists():
            shutil.rmtree(
                session_paths.temporary_directory
            )

        session_paths.temporary_directory.mkdir(
            parents=True,
            exist_ok=False,
        )

        try:
            manifest = _write_temporary_session(
                raw_session,
                session_paths.temporary_directory,
            )
            _promote_temporary_session(
                session_paths,
                backup_directory,
            )
        finally:
            if session_paths.temporary_directory.exists():
                shutil.rmtree(
                    session_paths.temporary_directory
                )

        return SessionWriteResult(
            status="written",
            directory=session_paths.directory,
            manifest=manifest,
        )


def _write_temporary_session(
    raw_session: RawSessionData,
    temporary_directory: Path,
) -> dict[str, object]:
    """Write and verify all temporary session files."""
    file_records: dict[str, object] = {}

    tables = {
        "laps": raw_session.laps,
        "weather": raw_session.weather,
        "results": raw_session.results,
    }

    for table_name, table in tables.items():
        filename = f"{table_name}.parquet"
        path = temporary_directory / filename

        file_records[filename] = _write_parquet_file(
            table_name=table_name,
            table=table,
            path=path,
        )

    metadata_path = temporary_directory / "metadata.json"

    write_json_document(
        raw_session.metadata,
        metadata_path,
    )

    restored_metadata = read_json_document(metadata_path)

    if restored_metadata != raw_session.metadata:
        raise ValueError(
            "metadata JSON readback differs from its source"
        )

    file_records["metadata.json"] = {
        "path": metadata_path.name,
        "sha256": sha256_file(metadata_path),
        "size_bytes": metadata_path.stat().st_size,
    }

    manifest: dict[str, object] = {
        "contract_version": RAW_CONTRACT_VERSION,
        "created_at_utc": _utc_timestamp(),
        "session": {
            "identifier": raw_session.session_key.identifier,
            "season": raw_session.session_key.season,
            "round_number": raw_session.session_key.round_number,
            "session_type": raw_session.session_key.session_type,
            "event_name": raw_session.metadata.get("event_name"),
        },
        "source": {
            "name": "FastF1",
            "version": raw_session.metadata.get(
                "fastf1_version"
            ),
        },
        "validation": {
            "status": "passed",
            "issue_count": 0,
        },
        "files": file_records,
    }

    manifest_path = temporary_directory / "manifest.json"

    write_json_document(
        manifest,
        manifest_path,
    )

    if read_json_document(manifest_path) != manifest:
        raise ValueError(
            "manifest JSON readback differs from its source"
        )

    return manifest


def _write_parquet_file(
    *,
    table_name: str,
    table: pd.DataFrame,
    path: Path,
) -> dict[str, object]:
    """Write, read back and describe one Parquet table."""
    write_parquet_table(
        table,
        path,
    )

    restored_table = read_parquet_table(path)

    _validate_parquet_readback(
        table_name=table_name,
        original=table,
        restored=restored_table,
    )

    return {
        "path": path.name,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "rows": len(table),
        "columns": [str(column) for column in table.columns],
    }


def _validate_parquet_readback(
    *,
    table_name: str,
    original: pd.DataFrame,
    restored: pd.DataFrame,
) -> None:
    """Verify values, null positions, columns and data types."""
    expected = original.reset_index(drop=True)
    actual = restored.reset_index(drop=True)

    if actual.shape != expected.shape:
        raise ParquetReadbackError(
            f"{table_name} Parquet shape changed from "
            f"{expected.shape} to {actual.shape}"
        )

    if tuple(actual.columns) != tuple(expected.columns):
        raise ParquetReadbackError(
            f"{table_name} Parquet columns changed during storage"
        )

    for column in expected.columns:
        expected_series = expected[column]
        actual_series = actual[column]

        if actual_series.dtype != expected_series.dtype:
            raise ParquetReadbackError(
                f"{table_name}.{column} dtype changed from "
                f"{expected_series.dtype} to {actual_series.dtype}"
            )

        expected_missing = expected_series.isna()
        actual_missing = actual_series.isna()

        if not actual_missing.equals(expected_missing):
            raise ParquetReadbackError(
                f"{table_name}.{column} missing-value "
                "positions changed during storage"
            )

        non_missing = ~expected_missing

        if not bool(non_missing.any()):
            continue

        expected_values = (
            expected_series.loc[non_missing]
            .reset_index(drop=True)
        )
        actual_values = (
            actual_series.loc[non_missing]
            .reset_index(drop=True)
        )

        try:
            pd.testing.assert_series_equal(
                actual_values,
                expected_values,
                check_names=False,
            )
        except AssertionError as error:
            raise ParquetReadbackError(
                f"{table_name}.{column} values changed "
                "during storage"
            ) from error


def _promote_temporary_session(
    session_paths: SessionPaths,
    backup_directory: Path,
) -> None:
    """Atomically promote temporary files into their final partition."""
    session_paths.directory.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if session_paths.directory.exists():
        session_paths.directory.rename(
            backup_directory
        )

    try:
        session_paths.temporary_directory.rename(
            session_paths.directory
        )
    except OSError:
        if (
            backup_directory.exists()
            and not session_paths.directory.exists()
        ):
            backup_directory.rename(
                session_paths.directory
            )
        raise

    if backup_directory.exists():
        shutil.rmtree(backup_directory)


def _recover_backup(
    session_paths: SessionPaths,
    backup_directory: Path,
) -> None:
    """Recover or remove a backup left by an interrupted write."""
    if not backup_directory.exists():
        return

    if session_paths.directory.exists():
        shutil.rmtree(backup_directory)
        return

    session_paths.directory.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    backup_directory.rename(
        session_paths.directory
    )


def _backup_directory(
    session_paths: SessionPaths,
) -> Path:
    """Return the exact backup path for one session."""
    return session_paths.temporary_directory.with_name(
        f"{session_paths.session_key.identifier}.backup"
    )


def _utc_timestamp() -> str:
    """Return the current time as ISO 8601 UTC text."""
    return (
        datetime.now(UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )