"""Atomically store processed Formula 1 session datasets."""

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pandas as pd

from app.cleaning.paths import (
    ProcessedDataPaths,
    ProcessedSessionPaths,
)
from app.cleaning.processing import (
    PROCESSED_CONTRACT_VERSION,
    ProcessedSessionData,
)
from app.pipeline.serialization import (
    read_json_document,
    read_parquet_table,
    sha256_file,
    write_json_document,
    write_parquet_table,
)


class ProcessedStorageError(RuntimeError):
    """Base error for processed-data storage failures."""


class IncompleteProcessedSessionError(
    ProcessedStorageError
):
    """Raised when a processed partition is incomplete."""


class ProcessedParquetReadbackError(
    ProcessedStorageError
):
    """Raised when Parquet readback changes a table."""


@dataclass(frozen=True, slots=True)
class ProcessedSessionWriteResult:
    """Describe one processed session write."""

    status: Literal["written", "skipped"]
    directory: Path
    manifest: dict[str, object]


@dataclass(frozen=True, slots=True)
class ProcessedSessionWriter:
    """Safely write complete processed session partitions."""

    processed_paths: ProcessedDataPaths

    def __post_init__(self) -> None:
        """Validate the configured processed-data paths."""
        if not isinstance(
            self.processed_paths,
            ProcessedDataPaths,
        ):
            raise TypeError(
                "processed_paths must be ProcessedDataPaths"
            )

    def write(
        self,
        data: ProcessedSessionData,
        *,
        force: bool = False,
    ) -> ProcessedSessionWriteResult:
        """Validate and atomically store one processed session."""
        if not isinstance(
            data,
            ProcessedSessionData,
        ):
            raise TypeError(
                "data must be ProcessedSessionData"
            )

        if not isinstance(force, bool):
            raise TypeError(
                "force must be a boolean"
            )

        _validate_processed_data(
            data=data,
            processed_paths=self.processed_paths,
        )

        session_paths = self.processed_paths.for_session(
            data.session_key
        )

        _recover_backup(session_paths)

        if session_paths.manifest.is_file() and not force:
            manifest = read_json_document(
                session_paths.manifest
            )

            _validate_completed_partition(
                session_paths=session_paths,
                manifest=manifest,
            )

            return ProcessedSessionWriteResult(
                status="skipped",
                directory=session_paths.directory,
                manifest=manifest,
            )

        if session_paths.directory.exists() and not force:
            raise IncompleteProcessedSessionError(
                "processed session directory exists without "
                f"a completed manifest: {session_paths.directory}"
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
            manifest = _write_temporary_partition(
                data=data,
                temporary_directory=(
                    session_paths.temporary_directory
                ),
                cleaning_rule_version=(
                    self.processed_paths.cleaning_rule_version
                ),
            )

            _promote_temporary_partition(
                session_paths
            )
        finally:
            if session_paths.temporary_directory.exists():
                shutil.rmtree(
                    session_paths.temporary_directory
                )

        return ProcessedSessionWriteResult(
            status="written",
            directory=session_paths.directory,
            manifest=manifest,
        )


def _validate_processed_data(
    *,
    data: ProcessedSessionData,
    processed_paths: ProcessedDataPaths,
) -> None:
    """Validate the processed tables and quality report."""
    report = data.quality_report

    if not isinstance(report, dict):
        raise ProcessedStorageError(
            "quality_report must be a dictionary"
        )

    if (
        report.get("processed_contract_version")
        != PROCESSED_CONTRACT_VERSION
    ):
        raise ProcessedStorageError(
            "processed contract version does not match "
            f"{PROCESSED_CONTRACT_VERSION}"
        )

    if (
        report.get("cleaning_rule_version")
        != processed_paths.cleaning_rule_version
    ):
        raise ProcessedStorageError(
            "quality report cleaning version does not "
            "match the configured output version"
        )

    session = report.get("session")

    if not isinstance(session, dict):
        raise ProcessedStorageError(
            "quality report session must be an object"
        )

    if (
        session.get("identifier")
        != data.session_key.identifier
    ):
        raise ProcessedStorageError(
            "quality report session identifier does not "
            "match the processed data"
        )

    expected_identity = {
        "season": data.session_key.season,
        "round_number": (
            data.session_key.round_number
        ),
        "session_type": (
            data.session_key.session_type
        ),
    }

    for field, expected_value in expected_identity.items():
        if session.get(field) != expected_value:
            raise ProcessedStorageError(
                f"quality report session {field} does not "
                "match the processed data"
            )

    tables = report.get("tables")

    if not isinstance(tables, dict):
        raise ProcessedStorageError(
            "quality report tables must be an object"
        )

    expected_rows = {
        "laps_rows": len(data.laps),
        "stints_rows": len(data.stints),
        "pit_events_rows": len(data.pit_events),
    }

    for field, expected_value in expected_rows.items():
        if tables.get(field) != expected_value:
            raise ProcessedStorageError(
                f"quality report {field} does not match "
                "the processed table"
            )

    validation = report.get("validation")

    if not isinstance(validation, dict):
        raise ProcessedStorageError(
            "quality report validation must be an object"
        )

    if validation.get("status") != "passed":
        raise ProcessedStorageError(
            "processed session validation has not passed"
        )

    if data.laps.empty:
        raise ProcessedStorageError(
            "processed lap table must not be empty"
        )


def _write_temporary_partition(
    *,
    data: ProcessedSessionData,
    temporary_directory: Path,
    cleaning_rule_version: str,
) -> dict[str, object]:
    """Write and verify all temporary processed files."""
    file_records: dict[str, object] = {}

    tables = {
        "laps": data.laps,
        "stints": data.stints,
        "pit_events": data.pit_events,
    }

    for table_name, table in tables.items():
        filename = f"{table_name}.parquet"
        path = temporary_directory / filename

        file_records[filename] = _write_parquet_file(
            table_name=table_name,
            table=table,
            path=path,
        )

    quality_report_path = (
        temporary_directory / "quality_report.json"
    )

    write_json_document(
        data.quality_report,
        quality_report_path,
    )

    restored_report = read_json_document(
        quality_report_path
    )

    if restored_report != data.quality_report:
        raise ProcessedStorageError(
            "quality-report JSON readback differs "
            "from its source"
        )

    file_records["quality_report.json"] = {
        "path": quality_report_path.name,
        "sha256": sha256_file(
            quality_report_path
        ),
        "size_bytes": (
            quality_report_path.stat().st_size
        ),
    }

    session_report = data.quality_report["session"]
    source_contract_version = data.quality_report.get(
        "source_contract_version"
    )

    manifest: dict[str, object] = {
        "processed_contract_version": (
            PROCESSED_CONTRACT_VERSION
        ),
        "cleaning_rule_version": (
            cleaning_rule_version
        ),
        "source_contract_version": (
            source_contract_version
        ),
        "created_at_utc": _utc_timestamp(),
        "session": session_report,
        "validation": {
            "status": "passed",
            "parquet_readback": "passed",
            "quality_report_readback": "passed",
        },
        "files": file_records,
    }

    manifest_path = (
        temporary_directory / "manifest.json"
    )

    write_json_document(
        manifest,
        manifest_path,
    )

    if read_json_document(manifest_path) != manifest:
        raise ProcessedStorageError(
            "processed manifest JSON readback differs "
            "from its source"
        )

    return manifest


def _write_parquet_file(
    *,
    table_name: str,
    table: pd.DataFrame,
    path: Path,
) -> dict[str, object]:
    """Write, restore and describe one Parquet table."""
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
        "columns": [
            str(column)
            for column in table.columns
        ],
    }


def _validate_parquet_readback(
    *,
    table_name: str,
    original: pd.DataFrame,
    restored: pd.DataFrame,
) -> None:
    """Verify shape, columns, dtypes, nulls and values."""
    expected = original.reset_index(drop=True)
    actual = restored.reset_index(drop=True)

    if actual.shape != expected.shape:
        raise ProcessedParquetReadbackError(
            f"{table_name} Parquet shape changed from "
            f"{expected.shape} to {actual.shape}"
        )

    if tuple(actual.columns) != tuple(expected.columns):
        raise ProcessedParquetReadbackError(
            f"{table_name} Parquet columns changed "
            "during storage"
        )

    for column in expected.columns:
        expected_series = expected[column]
        actual_series = actual[column]

        if actual_series.dtype != expected_series.dtype:
            raise ProcessedParquetReadbackError(
                f"{table_name}.{column} dtype changed "
                f"from {expected_series.dtype} "
                f"to {actual_series.dtype}"
            )

        expected_missing = expected_series.isna()
        actual_missing = actual_series.isna()

        if not actual_missing.equals(expected_missing):
            raise ProcessedParquetReadbackError(
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
            raise ProcessedParquetReadbackError(
                f"{table_name}.{column} values changed "
                "during storage"
            ) from error


def _validate_completed_partition(
    *,
    session_paths: ProcessedSessionPaths,
    manifest: dict[str, object],
) -> None:
    """Verify a completed partition before skipping it."""
    if (
        manifest.get("processed_contract_version")
        != PROCESSED_CONTRACT_VERSION
    ):
        raise ProcessedStorageError(
            "stored processed contract version is unsupported"
        )

    if (
        manifest.get("cleaning_rule_version")
        != session_paths.cleaning_rule_version
    ):
        raise ProcessedStorageError(
            "stored cleaning version does not match its path"
        )

    session = manifest.get("session")

    if not isinstance(session, dict):
        raise ProcessedStorageError(
            "stored manifest session must be an object"
        )

    if (
        session.get("identifier")
        != session_paths.session_key.identifier
    ):
        raise ProcessedStorageError(
            "stored manifest session identifier does not "
            "match its path"
        )

    files = manifest.get("files")

    if not isinstance(files, dict):
        raise IncompleteProcessedSessionError(
            "stored manifest files must be an object"
        )

    expected_files = {
        "laps.parquet",
        "stints.parquet",
        "pit_events.parquet",
        "quality_report.json",
    }

    if set(files) != expected_files:
        raise IncompleteProcessedSessionError(
            "stored processed partition has an unexpected "
            "file manifest"
        )

    for filename in sorted(expected_files):
        record = files[filename]

        if not isinstance(record, dict):
            raise IncompleteProcessedSessionError(
                f"manifest record for {filename} is invalid"
            )

        path = session_paths.directory / filename

        if not path.is_file():
            raise IncompleteProcessedSessionError(
                f"stored processed file is missing: {path}"
            )

        expected_checksum = record.get("sha256")

        if not isinstance(expected_checksum, str):
            raise IncompleteProcessedSessionError(
                f"manifest checksum for {filename} is invalid"
            )

        if sha256_file(path) != expected_checksum:
            raise ProcessedStorageError(
                f"stored processed file checksum failed: "
                f"{filename}"
            )

        expected_size = record.get("size_bytes")

        if (
            not isinstance(expected_size, int)
            or path.stat().st_size != expected_size
        ):
            raise ProcessedStorageError(
                f"stored processed file size failed: "
                f"{filename}"
            )


def _promote_temporary_partition(
    session_paths: ProcessedSessionPaths,
) -> None:
    """Atomically promote temporary files to their partition."""
    session_paths.directory.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    session_paths.backup_directory.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if session_paths.directory.exists():
        session_paths.directory.rename(
            session_paths.backup_directory
        )

    try:
        session_paths.temporary_directory.rename(
            session_paths.directory
        )
    except OSError:
        if (
            session_paths.backup_directory.exists()
            and not session_paths.directory.exists()
        ):
            session_paths.backup_directory.rename(
                session_paths.directory
            )

        raise

    if session_paths.backup_directory.exists():
        shutil.rmtree(
            session_paths.backup_directory
        )


def _recover_backup(
    session_paths: ProcessedSessionPaths,
) -> None:
    """Recover a partition left by an interrupted replacement."""
    if not session_paths.backup_directory.exists():
        return

    if session_paths.directory.exists():
        shutil.rmtree(
            session_paths.backup_directory
        )
        return

    session_paths.directory.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    session_paths.backup_directory.rename(
        session_paths.directory
    )


def _utc_timestamp() -> str:
    """Return the current time as ISO 8601 UTC text."""
    return (
        datetime.now(UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )