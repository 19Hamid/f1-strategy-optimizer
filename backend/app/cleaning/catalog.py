"""Build a verified catalog of processed development races."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pandas as pd

from app.cleaning.integrity import (
    verify_processed_partition,
)
from app.cleaning.paths import ProcessedDataPaths
from app.cleaning.profile import (
    DEVELOPMENT_SEASONS,
)
from app.pipeline.models import SessionKey
from app.pipeline.serialization import (
    read_json_document,
    read_parquet_table,
    sha256_file,
    write_parquet_table,
)

PROCESSED_CATALOG_COLUMNS: Final = (
    "session_id",
    "season",
    "round_number",
    "session_type",
    "event_name",
    "processed_contract_version",
    "cleaning_rule_version",
    "source_contract_version",
    "created_at_utc",
    "laps_rows",
    "eligible_laps",
    "excluded_laps",
    "eligibility_rate",
    "stints_rows",
    "complete_stints",
    "incomplete_stints",
    "pit_events_rows",
    "complete_pit_events",
    "incomplete_pit_events",
    "duration_analysis_candidates",
    "total_size_bytes",
    "session_directory",
)


class ProcessedCatalogError(RuntimeError):
    """Raised when the processed catalog cannot be built."""


@dataclass(frozen=True, slots=True)
class ProcessedCatalogBuildResult:
    """Contain a completed processed catalog."""

    catalog: pd.DataFrame
    path: Path
    sha256: str


@dataclass(frozen=True, slots=True)
class ProcessedCatalogBuilder:
    """Build one catalog from verified development partitions."""

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

    def build(
        self,
        session_keys: Iterable[SessionKey],
    ) -> ProcessedCatalogBuildResult:
        """Verify, catalog and atomically publish sessions."""
        requested_sessions = (
            _validate_session_keys(
                session_keys
            )
        )

        rows = [
            _build_catalog_row(
                processed_paths=self.processed_paths,
                session_key=session_key,
            )
            for session_key in requested_sessions
        ]

        catalog = pd.DataFrame(
            rows,
            columns=PROCESSED_CATALOG_COLUMNS,
        ).sort_values(
            [
                "season",
                "round_number",
                "session_type",
            ],
            kind="stable",
        ).reset_index(
            drop=True
        )

        _validate_catalog(
            catalog=catalog,
            expected_sessions=(
                requested_sessions
            ),
        )

        temporary_path = (
            self.processed_paths.version_root
            / ".tmp"
            / "catalog.parquet"
        )

        if temporary_path.exists():
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
                raise ProcessedCatalogError(
                    "processed catalog Parquet readback "
                    "differs from its source"
                ) from error

            self.processed_paths.catalog.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            temporary_path.replace(
                self.processed_paths.catalog
            )
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

        return ProcessedCatalogBuildResult(
            catalog=catalog,
            path=self.processed_paths.catalog,
            sha256=sha256_file(
                self.processed_paths.catalog
            ),
        )


def _build_catalog_row(
    *,
    processed_paths: ProcessedDataPaths,
    session_key: SessionKey,
) -> dict[str, object]:
    """Build one row from a verified partition."""
    integrity = verify_processed_partition(
        processed_paths,
        session_key,
    )

    if not integrity.is_valid:
        details = "; ".join(
            (
                f"{issue.code}: "
                f"{issue.message}"
            )
            for issue in integrity.issues
        )

        raise ProcessedCatalogError(
            "processed partition failed integrity for "
            f"{session_key.identifier}: {details}"
        )

    manifest = integrity.manifest

    if manifest is None:
        raise ProcessedCatalogError(
            "verified processed partition has no manifest"
        )

    session_paths = processed_paths.for_session(
        session_key
    )
    quality_report = read_json_document(
        session_paths.quality_report
    )

    session = _require_object(
        document=quality_report,
        field="session",
        source="quality report",
    )
    tables = _require_object(
        document=quality_report,
        field="tables",
        source="quality report",
    )
    lap_quality = _require_object(
        document=quality_report,
        field="lap_quality",
        source="quality report",
    )
    stint_quality = _require_object(
        document=quality_report,
        field="stint_quality",
        source="quality report",
    )
    pit_quality = _require_object(
        document=quality_report,
        field="pit_event_quality",
        source="quality report",
    )
    files = _require_object(
        document=manifest,
        field="files",
        source="manifest",
    )

    eligible_laps = _require_integer(
        document=lap_quality,
        field="eligible_laps",
        source="lap quality",
    )
    excluded_laps = _require_integer(
        document=lap_quality,
        field="excluded_laps",
        source="lap quality",
    )
    total_laps = (
        eligible_laps + excluded_laps
    )

    if total_laps <= 0:
        raise ProcessedCatalogError(
            "catalog session must contain at least one lap"
        )

    total_size_bytes = 0

    for filename, record in files.items():
        if not isinstance(record, dict):
            raise ProcessedCatalogError(
                f"manifest record is invalid: {filename}"
            )

        total_size_bytes += _require_integer(
            document=record,
            field="size_bytes",
            source=f"manifest file {filename}",
        )

    event_name = session.get("event_name")

    if not isinstance(event_name, str):
        raise ProcessedCatalogError(
            "quality report event_name must be text"
        )

    created_at_utc = manifest.get(
        "created_at_utc"
    )

    if not isinstance(created_at_utc, str):
        raise ProcessedCatalogError(
            "manifest created_at_utc must be text"
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
        "event_name": event_name,
        "processed_contract_version": (
            quality_report[
                "processed_contract_version"
            ]
        ),
        "cleaning_rule_version": (
            quality_report[
                "cleaning_rule_version"
            ]
        ),
        "source_contract_version": (
            quality_report[
                "source_contract_version"
            ]
        ),
        "created_at_utc": created_at_utc,
        "laps_rows": _require_integer(
            document=tables,
            field="laps_rows",
            source="quality-report tables",
        ),
        "eligible_laps": eligible_laps,
        "excluded_laps": excluded_laps,
        "eligibility_rate": (
            eligible_laps / total_laps
        ),
        "stints_rows": _require_integer(
            document=tables,
            field="stints_rows",
            source="quality-report tables",
        ),
        "complete_stints": _require_integer(
            document=stint_quality,
            field="complete_stints",
            source="stint quality",
        ),
        "incomplete_stints": _require_integer(
            document=stint_quality,
            field="incomplete_stints",
            source="stint quality",
        ),
        "pit_events_rows": _require_integer(
            document=tables,
            field="pit_events_rows",
            source="quality-report tables",
        ),
        "complete_pit_events": (
            _require_integer(
                document=pit_quality,
                field="complete_events",
                source="pit-event quality",
            )
        ),
        "incomplete_pit_events": (
            _require_integer(
                document=pit_quality,
                field="incomplete_events",
                source="pit-event quality",
            )
        ),
        "duration_analysis_candidates": (
            _require_integer(
                document=pit_quality,
                field=(
                    "duration_analysis_candidates"
                ),
                source="pit-event quality",
            )
        ),
        "total_size_bytes": total_size_bytes,
        "session_directory": str(
            session_paths.directory
        ),
    }


def _validate_catalog(
    *,
    catalog: pd.DataFrame,
    expected_sessions: tuple[
        SessionKey,
        ...,
    ],
) -> None:
    """Validate catalog identity and development isolation."""
    if tuple(catalog.columns) != (
        PROCESSED_CATALOG_COLUMNS
    ):
        raise ProcessedCatalogError(
            "processed catalog columns are invalid"
        )

    if len(catalog) != len(
        expected_sessions
    ):
        raise ProcessedCatalogError(
            "processed catalog row count is invalid"
        )

    if not catalog["session_id"].is_unique:
        raise ProcessedCatalogError(
            "processed catalog session IDs must be unique"
        )

    expected_ids = {
        session_key.identifier
        for session_key in expected_sessions
    }

    if set(catalog["session_id"]) != expected_ids:
        raise ProcessedCatalogError(
            "processed catalog sessions do not match "
            "the request"
        )

    if not set(
        catalog["season"]
    ).issubset(
        DEVELOPMENT_SEASONS
    ):
        raise ProcessedCatalogError(
            "processed catalog contains evaluation data"
        )


def _validate_session_keys(
    session_keys: Iterable[SessionKey],
) -> tuple[SessionKey, ...]:
    """Validate requested development sessions."""
    if isinstance(
        session_keys,
        (
            str,
            bytes,
        ),
    ):
        raise TypeError(
            "session_keys must contain SessionKey objects"
        )

    try:
        requested_sessions = tuple(
            session_keys
        )
    except TypeError as error:
        raise TypeError(
            "session_keys must be iterable"
        ) from error

    if not requested_sessions:
        raise ValueError(
            "at least one session key is required"
        )

    for session_key in requested_sessions:
        if not isinstance(
            session_key,
            SessionKey,
        ):
            raise TypeError(
                "every catalog session must be "
                "a SessionKey"
            )

        if (
            session_key.season
            not in DEVELOPMENT_SEASONS
        ):
            raise ValueError(
                "processed development catalogs cannot "
                "include evaluation seasons"
            )

    if (
        len(set(requested_sessions))
        != len(requested_sessions)
    ):
        raise ValueError(
            "duplicate catalog sessions are not allowed"
        )

    return requested_sessions


def _require_object(
    *,
    document: dict[str, object],
    field: str,
    source: str,
) -> dict[str, object]:
    """Return one required JSON object."""
    value = document.get(field)

    if not isinstance(value, dict):
        raise ProcessedCatalogError(
            f"{source} {field} must be an object"
        )

    return value


def _require_integer(
    *,
    document: dict[str, object],
    field: str,
    source: str,
) -> int:
    """Return one required non-negative integer."""
    value = document.get(field)

    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise ProcessedCatalogError(
            f"{source} {field} must be a "
            "non-negative integer"
        )

    return value