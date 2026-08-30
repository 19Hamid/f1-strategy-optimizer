"""Combine lap classification with leakage-safe weather alignment."""

from collections import Counter
from dataclasses import dataclass

import pandas as pd

from app.cleaning.laps import (
    LapClassificationResult,
    LapQualityReason,
    classify_laps,
)
from app.cleaning.weather import align_weather_to_laps

REASON_ORDER = {
    reason.value: position
    for position, reason in enumerate(LapQualityReason)
}


class SessionCleaningError(RuntimeError):
    """Indicate that one race session cannot be cleaned safely."""


@dataclass(frozen=True, slots=True)
class SessionLapCleaningResult:
    """Store fully classified and weather-aligned session laps."""

    laps: pd.DataFrame
    input_lap_count: int
    eligible_lap_count: int
    flagged_lap_count: int
    excluded_lap_count: int
    weather_observation_count: int
    rainy_lap_count: int
    rain_added_reason_count: int
    rain_newly_excluded_count: int
    maximum_weather_age_seconds: float | None
    weather_was_reordered: bool
    quality_counts: dict[str, int]


def clean_session_laps(
    laps: pd.DataFrame,
    weather: pd.DataFrame,
) -> SessionLapCleaningResult:
    """Align weather and classify one race session's laps."""
    weather_result = align_weather_to_laps(
        laps,
        weather,
    )

    if weather_result.unmatched_lap_count:
        raise SessionCleaningError(
            "every lap must have an earlier weather observation"
        )

    if weather_result.laps["Rainfall"].isna().any():
        raise SessionCleaningError(
            "matched rainfall values must not be missing"
        )

    classification = classify_laps(
        weather_result.laps
    )
    classified_laps = classification.laps.copy(
        deep=True
    )

    rain_mask = (
        classified_laps["Rainfall"]
        .astype("boolean")
        .fillna(False)
    )
    existing_wet_reason = classified_laps[
        "QualityFlags"
    ].map(
        lambda value: _contains_reason(
            value,
            LapQualityReason.WET_CONDITION,
        )
    )
    rain_added_reason = (
        rain_mask
        & ~existing_wet_reason
    )
    rain_newly_excluded = (
        rain_mask
        & classified_laps["IsEligible"]
    )

    _apply_rainfall_reason(
        classified_laps,
        rain_added_reason,
    )

    classified_laps["QualityFlagCount"] = (
        classified_laps["QualityFlags"].map(
            _reason_count
        )
    )
    classified_laps["ExclusionReasonCount"] = (
        classified_laps["ExclusionReasons"].map(
            _reason_count
        )
    )
    classified_laps["IsEligible"] = classified_laps[
        "ExclusionReasons"
    ].eq("")

    combined_classification = _build_classification(
        classified_laps
    )

    return SessionLapCleaningResult(
        laps=combined_classification.laps,
        input_lap_count=combined_classification.input_count,
        eligible_lap_count=(
            combined_classification.eligible_count
        ),
        flagged_lap_count=(
            combined_classification.flagged_count
        ),
        excluded_lap_count=(
            combined_classification.excluded_count
        ),
        weather_observation_count=(
            weather_result.weather_observation_count
        ),
        rainy_lap_count=weather_result.rainy_lap_count,
        rain_added_reason_count=int(
            rain_added_reason.sum()
        ),
        rain_newly_excluded_count=int(
            rain_newly_excluded.sum()
        ),
        maximum_weather_age_seconds=(
            weather_result.maximum_weather_age_seconds
        ),
        weather_was_reordered=(
            weather_result.weather_was_reordered
        ),
        quality_counts=(
            combined_classification.quality_counts
        ),
    )


def _apply_rainfall_reason(
    laps: pd.DataFrame,
    mask: pd.Series,
) -> None:
    """Add the wet-condition reason to rain-aligned laps."""
    reason = LapQualityReason.WET_CONDITION

    for row_index in laps.index[
        mask.astype("boolean").fillna(False)
    ]:
        laps.at[row_index, "QualityFlags"] = (
            _add_reason(
                laps.at[row_index, "QualityFlags"],
                reason,
            )
        )
        laps.at[row_index, "ExclusionReasons"] = (
            _add_reason(
                laps.at[
                    row_index,
                    "ExclusionReasons",
                ],
                reason,
            )
        )


def _add_reason(
    existing: str,
    reason: LapQualityReason,
) -> str:
    """Add one reason and return canonical reason ordering."""
    reason_codes = _split_reasons(existing)

    if reason.value not in reason_codes:
        reason_codes.append(reason.value)

    reason_codes.sort(
        key=lambda value: REASON_ORDER[value]
    )

    return "|".join(reason_codes)


def _contains_reason(
    existing: str,
    reason: LapQualityReason,
) -> bool:
    """Return whether a reason string contains one code."""
    return reason.value in _split_reasons(existing)


def _reason_count(existing: str) -> int:
    """Count codes in one serialized reason string."""
    return len(_split_reasons(existing))


def _split_reasons(existing: str) -> list[str]:
    """Split a serialized reason string."""
    if not existing:
        return []

    return existing.split("|")


def _build_classification(
    laps: pd.DataFrame,
) -> LapClassificationResult:
    """Recalculate classification statistics from updated laps."""
    quality_counts: Counter[str] = Counter()

    for value in laps["QualityFlags"]:
        quality_counts.update(
            _split_reasons(value)
        )

    input_count = len(laps)
    eligible_count = int(laps["IsEligible"].sum())
    flagged_count = int(
        laps["QualityFlags"].ne("").sum()
    )
    excluded_count = input_count - eligible_count

    return LapClassificationResult(
        laps=laps,
        input_count=input_count,
        eligible_count=eligible_count,
        flagged_count=flagged_count,
        excluded_count=excluded_count,
        quality_counts={
            reason.value: quality_counts[reason.value]
            for reason in LapQualityReason
        },
    )