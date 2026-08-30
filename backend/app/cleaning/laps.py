"""Normalize and classify raw Formula 1 lap records."""

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

import pandas as pd

DRY_COMPOUNDS = frozenset(
    {
        "HARD",
        "MEDIUM",
        "SOFT",
    }
)

WET_COMPOUNDS = frozenset(
    {
        "INTERMEDIATE",
        "WET",
    }
)

KNOWN_TRACK_STATUS_CHARACTERS = frozenset(
    {
        "1",
        "2",
        "4",
        "5",
        "6",
        "7",
    }
)

LAP_IDENTITY_COLUMNS = (
    "Season",
    "RoundNumber",
    "SessionType",
    "Driver",
    "LapNumber",
)

REQUIRED_IDENTITY_COLUMNS = (
    "Season",
    "RoundNumber",
    "SessionType",
    "EventName",
    "Driver",
    "Team",
    "LapNumber",
)

STRING_IDENTITY_COLUMNS = frozenset(
    {
        "SessionType",
        "EventName",
        "Driver",
        "Team",
    }
)

SECTOR_TIME_COLUMNS = (
    "Sector1Time",
    "Sector2Time",
    "Sector3Time",
)

DURATION_COLUMNS = (
    "LapTime",
    *SECTOR_TIME_COLUMNS,
)

REQUIRED_LAP_COLUMNS = (
    *REQUIRED_IDENTITY_COLUMNS,
    "LapTime",
    "Stint",
    "Compound",
    "TyreLife",
    "PitInTime",
    "PitOutTime",
    *SECTOR_TIME_COLUMNS,
    "TrackStatus",
    "IsAccurate",
    "IsPersonalBest",
)


class LapCleaningError(RuntimeError):
    """Indicate that lap records cannot be classified safely."""


class LapQualityReason(StrEnum):
    """Describe one detected lap-quality condition."""

    MISSING_IDENTITY = "MISSING_IDENTITY"
    DUPLICATE_LAP = "DUPLICATE_LAP"
    MISSING_LAP_TIME = "MISSING_LAP_TIME"
    NON_POSITIVE_LAP_TIME = "NON_POSITIVE_LAP_TIME"
    INACCURATE_LAP = "INACCURATE_LAP"
    FIRST_LAP = "FIRST_LAP"
    PIT_IN_LAP = "PIT_IN_LAP"
    PIT_OUT_LAP = "PIT_OUT_LAP"
    NON_GREEN_TRACK = "NON_GREEN_TRACK"
    WET_CONDITION = "WET_CONDITION"
    MISSING_COMPOUND = "MISSING_COMPOUND"
    UNSUPPORTED_COMPOUND = "UNSUPPORTED_COMPOUND"
    INVALID_TYRE_LIFE = "INVALID_TYRE_LIFE"
    MISSING_SECTOR_TIME = "MISSING_SECTOR_TIME"
    UNKNOWN_TRACK_STATUS = "UNKNOWN_TRACK_STATUS"


EXCLUDING_REASONS = frozenset(
    reason
    for reason in LapQualityReason
    if reason is not LapQualityReason.MISSING_SECTOR_TIME
)


@dataclass(frozen=True, slots=True)
class LapClassificationResult:
    """Store classified laps and their aggregated quality counts."""

    laps: pd.DataFrame
    input_count: int
    eligible_count: int
    flagged_count: int
    excluded_count: int
    quality_counts: dict[str, int]


def classify_laps(
    laps: pd.DataFrame,
) -> LapClassificationResult:
    """Normalize and classify a raw lap table without mutating it."""
    _require_columns(laps)

    classified = laps.copy(deep=True)
    classified.insert(
        0,
        "SourceRowNumber",
        range(len(classified)),
    )

    _normalize_columns(classified)
    _add_duration_seconds(classified)

    classified = (
        classified.sort_values(
            [
                "Season",
                "RoundNumber",
                "SessionType",
                "Driver",
                "LapNumber",
                "SourceRowNumber",
            ],
            kind="stable",
            na_position="last",
        )
        .reset_index(drop=True)
    )

    quality_flags: list[list[str]] = [
        [] for _ in range(len(classified))
    ]
    exclusion_reasons: list[list[str]] = [
        [] for _ in range(len(classified))
    ]
    quality_counts: Counter[str] = Counter()

    missing_identity = _missing_identity_mask(classified)
    duplicate_lap = classified.duplicated(
        subset=LAP_IDENTITY_COLUMNS,
        keep=False,
    )
    missing_lap_time = classified["LapTime"].isna()
    non_positive_lap_time = (
        classified["LapTime"].notna()
        & classified["LapTime"].le(
            pd.to_timedelta(0, unit="s")
        )
    )
    inaccurate_lap = ~classified["IsAccurate"].fillna(False)
    first_lap = classified["LapNumber"].eq(1)
    pit_in_lap = classified["PitInTime"].notna()
    pit_out_lap = classified["PitOutTime"].notna()

    track_status = classified["TrackStatus"]
    known_track_status = track_status.map(
        _is_known_track_status
    )
    unknown_track_status = (
        track_status.isna()
        | track_status.eq("")
        | ~known_track_status
    )
    non_green_track = ~track_status.eq("1").fillna(False)

    compound = classified["Compound"]
    missing_compound = compound.isna() | compound.eq("")
    wet_condition = compound.isin(WET_COMPOUNDS)
    supported_compounds = DRY_COMPOUNDS | WET_COMPOUNDS
    unsupported_compound = (
        ~missing_compound
        & ~compound.isin(supported_compounds)
    )

    invalid_tyre_life = (
        classified["TyreLife"].isna()
        | classified["TyreLife"].le(0)
    )
    missing_sector_time = (
        classified.loc[:, [*SECTOR_TIME_COLUMNS]]
        .isna()
        .any(axis=1)
    )

    reason_masks = (
        (
            LapQualityReason.MISSING_IDENTITY,
            missing_identity,
        ),
        (
            LapQualityReason.DUPLICATE_LAP,
            duplicate_lap,
        ),
        (
            LapQualityReason.MISSING_LAP_TIME,
            missing_lap_time,
        ),
        (
            LapQualityReason.NON_POSITIVE_LAP_TIME,
            non_positive_lap_time,
        ),
        (
            LapQualityReason.INACCURATE_LAP,
            inaccurate_lap,
        ),
        (
            LapQualityReason.FIRST_LAP,
            first_lap,
        ),
        (
            LapQualityReason.PIT_IN_LAP,
            pit_in_lap,
        ),
        (
            LapQualityReason.PIT_OUT_LAP,
            pit_out_lap,
        ),
        (
            LapQualityReason.NON_GREEN_TRACK,
            non_green_track,
        ),
        (
            LapQualityReason.WET_CONDITION,
            wet_condition,
        ),
        (
            LapQualityReason.MISSING_COMPOUND,
            missing_compound,
        ),
        (
            LapQualityReason.UNSUPPORTED_COMPOUND,
            unsupported_compound,
        ),
        (
            LapQualityReason.INVALID_TYRE_LIFE,
            invalid_tyre_life,
        ),
        (
            LapQualityReason.MISSING_SECTOR_TIME,
            missing_sector_time,
        ),
        (
            LapQualityReason.UNKNOWN_TRACK_STATUS,
            unknown_track_status,
        ),
    )

    for reason, mask in reason_masks:
        _apply_reason(
            reason,
            mask,
            quality_flags=quality_flags,
            exclusion_reasons=exclusion_reasons,
            quality_counts=quality_counts,
        )

    classified["QualityFlags"] = [
        "|".join(flags)
        for flags in quality_flags
    ]
    classified["ExclusionReasons"] = [
        "|".join(reasons)
        for reasons in exclusion_reasons
    ]
    classified["QualityFlagCount"] = [
        len(flags)
        for flags in quality_flags
    ]
    classified["ExclusionReasonCount"] = [
        len(reasons)
        for reasons in exclusion_reasons
    ]
    classified["IsEligible"] = [
        not reasons
        for reasons in exclusion_reasons
    ]

    input_count = len(classified)
    eligible_count = int(classified["IsEligible"].sum())
    flagged_count = int(
        classified["QualityFlags"].ne("").sum()
    )
    excluded_count = input_count - eligible_count

    return LapClassificationResult(
        laps=classified,
        input_count=input_count,
        eligible_count=eligible_count,
        flagged_count=flagged_count,
        excluded_count=excluded_count,
        quality_counts={
            reason.value: quality_counts[reason.value]
            for reason in LapQualityReason
        },
    )


def _require_columns(laps: pd.DataFrame) -> None:
    """Confirm that all classification columns are available."""
    missing_columns = sorted(
        set(REQUIRED_LAP_COLUMNS).difference(laps.columns)
    )

    if missing_columns:
        missing_text = ", ".join(missing_columns)
        raise LapCleaningError(
            "lap table is missing required columns: "
            f"{missing_text}"
        )


def _normalize_columns(laps: pd.DataFrame) -> None:
    """Normalize string and boolean lap columns."""
    laps["SessionType"] = _uppercase_strings(
        laps["SessionType"]
    )
    laps["Driver"] = _uppercase_strings(laps["Driver"])
    laps["Compound"] = _uppercase_strings(
        laps["Compound"]
    )
    laps["TrackStatus"] = _plain_strings(
        laps["TrackStatus"]
    )
    laps["EventName"] = _plain_strings(
        laps["EventName"]
    )
    laps["Team"] = _plain_strings(laps["Team"])

    laps["IsAccurate"] = _nullable_boolean(
        laps["IsAccurate"],
        column_name="IsAccurate",
    )
    laps["IsPersonalBest"] = _nullable_boolean(
        laps["IsPersonalBest"],
        column_name="IsPersonalBest",
    )


def _add_duration_seconds(laps: pd.DataFrame) -> None:
    """Add numerical second values for lap and sector durations."""
    for column in DURATION_COLUMNS:
        if getattr(laps[column].dtype, "kind", None) != "m":
            raise LapCleaningError(
                f"{column} must use a timedelta dtype"
            )

        laps[f"{column}Seconds"] = (
            laps[column].dt.total_seconds()
        )


def _missing_identity_mask(
    laps: pd.DataFrame,
) -> pd.Series:
    """Identify rows without a complete lap identity."""
    missing = pd.Series(
        False,
        index=laps.index,
        dtype="boolean",
    )

    for column in REQUIRED_IDENTITY_COLUMNS:
        column_missing = laps[column].isna()

        if column in STRING_IDENTITY_COLUMNS:
            column_missing = (
                column_missing
                | laps[column].eq("")
            )

        missing |= column_missing

    return missing


def _is_known_track_status(value: object) -> bool:
    """Return whether a track-status value uses known codes."""
    if not isinstance(value, str) or not value:
        return False

    return set(value).issubset(
        KNOWN_TRACK_STATUS_CHARACTERS
    )


def _apply_reason(
    reason: LapQualityReason,
    mask: pd.Series,
    *,
    quality_flags: list[list[str]],
    exclusion_reasons: list[list[str]],
    quality_counts: Counter[str],
) -> None:
    """Apply one quality reason to every matching row."""
    normalized_mask = (
        mask.astype("boolean")
        .fillna(False)
        .tolist()
    )
    reason_code = reason.value
    match_count = 0

    for position, matches in enumerate(normalized_mask):
        if not matches:
            continue

        quality_flags[position].append(reason_code)
        match_count += 1

        if reason in EXCLUDING_REASONS:
            exclusion_reasons[position].append(
                reason_code
            )

    quality_counts[reason_code] += match_count


def _plain_strings(values: pd.Series) -> pd.Series:
    """Normalize nullable strings and surrounding whitespace."""
    return values.astype("string").str.strip()


def _uppercase_strings(values: pd.Series) -> pd.Series:
    """Normalize nullable strings to uppercase."""
    return _plain_strings(values).str.upper()


def _nullable_boolean(
    values: pd.Series,
    *,
    column_name: str,
) -> pd.Series:
    """Normalize a column to Pandas nullable booleans."""
    try:
        return values.astype("boolean")
    except (TypeError, ValueError) as error:
        raise LapCleaningError(
            f"{column_name} contains invalid boolean values"
        ) from error