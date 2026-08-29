"""Build a searchable catalog of stored Formula 1 sessions."""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from app.pipeline.integrity import verify_session_partition
from app.pipeline.models import SessionKey
from app.pipeline.paths import RawDataPaths
from app.pipeline.serialization import (
    read_json_document,
    read_parquet_table,
    sha256_file,
    write_parquet_table,
)

CATALOG_COLUMNS = (
    "session_id",
    "season",
    "round_number",
    "session_type",
    "event_name",
    "created_at_utc",
    "fastf1_version",
    "telemetry_loaded",
    "laps_rows",
    "weather_rows",
    "results_rows",
    "total_size_bytes",
    "session_directory",
)


class CatalogBuildError(RuntimeError):
    """Raised when a raw-data catalog cannot be built safely."""


@dataclass(frozen=True, slots=True)
class CatalogBuildResult:
    """Describe a completed raw-data catalog."""

    path: Path
    session_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class RawCatalogBuilder:
    """Rebuild the raw-data catalog from verified manifests."""

    raw_paths: RawDataPaths

    def build(self) -> CatalogBuildResult:
        """Build and atomically publish the complete catalog."""
        manifest_paths = sorted(
            self.raw_paths.raw_root.glob(
                "season=*/round=*/session=*/manifest.json"
            )
        )

        if not manifest_paths:
            raise CatalogBuildError(
                "no completed session manifests were found"
            )

        records = [
            self._build_record(manifest_path)
            for manifest_path in manifest_paths
        ]

        catalog = pd.DataFrame.from_records(
            records,
            columns=CATALOG_COLUMNS,
        )
        catalog = catalog.sort_values(
            by=[
                "season",
                "round_number",
                "session_type",
            ],
            kind="stable",
        ).reset_index(drop=True)

        temporary_path = (
            self.raw_paths.raw_root
            / ".tmp"
            / "catalog.parquet"
        )
        temporary_path.unlink(missing_ok=True)

        write_parquet_table(
            catalog,
            temporary_path,
        )

        restored = read_parquet_table(temporary_path)

        try:
            pd.testing.assert_frame_equal(
                restored,
                catalog,
                check_frame_type=False,
            )
        except AssertionError as error:
            temporary_path.unlink(missing_ok=True)
            raise CatalogBuildError(
                "catalog Parquet readback validation failed"
            ) from error

        self.raw_paths.catalog.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        temporary_path.replace(
            self.raw_paths.catalog
        )

        return CatalogBuildResult(
            path=self.raw_paths.catalog,
            session_count=len(catalog),
            sha256=sha256_file(
                self.raw_paths.catalog
            ),
        )

    def _build_record(
        self,
        manifest_path: Path,
    ) -> dict[str, object]:
        """Build one catalog row from a verified session."""
        session_key = _session_key_from_path(
            manifest_path
        )

        integrity = verify_session_partition(
            self.raw_paths,
            session_key,
        )
        integrity.raise_for_errors()

        session_paths = self.raw_paths.for_session(
            session_key
        )
        manifest = read_json_document(
            manifest_path
        )
        metadata = read_json_document(
            session_paths.metadata
        )

        session = _required_mapping(
            manifest,
            "session",
        )
        source = _required_mapping(
            manifest,
            "source",
        )
        files = _required_mapping(
            manifest,
            "files",
        )

        laps_record = _required_mapping(
            files,
            "laps.parquet",
        )
        weather_record = _required_mapping(
            files,
            "weather.parquet",
        )
        results_record = _required_mapping(
            files,
            "results.parquet",
        )
        metadata_record = _required_mapping(
            files,
            "metadata.json",
        )

        telemetry_loaded = metadata.get(
            "telemetry_loaded"
        )

        if not isinstance(telemetry_loaded, bool):
            raise CatalogBuildError(
                "metadata telemetry_loaded must be a boolean"
            )

        size_records = (
            laps_record,
            weather_record,
            results_record,
            metadata_record,
        )

        total_size_bytes = sum(
            _required_integer(record, "size_bytes")
            for record in size_records
        )

        return {
            "session_id": session_key.identifier,
            "season": session_key.season,
            "round_number": session_key.round_number,
            "session_type": session_key.session_type,
            "event_name": _required_string(
                session,
                "event_name",
            ),
            "created_at_utc": _required_string(
                manifest,
                "created_at_utc",
            ),
            "fastf1_version": _required_string(
                source,
                "version",
            ),
            "telemetry_loaded": telemetry_loaded,
            "laps_rows": _required_integer(
                laps_record,
                "rows",
            ),
            "weather_rows": _required_integer(
                weather_record,
                "rows",
            ),
            "results_rows": _required_integer(
                results_record,
                "rows",
            ),
            "total_size_bytes": total_size_bytes,
            "session_directory": str(
                session_paths.directory.relative_to(
                    self.raw_paths.raw_root
                )
            ),
        }


def _session_key_from_path(
    manifest_path: Path,
) -> SessionKey:
    """Parse a session identity from partition directory names."""
    session_directory = manifest_path.parent

    season_text = _partition_value(
        session_directory.parent.parent.name,
        "season",
    )
    round_text = _partition_value(
        session_directory.parent.name,
        "round",
    )
    session_type = _partition_value(
        session_directory.name,
        "session",
    )

    try:
        season = int(season_text)
        round_number = int(round_text)
    except ValueError as error:
        raise CatalogBuildError(
            f"invalid session partition: {session_directory}"
        ) from error

    return SessionKey(
        season=season,
        round_number=round_number,
        session_type=session_type,
    )


def _partition_value(
    directory_name: str,
    expected_name: str,
) -> str:
    """Extract a value from one Hive-style partition name."""
    prefix = f"{expected_name}="

    if not directory_name.startswith(prefix):
        raise CatalogBuildError(
            f"expected partition beginning with {prefix!r}"
        )

    value = directory_name.removeprefix(prefix)

    if not value:
        raise CatalogBuildError(
            f"partition {directory_name!r} has no value"
        )

    return value


def _required_mapping(
    document: dict[str, object],
    key: str,
) -> dict[str, object]:
    """Return one required nested JSON object."""
    value = document.get(key)

    if not isinstance(value, dict):
        raise CatalogBuildError(
            f"{key} must be a JSON object"
        )

    return value


def _required_string(
    document: dict[str, object],
    key: str,
) -> str:
    """Return one required non-empty string."""
    value = document.get(key)

    if not isinstance(value, str) or not value.strip():
        raise CatalogBuildError(
            f"{key} must be a non-empty string"
        )

    return value


def _required_integer(
    document: dict[str, object],
    key: str,
) -> int:
    """Return one required non-negative integer."""
    value = document.get(key)

    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise CatalogBuildError(
            f"{key} must be a non-negative integer"
        )

    return value