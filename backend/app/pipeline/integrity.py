"""Verify the integrity of stored raw Formula 1 sessions."""

import json
from dataclasses import dataclass
from pathlib import Path

from app.pipeline.models import SessionKey
from app.pipeline.paths import RawDataPaths
from app.pipeline.serialization import (
    read_json_document,
    sha256_file,
)
from app.pipeline.storage import RAW_CONTRACT_VERSION

EXPECTED_SESSION_FILES = (
    "laps.parquet",
    "weather.parquet",
    "results.parquet",
    "metadata.json",
)


class SessionIntegrityError(RuntimeError):
    """Raised when a stored session fails integrity checks."""


@dataclass(frozen=True, slots=True)
class IntegrityIssue:
    """Describe one stored-data integrity problem."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    """Contain all integrity issues found for one session."""

    session_key: SessionKey
    issues: tuple[IntegrityIssue, ...]

    @property
    def is_valid(self) -> bool:
        """Return whether the stored session passed every check."""
        return not self.issues

    def raise_for_errors(self) -> None:
        """Raise an exception when integrity problems exist."""
        if self.is_valid:
            return

        details = "; ".join(
            f"{issue.code}: {issue.message}"
            for issue in self.issues
        )

        raise SessionIntegrityError(details)


def verify_session_partition(
    raw_paths: RawDataPaths,
    session_key: SessionKey,
) -> IntegrityReport:
    """Verify one stored session partition and its manifest."""
    session_paths = raw_paths.for_session(session_key)
    issues: list[IntegrityIssue] = []

    if not session_paths.manifest.is_file():
        issues.append(
            IntegrityIssue(
                code="missing_manifest",
                message=(
                    "completed session manifest does not exist"
                ),
            )
        )
        return IntegrityReport(
            session_key=session_key,
            issues=tuple(issues),
        )

    try:
        manifest = read_json_document(
            session_paths.manifest
        )
    except (
        json.JSONDecodeError,
        OSError,
        TypeError,
        UnicodeDecodeError,
    ) as error:
        issues.append(
            IntegrityIssue(
                code="invalid_manifest",
                message=str(error),
            )
        )
        return IntegrityReport(
            session_key=session_key,
            issues=tuple(issues),
        )

    _verify_contract_version(
        manifest,
        issues,
    )
    _verify_session_identity(
        manifest,
        session_key,
        issues,
    )
    _verify_file_records(
        manifest,
        session_paths.directory,
        issues,
    )

    return IntegrityReport(
        session_key=session_key,
        issues=tuple(issues),
    )


def _verify_contract_version(
    manifest: dict[str, object],
    issues: list[IntegrityIssue],
) -> None:
    """Verify the raw-data contract version."""
    actual_version = manifest.get("contract_version")

    if actual_version != RAW_CONTRACT_VERSION:
        issues.append(
            IntegrityIssue(
                code="contract_version_mismatch",
                message=(
                    f"found {actual_version!r}; "
                    f"expected {RAW_CONTRACT_VERSION!r}"
                ),
            )
        )


def _verify_session_identity(
    manifest: dict[str, object],
    session_key: SessionKey,
    issues: list[IntegrityIssue],
) -> None:
    """Verify manifest identity against its partition."""
    session = manifest.get("session")

    if not isinstance(session, dict):
        issues.append(
            IntegrityIssue(
                code="invalid_session_record",
                message="manifest session record must be an object",
            )
        )
        return

    expected_identity = {
        "identifier": session_key.identifier,
        "season": session_key.season,
        "round_number": session_key.round_number,
        "session_type": session_key.session_type,
    }

    for field, expected_value in expected_identity.items():
        actual_value = session.get(field)

        if actual_value != expected_value:
            issues.append(
                IntegrityIssue(
                    code="identity_mismatch",
                    message=(
                        f"{field} is {actual_value!r}; "
                        f"expected {expected_value!r}"
                    ),
                )
            )


def _verify_file_records(
    manifest: dict[str, object],
    directory: Path,
    issues: list[IntegrityIssue],
) -> None:
    """Verify every required stored file."""
    file_records = manifest.get("files")

    if not isinstance(file_records, dict):
        issues.append(
            IntegrityIssue(
                code="invalid_file_records",
                message="manifest files record must be an object",
            )
        )
        return

    for filename in EXPECTED_SESSION_FILES:
        record = file_records.get(filename)

        if not isinstance(record, dict):
            issues.append(
                IntegrityIssue(
                    code="missing_file_record",
                    message=f"manifest has no record for {filename}",
                )
            )
            continue

        _verify_file(
            filename=filename,
            record=record,
            directory=directory,
            issues=issues,
        )


def _verify_file(
    *,
    filename: str,
    record: dict[str, object],
    directory: Path,
    issues: list[IntegrityIssue],
) -> None:
    """Verify one file against its manifest record."""
    recorded_path = record.get("path")

    if recorded_path != filename:
        issues.append(
            IntegrityIssue(
                code="invalid_file_path",
                message=(
                    f"{filename} record points to "
                    f"{recorded_path!r}"
                ),
            )
        )
        return

    path = directory / filename

    if not path.is_file():
        issues.append(
            IntegrityIssue(
                code="missing_file",
                message=f"{filename} does not exist",
            )
        )
        return

    expected_size = record.get("size_bytes")

    if (
        isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
    ):
        issues.append(
            IntegrityIssue(
                code="invalid_size_record",
                message=f"{filename} has an invalid recorded size",
            )
        )
    elif path.stat().st_size != expected_size:
        issues.append(
            IntegrityIssue(
                code="size_mismatch",
                message=(
                    f"{filename} size is {path.stat().st_size}; "
                    f"expected {expected_size}"
                ),
            )
        )

    expected_checksum = record.get("sha256")

    if not isinstance(expected_checksum, str):
        issues.append(
            IntegrityIssue(
                code="invalid_checksum_record",
                message=(
                    f"{filename} has no valid SHA-256 record"
                ),
            )
        )
        return

    actual_checksum = sha256_file(path)

    if actual_checksum != expected_checksum:
        issues.append(
            IntegrityIssue(
                code="checksum_mismatch",
                message=f"{filename} SHA-256 does not match",
            )
        )