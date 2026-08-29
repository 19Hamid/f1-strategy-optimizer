"""Historical Formula 1 data-pipeline components."""

from app.pipeline.batch import (
    BatchRunResult,
    BatchSessionRecord,
    RawBatchRunner,
)
from app.pipeline.catalog import (
    CATALOG_COLUMNS,
    CatalogBuildError,
    CatalogBuildResult,
    RawCatalogBuilder,
)
from app.pipeline.config import (
    CORE_STUDY_SEASONS,
    DEVELOPMENT_SEASONS,
    EVALUATION_SEASONS,
    ExtractionPlan,
)
from app.pipeline.integrity import (
    IntegrityIssue,
    IntegrityReport,
    SessionIntegrityError,
    verify_session_partition,
)
from app.pipeline.models import SessionKey
from app.pipeline.paths import RawDataPaths, SessionPaths
from app.pipeline.runner import (
    RawPipelineRunner,
    SessionRunResult,
)
from app.pipeline.schedule import (
    discover_session_keys,
    extract_round_numbers,
)
from app.pipeline.serialization import (
    read_json_document,
    read_parquet_table,
    sha256_file,
    write_json_document,
    write_parquet_table,
)
from app.pipeline.source import FastF1Source, RawSessionData
from app.pipeline.storage import (
    IncompleteSessionDirectoryError,
    ParquetReadbackError,
    RawSessionWriter,
    SessionWriteResult,
)
from app.pipeline.telemetry import (
    TelemetryDataPaths,
    TelemetryRequest,
)
from app.pipeline.telemetry_runner import (
    TelemetryPipelineRunner,
    TelemetrySource,
)
from app.pipeline.telemetry_source import (
    TELEMETRY_PROVENANCE_COLUMNS,
    TELEMETRY_REQUIRED_COLUMNS,
    FastF1TelemetrySource,
    TelemetryExtractionError,
    TelemetryLapData,
)
from app.pipeline.telemetry_storage import (
    TELEMETRY_CONTRACT_VERSION,
    TelemetryStorageError,
    TelemetryWriter,
    TelemetryWriteResult,
    TelemetryWriteStatus,
)
from app.pipeline.validation import (
    RawDataValidationError,
    ValidationReport,
    validate_raw_session,
)

__all__ = [
    "CATALOG_COLUMNS",
    "CORE_STUDY_SEASONS",
    "DEVELOPMENT_SEASONS",
    "EVALUATION_SEASONS",
    "TELEMETRY_CONTRACT_VERSION",
    "TELEMETRY_PROVENANCE_COLUMNS",
    "TELEMETRY_REQUIRED_COLUMNS",
    "BatchRunResult",
    "BatchSessionRecord",
    "CatalogBuildError",
    "CatalogBuildResult",
    "ExtractionPlan",
    "FastF1Source",
    "FastF1TelemetrySource",
    "IncompleteSessionDirectoryError",
    "IntegrityIssue",
    "IntegrityReport",
    "ParquetReadbackError",
    "RawBatchRunner",
    "RawCatalogBuilder",
    "RawDataPaths",
    "RawDataValidationError",
    "RawPipelineRunner",
    "RawSessionData",
    "RawSessionWriter",
    "SessionIntegrityError",
    "SessionKey",
    "SessionPaths",
    "SessionRunResult",
    "SessionWriteResult",
    "TelemetryDataPaths",
    "TelemetryExtractionError",
    "TelemetryLapData",
    "TelemetryPipelineRunner",
    "TelemetryRequest",
    "TelemetrySource",
    "TelemetryStorageError",
    "TelemetryWriteResult",
    "TelemetryWriteStatus",
    "TelemetryWriter",
    "ValidationReport",
    "discover_session_keys",
    "extract_round_numbers",
    "read_json_document",
    "read_parquet_table",
    "sha256_file",
    "validate_raw_session",
    "verify_session_partition",
    "write_json_document",
    "write_parquet_table",
]