"""Historical Formula 1 data-pipeline components."""

from app.pipeline.config import (
    CORE_STUDY_SEASONS,
    DEVELOPMENT_SEASONS,
    EVALUATION_SEASONS,
    ExtractionPlan,
)
from app.pipeline.models import SessionKey
from app.pipeline.paths import RawDataPaths, SessionPaths
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
from app.pipeline.validation import (
    RawDataValidationError,
    ValidationReport,
    validate_raw_session,
)

__all__ = [
    "CORE_STUDY_SEASONS",
    "DEVELOPMENT_SEASONS",
    "EVALUATION_SEASONS",
    "ExtractionPlan",
    "FastF1Source",
    "IncompleteSessionDirectoryError",
    "ParquetReadbackError",
    "RawDataPaths",
    "RawDataValidationError",
    "RawSessionData",
    "RawSessionWriter",
    "SessionKey",
    "SessionPaths",
    "SessionWriteResult",
    "ValidationReport",
    "discover_session_keys",
    "extract_round_numbers",
    "read_json_document",
    "read_parquet_table",
    "sha256_file",
    "validate_raw_session",
    "write_json_document",
    "write_parquet_table",
]