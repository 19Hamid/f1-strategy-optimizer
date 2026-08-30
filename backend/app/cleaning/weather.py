"""Align weather observations to laps without future leakage."""

from dataclasses import dataclass

import pandas as pd

SESSION_IDENTITY_COLUMNS = (
    "Season",
    "RoundNumber",
    "SessionType",
    "EventName",
)

LAP_WEATHER_REQUIRED_COLUMNS = (
    *SESSION_IDENTITY_COLUMNS,
    "LapStartTime",
)

WEATHER_VALUE_COLUMNS = (
    "AirTemp",
    "Humidity",
    "Pressure",
    "Rainfall",
    "TrackTemp",
    "WindDirection",
    "WindSpeed",
)

WEATHER_REQUIRED_COLUMNS = (
    *SESSION_IDENTITY_COLUMNS,
    "Time",
    *WEATHER_VALUE_COLUMNS,
)

WEATHER_OUTPUT_COLUMNS = (
    "WeatherObservationTime",
    *WEATHER_VALUE_COLUMNS,
    "WeatherAgeSeconds",
    "WeatherMatched",
)

ALIGNMENT_ROW_COLUMN = "_WeatherAlignmentRow"


class WeatherAlignmentError(RuntimeError):
    """Indicate that weather cannot be aligned safely."""


@dataclass(frozen=True, slots=True)
class WeatherAlignmentResult:
    """Store weather-aligned laps and alignment statistics."""

    laps: pd.DataFrame
    input_lap_count: int
    weather_observation_count: int
    matched_lap_count: int
    unmatched_lap_count: int
    rainy_lap_count: int
    maximum_weather_age_seconds: float | None
    weather_was_reordered: bool


def align_weather_to_laps(
    laps: pd.DataFrame,
    weather: pd.DataFrame,
) -> WeatherAlignmentResult:
    """Match each lap with the latest available weather observation."""
    _require_columns(
        laps,
        LAP_WEATHER_REQUIRED_COLUMNS,
        table_name="lap",
    )
    _require_columns(
        weather,
        WEATHER_REQUIRED_COLUMNS,
        table_name="weather",
    )
    _require_absent_output_columns(laps)

    if laps.empty:
        raise WeatherAlignmentError(
            "lap table must contain at least one row"
        )

    if weather.empty:
        raise WeatherAlignmentError(
            "weather table must contain at least one observation"
        )

    _require_timedelta(
        laps["LapStartTime"],
        column_name="LapStartTime",
    )
    _require_timedelta(
        weather["Time"],
        column_name="Time",
    )

    if laps["LapStartTime"].isna().any():
        raise WeatherAlignmentError(
            "LapStartTime must not contain missing values"
        )

    if weather["Time"].isna().any():
        raise WeatherAlignmentError(
            "weather Time must not contain missing values"
        )

    duplicate_weather_times = weather["Time"].duplicated(
        keep=False
    )

    if duplicate_weather_times.any():
        raise WeatherAlignmentError(
            "weather Time must not contain duplicates"
        )

    zero_duration = pd.to_timedelta(0, unit="s")

    if weather["Time"].lt(zero_duration).any():
        raise WeatherAlignmentError(
            "weather Time must not contain negative values"
        )

    lap_identity = _session_identity(
        laps,
        table_name="lap",
    )
    weather_identity = _session_identity(
        weather,
        table_name="weather",
    )

    if lap_identity != weather_identity:
        raise WeatherAlignmentError(
            "lap and weather session identities do not match"
        )

    aligned_laps = laps.copy(deep=True)
    weather_for_merge = weather.loc[
        :,
        [
            "Time",
            *WEATHER_VALUE_COLUMNS,
        ],
    ].copy()

    weather_was_reordered = not weather_for_merge[
        "Time"
    ].is_monotonic_increasing

    aligned_laps[ALIGNMENT_ROW_COLUMN] = range(
        len(aligned_laps)
    )
    aligned_laps = aligned_laps.sort_values(
        "LapStartTime",
        kind="stable",
    )

    weather_for_merge = (
        weather_for_merge.sort_values(
            "Time",
            kind="stable",
        )
        .rename(
            columns={
                "Time": "WeatherObservationTime",
            }
        )
    )

    aligned_laps = pd.merge_asof(
        aligned_laps,
        weather_for_merge,
        left_on="LapStartTime",
        right_on="WeatherObservationTime",
        direction="backward",
        allow_exact_matches=True,
    )

    aligned_laps["WeatherMatched"] = aligned_laps[
        "WeatherObservationTime"
    ].notna()

    aligned_laps["WeatherAgeSeconds"] = (
        aligned_laps["LapStartTime"]
        - aligned_laps["WeatherObservationTime"]
    ).dt.total_seconds()

    future_weather = aligned_laps[
        "WeatherAgeSeconds"
    ].lt(0)

    if future_weather.fillna(False).any():
        raise WeatherAlignmentError(
            "weather alignment produced a future observation"
        )

    aligned_laps["Rainfall"] = aligned_laps[
        "Rainfall"
    ].astype("boolean")

    aligned_laps = (
        aligned_laps.sort_values(
            ALIGNMENT_ROW_COLUMN,
            kind="stable",
        )
        .drop(columns=ALIGNMENT_ROW_COLUMN)
        .reset_index(drop=True)
    )

    input_lap_count = len(aligned_laps)
    matched_lap_count = int(
        aligned_laps["WeatherMatched"].sum()
    )
    unmatched_lap_count = (
        input_lap_count
        - matched_lap_count
    )
    rainy_lap_count = int(
        (
            aligned_laps["WeatherMatched"]
            & aligned_laps["Rainfall"].fillna(False)
        ).sum()
    )

    matched_ages = aligned_laps.loc[
        aligned_laps["WeatherMatched"],
        "WeatherAgeSeconds",
    ]

    maximum_weather_age_seconds = (
        float(matched_ages.max())
        if not matched_ages.empty
        else None
    )

    return WeatherAlignmentResult(
        laps=aligned_laps,
        input_lap_count=input_lap_count,
        weather_observation_count=len(weather),
        matched_lap_count=matched_lap_count,
        unmatched_lap_count=unmatched_lap_count,
        rainy_lap_count=rainy_lap_count,
        maximum_weather_age_seconds=(
            maximum_weather_age_seconds
        ),
        weather_was_reordered=weather_was_reordered,
    )


def _require_columns(
    table: pd.DataFrame,
    required_columns: tuple[str, ...],
    *,
    table_name: str,
) -> None:
    """Confirm that an input table contains required columns."""
    missing_columns = sorted(
        set(required_columns).difference(table.columns)
    )

    if missing_columns:
        missing_text = ", ".join(missing_columns)
        raise WeatherAlignmentError(
            f"{table_name} table is missing required columns: "
            f"{missing_text}"
        )


def _require_absent_output_columns(
    laps: pd.DataFrame,
) -> None:
    """Prevent accidental repeated weather alignment."""
    existing_columns = sorted(
        set(WEATHER_OUTPUT_COLUMNS).intersection(
            laps.columns
        )
    )

    if existing_columns:
        existing_text = ", ".join(existing_columns)
        raise WeatherAlignmentError(
            "lap table already contains weather output "
            f"columns: {existing_text}"
        )


def _require_timedelta(
    values: pd.Series,
    *,
    column_name: str,
) -> None:
    """Confirm that a timeline column uses timedeltas."""
    if getattr(values.dtype, "kind", None) != "m":
        raise WeatherAlignmentError(
            f"{column_name} must use a timedelta dtype"
        )


def _session_identity(
    table: pd.DataFrame,
    *,
    table_name: str,
) -> tuple[object, ...]:
    """Extract one complete session identity from a table."""
    identities = table.loc[
        :,
        [*SESSION_IDENTITY_COLUMNS],
    ].drop_duplicates()

    if len(identities) != 1:
        raise WeatherAlignmentError(
            f"{table_name} table must contain exactly one "
            "session identity"
        )

    identity = identities.iloc[0]

    if identity.isna().any():
        raise WeatherAlignmentError(
            f"{table_name} session identity must be complete"
        )

    return tuple(
        identity[column]
        for column in SESSION_IDENTITY_COLUMNS
    )