"""Reconstruct pit events from raw Formula 1 lap markers."""

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import pandas as pd
from pandas.api.types import (
    is_bool_dtype,
    is_numeric_dtype,
)

SESSION_IDENTITY_COLUMNS: Final = (
    "Season",
    "RoundNumber",
    "SessionType",
    "EventName",
)

DRIVER_IDENTITY_COLUMNS: Final = (
    *SESSION_IDENTITY_COLUMNS,
    "Driver",
)

REQUIRED_PIT_COLUMNS: Final = frozenset(
    {
        *DRIVER_IDENTITY_COLUMNS,
        "Team",
        "LapNumber",
        "Stint",
        "Compound",
        "TyreLife",
        "PitInTime",
        "PitOutTime",
        "TrackStatus",
    }
)

SUPPORTED_COMPOUNDS: Final = frozenset(
    {
        "SOFT",
        "MEDIUM",
        "HARD",
        "INTERMEDIATE",
        "WET",
    }
)

DRY_COMPOUNDS: Final = frozenset(
    {
        "SOFT",
        "MEDIUM",
        "HARD",
    }
)

INTERRUPTED_DURATION_SECONDS: Final = 120.0

PIT_EVENT_COLUMNS: Final = (
    "pit_event_id",
    "season",
    "round_number",
    "session_type",
    "event_name",
    "driver",
    "team",
    "event_type",
    "pit_in_lap",
    "pit_out_lap",
    "stint_before",
    "stint_after",
    "compound_before",
    "compound_after",
    "tyre_life_before",
    "tyre_life_after",
    "pit_in_time_seconds",
    "pit_out_time_seconds",
    "observed_pit_lane_duration_seconds",
    "entry_track_status",
    "exit_track_status",
    "is_stint_change",
    "is_compound_change",
    "is_green_flag_pair",
    "is_dry_compound_pair",
    "is_interrupted_duration",
    "is_complete",
    "is_duration_analysis_candidate",
    "warning_count",
    "warnings",
)


class PitEventType(StrEnum):
    """Describe which pit markers are available."""

    MATCHED = "MATCHED"
    ENTRY_ONLY = "ENTRY_ONLY"
    EXIT_ONLY = "EXIT_ONLY"


class PitEventWarning(StrEnum):
    """Describe a pit-event reconstruction concern."""

    TEAM_CONFLICT = "TEAM_CONFLICT"
    ENTRY_ONLY = "ENTRY_ONLY"
    EXIT_ONLY = "EXIT_ONLY"
    NON_ADJACENT_LAPS = "NON_ADJACENT_LAPS"
    NON_POSITIVE_DURATION = "NON_POSITIVE_DURATION"
    NO_STINT_CHANGE = "NO_STINT_CHANGE"
    MISSING_COMPOUND_BEFORE = "MISSING_COMPOUND_BEFORE"
    MISSING_COMPOUND_AFTER = "MISSING_COMPOUND_AFTER"
    UNSUPPORTED_COMPOUND_BEFORE = (
        "UNSUPPORTED_COMPOUND_BEFORE"
    )
    UNSUPPORTED_COMPOUND_AFTER = (
        "UNSUPPORTED_COMPOUND_AFTER"
    )
    NON_GREEN_ENTRY = "NON_GREEN_ENTRY"
    NON_GREEN_EXIT = "NON_GREEN_EXIT"
    INTERRUPTED_DURATION = "INTERRUPTED_DURATION"


WARNING_ORDER: Final = {
    warning: position
    for position, warning in enumerate(PitEventWarning)
}


class PitEventReconstructionError(ValueError):
    """Raised when lap data cannot support pit reconstruction."""


@dataclass(frozen=True, slots=True)
class PitEventReconstructionResult:
    """Contain reconstructed pit events and quality counts."""

    pit_events: pd.DataFrame
    input_lap_count: int
    driver_count: int
    pit_event_count: int
    matched_event_count: int
    entry_only_event_count: int
    exit_only_event_count: int
    complete_event_count: int
    incomplete_event_count: int
    duration_analysis_candidate_count: int
    warning_counts: dict[str, int]


def reconstruct_pit_events(
    laps: pd.DataFrame,
) -> PitEventReconstructionResult:
    """Pair pit-entry and pit-exit markers deterministically."""
    _require_columns(laps)
    _validate_input(laps)

    if laps.empty:
        return _empty_result()

    ordered_laps = laps.sort_values(
        [
            *DRIVER_IDENTITY_COLUMNS,
            "LapNumber",
        ],
        kind="stable",
    ).reset_index(drop=True)

    records: list[dict[str, object]] = []
    driver_count = 0

    for driver_key, driver_laps in ordered_laps.groupby(
        list(DRIVER_IDENTITY_COLUMNS),
        sort=True,
        dropna=False,
    ):
        driver_count += 1
        records.extend(
            _reconstruct_driver_events(
                driver_key,
                driver_laps.reset_index(drop=True),
            )
        )

    pit_events = pd.DataFrame.from_records(
        records,
        columns=PIT_EVENT_COLUMNS,
    )

    sort_lap = pd.Series(
        [
            (
                pit_in_lap
                if pd.notna(pit_in_lap)
                else pit_out_lap
            )
            for pit_in_lap, pit_out_lap in zip(
                pit_events["pit_in_lap"],
                pit_events["pit_out_lap"],
                strict=True,
            )
        ],
        index=pit_events.index,
        dtype="float64",
    )

    pit_events = (
        pit_events.assign(
            _sort_lap=sort_lap
        )
        .sort_values(
            [
                "season",
                "round_number",
                "session_type",
                "driver",
                "_sort_lap",
                "event_type",
            ],
            kind="stable",
        )
        .drop(columns="_sort_lap")
        .reset_index(drop=True)
    )

    event_type_counts = pit_events[
        "event_type"
    ].value_counts()

    matched_count = int(
        event_type_counts.get(
            PitEventType.MATCHED.value,
            0,
        )
    )
    entry_only_count = int(
        event_type_counts.get(
            PitEventType.ENTRY_ONLY.value,
            0,
        )
    )
    exit_only_count = int(
        event_type_counts.get(
            PitEventType.EXIT_ONLY.value,
            0,
        )
    )

    complete_count = int(
        pit_events["is_complete"].sum()
    )
    candidate_count = int(
        pit_events[
            "is_duration_analysis_candidate"
        ].sum()
    )

    return PitEventReconstructionResult(
        pit_events=pit_events,
        input_lap_count=len(laps),
        driver_count=driver_count,
        pit_event_count=len(pit_events),
        matched_event_count=matched_count,
        entry_only_event_count=entry_only_count,
        exit_only_event_count=exit_only_count,
        complete_event_count=complete_count,
        incomplete_event_count=(
            len(pit_events) - complete_count
        ),
        duration_analysis_candidate_count=(
            candidate_count
        ),
        warning_counts=_count_warnings(pit_events),
    )


def _reconstruct_driver_events(
    driver_key: tuple[object, ...],
    driver_laps: pd.DataFrame,
) -> list[dict[str, object]]:
    """Reconstruct pit events for one driver-race."""
    records: list[dict[str, object]] = []
    matched_exit_positions = set()

    for position, entry_row in driver_laps.iterrows():
        if pd.isna(entry_row["PitInTime"]):
            continue

        exit_position = position + 1

        if (
            exit_position < len(driver_laps)
            and pd.notna(
                driver_laps.iloc[
                    exit_position
                ]["PitOutTime"]
            )
        ):
            exit_row = driver_laps.iloc[
                exit_position
            ]

            records.append(
                _build_event_record(
                    driver_key=driver_key,
                    entry_row=entry_row,
                    exit_row=exit_row,
                )
            )
            matched_exit_positions.add(
                exit_position
            )
        else:
            records.append(
                _build_event_record(
                    driver_key=driver_key,
                    entry_row=entry_row,
                    exit_row=None,
                )
            )

    for position, exit_row in driver_laps.iterrows():
        if (
            pd.isna(exit_row["PitOutTime"])
            or position in matched_exit_positions
        ):
            continue

        records.append(
            _build_event_record(
                driver_key=driver_key,
                entry_row=None,
                exit_row=exit_row,
            )
        )

    return records


def _build_event_record(
    *,
    driver_key: tuple[object, ...],
    entry_row: pd.Series | None,
    exit_row: pd.Series | None,
) -> dict[str, object]:
    """Build one complete or partial pit-event record."""
    season, round_number, session_type, event_name, driver = (
        driver_key
    )

    event_type = _event_type(
        entry_row,
        exit_row,
    )

    pit_in_lap = _optional_integer_from_row(
        entry_row,
        "LapNumber",
    )
    pit_out_lap = _optional_integer_from_row(
        exit_row,
        "LapNumber",
    )

    stint_before = _optional_integer_from_row(
        entry_row,
        "Stint",
    )
    stint_after = _optional_integer_from_row(
        exit_row,
        "Stint",
    )

    compound_before = _compound_from_row(
        entry_row
    )
    compound_after = _compound_from_row(
        exit_row
    )

    tyre_life_before = _optional_float_from_row(
        entry_row,
        "TyreLife",
    )
    tyre_life_after = _optional_float_from_row(
        exit_row,
        "TyreLife",
    )

    pit_in_time_seconds = _time_seconds_from_row(
        entry_row,
        "PitInTime",
    )
    pit_out_time_seconds = _time_seconds_from_row(
        exit_row,
        "PitOutTime",
    )

    entry_track_status = _text_from_row(
        entry_row,
        "TrackStatus",
    )
    exit_track_status = _text_from_row(
        exit_row,
        "TrackStatus",
    )

    duration_seconds = _duration_seconds(
        entry_row,
        exit_row,
    )

    is_stint_change = _changed_value(
        stint_before,
        stint_after,
    )
    is_compound_change = _changed_value(
        compound_before,
        compound_after,
    )

    is_green_flag_pair = bool(
        entry_track_status == "1"
        and exit_track_status == "1"
    )

    is_dry_compound_pair = bool(
        compound_before in DRY_COMPOUNDS
        and compound_after in DRY_COMPOUNDS
    )

    is_interrupted_duration = bool(
        duration_seconds is not None
        and duration_seconds
        >= INTERRUPTED_DURATION_SECONDS
    )

    teams = _team_values(
        entry_row,
        exit_row,
    )

    warnings = _event_warnings(
        event_type=event_type,
        pit_in_lap=pit_in_lap,
        pit_out_lap=pit_out_lap,
        stint_before=stint_before,
        stint_after=stint_after,
        compound_before=compound_before,
        compound_after=compound_after,
        duration_seconds=duration_seconds,
        entry_track_status=entry_track_status,
        exit_track_status=exit_track_status,
    )

    if len(teams) > 1:
        warnings.append(
            PitEventWarning.TEAM_CONFLICT
        )
        warnings = _ordered_unique_warnings(
            warnings
        )

    is_complete = bool(
        event_type is PitEventType.MATCHED
        and pit_in_lap is not None
        and pit_out_lap is not None
        and pit_out_lap - pit_in_lap == 1
        and duration_seconds is not None
        and duration_seconds > 0
    )

    is_duration_analysis_candidate = bool(
        is_complete
        and is_stint_change is True
        and is_green_flag_pair
        and is_dry_compound_pair
        and not is_interrupted_duration
    )

    team = (
        teams[0]
        if len(teams) == 1
        else "|".join(teams)
    )

    session_id = (
        f"{int(season)}-"
        f"{int(round_number):02d}-"
        f"{str(session_type).strip().upper()}"
    )

    pit_event_id = _pit_event_identifier(
        session_id=session_id,
        driver=str(driver).strip().upper(),
        pit_in_lap=pit_in_lap,
        pit_out_lap=pit_out_lap,
    )

    return {
        "pit_event_id": pit_event_id,
        "season": int(season),
        "round_number": int(round_number),
        "session_type": str(
            session_type
        ).strip().upper(),
        "event_name": str(event_name).strip(),
        "driver": str(driver).strip().upper(),
        "team": team,
        "event_type": event_type.value,
        "pit_in_lap": pit_in_lap,
        "pit_out_lap": pit_out_lap,
        "stint_before": stint_before,
        "stint_after": stint_after,
        "compound_before": compound_before,
        "compound_after": compound_after,
        "tyre_life_before": tyre_life_before,
        "tyre_life_after": tyre_life_after,
        "pit_in_time_seconds": pit_in_time_seconds,
        "pit_out_time_seconds": pit_out_time_seconds,
        "observed_pit_lane_duration_seconds": (
            duration_seconds
        ),
        "entry_track_status": entry_track_status,
        "exit_track_status": exit_track_status,
        "is_stint_change": is_stint_change,
        "is_compound_change": is_compound_change,
        "is_green_flag_pair": is_green_flag_pair,
        "is_dry_compound_pair": (
            is_dry_compound_pair
        ),
        "is_interrupted_duration": (
            is_interrupted_duration
        ),
        "is_complete": is_complete,
        "is_duration_analysis_candidate": (
            is_duration_analysis_candidate
        ),
        "warning_count": len(warnings),
        "warnings": "|".join(
            warning.value
            for warning in warnings
        ),
    }


def _event_warnings(
    *,
    event_type: PitEventType,
    pit_in_lap: int | None,
    pit_out_lap: int | None,
    stint_before: int | None,
    stint_after: int | None,
    compound_before: str | None,
    compound_after: str | None,
    duration_seconds: float | None,
    entry_track_status: str | None,
    exit_track_status: str | None,
) -> list[PitEventWarning]:
    """Build the canonical warning set for one pit event."""
    warnings: list[PitEventWarning] = []

    if event_type is PitEventType.ENTRY_ONLY:
        warnings.append(PitEventWarning.ENTRY_ONLY)

    if event_type is PitEventType.EXIT_ONLY:
        warnings.append(PitEventWarning.EXIT_ONLY)

    if (
        pit_in_lap is not None
        and pit_out_lap is not None
        and pit_out_lap - pit_in_lap != 1
    ):
        warnings.append(
            PitEventWarning.NON_ADJACENT_LAPS
        )

    if (
        duration_seconds is not None
        and duration_seconds <= 0
    ):
        warnings.append(
            PitEventWarning.NON_POSITIVE_DURATION
        )

    if (
        stint_before is not None
        and stint_after is not None
        and stint_before == stint_after
    ):
        warnings.append(
            PitEventWarning.NO_STINT_CHANGE
        )

    _append_compound_warnings(
        warnings,
        compound_before=compound_before,
        compound_after=compound_after,
    )

    if (
        entry_track_status is not None
        and entry_track_status != "1"
    ):
        warnings.append(
            PitEventWarning.NON_GREEN_ENTRY
        )

    if (
        exit_track_status is not None
        and exit_track_status != "1"
    ):
        warnings.append(
            PitEventWarning.NON_GREEN_EXIT
        )

    if (
        duration_seconds is not None
        and duration_seconds
        >= INTERRUPTED_DURATION_SECONDS
    ):
        warnings.append(
            PitEventWarning.INTERRUPTED_DURATION
        )

    return _ordered_unique_warnings(warnings)


def _append_compound_warnings(
    warnings: list[PitEventWarning],
    *,
    compound_before: str | None,
    compound_after: str | None,
) -> None:
    """Append compound warnings without modifying source data."""
    if compound_before is None:
        warnings.append(
            PitEventWarning.MISSING_COMPOUND_BEFORE
        )
    elif compound_before not in SUPPORTED_COMPOUNDS:
        warnings.append(
            PitEventWarning.UNSUPPORTED_COMPOUND_BEFORE
        )

    if compound_after is None:
        warnings.append(
            PitEventWarning.MISSING_COMPOUND_AFTER
        )
    elif compound_after not in SUPPORTED_COMPOUNDS:
        warnings.append(
            PitEventWarning.UNSUPPORTED_COMPOUND_AFTER
        )


def _event_type(
    entry_row: pd.Series | None,
    exit_row: pd.Series | None,
) -> PitEventType:
    """Determine marker completeness."""
    if entry_row is not None and exit_row is not None:
        return PitEventType.MATCHED

    if entry_row is not None:
        return PitEventType.ENTRY_ONLY

    return PitEventType.EXIT_ONLY


def _duration_seconds(
    entry_row: pd.Series | None,
    exit_row: pd.Series | None,
) -> float | None:
    """Calculate observed time between pit markers."""
    if entry_row is None or exit_row is None:
        return None

    pit_in_time = entry_row["PitInTime"]
    pit_out_time = exit_row["PitOutTime"]

    if pd.isna(pit_in_time) or pd.isna(pit_out_time):
        return None

    return float(
        (
            pit_out_time
            - pit_in_time
        ).total_seconds()
    )


def _changed_value(
    before: object | None,
    after: object | None,
) -> bool | None:
    """Compare two values while preserving unknown transitions."""
    if before is None or after is None:
        return None

    return before != after


def _team_values(
    entry_row: pd.Series | None,
    exit_row: pd.Series | None,
) -> list[str]:
    """Collect deterministic non-empty team values."""
    values = set()

    for row in (
        entry_row,
        exit_row,
    ):
        if row is None:
            continue

        value = row["Team"]

        if pd.isna(value):
            continue

        text = str(value).strip()

        if text:
            values.add(text)

    return sorted(values)


def _compound_from_row(
    row: pd.Series | None,
) -> str | None:
    """Read and normalize one compound value."""
    return _text_from_row(
        row,
        "Compound",
        uppercase=True,
    )


def _text_from_row(
    row: pd.Series | None,
    column: str,
    *,
    uppercase: bool = False,
) -> str | None:
    """Read optional normalized text from a row."""
    if row is None:
        return None

    value = row[column]

    if pd.isna(value):
        return None

    text = str(value).strip()

    if not text:
        return None

    if uppercase:
        text = text.upper()

    return text


def _optional_integer_from_row(
    row: pd.Series | None,
    column: str,
) -> int | None:
    """Read an optional integer from a row."""
    if row is None:
        return None

    value = row[column]

    if pd.isna(value):
        return None

    return int(value)


def _optional_float_from_row(
    row: pd.Series | None,
    column: str,
) -> float | None:
    """Read an optional float from a row."""
    if row is None:
        return None

    value = row[column]

    if pd.isna(value):
        return None

    return float(value)


def _time_seconds_from_row(
    row: pd.Series | None,
    column: str,
) -> float | None:
    """Convert an optional timedelta marker to seconds."""
    if row is None:
        return None

    value = row[column]

    if pd.isna(value):
        return None

    return float(value.total_seconds())


def _pit_event_identifier(
    *,
    session_id: str,
    driver: str,
    pit_in_lap: int | None,
    pit_out_lap: int | None,
) -> str:
    """Build a stable unique pit-event identifier."""
    entry_text = (
        f"IN{pit_in_lap:03d}"
        if pit_in_lap is not None
        else "IN---"
    )
    exit_text = (
        f"OUT{pit_out_lap:03d}"
        if pit_out_lap is not None
        else "OUT---"
    )

    return (
        f"{session_id}-"
        f"{driver}-"
        f"{entry_text}-"
        f"{exit_text}"
    )


def _ordered_unique_warnings(
    warnings: list[PitEventWarning],
) -> list[PitEventWarning]:
    """Deduplicate warnings using canonical order."""
    return sorted(
        set(warnings),
        key=WARNING_ORDER.__getitem__,
    )


def _count_warnings(
    pit_events: pd.DataFrame,
) -> dict[str, int]:
    """Count events affected by every warning code."""
    counts = Counter()

    for warning_text in pit_events["warnings"]:
        if not warning_text:
            continue

        counts.update(warning_text.split("|"))

    return {
        warning.value: counts[warning.value]
        for warning in PitEventWarning
    }


def _require_columns(
    laps: pd.DataFrame,
) -> None:
    """Confirm that all required lap columns exist."""
    missing_columns = sorted(
        REQUIRED_PIT_COLUMNS.difference(
            laps.columns
        )
    )

    if missing_columns:
        missing_text = ", ".join(missing_columns)

        raise PitEventReconstructionError(
            "lap table is missing required columns: "
            f"{missing_text}"
        )


def _validate_input(
    laps: pd.DataFrame,
) -> None:
    """Reject ambiguous lap identities."""
    text_identity_columns = (
        "SessionType",
        "EventName",
        "Driver",
        "Team",
    )

    for column in text_identity_columns:
        missing_mask = (
            laps[column].isna()
            | laps[column]
            .astype(str)
            .str.strip()
            .eq("")
        )

        if missing_mask.any():
            raise PitEventReconstructionError(
                f"{column} contains missing values"
            )

    for column in (
        "Season",
        "RoundNumber",
        "LapNumber",
        "Stint",
    ):
        _validate_positive_integer_column(
            laps,
            column,
        )

    duplicate_mask = laps.duplicated(
        subset=[
            "Season",
            "RoundNumber",
            "SessionType",
            "Driver",
            "LapNumber",
        ],
        keep=False,
    )

    if duplicate_mask.any():
        duplicate_count = int(
            duplicate_mask.sum()
        )

        raise PitEventReconstructionError(
            "lap table contains "
            f"{duplicate_count} duplicate lap identities"
        )

    event_counts = (
        laps.groupby(
            [
                "Season",
                "RoundNumber",
                "SessionType",
            ],
            dropna=False,
        )["EventName"]
        .nunique(dropna=False)
    )

    if (event_counts > 1).any():
        raise PitEventReconstructionError(
            "a session contains conflicting event names"
        )


def _validate_positive_integer_column(
    laps: pd.DataFrame,
    column: str,
) -> None:
    """Require a numeric column containing positive integers."""
    values = laps[column]

    if (
        is_bool_dtype(values.dtype)
        or not is_numeric_dtype(values.dtype)
    ):
        raise PitEventReconstructionError(
            f"{column} must contain numeric integers"
        )

    numeric = pd.to_numeric(
        values,
        errors="coerce",
    )

    invalid_mask = (
        numeric.isna()
        | (numeric <= 0)
        | (numeric % 1 != 0)
    )

    if invalid_mask.any():
        invalid_count = int(
            invalid_mask.sum()
        )

        raise PitEventReconstructionError(
            f"{column} contains "
            f"{invalid_count} invalid values"
        )


def _empty_result() -> PitEventReconstructionResult:
    """Create a deterministic empty result."""
    return PitEventReconstructionResult(
        pit_events=pd.DataFrame(
            columns=PIT_EVENT_COLUMNS
        ),
        input_lap_count=0,
        driver_count=0,
        pit_event_count=0,
        matched_event_count=0,
        entry_only_event_count=0,
        exit_only_event_count=0,
        complete_event_count=0,
        incomplete_event_count=0,
        duration_analysis_candidate_count=0,
        warning_counts={
            warning.value: 0
            for warning in PitEventWarning
        },
    )