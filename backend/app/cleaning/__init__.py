"""Data-cleaning and exploratory-analysis utilities."""

from app.cleaning.laps import (
    LapClassificationResult,
    LapCleaningError,
    LapQualityReason,
    classify_laps,
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
    "DEVELOPMENT_SEASONS",
    "DataProfileError",
    "DevelopmentDataProfile",
    "LapClassificationResult",
    "LapCleaningError",
    "LapQualityReason",
    "SessionCleaningError",
    "SessionLapCleaningResult",
    "StintReconstructionError",
    "StintReconstructionResult",
    "StintWarning",
    "WeatherAlignmentError",
    "WeatherAlignmentResult",
    "align_weather_to_laps",
    "classify_laps",
    "clean_session_laps",
    "profile_development_data",
    "reconstruct_stints",
]