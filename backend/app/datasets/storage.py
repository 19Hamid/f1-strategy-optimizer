"""Atomically store leakage-controlled modelling datasets."""

from __future__ import annotations

import re
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pandas as pd

from app.datasets.contracts import (
    DATASET_CONTRACT_VERSION,
    DECISION_LABELS_CONTRACT,
    DECISION_ROWS_CONTRACT,
    PIT_DURATION_OBSERVATIONS_CONTRACT,
    SOURCE_CLEANING_RULE_VERSION,
    SOURCE_PROCESSED_CONTRACT_VERSION,
    TableContract,
)
from app.datasets.decisions import (
    DecisionSessionData,
)
from app.datasets.paths import (
    DatasetPaths,
    DatasetSessionPaths,
)
from app.datasets.pit_durations import (
    PitDurationSessionData,
    validate_pit_duration_session,
)
from app.datasets.validation import (
    DecisionValidationReport,
    validate_decision_session,
)
from app.pipeline import SessionKey
from app.pipeline.serialization import (
    read_json_document,
    read_parquet_table,
    sha256_file,
    write_json_document,
    write_parquet_table,
)

SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")

SESSION_TABLE_CONTRACT_BY_FILE = {
    contract.file_name: contract
    for contract in (
        DECISION_ROWS_CONTRACT,
        DECISION_LABELS_CONTRACT,
        PIT_DURATION_OBSERVATIONS_CONTRACT,
    )
}

EXPECTED_SESSION_FILES = frozenset(
    {
        *SESSION_TABLE_CONTRACT_BY_FILE,
        "quality_report.json",
    }
)


class DatasetStorageError(RuntimeError):
    """Base error for modelling-dataset storage failures."""


class IncompleteDatasetSessionError(
    DatasetStorageError
):
    """Raised when a dataset partition is incomplete."""


class DatasetParquetReadbackError(
    DatasetStorageError
):
    """Raised when Parquet readback changes a table."""


@dataclass(frozen=True, slots=True)
class ProcessedSourceReference:
    """Immutable provenance for one processed source session."""

    cleaning_rule_version: str
    processed_contract_version: str
    session_directory: str
    manifest_sha256: str
    laps_sha256: str
    stints_sha256: str
    pit_events_sha256: str

    def __post_init__(self) -> None:
        """Validate versions, source location and SHA-256 values."""
        for field_name in (
            "cleaning_rule_version",
            "processed_contract_version",
            "session_directory",
            "manifest_sha256",
            "laps_sha256",
            "stints_sha256",
            "pit_events_sha256",
        ):
            value = getattr(self, field_name)

            if not isinstance(value, str):
                raise TypeError(
                    f"{field_name} must be a string"
                )

            if not value.strip():
                raise ValueError(
                    f"{field_name} must not be empty"
                )

        if (
            self.cleaning_rule_version
            != SOURCE_CLEANING_RULE_VERSION
        ):
            raise ValueError(
                "source cleaning-rule version must equal "
                f"{SOURCE_CLEANING_RULE_VERSION}"
            )

        if (
            self.processed_contract_version
            != SOURCE_PROCESSED_CONTRACT_VERSION
        ):
            raise ValueError(
                "source processed-contract version must equal "
                f"{SOURCE_PROCESSED_CONTRACT_VERSION}"
            )

        for field_name in (
            "manifest_sha256",
            "laps_sha256",
            "stints_sha256",
            "pit_events_sha256",
        ):
            value = getattr(self, field_name)

            if SHA256_PATTERN.fullmatch(value) is None:
                raise ValueError(
                    f"{field_name} must be a lowercase SHA-256 digest"
                )

    @property
    def table_sha256(self) -> dict[str, str]:
        """Return source-table hashes keyed by stored filename."""
        return {
            "laps.parquet": self.laps_sha256,
            "stints.parquet": self.stints_sha256,
            "pit_events.parquet": (
                self.pit_events_sha256
            ),
        }

    def as_document(self) -> dict[str, object]:
        """Return deterministic manifest-ready provenance."""
        return {
            "cleaning_rule_version": (
                self.cleaning_rule_version
            ),
            "processed_contract_version": (
                self.processed_contract_version
            ),
            "session_directory": (
                self.session_directory
            ),
            "manifest_sha256": (
                self.manifest_sha256
            ),
            "table_sha256": self.table_sha256,
        }


@dataclass(frozen=True, slots=True)
class DatasetSessionData:
    """All validated inputs required to store one dataset session."""

    source_lap_count: int
    decisions: DecisionSessionData
    pit_durations: PitDurationSessionData
    source: ProcessedSourceReference

    @property
    def session_key(self) -> SessionKey:
        """Return the shared session identity."""
        return self.decisions.session_key

    @property
    def event_name(self) -> str:
        """Return the shared event name."""
        return self.decisions.event_name

    @property
    def decision_rows(self) -> pd.DataFrame:
        """Return decision features and audit context."""
        return self.decisions.decision_rows

    @property
    def decision_labels(self) -> pd.DataFrame:
        """Return separated decision labels."""
        return self.decisions.decision_labels

    @property
    def pit_duration_observations(
        self,
    ) -> pd.DataFrame:
        """Return separated pit-duration targets."""
        return self.pit_durations.observations

    @property
    def tables(self) -> dict[str, pd.DataFrame]:
        """Return every authoritative session table."""
        return {
            "decision_rows": self.decision_rows,
            "decision_labels": self.decision_labels,
            "pit_duration_observations": (
                self.pit_duration_observations
            ),
        }


@dataclass(frozen=True, slots=True)
class DatasetSessionWriteResult:
    """Describe one modelling-dataset session write."""

    status: Literal["written", "skipped"]
    directory: Path
    manifest: dict[str, object]
    quality_report: dict[str, object]


@dataclass(frozen=True, slots=True)
class _ValidatedDatasetSession:
    """Internal reports produced immediately before storage."""

    decision_report: DecisionValidationReport
    quality_report: dict[str, object]


@dataclass(frozen=True, slots=True)
class DatasetSessionWriter:
    """Safely write complete modelling-dataset partitions."""

    dataset_paths: DatasetPaths

    def __post_init__(self) -> None:
        """Validate the configured dataset paths."""
        if not isinstance(
            self.dataset_paths,
            DatasetPaths,
        ):
            raise TypeError(
                "dataset_paths must be DatasetPaths"
            )

        if (
            self.dataset_paths.dataset_contract_version
            != DATASET_CONTRACT_VERSION
        ):
            raise ValueError(
                "dataset path version must equal "
                f"{DATASET_CONTRACT_VERSION}"
            )

    def write(
        self,
        data: DatasetSessionData,
        *,
        force: bool = False,
    ) -> DatasetSessionWriteResult:
        """Validate and atomically store one dataset session."""
        if not isinstance(
            data,
            DatasetSessionData,
        ):
            raise TypeError(
                "data must be DatasetSessionData"
            )

        if not isinstance(force, bool):
            raise TypeError(
                "force must be a boolean"
            )

        validated = _validate_dataset_data(
            data
        )
        session_paths = (
            self.dataset_paths.for_session(
                data.session_key
            )
        )

        _recover_backup(session_paths)

        if session_paths.manifest.is_file() and not force:
            manifest, quality_report = (
                _validate_completed_partition(
                    session_paths
                )
            )

            return DatasetSessionWriteResult(
                status="skipped",
                directory=session_paths.directory,
                manifest=manifest,
                quality_report=quality_report,
            )

        if session_paths.directory.exists() and not force:
            raise IncompleteDatasetSessionError(
                "dataset session directory exists without "
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
                validated=validated,
                temporary_directory=(
                    session_paths.temporary_directory
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

        return DatasetSessionWriteResult(
            status="written",
            directory=session_paths.directory,
            manifest=manifest,
            quality_report=validated.quality_report,
        )


def build_dataset_quality_report(
    data: DatasetSessionData,
    *,
    decision_report: DecisionValidationReport | None = None,
) -> dict[str, object]:
    """Build deterministic session quality and leakage metrics."""
    if not isinstance(
        data,
        DatasetSessionData,
    ):
        raise TypeError(
            "data must be DatasetSessionData"
        )

    if decision_report is None:
        decision_report = validate_decision_session(
            data.decisions
        )
    elif not isinstance(
        decision_report,
        DecisionValidationReport,
    ):
        raise TypeError(
            "decision_report must be a DecisionValidationReport"
        )

    decision_report.raise_for_errors()
    pit_report = validate_pit_duration_session(
        data.pit_durations
    )
    pit_report.raise_for_errors()

    decision_rows = data.decision_rows
    decision_labels = data.decision_labels
    eligible_mask = decision_rows[
        "is_decision_eligible"
    ].astype(bool)
    eligible_ids = set(
        decision_rows.loc[
            eligible_mask,
            "decision_id",
        ].astype(str)
    )
    eligible_label_mask = decision_labels[
        "decision_id"
    ].astype(str).isin(eligible_ids)
    eligible_labels = decision_labels.loc[
        eligible_label_mask
    ]

    decision_reason_counts = _reason_counts(
        decision_rows[
            "decision_exclusion_reasons"
        ]
    )
    pit_reason_counts = _reason_counts(
        data.pit_duration_observations[
            "pit_duration_exclusion_reasons"
        ]
    )

    eligible_decisions = int(
        eligible_mask.sum()
    )
    ineligible_decisions = (
        len(decision_rows)
        - eligible_decisions
    )
    pit_now_actions = int(
        eligible_labels[
            "historical_action"
        ].eq("PIT_NOW").sum()
    )
    stay_out_actions = int(
        eligible_labels[
            "historical_action"
        ].eq("STAY_OUT").sum()
    )
    lap_target_eligible = int(
        eligible_labels[
            "is_lap_time_target_eligible"
        ].eq(True).sum()
    )
    pit_target_eligible = (
        data.pit_durations.eligible_target_count
    )
    omitted_first_laps = (
        data.source_lap_count
        - len(decision_rows)
    )

    return {
        "dataset_contract_version": (
            DATASET_CONTRACT_VERSION
        ),
        "session": _session_document(data),
        "source_counts": {
            "processed_source_laps": (
                data.source_lap_count
            ),
            "candidate_decision_rows": (
                len(decision_rows)
            ),
            "omitted_first_recorded_laps": (
                omitted_first_laps
            ),
            "source_pit_events": (
                data.pit_durations
                .source_pit_event_count
            ),
        },
        "decision_quality": {
            "eligible_decisions": (
                eligible_decisions
            ),
            "ineligible_decisions": (
                ineligible_decisions
            ),
            "decision_eligibility_rate": (
                eligible_decisions
                / len(decision_rows)
                if len(decision_rows)
                else 0.0
            ),
            "exclusion_reason_counts": (
                decision_reason_counts
            ),
            "state_reconstruction_conflicts": (
                decision_reason_counts.get(
                    "STATE_RECONSTRUCTION_CONFLICT",
                    0,
                )
            ),
            "historical_pit_now_actions": (
                pit_now_actions
            ),
            "historical_stay_out_actions": (
                stay_out_actions
            ),
        },
        "target_quality": {
            "lap_time_target_eligible_rows": (
                lap_target_eligible
            ),
            "lap_time_target_ineligible_rows": (
                eligible_decisions
                - lap_target_eligible
            ),
            "pit_duration_target_eligible_rows": (
                pit_target_eligible
            ),
            "pit_duration_target_ineligible_rows": (
                len(data.pit_duration_observations)
                - pit_target_eligible
            ),
            "pit_duration_exclusion_reason_counts": (
                pit_reason_counts
            ),
        },
        "leakage_validation": {
            "future_weather_matches": (
                decision_report.future_weather_matches
            ),
            "current_lap_timing_features": list(
                decision_report
                .current_lap_timing_features
            ),
            "current_lap_quality_features": list(
                decision_report
                .current_lap_quality_features
            ),
            "features_outside_allowlist": list(
                decision_report
                .feature_columns_outside_allowlist
            ),
            "evaluation_season_rows": (
                decision_report
                .evaluation_season_rows
                + pit_report.evaluation_season_rows
            ),
            "protected_evaluation_season_accessed": (
                False
            ),
            "status": "passed",
        },
        "validation": {
            "status": "passed",
            "issue_count": (
                decision_report.issue_count
                + pit_report.issue_count
            ),
        },
    }


def _validate_dataset_data(
    data: DatasetSessionData,
) -> _ValidatedDatasetSession:
    """Validate identities, reports and source-count invariants."""
    if isinstance(data.source_lap_count, bool) or not isinstance(
        data.source_lap_count,
        int,
    ):
        raise TypeError(
            "source_lap_count must be an integer"
        )

    if data.source_lap_count <= 0:
        raise DatasetStorageError(
            "source_lap_count must be positive"
        )

    if not isinstance(
        data.decisions,
        DecisionSessionData,
    ):
        raise TypeError(
            "decisions must be DecisionSessionData"
        )

    if not isinstance(
        data.pit_durations,
        PitDurationSessionData,
    ):
        raise TypeError(
            "pit_durations must be PitDurationSessionData"
        )

    if not isinstance(
        data.source,
        ProcessedSourceReference,
    ):
        raise TypeError(
            "source must be ProcessedSourceReference"
        )

    if (
        data.decisions.session_key
        != data.pit_durations.session_key
    ):
        raise DatasetStorageError(
            "decision and pit-duration session identities differ"
        )

    if (
        data.decisions.event_name
        != data.pit_durations.event_name
    ):
        raise DatasetStorageError(
            "decision and pit-duration event names differ"
        )

    source_parts = Path(
        data.source.session_directory
    ).parts
    expected_source_suffix = (
        data.session_key.partition_parts
    )

    if tuple(
        source_parts[
            -len(expected_source_suffix):
        ]
    ) != expected_source_suffix:
        raise DatasetStorageError(
            "processed source directory does not match "
            "the dataset session identity"
        )

    if data.decision_rows.empty:
        raise DatasetStorageError(
            "decision-row table must not be empty"
        )

    if data.source_lap_count < len(
        data.decision_rows
    ):
        raise DatasetStorageError(
            "source_lap_count is smaller than candidate decisions"
        )

    decision_report = validate_decision_session(
        data.decisions
    )
    decision_report.raise_for_errors()
    pit_report = validate_pit_duration_session(
        data.pit_durations
    )
    pit_report.raise_for_errors()

    if (
        decision_report.session_key
        != data.session_key
        or pit_report.session_key
        != data.session_key
    ):
        raise DatasetStorageError(
            "validation report session identity differs"
        )

    quality_report = build_dataset_quality_report(
        data,
        decision_report=decision_report,
    )

    return _ValidatedDatasetSession(
        decision_report=decision_report,
        quality_report=quality_report,
    )


def _reason_counts(
    values: pd.Series,
) -> dict[str, int]:
    """Count deterministic pipe-delimited quality reasons."""
    counts: Counter[str] = Counter()

    for value in values.astype("string"):
        if pd.isna(value) or not value:
            continue

        counts.update(
            str(value).split("|")
        )

    return {
        reason: counts[reason]
        for reason in sorted(counts)
    }


def _session_document(
    data: DatasetSessionData,
) -> dict[str, object]:
    """Return the canonical manifest session identity."""
    return {
        "identifier": data.session_key.identifier,
        "season": data.session_key.season,
        "round_number": (
            data.session_key.round_number
        ),
        "session_type": (
            data.session_key.session_type
        ),
        "event_name": data.event_name,
    }


def _write_temporary_partition(
    *,
    data: DatasetSessionData,
    validated: _ValidatedDatasetSession,
    temporary_directory: Path,
) -> dict[str, object]:
    """Write and verify every temporary dataset file."""
    file_records: dict[str, object] = {}

    contract_by_name = {
        contract.name: contract
        for contract in (
            DECISION_ROWS_CONTRACT,
            DECISION_LABELS_CONTRACT,
            PIT_DURATION_OBSERVATIONS_CONTRACT,
        )
    }

    for table_name, table in data.tables.items():
        contract = contract_by_name[table_name]
        path = (
            temporary_directory
            / contract.file_name
        )

        file_records[contract.file_name] = (
            _write_parquet_file(
                contract=contract,
                table=table,
                path=path,
            )
        )

    quality_report_path = (
        temporary_directory
        / "quality_report.json"
    )
    write_json_document(
        validated.quality_report,
        quality_report_path,
    )

    if read_json_document(
        quality_report_path
    ) != validated.quality_report:
        raise DatasetStorageError(
            "quality-report JSON readback differs from its source"
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

    manifest: dict[str, object] = {
        "dataset_contract_version": (
            DATASET_CONTRACT_VERSION
        ),
        "created_at_utc": _utc_timestamp(),
        "session": _session_document(data),
        "source": data.source.as_document(),
        "files": file_records,
        "validation": {
            "status": "passed",
            "issue_count": 0,
            "decision_identity_unique": (
                data.decision_rows[
                    "decision_id"
                ].is_unique
            ),
            "decision_label_identity_equal": (
                set(
                    data.decision_rows[
                        "decision_id"
                    ].astype(str)
                )
                == set(
                    data.decision_labels[
                        "decision_id"
                    ].astype(str)
                )
            ),
            "feature_label_row_count_equal": (
                len(data.decision_rows)
                == len(data.decision_labels)
            ),
            "future_weather_match_count": (
                validated.decision_report
                .future_weather_matches
            ),
            "leakage_check_status": "passed",
            "evaluation_season_rows": 0,
            "protected_evaluation_season_accessed": (
                False
            ),
            "parquet_readback": "passed",
            "quality_report_readback": "passed",
        },
    }

    manifest_path = (
        temporary_directory
        / "manifest.json"
    )
    write_json_document(
        manifest,
        manifest_path,
    )

    if read_json_document(
        manifest_path
    ) != manifest:
        raise DatasetStorageError(
            "dataset manifest JSON readback differs from its source"
        )

    return manifest


def _write_parquet_file(
    *,
    contract: TableContract,
    table: pd.DataFrame,
    path: Path,
) -> dict[str, object]:
    """Write, restore and describe one contracted table."""
    _validate_table_contract(
        table=table,
        contract=contract,
        error_type=DatasetStorageError,
    )
    write_parquet_table(
        table,
        path,
    )
    restored_table = read_parquet_table(
        path
    )
    _validate_parquet_readback(
        table_name=contract.name,
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


def _validate_table_contract(
    *,
    table: pd.DataFrame,
    contract: TableContract,
    error_type: type[DatasetStorageError],
) -> None:
    """Require exact columns, dtypes and nullability."""
    if not isinstance(table, pd.DataFrame):
        raise TypeError(
            f"{contract.name} must be a pandas DataFrame"
        )

    expected_columns = tuple(
        column.name
        for column in contract.columns
    )
    actual_columns = tuple(
        str(column)
        for column in table.columns
    )

    if actual_columns != expected_columns:
        raise error_type(
            f"{contract.name} columns differ from the contract"
        )

    for column in contract.columns:
        series = table[column.name]

        if str(series.dtype) != column.pandas_dtype:
            raise error_type(
                f"{contract.name}.{column.name} has dtype "
                f"{series.dtype}; expected {column.pandas_dtype}"
            )

        if not column.nullable and series.isna().any():
            raise error_type(
                f"{contract.name}.{column.name} contains "
                "missing required values"
            )


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
        raise DatasetParquetReadbackError(
            f"{table_name} Parquet shape changed from "
            f"{expected.shape} to {actual.shape}"
        )

    if tuple(actual.columns) != tuple(expected.columns):
        raise DatasetParquetReadbackError(
            f"{table_name} Parquet columns changed during storage"
        )

    for column in expected.columns:
        expected_series = expected[column]
        actual_series = actual[column]

        if actual_series.dtype != expected_series.dtype:
            raise DatasetParquetReadbackError(
                f"{table_name}.{column} dtype changed from "
                f"{expected_series.dtype} to {actual_series.dtype}"
            )

        expected_missing = expected_series.isna()
        actual_missing = actual_series.isna()

        if not actual_missing.equals(expected_missing):
            raise DatasetParquetReadbackError(
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
            raise DatasetParquetReadbackError(
                f"{table_name}.{column} values changed during storage"
            ) from error


def _validate_completed_partition(
    session_paths: DatasetSessionPaths,
) -> tuple[
    dict[str, object],
    dict[str, object],
]:
    """Verify one completed partition before safely skipping it."""
    manifest = read_json_document(
        session_paths.manifest
    )

    if (
        manifest.get("dataset_contract_version")
        != DATASET_CONTRACT_VERSION
    ):
        raise DatasetStorageError(
            "stored dataset contract version is unsupported"
        )

    _validate_stored_session_identity(
        manifest=manifest,
        session_paths=session_paths,
    )
    _validate_stored_source(
        manifest=manifest,
        session_paths=session_paths,
    )

    validation = manifest.get("validation")

    if not isinstance(validation, dict):
        raise DatasetStorageError(
            "stored manifest validation must be an object"
        )

    if (
        validation.get("status") != "passed"
        or validation.get("issue_count") != 0
        or validation.get("leakage_check_status")
        != "passed"
        or validation.get(
            "protected_evaluation_season_accessed"
        )
        is not False
    ):
        raise DatasetStorageError(
            "stored dataset validation has not passed"
        )

    files = manifest.get("files")

    if not isinstance(files, dict):
        raise IncompleteDatasetSessionError(
            "stored manifest files must be an object"
        )

    if set(files) != EXPECTED_SESSION_FILES:
        raise IncompleteDatasetSessionError(
            "stored dataset partition has an unexpected file manifest"
        )

    for filename in sorted(
        EXPECTED_SESSION_FILES
    ):
        record = files[filename]

        if not isinstance(record, dict):
            raise IncompleteDatasetSessionError(
                f"manifest record for {filename} is invalid"
            )

        if record.get("path") != filename:
            raise DatasetStorageError(
                f"manifest path for {filename} is invalid"
            )

        path = session_paths.directory / filename

        if not path.is_file():
            raise IncompleteDatasetSessionError(
                f"stored dataset file is missing: {path}"
            )

        expected_checksum = record.get(
            "sha256"
        )

        if not isinstance(
            expected_checksum,
            str,
        ):
            raise IncompleteDatasetSessionError(
                f"manifest checksum for {filename} is invalid"
            )

        if sha256_file(path) != expected_checksum:
            raise DatasetStorageError(
                f"stored dataset file checksum failed: {filename}"
            )

        expected_size = record.get(
            "size_bytes"
        )

        if (
            isinstance(expected_size, bool)
            or not isinstance(expected_size, int)
            or path.stat().st_size != expected_size
        ):
            raise DatasetStorageError(
                f"stored dataset file size failed: {filename}"
            )

        contract = (
            SESSION_TABLE_CONTRACT_BY_FILE.get(
                filename
            )
        )

        if contract is None:
            continue

        table = read_parquet_table(path)
        _validate_table_contract(
            table=table,
            contract=contract,
            error_type=DatasetStorageError,
        )

        if record.get("rows") != len(table):
            raise DatasetStorageError(
                f"stored row count failed: {filename}"
            )

        if record.get("columns") != [
            str(column)
            for column in table.columns
        ]:
            raise DatasetStorageError(
                f"stored column list failed: {filename}"
            )

    quality_report = read_json_document(
        session_paths.quality_report
    )
    _validate_stored_quality_report(
        quality_report=quality_report,
        session_paths=session_paths,
    )

    return manifest, quality_report


def _validate_stored_session_identity(
    *,
    manifest: dict[str, object],
    session_paths: DatasetSessionPaths,
) -> None:
    """Require manifest identity to match its partition path."""
    session = manifest.get("session")

    if not isinstance(session, dict):
        raise DatasetStorageError(
            "stored manifest session must be an object"
        )

    expected = {
        "identifier": (
            session_paths.session_key.identifier
        ),
        "season": (
            session_paths.session_key.season
        ),
        "round_number": (
            session_paths.session_key.round_number
        ),
        "session_type": (
            session_paths.session_key.session_type
        ),
    }

    for field, expected_value in expected.items():
        if session.get(field) != expected_value:
            raise DatasetStorageError(
                f"stored manifest session {field} does not match its path"
            )

    event_name = session.get("event_name")

    if not isinstance(event_name, str) or not event_name:
        raise DatasetStorageError(
            "stored manifest event name is invalid"
        )


def _validate_stored_source(
    *,
    manifest: dict[str, object],
    session_paths: DatasetSessionPaths,
) -> None:
    """Validate stored processed-source provenance structure."""
    source = manifest.get("source")

    if not isinstance(source, dict):
        raise DatasetStorageError(
            "stored manifest source must be an object"
        )

    if (
        source.get("cleaning_rule_version")
        != SOURCE_CLEANING_RULE_VERSION
    ):
        raise DatasetStorageError(
            "stored source cleaning version is unsupported"
        )

    if (
        source.get("processed_contract_version")
        != SOURCE_PROCESSED_CONTRACT_VERSION
    ):
        raise DatasetStorageError(
            "stored source processed contract is unsupported"
        )

    directory = source.get(
        "session_directory"
    )

    if not isinstance(directory, str) or not directory:
        raise DatasetStorageError(
            "stored source session directory is invalid"
        )

    source_parts = Path(directory).parts
    expected_suffix = (
        session_paths.session_key.partition_parts
    )

    if tuple(
        source_parts[-len(expected_suffix):]
    ) != expected_suffix:
        raise DatasetStorageError(
            "stored source session directory does not match "
            "the dataset partition"
        )

    manifest_sha256 = source.get(
        "manifest_sha256"
    )

    if (
        not isinstance(manifest_sha256, str)
        or SHA256_PATTERN.fullmatch(
            manifest_sha256
        )
        is None
    ):
        raise DatasetStorageError(
            "stored source manifest SHA-256 is invalid"
        )

    table_sha256 = source.get(
        "table_sha256"
    )

    if not isinstance(table_sha256, dict) or set(
        table_sha256
    ) != {
        "laps.parquet",
        "stints.parquet",
        "pit_events.parquet",
    }:
        raise DatasetStorageError(
            "stored source table hashes are invalid"
        )

    for filename, digest in table_sha256.items():
        if (
            not isinstance(digest, str)
            or SHA256_PATTERN.fullmatch(
                digest
            )
            is None
        ):
            raise DatasetStorageError(
                f"stored source hash for {filename} is invalid"
            )


def _validate_stored_quality_report(
    *,
    quality_report: dict[str, object],
    session_paths: DatasetSessionPaths,
) -> None:
    """Require stored quality status and identity to pass."""
    if (
        quality_report.get(
            "dataset_contract_version"
        )
        != DATASET_CONTRACT_VERSION
    ):
        raise DatasetStorageError(
            "stored quality-report contract version is unsupported"
        )

    session = quality_report.get("session")

    if not isinstance(session, dict):
        raise DatasetStorageError(
            "stored quality-report session must be an object"
        )

    if (
        session.get("identifier")
        != session_paths.session_key.identifier
    ):
        raise DatasetStorageError(
            "stored quality-report session does not match its path"
        )

    validation = quality_report.get(
        "validation"
    )
    leakage = quality_report.get(
        "leakage_validation"
    )

    if (
        not isinstance(validation, dict)
        or validation.get("status") != "passed"
        or validation.get("issue_count") != 0
    ):
        raise DatasetStorageError(
            "stored quality-report validation has not passed"
        )

    if (
        not isinstance(leakage, dict)
        or leakage.get("status") != "passed"
        or leakage.get(
            "protected_evaluation_season_accessed"
        )
        is not False
        or leakage.get("evaluation_season_rows") != 0
    ):
        raise DatasetStorageError(
            "stored quality-report leakage validation has not passed"
        )


def _promote_temporary_partition(
    session_paths: DatasetSessionPaths,
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
    session_paths: DatasetSessionPaths,
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