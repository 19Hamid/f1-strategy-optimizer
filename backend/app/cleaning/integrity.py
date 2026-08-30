"""Verify stored processed Formula 1 session partitions."""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from app.cleaning.paths import ProcessedDataPaths
from app.cleaning.processing import (
    PROCESSED_CONTRACT_VERSION,
)
from app.pipeline.models import SessionKey
from app.pipeline.serialization import (
    read_json_document,
    read_parquet_table,
    sha256_file,
)

EXPECTED_PROCESSED_FILES = frozenset(
    {
        "laps.parquet",
        "stints.parquet",
        "pit_events.parquet",
        "quality_report.json",
    }
)

TABLE_FILENAMES = {
    "laps.parquet": "laps",
    "stints.parquet": "stints",
    "pit_events.parquet": "pit_events",
}

REPORT_ROW_FIELDS = {
    "laps": "laps_rows",
    "stints": "stints_rows",
    "pit_events": "pit_events_rows",
}


class ProcessedIntegrityError(RuntimeError):
    """Raised when a processed partition fails verification."""


@dataclass(frozen=True, slots=True)
class ProcessedIntegrityIssue:
    """Describe one processed-partition integrity problem."""

    code: str
    message: str
    filename: str | None = None


@dataclass(frozen=True, slots=True)
class ProcessedIntegrityReport:
    """Contain all integrity findings for one session."""

    session_key: SessionKey
    directory: Path
    issues: tuple[ProcessedIntegrityIssue, ...]
    manifest: dict[str, object] | None

    @property
    def is_valid(self) -> bool:
        """Return whether the partition passed every check."""
        return not self.issues

    def raise_for_errors(self) -> None:
        """Raise one combined error when issues exist."""
        if self.is_valid:
            return

        details = "\n".join(
            (
                f"[{issue.code}] "
                f"{issue.message}"
            )
            for issue in self.issues
        )

        raise ProcessedIntegrityError(
            "processed session integrity failed for "
            f"{self.session_key.identifier}:\n"
            f"{details}"
        )


def verify_processed_partition(
    processed_paths: ProcessedDataPaths,
    session_key: SessionKey,
) -> ProcessedIntegrityReport:
    """Verify one completed processed session partition."""
    if not isinstance(
        processed_paths,
        ProcessedDataPaths,
    ):
        raise TypeError(
            "processed_paths must be ProcessedDataPaths"
        )

    if not isinstance(session_key, SessionKey):
        raise TypeError(
            "session_key must be a SessionKey"
        )

    session_paths = processed_paths.for_session(
        session_key
    )
    issues: list[ProcessedIntegrityIssue] = []

    if not session_paths.directory.is_dir():
        issues.append(
            ProcessedIntegrityIssue(
                code="MISSING_DIRECTORY",
                message=(
                    "processed session directory "
                    f"does not exist: "
                    f"{session_paths.directory}"
                ),
            )
        )

        return ProcessedIntegrityReport(
            session_key=session_key,
            directory=session_paths.directory,
            issues=tuple(issues),
            manifest=None,
        )

    if not session_paths.manifest.is_file():
        issues.append(
            ProcessedIntegrityIssue(
                code="MISSING_MANIFEST",
                message=(
                    "processed session manifest "
                    "does not exist"
                ),
                filename="manifest.json",
            )
        )

        return ProcessedIntegrityReport(
            session_key=session_key,
            directory=session_paths.directory,
            issues=tuple(issues),
            manifest=None,
        )

    manifest = _read_json_safely(
        path=session_paths.manifest,
        filename="manifest.json",
        issues=issues,
    )

    if manifest is None:
        return ProcessedIntegrityReport(
            session_key=session_key,
            directory=session_paths.directory,
            issues=tuple(issues),
            manifest=None,
        )

    _validate_manifest_identity(
        manifest=manifest,
        processed_paths=processed_paths,
        session_key=session_key,
        issues=issues,
    )

    files = manifest.get("files")

    if not isinstance(files, dict):
        issues.append(
            ProcessedIntegrityIssue(
                code="INVALID_FILE_MANIFEST",
                message=(
                    "manifest files must be an object"
                ),
                filename="manifest.json",
            )
        )

        return ProcessedIntegrityReport(
            session_key=session_key,
            directory=session_paths.directory,
            issues=tuple(issues),
            manifest=manifest,
        )

    recorded_files = set(files)

    for filename in sorted(
        EXPECTED_PROCESSED_FILES - recorded_files
    ):
        issues.append(
            ProcessedIntegrityIssue(
                code="MISSING_FILE_RECORD",
                message=(
                    "manifest does not describe "
                    f"{filename}"
                ),
                filename=filename,
            )
        )

    for filename in sorted(
        recorded_files - EXPECTED_PROCESSED_FILES
    ):
        issues.append(
            ProcessedIntegrityIssue(
                code="UNEXPECTED_FILE_RECORD",
                message=(
                    "manifest unexpectedly describes "
                    f"{filename}"
                ),
                filename=filename,
            )
        )

    actual_files = {
        path.name
        for path in session_paths.directory.iterdir()
        if path.is_file()
    }
    expected_directory_files = (
        EXPECTED_PROCESSED_FILES
        | {"manifest.json"}
    )

    for filename in sorted(
        actual_files - expected_directory_files
    ):
        issues.append(
            ProcessedIntegrityIssue(
                code="UNEXPECTED_FILE",
                message=(
                    "processed partition contains "
                    f"unexpected file {filename}"
                ),
                filename=filename,
            )
        )

    verified_files: set[str] = set()
    restored_tables: dict[
        str,
        pd.DataFrame,
    ] = {}

    for filename in sorted(
        EXPECTED_PROCESSED_FILES
    ):
        record = files.get(filename)

        if not isinstance(record, dict):
            if filename in files:
                issues.append(
                    ProcessedIntegrityIssue(
                        code="INVALID_FILE_RECORD",
                        message=(
                            "manifest record must be "
                            "an object"
                        ),
                        filename=filename,
                    )
                )

            continue

        path = session_paths.directory / filename

        if not path.is_file():
            issues.append(
                ProcessedIntegrityIssue(
                    code="MISSING_FILE",
                    message=(
                        "processed file does not exist"
                    ),
                    filename=filename,
                )
            )
            continue

        if record.get("path") != filename:
            issues.append(
                ProcessedIntegrityIssue(
                    code="PATH_MISMATCH",
                    message=(
                        "manifest path does not match "
                        "its filename"
                    ),
                    filename=filename,
                )
            )

        expected_size = record.get("size_bytes")

        if (
            isinstance(expected_size, bool)
            or not isinstance(expected_size, int)
        ):
            issues.append(
                ProcessedIntegrityIssue(
                    code="INVALID_SIZE_RECORD",
                    message=(
                        "manifest size must be an integer"
                    ),
                    filename=filename,
                )
            )
        elif path.stat().st_size != expected_size:
            issues.append(
                ProcessedIntegrityIssue(
                    code="SIZE_MISMATCH",
                    message=(
                        "stored file size does not match "
                        "its manifest"
                    ),
                    filename=filename,
                )
            )

        expected_checksum = record.get("sha256")

        if not isinstance(expected_checksum, str):
            issues.append(
                ProcessedIntegrityIssue(
                    code="INVALID_CHECKSUM_RECORD",
                    message=(
                        "manifest checksum must be text"
                    ),
                    filename=filename,
                )
            )
            continue

        if sha256_file(path) != expected_checksum:
            issues.append(
                ProcessedIntegrityIssue(
                    code="CHECKSUM_MISMATCH",
                    message=(
                        "stored file checksum does not "
                        "match its manifest"
                    ),
                    filename=filename,
                )
            )
            continue

        verified_files.add(filename)

        table_name = TABLE_FILENAMES.get(
            filename
        )

        if table_name is None:
            continue

        table = _read_parquet_safely(
            path=path,
            filename=filename,
            issues=issues,
        )

        if table is None:
            continue

        restored_tables[table_name] = table

        _validate_table_record(
            filename=filename,
            table=table,
            record=record,
            issues=issues,
        )

    quality_report: dict[str, object] | None = None

    if "quality_report.json" in verified_files:
        quality_report = _read_json_safely(
            path=session_paths.quality_report,
            filename="quality_report.json",
            issues=issues,
        )

    if quality_report is not None:
        _validate_quality_report(
            quality_report=quality_report,
            manifest=manifest,
            processed_paths=processed_paths,
            session_key=session_key,
            restored_tables=restored_tables,
            issues=issues,
        )

    return ProcessedIntegrityReport(
        session_key=session_key,
        directory=session_paths.directory,
        issues=tuple(issues),
        manifest=manifest,
    )


def _validate_manifest_identity(
    *,
    manifest: dict[str, object],
    processed_paths: ProcessedDataPaths,
    session_key: SessionKey,
    issues: list[ProcessedIntegrityIssue],
) -> None:
    """Validate manifest versions and session identity."""
    if (
        manifest.get("processed_contract_version")
        != PROCESSED_CONTRACT_VERSION
    ):
        issues.append(
            ProcessedIntegrityIssue(
                code="CONTRACT_VERSION_MISMATCH",
                message=(
                    "processed contract version is "
                    "unsupported"
                ),
                filename="manifest.json",
            )
        )

    if (
        manifest.get("cleaning_rule_version")
        != processed_paths.cleaning_rule_version
    ):
        issues.append(
            ProcessedIntegrityIssue(
                code="CLEANING_VERSION_MISMATCH",
                message=(
                    "manifest cleaning version does not "
                    "match its directory"
                ),
                filename="manifest.json",
            )
        )

    session = manifest.get("session")

    if not isinstance(session, dict):
        issues.append(
            ProcessedIntegrityIssue(
                code="INVALID_SESSION_RECORD",
                message=(
                    "manifest session must be an object"
                ),
                filename="manifest.json",
            )
        )
        return

    expected_identity = {
        "identifier": session_key.identifier,
        "season": session_key.season,
        "round_number": (
            session_key.round_number
        ),
        "session_type": (
            session_key.session_type
        ),
    }

    for field, expected_value in expected_identity.items():
        if session.get(field) != expected_value:
            issues.append(
                ProcessedIntegrityIssue(
                    code="SESSION_IDENTITY_MISMATCH",
                    message=(
                        f"manifest session {field} does "
                        "not match its directory"
                    ),
                    filename="manifest.json",
                )
            )


def _validate_table_record(
    *,
    filename: str,
    table: pd.DataFrame,
    record: dict[str, object],
    issues: list[ProcessedIntegrityIssue],
) -> None:
    """Compare one restored table with its manifest."""
    expected_rows = record.get("rows")

    if (
        isinstance(expected_rows, bool)
        or not isinstance(expected_rows, int)
    ):
        issues.append(
            ProcessedIntegrityIssue(
                code="INVALID_ROW_RECORD",
                message=(
                    "manifest row count must be an integer"
                ),
                filename=filename,
            )
        )
    elif len(table) != expected_rows:
        issues.append(
            ProcessedIntegrityIssue(
                code="ROW_COUNT_MISMATCH",
                message=(
                    "stored table row count does not "
                    "match its manifest"
                ),
                filename=filename,
            )
        )

    expected_columns = record.get("columns")

    if not isinstance(expected_columns, list):
        issues.append(
            ProcessedIntegrityIssue(
                code="INVALID_COLUMN_RECORD",
                message=(
                    "manifest columns must be a list"
                ),
                filename=filename,
            )
        )
    elif [
        str(column)
        for column in table.columns
    ] != expected_columns:
        issues.append(
            ProcessedIntegrityIssue(
                code="COLUMN_MISMATCH",
                message=(
                    "stored table columns do not match "
                    "its manifest"
                ),
                filename=filename,
            )
        )


def _validate_quality_report(
    *,
    quality_report: dict[str, object],
    manifest: dict[str, object],
    processed_paths: ProcessedDataPaths,
    session_key: SessionKey,
    restored_tables: dict[str, pd.DataFrame],
    issues: list[ProcessedIntegrityIssue],
) -> None:
    """Validate report versions, identity and row counts."""
    if (
        quality_report.get(
            "processed_contract_version"
        )
        != PROCESSED_CONTRACT_VERSION
    ):
        issues.append(
            ProcessedIntegrityIssue(
                code="REPORT_CONTRACT_MISMATCH",
                message=(
                    "quality-report contract version is "
                    "unsupported"
                ),
                filename="quality_report.json",
            )
        )

    if (
        quality_report.get("cleaning_rule_version")
        != processed_paths.cleaning_rule_version
    ):
        issues.append(
            ProcessedIntegrityIssue(
                code="REPORT_CLEANING_VERSION_MISMATCH",
                message=(
                    "quality-report cleaning version does "
                    "not match its directory"
                ),
                filename="quality_report.json",
            )
        )

    if (
        quality_report.get("source_contract_version")
        != manifest.get("source_contract_version")
    ):
        issues.append(
            ProcessedIntegrityIssue(
                code="SOURCE_CONTRACT_MISMATCH",
                message=(
                    "quality report and manifest disagree "
                    "on the raw contract version"
                ),
                filename="quality_report.json",
            )
        )

    session = quality_report.get("session")

    if (
        not isinstance(session, dict)
        or session.get("identifier")
        != session_key.identifier
    ):
        issues.append(
            ProcessedIntegrityIssue(
                code="REPORT_SESSION_MISMATCH",
                message=(
                    "quality-report session does not "
                    "match its directory"
                ),
                filename="quality_report.json",
            )
        )

    validation = quality_report.get("validation")

    if (
        not isinstance(validation, dict)
        or validation.get("status") != "passed"
    ):
        issues.append(
            ProcessedIntegrityIssue(
                code="REPORT_VALIDATION_FAILED",
                message=(
                    "quality report does not contain a "
                    "passed validation result"
                ),
                filename="quality_report.json",
            )
        )

    tables = quality_report.get("tables")

    if not isinstance(tables, dict):
        issues.append(
            ProcessedIntegrityIssue(
                code="INVALID_REPORT_TABLES",
                message=(
                    "quality-report tables must be an "
                    "object"
                ),
                filename="quality_report.json",
            )
        )
        return

    for table_name, table in restored_tables.items():
        field = REPORT_ROW_FIELDS[
            table_name
        ]

        if tables.get(field) != len(table):
            issues.append(
                ProcessedIntegrityIssue(
                    code="REPORT_ROW_COUNT_MISMATCH",
                    message=(
                        f"quality-report {field} does not "
                        "match the stored table"
                    ),
                    filename="quality_report.json",
                )
            )


def _read_json_safely(
    *,
    path: Path,
    filename: str,
    issues: list[ProcessedIntegrityIssue],
) -> dict[str, object] | None:
    """Read JSON while converting failures into issues."""
    try:
        return read_json_document(path)
    except (
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as error:
        issues.append(
            ProcessedIntegrityIssue(
                code="INVALID_JSON",
                message=(
                    f"could not read {filename}: "
                    f"{error}"
                ),
                filename=filename,
            )
        )
        return None


def _read_parquet_safely(
    *,
    path: Path,
    filename: str,
    issues: list[ProcessedIntegrityIssue],
) -> pd.DataFrame | None:
    """Read Parquet while converting failures into issues."""
    try:
        return read_parquet_table(path)
    except (
        OSError,
        TypeError,
        ValueError,
    ) as error:
        issues.append(
            ProcessedIntegrityIssue(
                code="INVALID_PARQUET",
                message=(
                    f"could not read {filename}: "
                    f"{error}"
                ),
                filename=filename,
            )
        )
        return None