"""Leakage-controlled construction of decision rows and labels."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.datasets.contracts import (
    DATASET_CONTRACT_VERSION,
    DECISION_EXCLUSION_REASON_ORDER,
    DECISION_LABELS_CONTRACT,
    DECISION_ROWS_CONTRACT,
    DEVELOPMENT_SEASONS,
    DRY_COMPOUNDS,
    PROTECTED_EVALUATION_SEASON,
    SOURCE_CLEANING_RULE_VERSION,
    SOURCE_PROCESSED_CONTRACT_VERSION,
    DecisionExclusionReason,
    HistoricalAction,
    TableContract,
)
from app.datasets.normalization import (
    NormalizedProcessedSession,
)
from app.pipeline import SessionKey

REQUIRED_DECISION_LAP_COLUMNS = (
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
    "IsEligible",
    "ExclusionReasonCount",
    "ExclusionReasons",
)

REQUIRED_DECISION_PIT_COLUMNS = (
    "pit_event_id",
    "driver",
    "pit_in_lap",
)


class DecisionConstructionError(ValueError):
    """Raised when safe decision-table construction is impossible."""


@dataclass(frozen=True, slots=True)
class DecisionSessionData:
    """Decision rows and separated labels for one race session."""

    session_key: SessionKey
    event_name: str
    decision_rows: pd.DataFrame
    decision_labels: pd.DataFrame


def _require_columns(
    table: pd.DataFrame,
    required_columns: tuple[str, ...],
    *,
    table_name: str,
) -> None:
    """Require every source column used by the decision builder."""
    missing = [
        column
        for column in required_columns
        if column not in table.columns
    ]

    if missing:
        raise DecisionConstructionError(
            f"{table_name} is missing required columns: "
            f"{missing}"
        )


def _validate_session(
    session: NormalizedProcessedSession,
) -> None:
    """Validate the normalized development-session boundary."""
    if not isinstance(
        session,
        NormalizedProcessedSession,
    ):
        raise TypeError(
            "session must be a NormalizedProcessedSession"
        )

    session_key = session.session_key

    if (
        session_key.season
        == PROTECTED_EVALUATION_SEASON
    ):
        raise DecisionConstructionError(
            f"{session_key.identifier} belongs to the "
            "protected evaluation season"
        )

    if (
        session_key.season
        not in DEVELOPMENT_SEASONS
    ):
        raise DecisionConstructionError(
            f"{session_key.identifier} is outside the "
            "development seasons"
        )

    if session_key.session_type != "R":
        raise DecisionConstructionError(
            f"{session_key.identifier} is not a race session"
        )

    _require_columns(
        session.laps,
        REQUIRED_DECISION_LAP_COLUMNS,
        table_name="laps",
    )
    _require_columns(
        session.pit_events,
        REQUIRED_DECISION_PIT_COLUMNS,
        table_name="pit_events",
    )

    if session.laps.empty:
        raise DecisionConstructionError(
            f"{session_key.identifier} contains no laps"
        )


def _nullable_integer(
    value: object,
) -> object:
    """Return one nullable whole-number value."""
    if pd.isna(value):
        return pd.NA

    return int(value)


def _required_float(
    value: object,
    *,
    field_name: str,
    decision_id: str,
) -> float:
    """Return one required finite floating-point value."""
    if pd.isna(value):
        raise DecisionConstructionError(
            f"{decision_id} lacks required "
            f"{field_name}"
        )

    result = float(value)

    if not np.isfinite(result):
        raise DecisionConstructionError(
            f"{decision_id} has non-finite "
            f"{field_name}"
        )

    return result


def _required_boolean(
    value: object,
    *,
    field_name: str,
    decision_id: str,
) -> bool:
    """Return one required boolean without truth coercion."""
    if isinstance(
        value,
        (bool, np.bool_),
    ):
        return bool(value)

    raise DecisionConstructionError(
        f"{decision_id} has invalid "
        f"{field_name}"
    )


def _timedelta_seconds(
    value: object,
    *,
    field_name: str,
    decision_id: str,
) -> float:
    """Convert one required timedelta to seconds."""
    if pd.isna(value):
        raise DecisionConstructionError(
            f"{decision_id} lacks required "
            f"{field_name}"
        )

    try:
        result = (
            pd.Timedelta(value)
            .total_seconds()
        )
    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise DecisionConstructionError(
            f"{decision_id} has invalid "
            f"{field_name}"
        ) from error

    if not np.isfinite(result):
        raise DecisionConstructionError(
            f"{decision_id} has non-finite "
            f"{field_name}"
        )

    return float(result)


def _same_nullable_value(
    left: object,
    right: object,
) -> bool:
    """Compare scalar values with explicit missingness."""
    left_missing = bool(pd.isna(left))
    right_missing = bool(pd.isna(right))

    if left_missing or right_missing:
        return (
            left_missing
            and right_missing
        )

    return bool(left == right)


def _rolling_statistics(
    eligible_lap_times: list[float],
) -> tuple[
    float,
    float,
    float,
    float,
]:
    """Calculate frozen past-only rolling statistics."""
    if len(eligible_lap_times) < 3:
        missing = float("nan")

        return (
            missing,
            missing,
            missing,
            missing,
        )

    latest_three = np.asarray(
        eligible_lap_times[-3:],
        dtype="float64",
    )
    latest_five = np.asarray(
        eligible_lap_times[-5:],
        dtype="float64",
    )

    positions = np.arange(
        len(latest_five),
        dtype="float64",
    )
    centered_positions = (
        positions
        - positions.mean()
    )
    centered_times = (
        latest_five
        - latest_five.mean()
    )

    denominator = float(
        np.square(
            centered_positions
        ).sum()
    )

    if denominator <= 0:
        trend = float("nan")
    else:
        trend = float(
            (
                centered_positions
                * centered_times
            ).sum()
            / denominator
        )

    return (
        float(
            np.median(
                latest_three
            )
        ),
        float(
            np.median(
                latest_five
            )
        ),
        float(
            np.std(
                latest_five,
                ddof=0,
            )
        ),
        trend,
    )


def _pit_event_lookup(
    pit_events: pd.DataFrame,
    *,
    session_key: SessionKey,
) -> dict[
    tuple[str, int],
    str,
]:
    """Index represented pit-in markers by driver and lap."""
    lookup: dict[
        tuple[str, int],
        str,
    ] = {}

    for event in pit_events.itertuples(
        index=False
    ):
        if pd.isna(
            event.pit_in_lap
        ):
            continue

        key = (
            str(event.driver),
            int(event.pit_in_lap),
        )

        if key in lookup:
            raise DecisionConstructionError(
                f"{session_key.identifier} has "
                "multiple pit events for "
                f"{key[0]} lap {key[1]}"
            )

        lookup[key] = str(
            event.pit_event_id
        )

    return lookup


def _cast_to_contract(
    records: list[
        dict[str, object]
    ],
    contract: TableContract,
) -> pd.DataFrame:
    """Create a table with exact contract order and dtypes."""
    column_names = [
        column.name
        for column in contract.columns
    ]

    table = pd.DataFrame(
        records,
        columns=column_names,
    )

    supported_dtypes = {
        "string",
        "int64",
        "Int64",
        "float64",
        "bool",
        "boolean",
    }

    for column in contract.columns:
        if (
            column.pandas_dtype
            not in supported_dtypes
        ):
            raise DecisionConstructionError(
                "unsupported contract dtype "
                f"{column.pandas_dtype} for "
                f"{column.name}"
            )

        try:
            table[column.name] = (
                table[column.name]
                .astype(
                    column.pandas_dtype
                )
            )
        except (
            TypeError,
            ValueError,
            OverflowError,
        ) as error:
            raise DecisionConstructionError(
                f"cannot cast {contract.name}."
                f"{column.name} to "
                f"{column.pandas_dtype}"
            ) from error

        if (
            not column.nullable
            and table[
                column.name
            ].isna().any()
        ):
            raise DecisionConstructionError(
                f"{contract.name}."
                f"{column.name} contains "
                "missing values"
            )

        actual_dtype = str(
            table[
                column.name
            ].dtype
        )

        if (
            actual_dtype
            != column.pandas_dtype
        ):
            raise DecisionConstructionError(
                f"{contract.name}."
                f"{column.name} has dtype "
                f"{actual_dtype}; expected "
                f"{column.pandas_dtype}"
            )

    return table


def _validate_lap_identities(
    laps: pd.DataFrame,
    *,
    session_key: SessionKey,
) -> None:
    """Require one source row per driver and lap number."""
    duplicated = laps.duplicated(
        subset=[
            "Driver",
            "LapNumber",
        ],
        keep=False,
    )

    if duplicated.any():
        examples = (
            laps.loc[
                duplicated,
                [
                    "Driver",
                    "LapNumber",
                ],
            ]
            .head(5)
            .to_dict(
                orient="records"
            )
        )

        raise DecisionConstructionError(
            f"{session_key.identifier} has "
            "duplicate driver-lap identities: "
            f"{examples}"
        )


def _update_past_state(
    row: object,
    *,
    eligible_lap_times: list[
        float
    ],
    stint_lap_counts: dict[
        int,
        int,
    ],
    decision_id: str,
) -> int:
    """Add one completed lap to the past-only state."""
    if _required_boolean(
        row.IsEligible,
        field_name="IsEligible",
        decision_id=decision_id,
    ):
        eligible_lap_times.append(
            _required_float(
                row.LapTimeSeconds,
                field_name=(
                    "LapTimeSeconds"
                ),
                decision_id=decision_id,
            )
        )

    if not pd.isna(row.Stint):
        stint_number = int(
            row.Stint
        )

        stint_lap_counts[
            stint_number
        ] = (
            stint_lap_counts.get(
                stint_number,
                0,
            )
            + 1
        )

    return int(
        not pd.isna(
            row.PitOutTime
        )
    )


def build_session_decisions(
    session: NormalizedProcessedSession,
) -> DecisionSessionData:
    """Build decision rows and labels for one race."""
    _validate_session(session)

    session_key = session.session_key
    session_id = (
        session_key.identifier
    )

    laps = session.laps.copy(
        deep=True
    )
    pit_events = (
        session.pit_events.copy(
            deep=True
        )
    )

    _validate_lap_identities(
        laps,
        session_key=session_key,
    )

    pit_lookup = _pit_event_lookup(
        pit_events,
        session_key=session_key,
    )

    ordered_laps = laps.sort_values(
        [
            "Driver",
            "LapNumber",
            "SourceRowNumber",
        ],
        kind="stable",
    )

    decision_records: list[
        dict[str, object]
    ] = []
    label_records: list[
        dict[str, object]
    ] = []

    for (
        driver,
        driver_laps,
    ) in ordered_laps.groupby(
        "Driver",
        sort=False,
    ):
        rows = list(
            driver_laps.itertuples(
                index=False
            )
        )

        if not rows:
            continue

        eligible_lap_times: list[
            float
        ] = []
        stint_lap_counts: dict[
            int,
            int,
        ] = {}
        completed_pit_stops = 0

        first_row = rows[0]
        first_lap = int(
            first_row.LapNumber
        )
        first_context_id = (
            f"{session_id}-{driver}-"
            f"{first_lap:03d}"
        )

        completed_pit_stops += (
            _update_past_state(
                first_row,
                eligible_lap_times=(
                    eligible_lap_times
                ),
                stint_lap_counts=(
                    stint_lap_counts
                ),
                decision_id=(
                    first_context_id
                ),
            )
        )

        previous = first_row

        for current in rows[1:]:
            decision_lap = int(
                current.LapNumber
            )
            normalized_driver = str(
                driver
            )
            decision_id = (
                f"{session_id}-"
                f"{normalized_driver}-"
                f"{decision_lap:03d}"
            )

            previous_lap = int(
                previous.LapNumber
            )
            has_consecutive_previous_lap = (
                previous_lap
                == decision_lap - 1
            )

            previous_pit_commitment = (
                not pd.isna(
                    previous.PitInTime
                )
            )
            previous_lap_not_pit_commitment = (
                not previous_pit_commitment
            )

            if previous_pit_commitment:
                state_reconstruction_consistent = (
                    True
                )
            else:
                state_reconstruction_consistent = (
                    _same_nullable_value(
                        previous.Compound,
                        current.Compound,
                    )
                    and _same_nullable_value(
                        previous.Stint,
                        current.Stint,
                    )
                )

            current_compound = (
                pd.NA
                if pd.isna(
                    previous.Compound
                )
                else str(
                    previous.Compound
                )
            )
            tyre_age_laps = (
                _nullable_integer(
                    previous.TyreLife
                )
            )
            current_stint_number = (
                _nullable_integer(
                    previous.Stint
                )
            )

            supported_dry_compound = (
                not pd.isna(
                    current_compound
                )
                and str(
                    current_compound
                )
                in DRY_COMPOUNDS
            )
            valid_current_tyre_age = (
                not pd.isna(
                    tyre_age_laps
                )
                and int(
                    tyre_age_laps
                )
                > 0
            )
            current_stint_identified = (
                not pd.isna(
                    current_stint_number
                )
                and int(
                    current_stint_number
                )
                > 0
            )

            if (
                current_stint_identified
            ):
                current_stint_laps_completed: (
                    object
                ) = (
                    stint_lap_counts.get(
                        int(
                            current_stint_number
                        ),
                        0,
                    )
                )
            else:
                current_stint_laps_completed = (
                    pd.NA
                )

            previous_position = (
                _nullable_integer(
                    previous.Position
                )
            )
            previous_position_available = (
                not pd.isna(
                    previous_position
                )
            )

            previous_target_eligible = (
                _required_boolean(
                    previous.IsEligible,
                    field_name=(
                        "IsEligible"
                    ),
                    decision_id=(
                        decision_id
                    ),
                )
            )

            if (
                previous_target_eligible
            ):
                previous_lap_time = (
                    _required_float(
                        previous.LapTimeSeconds,
                        field_name=(
                            "previous "
                            "LapTimeSeconds"
                        ),
                        decision_id=(
                            decision_id
                        ),
                    )
                )
                previous_sector1 = (
                    _required_float(
                        previous.Sector1TimeSeconds,
                        field_name=(
                            "previous "
                            "Sector1TimeSeconds"
                        ),
                        decision_id=(
                            decision_id
                        ),
                    )
                )
                previous_sector2 = (
                    _required_float(
                        previous.Sector2TimeSeconds,
                        field_name=(
                            "previous "
                            "Sector2TimeSeconds"
                        ),
                        decision_id=(
                            decision_id
                        ),
                    )
                )
                previous_sector3 = (
                    _required_float(
                        previous.Sector3TimeSeconds,
                        field_name=(
                            "previous "
                            "Sector3TimeSeconds"
                        ),
                        decision_id=(
                            decision_id
                        ),
                    )
                )
            else:
                previous_lap_time = (
                    float("nan")
                )
                previous_sector1 = (
                    float("nan")
                )
                previous_sector2 = (
                    float("nan")
                )
                previous_sector3 = (
                    float("nan")
                )

            eligible_laps_completed = (
                len(
                    eligible_lap_times
                )
            )
            minimum_history_available = (
                eligible_laps_completed
                >= 3
            )

            (
                rolling_median_3,
                rolling_median_5,
                rolling_std_5,
                rolling_trend_5,
            ) = _rolling_statistics(
                eligible_lap_times
            )

            decision_time_seconds = (
                _timedelta_seconds(
                    current.LapStartTime,
                    field_name=(
                        "LapStartTime"
                    ),
                    decision_id=(
                        decision_id
                    ),
                )
            )
            weather_time_seconds = (
                _timedelta_seconds(
                    current.WeatherObservationTime,
                    field_name=(
                        "WeatherObservationTime"
                    ),
                    decision_id=(
                        decision_id
                    ),
                )
            )
            weather_age_seconds = (
                _required_float(
                    current.WeatherAgeSeconds,
                    field_name=(
                        "WeatherAgeSeconds"
                    ),
                    decision_id=(
                        decision_id
                    ),
                )
            )
            weather_matched = (
                _required_boolean(
                    current.WeatherMatched,
                    field_name=(
                        "WeatherMatched"
                    ),
                    decision_id=(
                        decision_id
                    ),
                )
            )

            weather_available_by_decision = (
                weather_matched
                and weather_time_seconds
                <= decision_time_seconds
                and weather_age_seconds
                >= 0
            )

            rainfall = (
                _required_boolean(
                    current.Rainfall,
                    field_name=(
                        "Rainfall"
                    ),
                    decision_id=(
                        decision_id
                    ),
                )
            )
            dry_at_decision = (
                not rainfall
            )

            previous_track_status = (
                pd.NA
                if pd.isna(
                    previous.TrackStatus
                )
                else str(
                    previous.TrackStatus
                )
            )
            previous_lap_green = (
                not pd.isna(
                    previous_track_status
                )
                and str(
                    previous_track_status
                )
                == "1"
            )

            eligibility_conditions = {
                DecisionExclusionReason.NON_CONSECUTIVE_PREVIOUS_LAP: (
                    has_consecutive_previous_lap
                ),
                DecisionExclusionReason.WEATHER_NOT_AVAILABLE_BY_DECISION: (
                    weather_available_by_decision
                ),
                DecisionExclusionReason.PREVIOUS_LAP_PIT_COMMITMENT: (
                    previous_lap_not_pit_commitment
                ),
                DecisionExclusionReason.STATE_RECONSTRUCTION_CONFLICT: (
                    state_reconstruction_consistent
                ),
                DecisionExclusionReason.UNSUPPORTED_CURRENT_COMPOUND: (
                    supported_dry_compound
                ),
                DecisionExclusionReason.INVALID_CURRENT_TYRE_AGE: (
                    valid_current_tyre_age
                ),
                DecisionExclusionReason.MISSING_CURRENT_STINT: (
                    current_stint_identified
                ),
                DecisionExclusionReason.WET_AT_DECISION: (
                    dry_at_decision
                ),
                DecisionExclusionReason.PREVIOUS_LAP_NOT_GREEN: (
                    previous_lap_green
                ),
                DecisionExclusionReason.INSUFFICIENT_ELIGIBLE_HISTORY: (
                    minimum_history_available
                ),
                DecisionExclusionReason.MISSING_PREVIOUS_POSITION: (
                    previous_position_available
                ),
            }

            exclusion_reasons = [
                reason.value
                for reason in (
                    DECISION_EXCLUSION_REASON_ORDER
                )
                if not (
                    eligibility_conditions[
                        reason
                    ]
                )
            ]
            exclusion_text = "|".join(
                exclusion_reasons
            )
            is_decision_eligible = (
                not exclusion_reasons
            )

            decision_records.append(
                {
                    "decision_id": (
                        decision_id
                    ),
                    "session_id": (
                        session_id
                    ),
                    "season": (
                        session_key.season
                    ),
                    "round_number": (
                        session_key.round_number
                    ),
                    "session_type": (
                        session_key.session_type
                    ),
                    "event_name": (
                        session.event_name
                    ),
                    "driver": (
                        normalized_driver
                    ),
                    "driver_number": str(
                        current.DriverNumber
                    ),
                    "team": str(
                        current.Team
                    ),
                    "decision_lap": (
                        decision_lap
                    ),
                    "decision_time_seconds": (
                        decision_time_seconds
                    ),
                    "source_row_number": int(
                        current.SourceRowNumber
                    ),
                    "dataset_contract_version": (
                        DATASET_CONTRACT_VERSION
                    ),
                    "cleaning_rule_version": (
                        SOURCE_CLEANING_RULE_VERSION
                    ),
                    "processed_contract_version": (
                        SOURCE_PROCESSED_CONTRACT_VERSION
                    ),
                    "current_compound": (
                        current_compound
                    ),
                    "tyre_age_laps": (
                        tyre_age_laps
                    ),
                    "current_stint_number": (
                        current_stint_number
                    ),
                    "current_stint_laps_completed": (
                        current_stint_laps_completed
                    ),
                    "completed_pit_stops": (
                        completed_pit_stops
                    ),
                    "previous_position": (
                        previous_position
                    ),
                    "previous_lap_was_target_eligible": (
                        previous_target_eligible
                    ),
                    "previous_lap_time_seconds": (
                        previous_lap_time
                    ),
                    "previous_sector1_time_seconds": (
                        previous_sector1
                    ),
                    "previous_sector2_time_seconds": (
                        previous_sector2
                    ),
                    "previous_sector3_time_seconds": (
                        previous_sector3
                    ),
                    "eligible_laps_completed": (
                        eligible_laps_completed
                    ),
                    "rolling_lap_time_median_3": (
                        rolling_median_3
                    ),
                    "rolling_lap_time_median_5": (
                        rolling_median_5
                    ),
                    "rolling_lap_time_std_5": (
                        rolling_std_5
                    ),
                    "rolling_lap_time_trend_5": (
                        rolling_trend_5
                    ),
                    "previous_track_status": (
                        previous_track_status
                    ),
                    "weather_observation_time_seconds": (
                        weather_time_seconds
                    ),
                    "weather_age_seconds": (
                        weather_age_seconds
                    ),
                    "air_temperature_celsius": (
                        _required_float(
                            current.AirTemp,
                            field_name=(
                                "AirTemp"
                            ),
                            decision_id=(
                                decision_id
                            ),
                        )
                    ),
                    "humidity_percent": (
                        _required_float(
                            current.Humidity,
                            field_name=(
                                "Humidity"
                            ),
                            decision_id=(
                                decision_id
                            ),
                        )
                    ),
                    "pressure_mbar": (
                        _required_float(
                            current.Pressure,
                            field_name=(
                                "Pressure"
                            ),
                            decision_id=(
                                decision_id
                            ),
                        )
                    ),
                    "track_temperature_celsius": (
                        _required_float(
                            current.TrackTemp,
                            field_name=(
                                "TrackTemp"
                            ),
                            decision_id=(
                                decision_id
                            ),
                        )
                    ),
                    "wind_direction_degrees": int(
                        current.WindDirection
                    ),
                    "wind_speed_mps": (
                        _required_float(
                            current.WindSpeed,
                            field_name=(
                                "WindSpeed"
                            ),
                            decision_id=(
                                decision_id
                            ),
                        )
                    ),
                    "rainfall": (
                        rainfall
                    ),
                    "has_consecutive_previous_lap": (
                        has_consecutive_previous_lap
                    ),
                    "weather_available_by_decision": (
                        weather_available_by_decision
                    ),
                    "previous_lap_not_pit_commitment": (
                        previous_lap_not_pit_commitment
                    ),
                    "state_reconstruction_consistent": (
                        state_reconstruction_consistent
                    ),
                    "supported_dry_compound": (
                        supported_dry_compound
                    ),
                    "valid_current_tyre_age": (
                        valid_current_tyre_age
                    ),
                    "current_stint_identified": (
                        current_stint_identified
                    ),
                    "dry_at_decision": (
                        dry_at_decision
                    ),
                    "previous_lap_green": (
                        previous_lap_green
                    ),
                    "minimum_history_available": (
                        minimum_history_available
                    ),
                    "previous_position_available": (
                        previous_position_available
                    ),
                    "is_decision_eligible": (
                        is_decision_eligible
                    ),
                    "decision_exclusion_count": (
                        len(
                            exclusion_reasons
                        )
                    ),
                    "decision_exclusion_reasons": (
                        exclusion_text
                    ),
                }
            )

            did_pit = not pd.isna(
                current.PitInTime
            )
            pit_key = (
                normalized_driver,
                decision_lap,
            )
            pit_event_id = (
                pit_lookup.get(
                    pit_key
                )
            )

            if (
                did_pit
                and pit_event_id
                is None
            ):
                raise DecisionConstructionError(
                    f"{decision_id} has a "
                    "pit-in marker without a "
                    "reconstructed pit event"
                )

            if (
                not did_pit
                and pit_event_id
                is not None
            ):
                raise DecisionConstructionError(
                    f"{decision_id} has a "
                    "reconstructed pit event "
                    "without a pit-in marker"
                )

            lap_target_eligible = (
                _required_boolean(
                    current.IsEligible,
                    field_name=(
                        "IsEligible"
                    ),
                    decision_id=(
                        decision_id
                    ),
                )
            )

            if lap_target_eligible:
                lap_time_target = (
                    _required_float(
                        current.LapTimeSeconds,
                        field_name=(
                            "LapTimeSeconds"
                        ),
                        decision_id=(
                            decision_id
                        ),
                    )
                )
            else:
                lap_time_target = (
                    float("nan")
                )

            label_records.append(
                {
                    "decision_id": (
                        decision_id
                    ),
                    "session_id": (
                        session_id
                    ),
                    "season": (
                        session_key.season
                    ),
                    "round_number": (
                        session_key.round_number
                    ),
                    "session_type": (
                        session_key.session_type
                    ),
                    "driver": (
                        normalized_driver
                    ),
                    "decision_lap": (
                        decision_lap
                    ),
                    "historical_action": (
                        HistoricalAction.PIT_NOW.value
                        if did_pit
                        else HistoricalAction.STAY_OUT.value
                    ),
                    "did_pit": (
                        did_pit
                    ),
                    "pit_event_id": (
                        pit_event_id
                        if (
                            pit_event_id
                            is not None
                        )
                        else pd.NA
                    ),
                    "is_lap_time_target_eligible": (
                        lap_target_eligible
                    ),
                    "lap_time_target_seconds": (
                        lap_time_target
                    ),
                    "lap_target_exclusion_count": int(
                        current.ExclusionReasonCount
                    ),
                    "lap_target_exclusion_reasons": str(
                        current.ExclusionReasons
                    ),
                    "dataset_contract_version": (
                        DATASET_CONTRACT_VERSION
                    ),
                }
            )

            completed_pit_stops += (
                _update_past_state(
                    current,
                    eligible_lap_times=(
                        eligible_lap_times
                    ),
                    stint_lap_counts=(
                        stint_lap_counts
                    ),
                    decision_id=(
                        decision_id
                    ),
                )
            )
            previous = current

    decision_rows = (
        _cast_to_contract(
            decision_records,
            DECISION_ROWS_CONTRACT,
        )
    )
    decision_labels = (
        _cast_to_contract(
            label_records,
            DECISION_LABELS_CONTRACT,
        )
    )

    if decision_rows[
        "decision_id"
    ].duplicated().any():
        raise DecisionConstructionError(
            f"{session_id} produced "
            "duplicate decision IDs"
        )

    if not decision_rows[
        "decision_id"
    ].equals(
        decision_labels[
            "decision_id"
        ]
    ):
        raise DecisionConstructionError(
            f"{session_id} decision rows "
            "and labels disagree"
        )

    expected_candidates = (
        len(laps)
        - int(
            laps[
                "Driver"
            ].nunique()
        )
    )

    if (
        len(decision_rows)
        != expected_candidates
    ):
        raise DecisionConstructionError(
            f"{session_id} produced "
            f"{len(decision_rows)} candidate "
            "decisions; expected "
            f"{expected_candidates}"
        )

    return DecisionSessionData(
        session_key=session_key,
        event_name=session.event_name,
        decision_rows=decision_rows,
        decision_labels=(
            decision_labels
        ),
    )