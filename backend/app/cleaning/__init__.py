"""Data-cleaning and exploratory-analysis utilities."""

from app.cleaning.laps import (
    LapClassificationResult,
    LapCleaningError,
    LapQualityReason,
    classify_laps,
)
from app.cleaning.pits import (
    PitEventReconstructionError,
    PitEventReconstructionResult,
    PitEventType,
    PitEventWarning,
    reconstruct_pit_events,
)
from app.cleaning.processing import (
    CLEANING_RULE_VERSION,
    PROCESSED_CONTRACT_VERSION,
    ProcessedSessionData,
    SessionProcessingError,
    process_session_tables,
)
from app.cleaning.profile import (
    DEVELOPMENT_SEASONS,
    DataProfileError,
    DevelopmentDataProfile,
    profile_development_data,
)
from app.cleaning.session import (
    SessionCleaningError,
    SessionLapCleaningResult,
    clean_session_laps,
)
from app.cleaning.stints import (
    StintReconstructionError,
    StintReconstructionResult,
    StintWarning,
    reconstruct_stints,
)
from app.cleaning.weather import (
    WeatherAlignmentError,
    WeatherAlignmentResult,
    align_weather_to_laps,
)

__all__ = [
    "CLEANING_RULE_VERSION",
    "DEVELOPMENT_SEASONS",
    "PROCESSED_CONTRACT_VERSION",
    "DataProfileError",
    "DevelopmentDataProfile",
    "LapClassificationResult",
    "LapCleaningError",
    "LapQualityReason",
    "PitEventReconstructionError",
    "PitEventReconstructionResult",
    "PitEventType",
    "PitEventWarning",
    "ProcessedSessionData",
    "SessionCleaningError",
    "SessionLapCleaningResult",
    "SessionProcessingError",
    "StintReconstructionError",
    "StintReconstructionResult",
    "StintWarning",
    "WeatherAlignmentError",
    "WeatherAlignmentResult",
    "align_weather_to_laps",
    "classify_laps",
    "clean_session_laps",
    "process_session_tables",
    "profile_development_data",
    "reconstruct_pit_events",
    "reconstruct_stints",
]