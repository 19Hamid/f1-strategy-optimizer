"""PostgreSQL persistence for verified F1 data."""

from app.db.artifacts import (
    DatabaseArtifactError,
    PreparedSessionArtifacts,
    prepare_session_artifacts,
)
from app.db.base import (
    DATABASE_SCHEMA_NAME,
    DATABASE_SCHEMA_VERSION,
    NAMING_CONVENTION,
    Base,
)
from app.db.decision_labels import (
    DECISION_LABEL_SOURCE_COLUMN_MAP,
    DECISION_LABEL_TABLE_NAME,
    DecisionLabel,
)
from app.db.decision_rows import (
    DECISION_ROW_SOURCE_COLUMN_MAP,
    DECISION_ROW_TABLE_NAME,
    DecisionRow,
)
from app.db.loading import (
    DatabaseLoadError,
    SessionDatabaseLoader,
    SessionLoadResult,
)
from app.db.pit_duration_observations import (
    PIT_DURATION_OBSERVATION_SOURCE_COLUMN_MAP,
    PIT_DURATION_OBSERVATION_TABLE_NAME,
    PitDurationObservation,
)
from app.db.processed_laps import (
    PROCESSED_LAP_SOURCE_COLUMN_MAP,
    PROCESSED_LAP_TABLE_NAME,
    ProcessedLap,
)
from app.db.provenance import (
    PROVENANCE_TABLE_NAMES,
    DatasetBuild,
    DatasetSession,
    DatasetVersion,
    ProcessedSessionPartition,
)
from app.db.quality_reasons import (
    QUALITY_REASON_CODES_BY_SCOPE,
    QUALITY_REASON_EXCLUSION_CODES_BY_SCOPE,
    QUALITY_REASON_LINK_TABLE_NAMES,
    QUALITY_REASON_SCOPES,
    QUALITY_REASON_TABLE_NAME,
    DecisionQualityReason,
    LapTargetQualityReason,
    PitDurationQualityReason,
    PitEventQualityReason,
    ProcessedLapQualityReason,
    QualityReason,
    StintQualityReason,
)
from app.db.reconstructed_pit_events import (
    RECONSTRUCTED_PIT_EVENT_SOURCE_COLUMN_MAP,
    RECONSTRUCTED_PIT_EVENT_TABLE_NAME,
    ReconstructedPitEvent,
)
from app.db.reconstructed_stints import (
    RECONSTRUCTED_STINT_SOURCE_COLUMN_MAP,
    RECONSTRUCTED_STINT_TABLE_NAME,
    ReconstructedStint,
)
from app.db.records import (
    DatabaseRecordError,
    iter_dataframe_records,
    iter_quality_reason_link_records,
    quality_reason_definition_records,
)
from app.db.reference import (
    REFERENCE_TABLE_NAMES,
    Circuit,
    Driver,
    Event,
    RaceSession,
    Season,
    SessionParticipant,
    Team,
)
from app.db.repositories import (
    ImmutableRepository,
    ImmutableRowConflictError,
    RepositoryConflictError,
    RepositoryError,
    RepositoryWriteResult,
    insert_rows,
)
from app.db.runtime import (
    DATABASE_URL_ENVIRONMENT_VARIABLE,
    SUPPORTED_DATABASE_DRIVER,
    DatabaseConfigurationError,
    DatabaseSettings,
    create_database_engine,
    create_database_session_factory,
    database_transaction,
)
from app.db.temporal_splits import (
    SESSION_SPLIT_ASSIGNMENT_SOURCE_COLUMN_MAP,
    SESSION_SPLIT_ASSIGNMENT_TABLE_NAME,
    TEMPORAL_FOLD_TABLE_NAME,
    SessionSplitAssignment,
    TemporalFold,
)

__all__ = [
    "DATABASE_SCHEMA_NAME",
    "DATABASE_SCHEMA_VERSION",
    "DATABASE_URL_ENVIRONMENT_VARIABLE",
    "DECISION_LABEL_SOURCE_COLUMN_MAP",
    "DECISION_LABEL_TABLE_NAME",
    "DECISION_ROW_SOURCE_COLUMN_MAP",
    "DECISION_ROW_TABLE_NAME",
    "NAMING_CONVENTION",
    "PIT_DURATION_OBSERVATION_SOURCE_COLUMN_MAP",
    "PIT_DURATION_OBSERVATION_TABLE_NAME",
    "PROCESSED_LAP_SOURCE_COLUMN_MAP",
    "PROCESSED_LAP_TABLE_NAME",
    "PROVENANCE_TABLE_NAMES",
    "QUALITY_REASON_CODES_BY_SCOPE",
    "QUALITY_REASON_EXCLUSION_CODES_BY_SCOPE",
    "QUALITY_REASON_LINK_TABLE_NAMES",
    "QUALITY_REASON_SCOPES",
    "QUALITY_REASON_TABLE_NAME",
    "RECONSTRUCTED_PIT_EVENT_SOURCE_COLUMN_MAP",
    "RECONSTRUCTED_PIT_EVENT_TABLE_NAME",
    "RECONSTRUCTED_STINT_SOURCE_COLUMN_MAP",
    "RECONSTRUCTED_STINT_TABLE_NAME",
    "REFERENCE_TABLE_NAMES",
    "SESSION_SPLIT_ASSIGNMENT_SOURCE_COLUMN_MAP",
    "SESSION_SPLIT_ASSIGNMENT_TABLE_NAME",
    "SUPPORTED_DATABASE_DRIVER",
    "TEMPORAL_FOLD_TABLE_NAME",
    "Base",
    "Circuit",
    "DatabaseArtifactError",
    "DatabaseConfigurationError",
    "DatabaseLoadError",
    "DatabaseRecordError",
    "DatabaseSettings",
    "DatasetBuild",
    "DatasetSession",
    "DatasetVersion",
    "DecisionLabel",
    "DecisionQualityReason",
    "DecisionRow",
    "Driver",
    "Event",
    "ImmutableRepository",
    "ImmutableRowConflictError",
    "LapTargetQualityReason",
    "PitDurationObservation",
    "PitDurationQualityReason",
    "PitEventQualityReason",
    "PreparedSessionArtifacts",
    "ProcessedLap",
    "ProcessedLapQualityReason",
    "ProcessedSessionPartition",
    "QualityReason",
    "RaceSession",
    "ReconstructedPitEvent",
    "ReconstructedStint",
    "RepositoryConflictError",
    "RepositoryError",
    "RepositoryWriteResult",
    "Season",
    "SessionDatabaseLoader",
    "SessionLoadResult",
    "SessionParticipant",
    "SessionSplitAssignment",
    "StintQualityReason",
    "Team",
    "TemporalFold",
    "create_database_engine",
    "create_database_session_factory",
    "database_transaction",
    "insert_rows",
    "iter_dataframe_records",
    "iter_quality_reason_link_records",
    "prepare_session_artifacts",
    "quality_reason_definition_records",
]
