"""Reconstruct tyre stints from raw Formula 1 lap records."""

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

REQUIRED_STINT_COLUMNS: Final = frozenset(
    {
        *DRIVER_IDENTITY_COLUMNS,
        "Team",
        "LapNumber",
        "Stint",
        "Compound",
        "TyreLife",
        "PitInTime",
        "PitOutTime",
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

STINT_TABLE_COLUMNS: Final = (
    "season",
    "round_number",
    "session_type",
    "event_name",
    "driver",
    "team",
    "stint_number",
    "compound",
    "start_lap",
    "end_lap",
    "recorded_laps",
    "start_tyre_life",
    "end_tyre_life",
    "is_first_stint",
    "is_last_stint",
    "boundary_before_verified",
    "boundary_after_verified",
    "is_complete",
    "warning_count",
    "warnings",
)

TYRE_LIFE_TOLERANCE: Final = 0.001


class StintWarning(StrEnum):
    """Describe a consistency problem affecting one reconstructed stint."""

    TEAM_CONFLICT = "TEAM_CONFLICT"
    MISSING_COMPOUND = "MISSING_COMPOUND"
    MULTIPLE_COMPOUNDS = "MULTIPLE_COMPOUNDS"
    UNSUPPORTED_COMPOUND = "UNSUPPORTED_COMPOUND"
    MISSING_TYRE_LIFE = "MISSING_TYRE_LIFE"
    INVALID_TYRE_LIFE = "INVALID_TYRE_LIFE"
    TYRE_LIFE_DECREASE = "TYRE_LIFE_DECREASE"
    TYRE_LIFE_STEP_MISMATCH = "TYRE_LIFE_STEP_MISMATCH"
    LAP_NUMBER_GAP = "LAP_NUMBER_GAP"
    DISJOINT_STINT = "DISJOINT_STINT"
    NON_SEQUENTIAL_STINT = "NON_SEQUENTIAL_STINT"
    MISSING_PIT_EVIDENCE_BEFORE = (
        "MISSING_PIT_EVIDENCE_BEFORE"
    )
    MISSING_PIT_EVIDENCE_AFTER = (
        "MISSING_PIT_EVIDENCE_AFTER"
    )


WARNING_ORDER: Final = {
    warning: position
    for position, warning in enumerate(StintWarning)
}


class StintReconstructionError(ValueError):
    """Raised when lap records cannot support stint reconstruction."""


@dataclass(frozen=True, slots=True)
class StintReconstructionResult:
    """Contain reconstructed stints and their quality summary."""

    stints: pd.DataFrame
    input_lap_count: int
    driver_count: int
    stint_count: int
    complete_stint_count: int
    incomplete_stint_count: int
    warning_counts: dict[str, int]


def reconstruct_stints(
    laps: pd.DataFrame,
) -> StintReconstructionResult:
    """Reconstruct ordered tyre stints from lap-level records."""
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
            _reconstruct_driver_stints(
                driver_key,
                driver_laps.reset_index(drop=True),
            )
        )

    stints = pd.DataFrame.from_records(
        records,
        columns=STINT_TABLE_COLUMNS,
    )

    stints = stints.sort_values(
        [
            "season",
            "round_number",
            "session_type",
            "driver",
            "start_lap",
            "stint_number",
        ],
        kind="stable",
    ).reset_index(drop=True)

    warning_counts = _count_warnings(stints)
    complete_count = int(stints["is_complete"].sum())

    return StintReconstructionResult(
        stints=stints,
        input_lap_count=len(laps),
        driver_count=driver_count,
        stint_count=len(stints),
        complete_stint_count=complete_count,
        incomplete_stint_count=len(stints) - complete_count,
        warning_counts=warning_counts,
    )


def _reconstruct_driver_stints(
    driver_key: tuple[object, ...],
    driver_laps: pd.DataFrame,
) -> list[dict[str, object]]:
    """Reconstruct every contiguous stint for one driver."""
    stint_numbers = driver_laps["Stint"].astype(int)
    block_numbers = stint_numbers.ne(
        stint_numbers.shift()
    ).cumsum()

    blocks = [
        block.reset_index(drop=True)
        for _, block in driver_laps.groupby(
            block_numbers,
            sort=True,
        )
    ]

    block_stint_numbers = [
        int(block["Stint"].iloc[0])
        for block in blocks
    ]
    occurrence_counts = Counter(block_stint_numbers)

    records = []

    for position, block in enumerate(blocks):
        previous_block = (
            blocks[position - 1]
            if position > 0
            else None
        )
        next_block = (
            blocks[position + 1]
            if position < len(blocks) - 1
            else None
        )

        record = _build_stint_record(
            driver_key=driver_key,
            block=block,
            position=position,
            block_count=len(blocks),
            previous_block=previous_block,
            next_block=next_block,
            occurrence_counts=occurrence_counts,
        )
        records.append(record)

    return records


def _build_stint_record(
    *,
    driver_key: tuple[object, ...],
    block: pd.DataFrame,
    position: int,
    block_count: int,
    previous_block: pd.DataFrame | None,
    next_block: pd.DataFrame | None,
    occurrence_counts: Counter[int],
) -> dict[str, object]:
    """Build one reconstructed stint record."""
    season, round_number, session_type, event_name, driver = (
        driver_key
    )

    stint_number = int(block["Stint"].iloc[0])
    warnings = _intrinsic_warnings(block)

    if occurrence_counts[stint_number] > 1:
        warnings.append(StintWarning.DISJOINT_STINT)

    if previous_block is not None:
        previous_stint = int(
            previous_block["Stint"].iloc[0]
        )

        if stint_number != previous_stint + 1:
            warnings.append(
                StintWarning.NON_SEQUENTIAL_STINT
            )

    is_first_stint = position == 0
    is_last_stint = position == block_count - 1

    boundary_before_verified = _boundary_before_verified(
        block,
        previous_block,
    )
    boundary_after_verified = _boundary_after_verified(
        block,
        next_block,
    )

    if not boundary_before_verified:
        warnings.append(
            StintWarning.MISSING_PIT_EVIDENCE_BEFORE
        )

    if not boundary_after_verified:
        warnings.append(
            StintWarning.MISSING_PIT_EVIDENCE_AFTER
        )

    warnings = _ordered_unique_warnings(warnings)

    teams = _normalized_text_values(
        block["Team"],
        uppercase=False,
    )
    compounds = _normalized_text_values(
        block["Compound"],
        uppercase=True,
    )

    team = (
        teams[0]
        if len(teams) == 1
        else "|".join(teams)
    )
    compound = (
        compounds[0]
        if len(compounds) == 1
        else (
            "|".join(compounds)
            if compounds
            else None
        )
    )

    first_row = block.iloc[0]
    last_row = block.iloc[-1]

    return {
        "season": int(season),
        "round_number": int(round_number),
        "session_type": str(session_type).strip().upper(),
        "event_name": str(event_name).strip(),
        "driver": str(driver).strip().upper(),
        "team": team,
        "stint_number": stint_number,
        "compound": compound,
        "start_lap": int(first_row["LapNumber"]),
        "end_lap": int(last_row["LapNumber"]),
        "recorded_laps": len(block),
        "start_tyre_life": _optional_float(
            first_row["TyreLife"]
        ),
        "end_tyre_life": _optional_float(
            last_row["TyreLife"]
        ),
        "is_first_stint": is_first_stint,
        "is_last_stint": is_last_stint,
        "boundary_before_verified": (
            boundary_before_verified
        ),
        "boundary_after_verified": (
            boundary_after_verified
        ),
        "is_complete": not warnings,
        "warning_count": len(warnings),
        "warnings": "|".join(
            warning.value
            for warning in warnings
        ),
    }


def _intrinsic_warnings(
    block: pd.DataFrame,
) -> list[StintWarning]:
    """Find problems contained within one stint block."""
    warnings: list[StintWarning] = []

    teams = _normalized_text_values(
        block["Team"],
        uppercase=False,
    )
    compounds = _normalized_text_values(
        block["Compound"],
        uppercase=True,
    )

    if len(teams) > 1:
        warnings.append(StintWarning.TEAM_CONFLICT)

    if not compounds:
        warnings.append(StintWarning.MISSING_COMPOUND)
    elif len(compounds) > 1:
        warnings.append(
            StintWarning.MULTIPLE_COMPOUNDS
        )

    if any(
        compound not in SUPPORTED_COMPOUNDS
        for compound in compounds
    ):
        warnings.append(
            StintWarning.UNSUPPORTED_COMPOUND
        )

    tyre_life = pd.to_numeric(
        block["TyreLife"],
        errors="coerce",
    )

    if tyre_life.isna().any():
        warnings.append(
            StintWarning.MISSING_TYRE_LIFE
        )

    if (
        tyre_life.notna()
        & (tyre_life <= 0)
    ).any():
        warnings.append(
            StintWarning.INVALID_TYRE_LIFE
        )

    lap_numbers = block["LapNumber"].astype(float)
    lap_differences = lap_numbers.diff()

    if (lap_differences > 1).any():
        warnings.append(
            StintWarning.LAP_NUMBER_GAP
        )

    comparison = pd.DataFrame(
        {
            "lap_difference": lap_differences,
            "tyre_difference": tyre_life.diff(),
            "previous_tyre_life": tyre_life.shift(),
            "current_tyre_life": tyre_life,
        }
    )

    comparable = (
        comparison["lap_difference"].notna()
        & comparison["previous_tyre_life"].notna()
        & comparison["current_tyre_life"].notna()
    )

    comparable_rows = comparison[comparable]

    if (
        comparable_rows["tyre_difference"] < 0
    ).any():
        warnings.append(
            StintWarning.TYRE_LIFE_DECREASE
        )

    step_difference = (
        comparable_rows["tyre_difference"]
        - comparable_rows["lap_difference"]
    ).abs()

    if (
        step_difference > TYRE_LIFE_TOLERANCE
    ).any():
        warnings.append(
            StintWarning.TYRE_LIFE_STEP_MISMATCH
        )

    return warnings


def _boundary_before_verified(
    block: pd.DataFrame,
    previous_block: pd.DataFrame | None,
) -> bool:
    """Check evidence for the boundary before a stint."""
    if previous_block is None:
        return True

    previous_last = previous_block.iloc[-1]
    current_first = block.iloc[0]

    return bool(
        pd.notna(previous_last["PitInTime"])
        or pd.notna(current_first["PitOutTime"])
    )


def _boundary_after_verified(
    block: pd.DataFrame,
    next_block: pd.DataFrame | None,
) -> bool:
    """Check evidence for the boundary after a stint."""
    if next_block is None:
        return True

    current_last = block.iloc[-1]
    next_first = next_block.iloc[0]

    return bool(
        pd.notna(current_last["PitInTime"])
        or pd.notna(next_first["PitOutTime"])
    )


def _normalized_text_values(
    values: pd.Series,
    *,
    uppercase: bool,
) -> list[str]:
    """Return deterministic unique non-empty text values."""
    normalized = set()

    for value in values:
        if pd.isna(value):
            continue

        text = str(value).strip()

        if not text:
            continue

        if uppercase:
            text = text.upper()

        normalized.add(text)

    return sorted(normalized)


def _ordered_unique_warnings(
    warnings: list[StintWarning],
) -> list[StintWarning]:
    """Deduplicate warnings using their canonical order."""
    return sorted(
        set(warnings),
        key=WARNING_ORDER.__getitem__,
    )


def _optional_float(
    value: object,
) -> float | None:
    """Convert a numeric value while preserving missingness."""
    if pd.isna(value):
        return None

    return float(value)


def _count_warnings(
    stints: pd.DataFrame,
) -> dict[str, int]:
    """Count affected stints for every warning code."""
    counts = Counter()

    for warning_text in stints["warnings"]:
        if not warning_text:
            continue

        counts.update(warning_text.split("|"))

    return {
        warning.value: counts[warning.value]
        for warning in StintWarning
    }


def _require_columns(
    laps: pd.DataFrame,
) -> None:
    """Confirm that every required raw column is present."""
    missing_columns = sorted(
        REQUIRED_STINT_COLUMNS.difference(
            laps.columns
        )
    )

    if missing_columns:
        missing_text = ", ".join(missing_columns)

        raise StintReconstructionError(
            "lap table is missing required columns: "
            f"{missing_text}"
        )


def _validate_input(
    laps: pd.DataFrame,
) -> None:
    """Reject identities and numeric fields that cannot be grouped."""
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
            raise StintReconstructionError(
                f"{column} contains missing values"
            )

    _validate_positive_integer_column(
        laps,
        "Season",
    )
    _validate_positive_integer_column(
        laps,
        "RoundNumber",
    )
    _validate_positive_integer_column(
        laps,
        "LapNumber",
    )
    _validate_positive_integer_column(
        laps,
        "Stint",
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

        raise StintReconstructionError(
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
        raise StintReconstructionError(
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
        raise StintReconstructionError(
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

        raise StintReconstructionError(
            f"{column} contains "
            f"{invalid_count} invalid values"
        )


def _empty_result() -> StintReconstructionResult:
    """Create an empty deterministic reconstruction result."""
    return StintReconstructionResult(
        stints=pd.DataFrame(
            columns=STINT_TABLE_COLUMNS
        ),
        input_lap_count=0,
        driver_count=0,
        stint_count=0,
        complete_stint_count=0,
        incomplete_stint_count=0,
        warning_counts={
            warning.value: 0
            for warning in StintWarning
        },
    )