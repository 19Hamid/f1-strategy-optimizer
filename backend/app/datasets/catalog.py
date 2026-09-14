"""Build a verified catalog of stored development datasets."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pandas as pd

from app.datasets.contracts import (
    CATALOG_CONTRACT,
    DATASET_CONTRACT_VERSION,
    DEVELOPMENT_SEASONS,
    PROTECTED_EVALUATION_SEASON,
    SOURCE_CLEANING_RULE_VERSION,
    SOURCE_PROCESSED_CONTRACT_VERSION,
)
from app.datasets.paths import DatasetPaths
from app.datasets.storage import (
    DatasetStorageError,
    _validate_completed_partition,
)
from app.pipeline.models import SessionKey
from app.pipeline.serialization import (
    read_parquet_table,
    sha256_file,
    write_parquet_table,
)

DATASET_CATALOG_COLUMNS: Final = tuple(
    column.name
    for column in CATALOG_CONTRACT.columns
)

_DECISION_ROWS_FILE_NAME: Final = (
    "decision_rows.parquet"
)
_DECISION_LABELS_FILE_NAME: Final = (
    "decision_labels.parquet"
)
_PIT_DURATION_FILE_NAME: Final = (
    "pit_duration_observations.parquet"
)


class DatasetCatalogError(RuntimeError):
    """Raised when the dataset catalog cannot be built safely."""


@dataclass(frozen=True, slots=True)
class DatasetCatalogBuildResult:
    """Contain one completed global dataset catalog."""

    catalog: pd.DataFrame
    path: Path
    sha256: str


@dataclass(frozen=True, slots=True)
class DatasetCatalogBuilder:
    """Build a catalog from verified development partitions."""

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

    def build(
        self,
        session_keys: Iterable[SessionKey],
    ) -> DatasetCatalogBuildResult:
        """Verify, catalog and atomically publish sessions."""
        requested_sessions = _validate_session_keys(
            session_keys
        )

        rows = [
            _build_catalog_row(
                dataset_paths=self.dataset_paths,
                session_key=session_key,
            )
            for session_key in requested_sessions
        ]

        catalog = _build_catalog_frame(rows)

        _validate_catalog(
            catalog=catalog,
            expected_sessions=requested_sessions,
        )

        _publish_catalog(
            dataset_paths=self.dataset_paths,
            catalog=catalog,
            expected_sessions=requested_sessions,
        )

        return DatasetCatalogBuildResult(
            catalog=catalog,
            path=self.dataset_paths.catalog,
            sha256=sha256_file(
                self.dataset_paths.catalog
            ),
        )


def _build_catalog_row(
    *,
    dataset_paths: DatasetPaths,
    session_key: SessionKey,
) -> dict[str, object]:
    """Build one row from a verified stored partition."""
    session_paths = dataset_paths.for_session(
        session_key
    )

    try:
        manifest, quality_report = (
            _validate_completed_partition(
                session_paths
            )
        )
    except (
        AttributeError,
        DatasetStorageError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        raise DatasetCatalogError(
            "dataset partition failed storage validation "
            f"for {session_key.identifier}: {error}"
        ) from error

    session = _require_object(
        document=manifest,
        field="session",
        source="manifest",
    )
    source = _require_object(
        document=manifest,
        field="source",
        source="manifest",
    )
    files = _require_object(
        document=manifest,
        field="files",
        source="manifest",
    )
    source_counts = _require_object(
        document=quality_report,
        field="source_counts",
        source="quality report",
    )
    decision_quality = _require_object(
        document=quality_report,
        field="decision_quality",
        source="quality report",
    )
    target_quality = _require_object(
        document=quality_report,
        field="target_quality",
        source="quality report",
    )
    leakage_validation = _require_object(
        document=quality_report,
        field="leakage_validation",
        source="quality report",
    )

    _validate_session_identity(
        session=session,
        session_key=session_key,
    )
    _validate_versions(
        manifest=manifest,
        quality_report=quality_report,
        source=source,
        session_key=session_key,
    )
    _validate_leakage_summary(
        leakage_validation=(
            leakage_validation
        ),
        session_key=session_key,
    )

    decision_rows_record = _require_object(
        document=files,
        field=_DECISION_ROWS_FILE_NAME,
        source="manifest files",
    )
    decision_labels_record = _require_object(
        document=files,
        field=_DECISION_LABELS_FILE_NAME,
        source="manifest files",
    )
    pit_duration_record = _require_object(
        document=files,
        field=_PIT_DURATION_FILE_NAME,
        source="manifest files",
    )

    decision_rows = _require_nonnegative_integer(
        document=decision_rows_record,
        field="rows",
        source="decision-row manifest record",
    )
    decision_label_rows = (
        _require_nonnegative_integer(
            document=decision_labels_record,
            field="rows",
            source=(
                "decision-label manifest record"
            ),
        )
    )
    pit_duration_rows = (
        _require_nonnegative_integer(
            document=pit_duration_record,
            field="rows",
            source=(
                "pit-duration manifest record"
            ),
        )
    )
    candidate_decisions = (
        _require_nonnegative_integer(
            document=source_counts,
            field="candidate_decision_rows",
            source="quality-report source counts",
        )
    )
    source_pit_events = (
        _require_nonnegative_integer(
            document=source_counts,
            field="source_pit_events",
            source="quality-report source counts",
        )
    )
    eligible_decisions = (
        _require_nonnegative_integer(
            document=decision_quality,
            field="eligible_decisions",
            source=(
                "quality-report decision quality"
            ),
        )
    )
    ineligible_decisions = (
        _require_nonnegative_integer(
            document=decision_quality,
            field="ineligible_decisions",
            source=(
                "quality-report decision quality"
            ),
        )
    )
    pit_now_rows = _require_nonnegative_integer(
        document=decision_quality,
        field="historical_pit_now_actions",
        source="quality-report decision quality",
    )
    stay_out_rows = _require_nonnegative_integer(
        document=decision_quality,
        field="historical_stay_out_actions",
        source="quality-report decision quality",
    )
    lap_target_rows = (
        _require_nonnegative_integer(
            document=target_quality,
            field=(
                "lap_time_target_eligible_rows"
            ),
            source="quality-report target quality",
        )
    )
    lap_target_ineligible_rows = (
        _require_nonnegative_integer(
            document=target_quality,
            field=(
                "lap_time_target_ineligible_rows"
            ),
            source="quality-report target quality",
        )
    )
    pit_target_rows = (
        _require_nonnegative_integer(
            document=target_quality,
            field=(
                "pit_duration_target_eligible_rows"
            ),
            source="quality-report target quality",
        )
    )
    pit_target_ineligible_rows = (
        _require_nonnegative_integer(
            document=target_quality,
            field=(
                "pit_duration_target_ineligible_rows"
            ),
            source="quality-report target quality",
        )
    )

    _validate_row_counts(
        session_key=session_key,
        decision_rows=decision_rows,
        candidate_decisions=(
            candidate_decisions
        ),
        eligible_decisions=eligible_decisions,
        ineligible_decisions=(
            ineligible_decisions
        ),
        decision_label_rows=(
            decision_label_rows
        ),
        lap_target_rows=lap_target_rows,
        lap_target_ineligible_rows=(
            lap_target_ineligible_rows
        ),
        pit_now_rows=pit_now_rows,
        stay_out_rows=stay_out_rows,
        pit_duration_rows=pit_duration_rows,
        source_pit_events=source_pit_events,
        pit_target_rows=pit_target_rows,
        pit_target_ineligible_rows=(
            pit_target_ineligible_rows
        ),
    )

    total_size_bytes = _total_size_bytes(
        files=files,
        session_key=session_key,
    )

    return {
        "session_id": session_key.identifier,
        "season": session_key.season,
        "round_number": (
            session_key.round_number
        ),
        "session_type": (
            session_key.session_type
        ),
        "event_name": _require_text(
            document=session,
            field="event_name",
            source="manifest session",
        ),
        "dataset_contract_version": (
            DATASET_CONTRACT_VERSION
        ),
        "cleaning_rule_version": (
            SOURCE_CLEANING_RULE_VERSION
        ),
        "processed_contract_version": (
            SOURCE_PROCESSED_CONTRACT_VERSION
        ),
        "created_at_utc": _require_text(
            document=manifest,
            field="created_at_utc",
            source="manifest",
        ),
        "decision_rows": decision_rows,
        "eligible_decisions": (
            eligible_decisions
        ),
        "ineligible_decisions": (
            ineligible_decisions
        ),
        "decision_label_rows": (
            decision_label_rows
        ),
        "lap_time_target_eligible_rows": (
            lap_target_rows
        ),
        "pit_now_rows": pit_now_rows,
        "stay_out_rows": stay_out_rows,
        "pit_duration_rows": pit_duration_rows,
        "pit_duration_target_eligible_rows": (
            pit_target_rows
        ),
        "total_size_bytes": total_size_bytes,
        "session_directory": str(
            session_paths.directory
        ),
    }


def _validate_session_identity(
    *,
    session: dict[str, object],
    session_key: SessionKey,
) -> None:
    """Require stored identity to match the requested session."""
    expected = {
        "identifier": session_key.identifier,
        "season": session_key.season,
        "round_number": (
            session_key.round_number
        ),
        "session_type": (
            session_key.session_type
        ),
    }

    for field, expected_value in expected.items():
        actual_value = session.get(field)

        if actual_value != expected_value:
            raise DatasetCatalogError(
                "stored session identity mismatch for "
                f"{session_key.identifier}: "
                f"{field}={actual_value!r}"
            )

    _require_text(
        document=session,
        field="event_name",
        source="manifest session",
    )


def _validate_versions(
    *,
    manifest: dict[str, object],
    quality_report: dict[str, object],
    source: dict[str, object],
    session_key: SessionKey,
) -> None:
    """Require every stored contract version to be supported."""
    dataset_versions = (
        _require_text(
            document=manifest,
            field="dataset_contract_version",
            source="manifest",
        ),
        _require_text(
            document=quality_report,
            field="dataset_contract_version",
            source="quality report",
        ),
    )

    if any(
        version != DATASET_CONTRACT_VERSION
        for version in dataset_versions
    ):
        raise DatasetCatalogError(
            "dataset contract version mismatch for "
            f"{session_key.identifier}: "
            f"{dataset_versions}"
        )

    cleaning_version = _require_text(
        document=source,
        field="cleaning_rule_version",
        source="manifest source",
    )
    processed_version = _require_text(
        document=source,
        field="processed_contract_version",
        source="manifest source",
    )

    if (
        cleaning_version
        != SOURCE_CLEANING_RULE_VERSION
    ):
        raise DatasetCatalogError(
            "cleaning-rule version mismatch for "
            f"{session_key.identifier}: "
            f"{cleaning_version!r}"
        )

    if (
        processed_version
        != SOURCE_PROCESSED_CONTRACT_VERSION
    ):
        raise DatasetCatalogError(
            "processed-contract version mismatch for "
            f"{session_key.identifier}: "
            f"{processed_version!r}"
        )


def _validate_leakage_summary(
    *,
    leakage_validation: dict[str, object],
    session_key: SessionKey,
) -> None:
    """Require every persisted leakage check to pass."""
    status = _require_text(
        document=leakage_validation,
        field="status",
        source="quality-report leakage validation",
    )

    if status != "passed":
        raise DatasetCatalogError(
            "stored leakage validation failed for "
            f"{session_key.identifier}: {status!r}"
        )

    for field in (
        "future_weather_matches",
        "evaluation_season_rows",
    ):
        count = _require_nonnegative_integer(
            document=leakage_validation,
            field=field,
            source=(
                "quality-report leakage validation"
            ),
        )

        if count != 0:
            raise DatasetCatalogError(
                "stored leakage count is non-zero for "
                f"{session_key.identifier}: "
                f"{field}={count}"
            )

    for field in (
        "current_lap_timing_features",
        "current_lap_quality_features",
        "features_outside_allowlist",
    ):
        value = leakage_validation.get(field)

        if not isinstance(value, list):
            raise DatasetCatalogError(
                "stored leakage field must be a list for "
                f"{session_key.identifier}: {field}"
            )

        if value:
            raise DatasetCatalogError(
                "stored leakage field must be empty for "
                f"{session_key.identifier}: {field}"
            )

    protected_accessed = leakage_validation.get(
        "protected_evaluation_season_accessed"
    )

    if protected_accessed is not False:
        raise DatasetCatalogError(
            "quality report indicates protected-season "
            f"access for {session_key.identifier}"
        )


def _validate_row_counts(
    *,
    session_key: SessionKey,
    decision_rows: int,
    candidate_decisions: int,
    eligible_decisions: int,
    ineligible_decisions: int,
    decision_label_rows: int,
    lap_target_rows: int,
    lap_target_ineligible_rows: int,
    pit_now_rows: int,
    stay_out_rows: int,
    pit_duration_rows: int,
    source_pit_events: int,
    pit_target_rows: int,
    pit_target_ineligible_rows: int,
) -> None:
    """Cross-check manifest and quality-report counts."""
    if decision_rows <= 0:
        raise DatasetCatalogError(
            "catalog session must contain decisions: "
            f"{session_key.identifier}"
        )

    checks = (
        (
            candidate_decisions,
            decision_rows,
            "candidate decisions",
        ),
        (
            eligible_decisions
            + ineligible_decisions,
            decision_rows,
            "decision eligibility",
        ),
        (
            decision_label_rows,
            decision_rows,
            "decision labels",
        ),
        (
            pit_now_rows + stay_out_rows,
            eligible_decisions,
            "eligible historical actions",
        ),
        (
            lap_target_rows
            + lap_target_ineligible_rows,
            eligible_decisions,
            "eligible decision lap targets",
        ),
        (
            source_pit_events,
            pit_duration_rows,
            "source pit events",
        ),
        (
            pit_target_rows
            + pit_target_ineligible_rows,
            pit_duration_rows,
            "pit-duration targets",
        ),
    )

    for actual, expected, label in checks:
        if actual != expected:
            raise DatasetCatalogError(
                f"{label} count mismatch for "
                f"{session_key.identifier}: "
                f"{actual} != {expected}"
            )


def _total_size_bytes(
    *,
    files: dict[str, object],
    session_key: SessionKey,
) -> int:
    """Sum authoritative file sizes from the manifest."""
    total_size_bytes = 0

    for filename, value in files.items():
        if not isinstance(value, dict):
            raise DatasetCatalogError(
                "manifest file record must be an object "
                f"for {session_key.identifier}: {filename}"
            )

        total_size_bytes += (
            _require_nonnegative_integer(
                document=value,
                field="size_bytes",
                source=(
                    f"manifest file {filename}"
                ),
            )
        )

    if total_size_bytes <= 0:
        raise DatasetCatalogError(
            "catalog session must contain stored bytes: "
            f"{session_key.identifier}"
        )

    return total_size_bytes


def _build_catalog_frame(
    rows: list[dict[str, object]],
) -> pd.DataFrame:
    """Create a canonically typed and sorted catalog."""
    catalog = pd.DataFrame(
        rows,
        columns=DATASET_CATALOG_COLUMNS,
    )

    for column in CATALOG_CONTRACT.columns:
        try:
            catalog[column.name] = catalog[
                column.name
            ].astype(column.pandas_dtype)
        except (TypeError, ValueError) as error:
            raise DatasetCatalogError(
                "dataset catalog column cannot be cast: "
                f"{column.name} -> "
                f"{column.pandas_dtype}"
            ) from error

    return catalog.sort_values(
        [
            "season",
            "round_number",
            "session_type",
        ],
        kind="stable",
    ).reset_index(drop=True)


def _validate_catalog(
    *,
    catalog: pd.DataFrame,
    expected_sessions: tuple[SessionKey, ...],
) -> None:
    """Validate global catalog schema and identities."""
    actual_columns = tuple(
        str(column)
        for column in catalog.columns
    )

    if actual_columns != DATASET_CATALOG_COLUMNS:
        raise DatasetCatalogError(
            "dataset catalog columns are invalid"
        )

    if len(catalog) != len(expected_sessions):
        raise DatasetCatalogError(
            "dataset catalog row count is invalid"
        )

    for column in CATALOG_CONTRACT.columns:
        actual_dtype = str(
            catalog[column.name].dtype
        )

        if actual_dtype != column.pandas_dtype:
            raise DatasetCatalogError(
                "dataset catalog dtype is invalid: "
                f"{column.name} expected "
                f"{column.pandas_dtype}, got "
                f"{actual_dtype}"
            )

        if (
            not column.nullable
            and catalog[column.name].isna().any()
        ):
            raise DatasetCatalogError(
                "dataset catalog required column has "
                f"nulls: {column.name}"
            )

    if not catalog["session_id"].is_unique:
        raise DatasetCatalogError(
            "dataset catalog session IDs must be unique"
        )

    expected_ids = {
        session_key.identifier
        for session_key in expected_sessions
    }
    actual_ids = set(
        catalog["session_id"].astype(str)
    )

    if actual_ids != expected_ids:
        raise DatasetCatalogError(
            "dataset catalog identities differ from the "
            "requested sessions"
        )

    if not set(catalog["season"]).issubset(
        DEVELOPMENT_SEASONS
    ):
        raise DatasetCatalogError(
            "dataset catalog contains a non-development "
            "season"
        )

    _validate_catalog_order(catalog)

    count_columns = (
        "decision_rows",
        "eligible_decisions",
        "ineligible_decisions",
        "decision_label_rows",
        "lap_time_target_eligible_rows",
        "pit_now_rows",
        "stay_out_rows",
        "pit_duration_rows",
        "pit_duration_target_eligible_rows",
        "total_size_bytes",
    )

    if catalog[list(count_columns)].lt(0).any().any():
        raise DatasetCatalogError(
            "dataset catalog contains a negative count"
        )

    if not catalog[
        "dataset_contract_version"
    ].eq(DATASET_CONTRACT_VERSION).all():
        raise DatasetCatalogError(
            "dataset catalog contract version is invalid"
        )

    if not catalog[
        "cleaning_rule_version"
    ].eq(SOURCE_CLEANING_RULE_VERSION).all():
        raise DatasetCatalogError(
            "dataset catalog cleaning version is invalid"
        )

    if not catalog[
        "processed_contract_version"
    ].eq(SOURCE_PROCESSED_CONTRACT_VERSION).all():
        raise DatasetCatalogError(
            "dataset catalog processed version is invalid"
        )


def _validate_catalog_order(
    catalog: pd.DataFrame,
) -> None:
    """Require canonical stable identity ordering."""
    identity_columns = [
        "season",
        "round_number",
        "session_type",
    ]
    actual_identity = catalog[
        identity_columns
    ].reset_index(drop=True)
    sorted_identity = actual_identity.sort_values(
        identity_columns,
        kind="stable",
    ).reset_index(drop=True)

    try:
        pd.testing.assert_frame_equal(
            actual_identity,
            sorted_identity,
        )
    except AssertionError as error:
        raise DatasetCatalogError(
            "dataset catalog is not sorted by its "
            "canonical identity"
        ) from error


def _publish_catalog(
    *,
    dataset_paths: DatasetPaths,
    catalog: pd.DataFrame,
    expected_sessions: tuple[SessionKey, ...],
) -> None:
    """Write, read back and atomically promote the catalog."""
    temporary_path = (
        dataset_paths.version_root
        / ".tmp"
        / CATALOG_CONTRACT.file_name
    )

    if temporary_path.exists():
        if not temporary_path.is_file():
            raise DatasetCatalogError(
                "temporary catalog path is not a file: "
                f"{temporary_path}"
            )

        temporary_path.unlink()

    try:
        write_parquet_table(
            catalog,
            temporary_path,
        )

        restored_catalog = read_parquet_table(
            temporary_path
        )

        try:
            pd.testing.assert_frame_equal(
                restored_catalog,
                catalog,
            )
        except AssertionError as error:
            raise DatasetCatalogError(
                "dataset catalog Parquet readback "
                "differs from its source"
            ) from error

        _validate_catalog(
            catalog=restored_catalog,
            expected_sessions=(
                expected_sessions
            ),
        )

        dataset_paths.catalog.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        temporary_path.replace(
            dataset_paths.catalog
        )
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _validate_session_keys(
    session_keys: Iterable[SessionKey],
) -> tuple[SessionKey, ...]:
    """Validate requested development-session identities."""
    if isinstance(session_keys, (str, bytes)):
        raise TypeError(
            "session_keys must be an iterable of "
            "SessionKey values"
        )

    try:
        requested = tuple(session_keys)
    except TypeError as error:
        raise TypeError(
            "session_keys must be an iterable of "
            "SessionKey values"
        ) from error

    if not requested:
        raise DatasetCatalogError(
            "dataset catalog requires at least one "
            "session"
        )

    for session_key in requested:
        if not isinstance(session_key, SessionKey):
            raise TypeError(
                "session_keys must contain only "
                "SessionKey values"
            )

        if (
            session_key.season
            == PROTECTED_EVALUATION_SEASON
        ):
            raise DatasetCatalogError(
                f"{session_key.identifier} belongs to the "
                "protected evaluation season"
            )

        if session_key.season not in DEVELOPMENT_SEASONS:
            raise DatasetCatalogError(
                f"{session_key.identifier} is outside the "
                "development seasons"
            )

        if session_key.session_type != "R":
            raise DatasetCatalogError(
                f"{session_key.identifier} is not a race "
                "session"
            )

    identifiers = [
        session_key.identifier
        for session_key in requested
    ]

    if len(identifiers) != len(set(identifiers)):
        raise DatasetCatalogError(
            "dataset catalog session identities must be "
            "unique"
        )

    return requested


def _require_object(
    *,
    document: dict[str, object],
    field: str,
    source: str,
) -> dict[str, object]:
    """Return a required nested JSON object."""
    value = document.get(field)

    if not isinstance(value, dict):
        raise DatasetCatalogError(
            f"{source} field {field!r} must be an object"
        )

    return value


def _require_text(
    *,
    document: dict[str, object],
    field: str,
    source: str,
) -> str:
    """Return required non-empty JSON text."""
    value = document.get(field)

    if not isinstance(value, str) or not value.strip():
        raise DatasetCatalogError(
            f"{source} field {field!r} must be "
            "non-empty text"
        )

    return value


def _require_nonnegative_integer(
    *,
    document: dict[str, object],
    field: str,
    source: str,
) -> int:
    """Return a required non-negative JSON integer."""
    value = document.get(field)

    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise DatasetCatalogError(
            f"{source} field {field!r} must be a "
            "non-negative integer"
        )

    return value