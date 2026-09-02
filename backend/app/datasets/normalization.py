"""Canonical normalization for Phase 3 processed tables."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.datasets.contracts import (
    DEVELOPMENT_SEASONS,
    PIT_EVENT_NULLABLE_BOOLEAN_COLUMNS,
    PIT_EVENT_NULLABLE_INTEGER_COLUMNS,
    PROTECTED_EVALUATION_SEASON,
)
from app.pipeline import SessionKey

REQUIRED_LAP_SOURCE_COLUMNS = (
    "SourceRowNumber",
    "Season",
    "RoundNumber",
    "SessionType",
    "EventName",
    "Driver",
    "DriverNumber",
    "Team",
    "LapNumber",
    "Stint",
    "Compound",
    "TyreLife",
    "FreshTyre",
    "LapStartTime",
    "TrackStatus",
    "Position",
    "WeatherObservationTime",
    "AirTemp",
    "Humidity",
    "Pressure",
    "Rainfall",
    "TrackTemp",
    "WindDirection",
    "WindSpeed",
    "WeatherMatched",
    "WeatherAgeSeconds",
    "LapTimeSeconds",
    "Sector1TimeSeconds",
    "Sector2TimeSeconds",
    "Sector3TimeSeconds",
    "PitInTime",
    "PitOutTime",
    "IsAccurate",
    "IsEligible",
    "QualityFlags",
    "ExclusionReasons",
)

REQUIRED_STINT_SOURCE_COLUMNS = (
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

REQUIRED_PIT_EVENT_SOURCE_COLUMNS = (
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
    "entry_rainfall",
    "exit_rainfall",
    "is_dry_weather_pair",
)

PIT_EVENT_TYPES = frozenset(
    {
        "MATCHED",
        "ENTRY_ONLY",
        "EXIT_ONLY",
    }
)


class SourceNormalizationError(ValueError):
    """Raised when processed data cannot be normalized safely."""


@dataclass(frozen=True, slots=True)
class NormalizedProcessedSession:
    """Canonical processed tables for one development race."""

    session_key: SessionKey
    event_name: str
    laps: pd.DataFrame
    stints: pd.DataFrame
    pit_events: pd.DataFrame


def _validate_development_session_key(
    session_key: SessionKey,
) -> None:
    """Reject evaluation and unsupported seasons immediately."""
    if (
        session_key.season
        == PROTECTED_EVALUATION_SEASON
    ):
        raise SourceNormalizationError(
            f"{session_key.identifier} belongs to the "
            "protected evaluation season"
        )

    if session_key.season not in DEVELOPMENT_SEASONS:
        raise SourceNormalizationError(
            f"{session_key.identifier} is outside the "
            "development seasons"
        )

    if session_key.session_type != "R":
        raise SourceNormalizationError(
            f"{session_key.identifier} is not a race session"
        )


def _require_dataframe(
    table: pd.DataFrame,
    *,
    table_name: str,
) -> None:
    """Require callers to provide a pandas DataFrame."""
    if not isinstance(table, pd.DataFrame):
        raise TypeError(
            f"{table_name} must be a pandas DataFrame"
        )


def _require_columns(
    table: pd.DataFrame,
    *,
    table_name: str,
    required_columns: Iterable[str],
) -> None:
    """Require every source column needed by Phase 4."""
    missing = tuple(
        column
        for column in required_columns
        if column not in table.columns
    )

    if missing:
        raise SourceNormalizationError(
            f"{table_name} is missing required columns: "
            f"{missing}"
        )


def _invalid_examples(
    source: pd.Series,
    mask: pd.Series,
) -> list[object]:
    """Return a small stable sample of invalid values."""
    return (
        source.loc[mask]
        .head(5)
        .tolist()
    )


def _normalize_integer(
    source: pd.Series,
    *,
    table_name: str,
    column_name: str,
    nullable: bool,
    minimum: int | None = None,
) -> pd.Series:
    """Normalize one integer-like source column safely."""
    numeric = pd.to_numeric(
        source,
        errors="coerce",
    )

    invalid_conversion = (
        source.notna()
        & numeric.isna()
    )

    if invalid_conversion.any():
        examples = _invalid_examples(
            source,
            invalid_conversion,
        )

        raise SourceNormalizationError(
            f"{table_name}.{column_name} contains "
            f"non-numeric values: {examples}"
        )

    non_null = numeric.dropna()

    fractional = non_null.mod(1).ne(0)

    if fractional.any():
        examples = (
            non_null.loc[fractional]
            .head(5)
            .tolist()
        )

        raise SourceNormalizationError(
            f"{table_name}.{column_name} contains "
            f"fractional values: {examples}"
        )

    if minimum is not None:
        below_minimum = (
            numeric.notna()
            & numeric.lt(minimum)
        )

        if below_minimum.any():
            examples = _invalid_examples(
                numeric,
                below_minimum,
            )

            raise SourceNormalizationError(
                f"{table_name}.{column_name} contains "
                f"values below {minimum}: {examples}"
            )

    if not nullable and numeric.isna().any():
        raise SourceNormalizationError(
            f"{table_name}.{column_name} contains "
            "missing values"
        )

    if nullable:
        return numeric.astype("Int64")

    return numeric.astype("int64")


def _normalize_float(
    source: pd.Series,
    *,
    table_name: str,
    column_name: str,
    nullable: bool,
    minimum: float | None = None,
) -> pd.Series:
    """Normalize one floating-point source column."""
    numeric = pd.to_numeric(
        source,
        errors="coerce",
    )

    invalid_conversion = (
        source.notna()
        & numeric.isna()
    )

    if invalid_conversion.any():
        examples = _invalid_examples(
            source,
            invalid_conversion,
        )

        raise SourceNormalizationError(
            f"{table_name}.{column_name} contains "
            f"non-numeric values: {examples}"
        )

    if minimum is not None:
        below_minimum = (
            numeric.notna()
            & numeric.lt(minimum)
        )

        if below_minimum.any():
            examples = _invalid_examples(
                numeric,
                below_minimum,
            )

            raise SourceNormalizationError(
                f"{table_name}.{column_name} contains "
                f"values below {minimum}: {examples}"
            )

    if not nullable and numeric.isna().any():
        raise SourceNormalizationError(
            f"{table_name}.{column_name} contains "
            "missing values"
        )

    return numeric.astype("float64")


def _normalize_boolean(
    source: pd.Series,
    *,
    table_name: str,
    column_name: str,
    nullable: bool,
) -> pd.Series:
    """Normalize one boolean column without accepting 0/1."""
    invalid_values = [
        value
        for value in source.dropna().unique()
        if not isinstance(
            value,
            (
                bool,
                np.bool_,
            ),
        )
    ]

    if invalid_values:
        raise SourceNormalizationError(
            f"{table_name}.{column_name} contains "
            f"non-boolean values: {invalid_values[:5]}"
        )

    if not nullable and source.isna().any():
        raise SourceNormalizationError(
            f"{table_name}.{column_name} contains "
            "missing values"
        )

    normalized = source.astype("boolean")

    if nullable:
        return normalized

    return normalized.astype("bool")


def _normalize_string(
    source: pd.Series,
    *,
    table_name: str,
    column_name: str,
    nullable: bool,
    uppercase: bool = False,
    allow_empty: bool = False,
) -> pd.Series:
    """Normalize one source column to pandas string dtype."""
    normalized = source.astype("string")

    normalized = normalized.str.strip()

    if uppercase:
        normalized = normalized.str.upper()

    if not nullable and normalized.isna().any():
        raise SourceNormalizationError(
            f"{table_name}.{column_name} contains "
            "missing values"
        )

    if not allow_empty:
        empty = (
            normalized.notna()
            & normalized.eq("")
        )

        if empty.any():
            raise SourceNormalizationError(
                f"{table_name}.{column_name} contains "
                "empty values"
            )

    return normalized


def _normalize_timedelta(
    source: pd.Series,
    *,
    table_name: str,
    column_name: str,
    nullable: bool,
) -> pd.Series:
    """Normalize a timedelta source column."""
    normalized = pd.to_timedelta(
        source,
        errors="coerce",
    )

    invalid_conversion = (
        source.notna()
        & normalized.isna()
    )

    if invalid_conversion.any():
        examples = _invalid_examples(
            source,
            invalid_conversion,
        )

        raise SourceNormalizationError(
            f"{table_name}.{column_name} contains "
            f"invalid timedeltas: {examples}"
        )

    if not nullable and normalized.isna().any():
        raise SourceNormalizationError(
            f"{table_name}.{column_name} contains "
            "missing values"
        )

    return normalized.astype(
        "timedelta64[ns]"
    )


def _validate_identity(
    table: pd.DataFrame,
    session_key: SessionKey,
    *,
    table_name: str,
    season_column: str,
    round_column: str,
    session_type_column: str,
    event_name_column: str,
) -> str | None:
    """Verify one table belongs to exactly one session."""
    if table.empty:
        return None

    seasons = set(
        table[season_column]
        .astype("int64")
        .tolist()
    )

    if seasons != {session_key.season}:
        raise SourceNormalizationError(
            f"{table_name} season does not match "
            f"{session_key.identifier}"
        )

    round_numbers = set(
        table[round_column]
        .astype("int64")
        .tolist()
    )

    if round_numbers != {
        session_key.round_number
    }:
        raise SourceNormalizationError(
            f"{table_name} round does not match "
            f"{session_key.identifier}"
        )

    session_types = set(
        table[session_type_column]
        .astype("string")
        .tolist()
    )

    if session_types != {
        session_key.session_type
    }:
        raise SourceNormalizationError(
            f"{table_name} session type does not match "
            f"{session_key.identifier}"
        )

    event_names = set(
        table[event_name_column]
        .dropna()
        .astype("string")
        .tolist()
    )

    if len(event_names) != 1:
        raise SourceNormalizationError(
            f"{table_name} must contain exactly "
            "one event name"
        )

    return next(iter(event_names))


def normalize_processed_laps(
    laps: pd.DataFrame,
    session_key: SessionKey,
) -> pd.DataFrame:
    """Return canonical processed laps for Phase 4."""
    _validate_development_session_key(
        session_key
    )
    _require_dataframe(
        laps,
        table_name="laps",
    )
    _require_columns(
        laps,
        table_name="laps",
        required_columns=(
            REQUIRED_LAP_SOURCE_COLUMNS
        ),
    )

    normalized = laps.copy(deep=True)

    normalized["SourceRowNumber"] = (
        _normalize_integer(
            normalized["SourceRowNumber"],
            table_name="laps",
            column_name="SourceRowNumber",
            nullable=False,
            minimum=0,
        )
    )
    normalized["Season"] = _normalize_integer(
        normalized["Season"],
        table_name="laps",
        column_name="Season",
        nullable=False,
        minimum=1,
    )
    normalized["RoundNumber"] = (
        _normalize_integer(
            normalized["RoundNumber"],
            table_name="laps",
            column_name="RoundNumber",
            nullable=False,
            minimum=1,
        )
    )
    normalized["LapNumber"] = _normalize_integer(
        normalized["LapNumber"],
        table_name="laps",
        column_name="LapNumber",
        nullable=True,
        minimum=1,
    )
    normalized["Stint"] = _normalize_integer(
        normalized["Stint"],
        table_name="laps",
        column_name="Stint",
        nullable=True,
        minimum=1,
    )
    normalized["TyreLife"] = _normalize_integer(
        normalized["TyreLife"],
        table_name="laps",
        column_name="TyreLife",
        nullable=True,
        minimum=1,
    )
    normalized["Position"] = _normalize_integer(
        normalized["Position"],
        table_name="laps",
        column_name="Position",
        nullable=True,
        minimum=1,
    )
    normalized["WindDirection"] = (
        _normalize_integer(
            normalized["WindDirection"],
            table_name="laps",
            column_name="WindDirection",
            nullable=False,
            minimum=0,
        )
    )

    for column in (
        "SessionType",
        "Driver",
        "DriverNumber",
        "Team",
    ):
        normalized[column] = _normalize_string(
            normalized[column],
            table_name="laps",
            column_name=column,
            nullable=False,
            uppercase=(
                column
                in {
                    "SessionType",
                    "Driver",
                }
            ),
        )

    normalized["EventName"] = _normalize_string(
        normalized["EventName"],
        table_name="laps",
        column_name="EventName",
        nullable=False,
    )
    normalized["Compound"] = _normalize_string(
        normalized["Compound"],
        table_name="laps",
        column_name="Compound",
        nullable=False,
        uppercase=True,
    )
    normalized["TrackStatus"] = (
        _normalize_string(
            normalized["TrackStatus"],
            table_name="laps",
            column_name="TrackStatus",
            nullable=False,
        )
    )
    normalized["QualityFlags"] = (
        _normalize_string(
            normalized["QualityFlags"],
            table_name="laps",
            column_name="QualityFlags",
            nullable=False,
            allow_empty=True,
        )
    )
    normalized["ExclusionReasons"] = (
        _normalize_string(
            normalized["ExclusionReasons"],
            table_name="laps",
            column_name="ExclusionReasons",
            nullable=False,
            allow_empty=True,
        )
    )

    normalized["LapStartTime"] = (
        _normalize_timedelta(
            normalized["LapStartTime"],
            table_name="laps",
            column_name="LapStartTime",
            nullable=False,
        )
    )
    normalized["WeatherObservationTime"] = (
        _normalize_timedelta(
            normalized[
                "WeatherObservationTime"
            ],
            table_name="laps",
            column_name=(
                "WeatherObservationTime"
            ),
            nullable=False,
        )
    )
    normalized["PitInTime"] = (
        _normalize_timedelta(
            normalized["PitInTime"],
            table_name="laps",
            column_name="PitInTime",
            nullable=True,
        )
    )
    normalized["PitOutTime"] = (
        _normalize_timedelta(
            normalized["PitOutTime"],
            table_name="laps",
            column_name="PitOutTime",
            nullable=True,
        )
    )

    for column in (
        "AirTemp",
        "Humidity",
        "Pressure",
        "TrackTemp",
        "WindSpeed",
        "WeatherAgeSeconds",
    ):
        normalized[column] = _normalize_float(
            normalized[column],
            table_name="laps",
            column_name=column,
            nullable=False,
            minimum=(
                0.0
                if column
                in {
                    "Humidity",
                    "Pressure",
                    "WindSpeed",
                    "WeatherAgeSeconds",
                }
                else None
            ),
        )

    for column in (
        "LapTimeSeconds",
        "Sector1TimeSeconds",
        "Sector2TimeSeconds",
        "Sector3TimeSeconds",
    ):
        normalized[column] = _normalize_float(
            normalized[column],
            table_name="laps",
            column_name=column,
            nullable=True,
            minimum=0.0,
        )

    normalized["FreshTyre"] = (
        _normalize_boolean(
            normalized["FreshTyre"],
            table_name="laps",
            column_name="FreshTyre",
            nullable=False,
        )
    )
    normalized["Rainfall"] = (
        _normalize_boolean(
            normalized["Rainfall"],
            table_name="laps",
            column_name="Rainfall",
            nullable=True,
        )
    )
    normalized["WeatherMatched"] = (
        _normalize_boolean(
            normalized["WeatherMatched"],
            table_name="laps",
            column_name="WeatherMatched",
            nullable=False,
        )
    )
    normalized["IsAccurate"] = (
        _normalize_boolean(
            normalized["IsAccurate"],
            table_name="laps",
            column_name="IsAccurate",
            nullable=True,
        )
    )
    normalized["IsEligible"] = (
        _normalize_boolean(
            normalized["IsEligible"],
            table_name="laps",
            column_name="IsEligible",
            nullable=False,
        )
    )

    _validate_identity(
        normalized,
        session_key,
        table_name="laps",
        season_column="Season",
        round_column="RoundNumber",
        session_type_column="SessionType",
        event_name_column="EventName",
    )

    return normalized


def normalize_processed_stints(
    stints: pd.DataFrame,
    session_key: SessionKey,
) -> pd.DataFrame:
    """Return canonical processed stints for Phase 4."""
    _validate_development_session_key(
        session_key
    )
    _require_dataframe(
        stints,
        table_name="stints",
    )
    _require_columns(
        stints,
        table_name="stints",
        required_columns=(
            REQUIRED_STINT_SOURCE_COLUMNS
        ),
    )

    normalized = stints.copy(deep=True)

    for column in (
        "season",
        "round_number",
        "stint_number",
        "start_lap",
        "end_lap",
        "recorded_laps",
        "warning_count",
    ):
        normalized[column] = _normalize_integer(
            normalized[column],
            table_name="stints",
            column_name=column,
            nullable=False,
            minimum=(
                0
                if column == "warning_count"
                else 1
            ),
        )

    for column in (
        "session_type",
        "driver",
        "team",
        "compound",
    ):
        normalized[column] = _normalize_string(
            normalized[column],
            table_name="stints",
            column_name=column,
            nullable=False,
            uppercase=(
                column
                in {
                    "session_type",
                    "driver",
                    "compound",
                }
            ),
        )

    normalized["event_name"] = (
        _normalize_string(
            normalized["event_name"],
            table_name="stints",
            column_name="event_name",
            nullable=False,
        )
    )
    normalized["warnings"] = (
        _normalize_string(
            normalized["warnings"],
            table_name="stints",
            column_name="warnings",
            nullable=False,
            allow_empty=True,
        )
    )

    for column in (
        "start_tyre_life",
        "end_tyre_life",
    ):
        normalized[column] = _normalize_float(
            normalized[column],
            table_name="stints",
            column_name=column,
            nullable=True,
            minimum=0.0,
        )

    for column in (
        "is_first_stint",
        "is_last_stint",
        "boundary_before_verified",
        "boundary_after_verified",
        "is_complete",
    ):
        normalized[column] = _normalize_boolean(
            normalized[column],
            table_name="stints",
            column_name=column,
            nullable=False,
        )

    _validate_identity(
        normalized,
        session_key,
        table_name="stints",
        season_column="season",
        round_column="round_number",
        session_type_column="session_type",
        event_name_column="event_name",
    )

    return normalized


def normalize_processed_pit_events(
    pit_events: pd.DataFrame,
    session_key: SessionKey,
) -> pd.DataFrame:
    """Return canonical processed pit events for Phase 4."""
    _validate_development_session_key(
        session_key
    )
    _require_dataframe(
        pit_events,
        table_name="pit_events",
    )
    _require_columns(
        pit_events,
        table_name="pit_events",
        required_columns=(
            REQUIRED_PIT_EVENT_SOURCE_COLUMNS
        ),
    )

    normalized = pit_events.copy(deep=True)

    normalized["season"] = _normalize_integer(
        normalized["season"],
        table_name="pit_events",
        column_name="season",
        nullable=False,
        minimum=1,
    )
    normalized["round_number"] = (
        _normalize_integer(
            normalized["round_number"],
            table_name="pit_events",
            column_name="round_number",
            nullable=False,
            minimum=1,
        )
    )
    normalized["warning_count"] = (
        _normalize_integer(
            normalized["warning_count"],
            table_name="pit_events",
            column_name="warning_count",
            nullable=False,
            minimum=0,
        )
    )

    for column in (
        PIT_EVENT_NULLABLE_INTEGER_COLUMNS
    ):
        normalized[column] = _normalize_integer(
            normalized[column],
            table_name="pit_events",
            column_name=column,
            nullable=True,
            minimum=1,
        )

    for column in (
        "pit_event_id",
        "session_type",
        "driver",
        "event_type",
    ):
        normalized[column] = _normalize_string(
            normalized[column],
            table_name="pit_events",
            column_name=column,
            nullable=False,
            uppercase=(
                column
                in {
                    "session_type",
                    "driver",
                    "event_type",
                }
            ),
        )

    normalized["event_name"] = (
        _normalize_string(
            normalized["event_name"],
            table_name="pit_events",
            column_name="event_name",
            nullable=False,
        )
    )
    normalized["team"] = _normalize_string(
        normalized["team"],
        table_name="pit_events",
        column_name="team",
        nullable=False,
    )

    for column in (
        "compound_before",
        "compound_after",
    ):
        normalized[column] = _normalize_string(
            normalized[column],
            table_name="pit_events",
            column_name=column,
            nullable=True,
            uppercase=True,
        )

    for column in (
        "entry_track_status",
        "exit_track_status",
    ):
        normalized[column] = _normalize_string(
            normalized[column],
            table_name="pit_events",
            column_name=column,
            nullable=True,
        )

    normalized["warnings"] = (
        _normalize_string(
            normalized["warnings"],
            table_name="pit_events",
            column_name="warnings",
            nullable=False,
            allow_empty=True,
        )
    )

    for column in (
        "tyre_life_before",
        "tyre_life_after",
        "pit_in_time_seconds",
        "pit_out_time_seconds",
        "observed_pit_lane_duration_seconds",
    ):
        normalized[column] = _normalize_float(
            normalized[column],
            table_name="pit_events",
            column_name=column,
            nullable=True,
            minimum=0.0,
        )

    for column in (
        PIT_EVENT_NULLABLE_BOOLEAN_COLUMNS
    ):
        normalized[column] = _normalize_boolean(
            normalized[column],
            table_name="pit_events",
            column_name=column,
            nullable=True,
        )

    for column in (
        "is_green_flag_pair",
        "is_dry_compound_pair",
        "is_interrupted_duration",
        "is_complete",
        "is_duration_analysis_candidate",
        "is_dry_weather_pair",
    ):
        normalized[column] = _normalize_boolean(
            normalized[column],
            table_name="pit_events",
            column_name=column,
            nullable=False,
        )

    for column in (
        "entry_rainfall",
        "exit_rainfall",
    ):
        normalized[column] = _normalize_boolean(
            normalized[column],
            table_name="pit_events",
            column_name=column,
            nullable=True,
        )

    observed_event_types = set(
        normalized["event_type"]
        .dropna()
        .tolist()
    )

    unsupported_event_types = (
        observed_event_types
        - PIT_EVENT_TYPES
    )

    if unsupported_event_types:
        raise SourceNormalizationError(
            "pit_events.event_type contains "
            f"unsupported values: "
            f"{sorted(unsupported_event_types)}"
        )

    _validate_identity(
        normalized,
        session_key,
        table_name="pit_events",
        season_column="season",
        round_column="round_number",
        session_type_column="session_type",
        event_name_column="event_name",
    )

    return normalized


def normalize_processed_session_tables(
    *,
    laps: pd.DataFrame,
    stints: pd.DataFrame,
    pit_events: pd.DataFrame,
    session_key: SessionKey,
) -> NormalizedProcessedSession:
    """Normalize and cross-check one processed session."""
    _validate_development_session_key(
        session_key
    )

    normalized_laps = normalize_processed_laps(
        laps,
        session_key,
    )
    normalized_stints = (
        normalize_processed_stints(
            stints,
            session_key,
        )
    )
    normalized_pit_events = (
        normalize_processed_pit_events(
            pit_events,
            session_key,
        )
    )

    event_names = {
        str(
            normalized_laps[
                "EventName"
            ].iloc[0]
        ),
        str(
            normalized_stints[
                "event_name"
            ].iloc[0]
        ),
    }

    if not normalized_pit_events.empty:
        event_names.add(
            str(
                normalized_pit_events[
                    "event_name"
                ].iloc[0]
            )
        )

    if len(event_names) != 1:
        raise SourceNormalizationError(
            f"processed tables for "
            f"{session_key.identifier} disagree "
            f"on event name: {sorted(event_names)}"
        )

    return NormalizedProcessedSession(
        session_key=session_key,
        event_name=next(iter(event_names)),
        laps=normalized_laps,
        stints=normalized_stints,
        pit_events=normalized_pit_events,
    )