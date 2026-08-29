"""Validate extracted raw Formula 1 session data."""

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

from app.pipeline.schemas import (
    RAW_TABLE_CONTRACTS,
    TableContract,
)
from app.pipeline.source import RawSessionData


class RawDataValidationError(ValueError):
    """Raised when extracted raw data violates its contract."""


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Describe one raw-data validation problem."""

    table_name: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Contain all validation issues found for one session."""

    issues: tuple[ValidationIssue, ...]

    @property
    def is_valid(self) -> bool:
        """Return whether validation found no issues."""
        return not self.issues

    def raise_for_errors(self) -> None:
        """Raise an exception when the report contains issues."""
        if self.is_valid:
            return

        details = "; ".join(
            (
                f"{issue.table_name}:{issue.code}: "
                f"{issue.message}"
            )
            for issue in self.issues
        )

        raise RawDataValidationError(details)


def validate_raw_session(
    raw_session: RawSessionData,
) -> ValidationReport:
    """Validate the structure and identity of one raw session."""
    issues: list[ValidationIssue] = []

    event_name = raw_session.metadata.get("event_name")

    expected_provenance: dict[str, object] = {
        "Season": raw_session.session_key.season,
        "RoundNumber": raw_session.session_key.round_number,
        "SessionType": raw_session.session_key.session_type,
        "EventName": event_name,
    }

    tables = {
        "laps": raw_session.laps,
        "weather": raw_session.weather,
        "results": raw_session.results,
    }

    for contract in RAW_TABLE_CONTRACTS:
        _validate_table(
            table=tables[contract.name],
            contract=contract,
            expected_provenance=expected_provenance,
            issues=issues,
        )

    _validate_metadata(
        raw_session,
        issues,
    )

    return ValidationReport(issues=tuple(issues))


def _validate_table(
    *,
    table: pd.DataFrame,
    contract: TableContract,
    expected_provenance: Mapping[str, object],
    issues: list[ValidationIssue],
) -> None:
    """Validate one raw table."""
    if table.empty:
        issues.append(
            ValidationIssue(
                table_name=contract.name,
                code="empty_table",
                message="table does not contain any rows",
            )
        )

    missing_columns = sorted(
        contract.required_columns.difference(table.columns)
    )

    if missing_columns:
        issues.append(
            ValidationIssue(
                table_name=contract.name,
                code="missing_columns",
                message=(
                    "missing required columns: "
                    + ", ".join(missing_columns)
                ),
            )
        )

    for column, expected_value in expected_provenance.items():
        if column not in table.columns or table.empty:
            continue

        matching_values = (
            table[column]
            .eq(expected_value)
            .fillna(False)
        )

        if not bool(matching_values.all()):
            issues.append(
                ValidationIssue(
                    table_name=contract.name,
                    code="invalid_provenance",
                    message=(
                        f"{column} does not consistently equal "
                        f"{expected_value!r}"
                    ),
                )
            )


def _validate_metadata(
    raw_session: RawSessionData,
    issues: list[ValidationIssue],
) -> None:
    """Validate session metadata against its session key."""
    expected_metadata = {
        "season": raw_session.session_key.season,
        "round_number": raw_session.session_key.round_number,
        "session_type": raw_session.session_key.session_type,
    }

    for field, expected_value in expected_metadata.items():
        actual_value = raw_session.metadata.get(field)

        if actual_value != expected_value:
            issues.append(
                ValidationIssue(
                    table_name="metadata",
                    code="identity_mismatch",
                    message=(
                        f"{field} is {actual_value!r}; "
                        f"expected {expected_value!r}"
                    ),
                )
            )

    event_name = raw_session.metadata.get("event_name")

    if not isinstance(event_name, str) or not event_name.strip():
        issues.append(
            ValidationIssue(
                table_name="metadata",
                code="missing_event_name",
                message="event_name must be a non-empty string",
            )
        )