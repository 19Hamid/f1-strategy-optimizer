"""Build deterministic processed data for one race session."""

from dataclasses import dataclass
from typing import Final

import pandas as pd

from app.cleaning.pits import reconstruct_pit_events
from app.cleaning.session import clean_session_laps
from app.cleaning.stints import reconstruct_stints
from app.pipeline.models import SessionKey
from app.pipeline.storage import RAW_CONTRACT_VERSION

PROCESSED_CONTRACT_VERSION: Final = "1.0"
CLEANING_RULE_VERSION: Final = "1.0"

PROVENANCE_COLUMNS: Final = frozenset(
    {
        "Season",
        "RoundNumber",
        "SessionType",
        "EventName",
    }
)


class SessionProcessingError(ValueError):
    """Raised when session tables cannot be processed safely."""


@dataclass(frozen=True, slots=True)
class ProcessedSessionData:
    """Contain every processed table and its quality report."""

    session_key: SessionKey
    laps: pd.DataFrame
    stints: pd.DataFrame
    pit_events: pd.DataFrame
    quality_report: dict[str, object]


def process_session_tables(
    session_key: SessionKey,
    laps: pd.DataFrame,
    weather: pd.DataFrame,
) -> ProcessedSessionData:
    """Clean and reconstruct all analytical session tables."""
    if not isinstance(session_key, SessionKey):
        raise TypeError(
            "session_key must be a SessionKey"
        )

    event_name = _validate_source_identity(
        session_key=session_key,
        laps=laps,
        weather=weather,
    )

    lap_result = clean_session_laps(
        laps,
        weather,
    )
    stint_result = reconstruct_stints(
        lap_result.laps
    )
    pit_result = reconstruct_pit_events(
        lap_result.laps
    )

    pit_events = _add_pit_weather_context(
        pit_events=pit_result.pit_events,
        laps=lap_result.laps,
    )

    duration_candidate_count = int(
        pit_events[
            "is_duration_analysis_candidate"
        ].sum()
    )
    dry_weather_pair_count = int(
        pit_events[
            "is_dry_weather_pair"
        ].sum()
    )

    _validate_processed_counts(
        source_laps=laps,
        processed_laps=lap_result.laps,
        eligible_lap_count=(
            lap_result.eligible_lap_count
        ),
        excluded_lap_count=(
            lap_result.excluded_lap_count
        ),
        stints=stint_result.stints,
        pit_events=pit_events,
        matched_pit_event_count=(
            pit_result.matched_event_count
        ),
        entry_only_pit_event_count=(
            pit_result.entry_only_event_count
        ),
        exit_only_pit_event_count=(
            pit_result.exit_only_event_count
        ),
    )

    quality_report = {
        "processed_contract_version": (
            PROCESSED_CONTRACT_VERSION
        ),
        "cleaning_rule_version": (
            CLEANING_RULE_VERSION
        ),
        "source_contract_version": (
            RAW_CONTRACT_VERSION
        ),
        "session": {
            "identifier": session_key.identifier,
            "season": session_key.season,
            "round_number": (
                session_key.round_number
            ),
            "session_type": (
                session_key.session_type
            ),
            "event_name": event_name,
        },
        "tables": {
            "laps_rows": len(
                lap_result.laps
            ),
            "stints_rows": len(
                stint_result.stints
            ),
            "pit_events_rows": len(
                pit_events
            ),
        },
        "lap_quality": {
            "input_laps": (
                lap_result.input_lap_count
            ),
            "eligible_laps": (
                lap_result.eligible_lap_count
            ),
            "flagged_laps": (
                lap_result.flagged_lap_count
            ),
            "excluded_laps": (
                lap_result.excluded_lap_count
            ),
            "weather_observations": (
                lap_result.weather_observation_count
            ),
            "rain_aligned_laps": (
                lap_result.rainy_lap_count
            ),
            "rainfall_reasons_added": (
                lap_result.rain_added_reason_count
            ),
            "rainfall_newly_excluded_laps": (
                lap_result.rain_newly_excluded_count
            ),
            "maximum_weather_age_seconds": (
                lap_result.maximum_weather_age_seconds
            ),
            "weather_was_reordered": (
                lap_result.weather_was_reordered
            ),
            "reason_counts": dict(
                lap_result.quality_counts
            ),
        },
        "stint_quality": {
            "drivers": (
                stint_result.driver_count
            ),
            "stints": (
                stint_result.stint_count
            ),
            "complete_stints": (
                stint_result.complete_stint_count
            ),
            "incomplete_stints": (
                stint_result.incomplete_stint_count
            ),
            "warning_counts": dict(
                stint_result.warning_counts
            ),
        },
        "pit_event_quality": {
            "drivers": (
                pit_result.driver_count
            ),
            "pit_events": (
                pit_result.pit_event_count
            ),
            "matched_events": (
                pit_result.matched_event_count
            ),
            "entry_only_events": (
                pit_result.entry_only_event_count
            ),
            "exit_only_events": (
                pit_result.exit_only_event_count
            ),
            "complete_events": (
                pit_result.complete_event_count
            ),
            "incomplete_events": (
                pit_result.incomplete_event_count
            ),
            "dry_weather_pairs": (
                dry_weather_pair_count
            ),
            "duration_analysis_candidates": (
                duration_candidate_count
            ),
            "warning_counts": dict(
                pit_result.warning_counts
            ),
        },
        "validation": {
            "status": "passed",
            "raw_laps_preserved": True,
            "future_weather_matches": 0,
            "pit_weather_context_complete": True,
        },
    }

    return ProcessedSessionData(
        session_key=session_key,
        laps=lap_result.laps,
        stints=stint_result.stints,
        pit_events=pit_events,
        quality_report=quality_report,
    )


def _add_pit_weather_context(
    *,
    pit_events: pd.DataFrame,
    laps: pd.DataFrame,
) -> pd.DataFrame:
    """Attach aligned rainfall to pit-entry and pit-exit laps."""
    if "Rainfall" not in laps.columns:
        raise SessionProcessingError(
            "processed laps are missing aligned Rainfall"
        )

    rainfall_lookup = laps[
        [
            "Driver",
            "LapNumber",
            "Rainfall",
        ]
    ].copy()

    rainfall_lookup["Driver"] = (
        rainfall_lookup["Driver"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    duplicate_mask = rainfall_lookup.duplicated(
        subset=[
            "Driver",
            "LapNumber",
        ],
        keep=False,
    )

    if duplicate_mask.any():
        raise SessionProcessingError(
            "rainfall lookup contains duplicate driver laps"
        )

    entry_lookup = rainfall_lookup.rename(
        columns={
            "Driver": "driver",
            "LapNumber": "pit_in_lap",
            "Rainfall": "entry_rainfall",
        }
    )

    exit_lookup = rainfall_lookup.rename(
        columns={
            "Driver": "driver",
            "LapNumber": "pit_out_lap",
            "Rainfall": "exit_rainfall",
        }
    )

    enriched = pit_events.merge(
        entry_lookup,
        how="left",
        on=[
            "driver",
            "pit_in_lap",
        ],
        sort=False,
        validate="many_to_one",
    )

    enriched = enriched.merge(
        exit_lookup,
        how="left",
        on=[
            "driver",
            "pit_out_lap",
        ],
        sort=False,
        validate="many_to_one",
    )

    enriched["entry_rainfall"] = enriched[
        "entry_rainfall"
    ].astype("boolean")
    enriched["exit_rainfall"] = enriched[
        "exit_rainfall"
    ].astype("boolean")

    complete_mask = enriched[
        "is_complete"
    ].astype(bool)

    missing_complete_weather = (
        complete_mask
        & (
            enriched["entry_rainfall"].isna()
            | enriched["exit_rainfall"].isna()
        )
    )

    if missing_complete_weather.any():
        raise SessionProcessingError(
            "complete pit events are missing rainfall context"
        )

    dry_weather_pair = (
        enriched["entry_rainfall"].eq(False)
        & enriched["exit_rainfall"].eq(False)
    )

    enriched["is_dry_weather_pair"] = (
        dry_weather_pair
        .fillna(False)
        .astype(bool)
    )

    enriched[
        "is_duration_analysis_candidate"
    ] = (
        enriched[
            "is_duration_analysis_candidate"
        ].astype(bool)
        & enriched[
            "is_dry_weather_pair"
        ]
    )

    return enriched


def _validate_source_identity(
    *,
    session_key: SessionKey,
    laps: pd.DataFrame,
    weather: pd.DataFrame,
) -> str:
    """Confirm that source tables belong to one requested session."""
    lap_event_name = _validate_table_identity(
        table_name="laps",
        table=laps,
        session_key=session_key,
    )
    weather_event_name = _validate_table_identity(
        table_name="weather",
        table=weather,
        session_key=session_key,
    )

    if lap_event_name != weather_event_name:
        raise SessionProcessingError(
            "lap and weather event names differ"
        )

    return lap_event_name


def _validate_table_identity(
    *,
    table_name: str,
    table: pd.DataFrame,
    session_key: SessionKey,
) -> str:
    """Validate one table's session provenance."""
    missing_columns = sorted(
        PROVENANCE_COLUMNS.difference(
            table.columns
        )
    )

    if missing_columns:
        missing_text = ", ".join(
            missing_columns
        )

        raise SessionProcessingError(
            f"{table_name} table is missing "
            f"provenance columns: {missing_text}"
        )

    if table.empty:
        raise SessionProcessingError(
            f"{table_name} table must not be empty"
        )

    seasons = set(
        pd.to_numeric(
            table["Season"],
            errors="coerce",
        )
        .dropna()
        .astype(int)
    )

    if seasons != {session_key.season}:
        raise SessionProcessingError(
            f"{table_name} table season does not match "
            f"{session_key.identifier}"
        )

    round_numbers = set(
        pd.to_numeric(
            table["RoundNumber"],
            errors="coerce",
        )
        .dropna()
        .astype(int)
    )

    if round_numbers != {
        session_key.round_number
    }:
        raise SessionProcessingError(
            f"{table_name} table round does not match "
            f"{session_key.identifier}"
        )

    session_types = set(
        table["SessionType"]
        .dropna()
        .astype(str)
        .str.strip()
        .str.upper()
    )

    if session_types != {
        session_key.session_type
    }:
        raise SessionProcessingError(
            f"{table_name} table session type does not "
            f"match {session_key.identifier}"
        )

    event_names = set(
        table["EventName"]
        .dropna()
        .astype(str)
        .str.strip()
    )
    event_names.discard("")

    if len(event_names) != 1:
        raise SessionProcessingError(
            f"{table_name} table must contain exactly "
            "one event name"
        )

    return next(iter(event_names))


def _validate_processed_counts(
    *,
    source_laps: pd.DataFrame,
    processed_laps: pd.DataFrame,
    eligible_lap_count: int,
    excluded_lap_count: int,
    stints: pd.DataFrame,
    pit_events: pd.DataFrame,
    matched_pit_event_count: int,
    entry_only_pit_event_count: int,
    exit_only_pit_event_count: int,
) -> None:
    """Verify that processing preserves every source record."""
    if len(processed_laps) != len(source_laps):
        raise SessionProcessingError(
            "processed lap count differs from raw lap count"
        )

    if (
        eligible_lap_count
        + excluded_lap_count
        != len(source_laps)
    ):
        raise SessionProcessingError(
            "eligible and excluded lap counts do not "
            "cover every raw lap"
        )

    represented_stint_laps = int(
        stints["recorded_laps"].sum()
    )

    if represented_stint_laps != len(source_laps):
        raise SessionProcessingError(
            "reconstructed stints do not represent every "
            "raw lap"
        )

    source_pit_markers = int(
        source_laps["PitInTime"].notna().sum()
        + source_laps["PitOutTime"].notna().sum()
    )

    represented_pit_markers = (
        matched_pit_event_count * 2
        + entry_only_pit_event_count
        + exit_only_pit_event_count
    )

    if represented_pit_markers != source_pit_markers:
        raise SessionProcessingError(
            "reconstructed pit events do not represent "
            "every raw pit marker"
        )

    complete_events = pit_events[
        pit_events["is_complete"]
    ]

    if (
        complete_events["entry_rainfall"].isna().any()
        or complete_events["exit_rainfall"].isna().any()
    ):
        raise SessionProcessingError(
            "complete pit events lack weather context"
        )