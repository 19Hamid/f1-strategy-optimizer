"""Atomically store and verify on-demand lap telemetry."""

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pandas as pd

from app.pipeline.serialization import (
    read_json_document,
    read_parquet_table,
    sha256_file,
    write_json_document,
    write_parquet_table,
)
from app.pipeline.telemetry import (
    TelemetryDataPaths,
    TelemetryRequest,
)
from app.pipeline.telemetry_source import TelemetryLapData

TELEMETRY_CONTRACT_VERSION = "1.0"
TELEMETRY_FILENAME = "telemetry.parquet"
METADATA_FILENAME = "metadata.json"
MANIFEST_FILENAME = "manifest.json"

type TelemetryWriteStatus = Literal[
    "written",
    "skipped",
]


class TelemetryStorageError(RuntimeError):
    """Raised when telemetry cannot be stored safely."""


@dataclass(frozen=True, slots=True)
class TelemetryWriteResult:
    """Describe the result of one telemetry write."""

    request: TelemetryRequest
    status: TelemetryWriteStatus
    directory: Path
    manifest: dict[str, object]


@dataclass(frozen=True, slots=True)
class TelemetryWriter:
    """Write telemetry using temporary and atomic directories."""

    paths: TelemetryDataPaths

    def __post_init__(self) -> None:
        """Validate the configured telemetry paths."""
        if not isinstance(self.paths, TelemetryDataPaths):
            raise TypeError(
                "paths must be TelemetryDataPaths"
            )

    def inspect_existing(
        self,
        request: TelemetryRequest,
    ) -> TelemetryWriteResult | None:
        """Inspect a stored request without extracting telemetry."""
        if not isinstance(request, TelemetryRequest):
            raise TypeError(
                "request must be a TelemetryRequest"
            )

        final_directory = self.paths.directory_for(
            request
        )

        if not final_directory.exists():
            return None

        manifest = self._verified_manifest(
            request,
            final_directory,
        )

        if manifest is None:
            raise TelemetryStorageError(
                "telemetry partition is incomplete or "
                "corrupted; rerun with force=True: "
                f"{final_directory}"
            )

        return TelemetryWriteResult(
            request=request,
            status="skipped",
            directory=final_directory,
            manifest=manifest,
        )

    def write(
        self,
        data: TelemetryLapData,
        *,
        force: bool = False,
    ) -> TelemetryWriteResult:
        """Write one telemetry request safely."""
        if not isinstance(data, TelemetryLapData):
            raise TypeError(
                "data must be TelemetryLapData"
            )

        if not isinstance(force, bool):
            raise TypeError("force must be a boolean")

        if data.telemetry.empty:
            raise TelemetryStorageError(
                "telemetry table must not be empty"
            )

        request = data.request
        final_directory = self.paths.directory_for(
            request
        )

        if not force:
            existing_result = self.inspect_existing(
                request
            )

            if existing_result is not None:
                return existing_result

        temporary_directory = (
            self.paths.temporary_root
            / f"{request.identifier}-{uuid4().hex}"
        )

        temporary_directory.mkdir(
            parents=True,
            exist_ok=False,
        )

        try:
            manifest = self._write_temporary_partition(
                data,
                temporary_directory,
            )

            self._promote_directory(
                temporary_directory,
                final_directory,
            )
        finally:
            if temporary_directory.exists():
                shutil.rmtree(
                    temporary_directory,
                    ignore_errors=True,
                )

        verified_manifest = self._verified_manifest(
            request,
            final_directory,
        )

        if verified_manifest is None:
            raise TelemetryStorageError(
                "written telemetry partition failed its "
                "final integrity verification"
            )

        return TelemetryWriteResult(
            request=request,
            status="written",
            directory=final_directory,
            manifest=manifest,
        )

    def _write_temporary_partition(
        self,
        data: TelemetryLapData,
        directory: Path,
    ) -> dict[str, object]:
        """Write and verify files inside a temporary directory."""
        telemetry_path = directory / TELEMETRY_FILENAME
        metadata_path = directory / METADATA_FILENAME
        manifest_path = directory / MANIFEST_FILENAME

        metadata = self._build_metadata(data)

        write_parquet_table(
            data.telemetry,
            telemetry_path,
        )
        write_json_document(
            metadata,
            metadata_path,
        )

        stored_telemetry = read_parquet_table(
            telemetry_path
        )
        stored_metadata = read_json_document(
            metadata_path
        )

        self._assert_frames_equivalent(
            data.telemetry,
            stored_telemetry,
        )

        if stored_metadata != metadata:
            raise TelemetryStorageError(
                "telemetry metadata failed JSON readback"
            )

        files: dict[str, object] = {
            TELEMETRY_FILENAME: {
                "rows": len(stored_telemetry),
                "size_bytes": telemetry_path.stat().st_size,
                "sha256": sha256_file(telemetry_path),
            },
            METADATA_FILENAME: {
                "size_bytes": metadata_path.stat().st_size,
                "sha256": sha256_file(metadata_path),
            },
        }

        manifest: dict[str, object] = {
            "contract_version": (
                TELEMETRY_CONTRACT_VERSION
            ),
            "telemetry_id": data.request.identifier,
            "session_id": (
                data.request.session_key.identifier
            ),
            "season": data.request.session_key.season,
            "round_number": (
                data.request.session_key.round_number
            ),
            "session_type": (
                data.request.session_key.session_type
            ),
            "driver": data.request.driver,
            "lap_number": data.request.lap_number,
            "files": files,
        }

        write_json_document(
            manifest,
            manifest_path,
        )

        if read_json_document(manifest_path) != manifest:
            raise TelemetryStorageError(
                "telemetry manifest failed JSON readback"
            )

        return manifest

    @staticmethod
    def _build_metadata(
        data: TelemetryLapData,
    ) -> dict[str, object]:
        """Build authoritative stored metadata."""
        metadata = dict(data.metadata)

        metadata.update(
            {
                "contract_version": (
                    TELEMETRY_CONTRACT_VERSION
                ),
                "storage_format": "parquet",
                "compression": "zstd",
                "telemetry_id": (
                    data.request.identifier
                ),
                "session_id": (
                    data.request.session_key.identifier
                ),
                "season": (
                    data.request.session_key.season
                ),
                "round_number": (
                    data.request.session_key.round_number
                ),
                "session_type": (
                    data.request.session_key.session_type
                ),
                "driver": data.request.driver,
                "lap_number": data.request.lap_number,
                "sample_count": len(data.telemetry),
                "available_columns": list(
                    data.telemetry.columns
                ),
            }
        )

        return metadata

    @staticmethod
    def _assert_frames_equivalent(
        expected: pd.DataFrame,
        actual: pd.DataFrame,
    ) -> None:
        """Compare Parquet readback while ignoring row labels."""
        expected_normalized = expected.reset_index(
            drop=True
        )
        actual_normalized = actual.reset_index(
            drop=True
        )

        if (
            expected_normalized.shape
            != actual_normalized.shape
        ):
            raise TelemetryStorageError(
                "telemetry Parquet readback changed "
                "the table shape"
            )

        if (
            list(expected_normalized.columns)
            != list(actual_normalized.columns)
        ):
            raise TelemetryStorageError(
                "telemetry Parquet readback changed "
                "the column order"
            )

        for column in expected_normalized.columns:
            expected_series = expected_normalized[column]
            actual_series = actual_normalized[column]

            if expected_series.dtype != actual_series.dtype:
                raise TelemetryStorageError(
                    "telemetry Parquet readback changed "
                    f"the dtype of {column}"
                )

            expected_nulls = expected_series.isna()
            actual_nulls = actual_series.isna()

            if not expected_nulls.equals(actual_nulls):
                raise TelemetryStorageError(
                    "telemetry Parquet readback changed "
                    f"the null values of {column}"
                )

            expected_values = expected_series[
                ~expected_nulls
            ].reset_index(drop=True)
            actual_values = actual_series[
                ~actual_nulls
            ].reset_index(drop=True)

            try:
                pd.testing.assert_series_equal(
                    expected_values,
                    actual_values,
                    check_names=False,
                    check_dtype=True,
                    check_exact=True,
                )
            except AssertionError as error:
                raise TelemetryStorageError(
                    "telemetry Parquet readback changed "
                    f"the values of {column}"
                ) from error

    def _verified_manifest(
        self,
        request: TelemetryRequest,
        directory: Path,
    ) -> dict[str, object] | None:
        """Return the manifest when the partition is valid."""
        manifest_path = directory / MANIFEST_FILENAME
        telemetry_path = directory / TELEMETRY_FILENAME
        metadata_path = directory / METADATA_FILENAME

        required_paths = (
            manifest_path,
            telemetry_path,
            metadata_path,
        )

        if any(
            not path.is_file()
            for path in required_paths
        ):
            return None

        try:
            manifest = read_json_document(
                manifest_path
            )
            metadata = read_json_document(
                metadata_path
            )
        except (OSError, TypeError, ValueError):
            return None

        if (
            manifest.get("contract_version")
            != TELEMETRY_CONTRACT_VERSION
        ):
            return None

        if (
            manifest.get("telemetry_id")
            != request.identifier
        ):
            return None

        if (
            metadata.get("telemetry_id")
            != request.identifier
        ):
            return None

        files = manifest.get("files")

        if not isinstance(files, dict):
            return None

        file_paths = {
            TELEMETRY_FILENAME: telemetry_path,
            METADATA_FILENAME: metadata_path,
        }

        for filename, path in file_paths.items():
            record = files.get(filename)

            if not isinstance(record, dict):
                return None

            expected_size = record.get("size_bytes")
            expected_checksum = record.get("sha256")

            if (
                isinstance(expected_size, bool)
                or not isinstance(expected_size, int)
            ):
                return None

            if not isinstance(expected_checksum, str):
                return None

            if path.stat().st_size != expected_size:
                return None

            if sha256_file(path) != expected_checksum:
                return None

        return manifest

    def _promote_directory(
        self,
        temporary_directory: Path,
        final_directory: Path,
    ) -> None:
        """Atomically promote a temporary telemetry partition."""
        final_directory.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        backup_directory: Path | None = None

        if final_directory.exists():
            backup_directory = (
                self.paths.temporary_root
                / (
                    f"{final_directory.name}-backup-"
                    f"{uuid4().hex}"
                )
            )

            final_directory.rename(
                backup_directory
            )

        try:
            temporary_directory.rename(
                final_directory
            )
        except OSError:
            if (
                backup_directory is not None
                and backup_directory.exists()
                and not final_directory.exists()
            ):
                backup_directory.rename(
                    final_directory
                )

            raise

        if (
            backup_directory is not None
            and backup_directory.exists()
        ):
            shutil.rmtree(
                backup_directory,
                ignore_errors=True,
            )