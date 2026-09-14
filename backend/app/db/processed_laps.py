"""Database model for normalized processed laps."""

from datetime import datetime
from typing import Final

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    DATABASE_SCHEMA_NAME,
    Base,
)

PROCESSED_LAP_TABLE_NAME: Final = (
    "processed_laps"
)

PROCESSED_LAP_SOURCE_COLUMN_MAP: Final[
    dict[str, str]
] = {
    "SourceRowNumber": "source_row_number",
    "Season": "season",
    "RoundNumber": "round_number",
    "SessionType": "session_type",
    "EventName": "event_name",
    "Time": "session_time_nanoseconds",
    "Driver": "driver",
    "DriverNumber": "driver_number",
    "LapTime": "lap_time_nanoseconds",
    "LapNumber": "lap_number",
    "Stint": "stint_number",
    "PitOutTime": "pit_out_time_nanoseconds",
    "PitInTime": "pit_in_time_nanoseconds",
    "Sector1Time": "sector1_time_nanoseconds",
    "Sector2Time": "sector2_time_nanoseconds",
    "Sector3Time": "sector3_time_nanoseconds",
    "Sector1SessionTime": (
        "sector1_session_time_nanoseconds"
    ),
    "Sector2SessionTime": (
        "sector2_session_time_nanoseconds"
    ),
    "Sector3SessionTime": (
        "sector3_session_time_nanoseconds"
    ),
    "SpeedI1": "speed_i1",
    "SpeedI2": "speed_i2",
    "SpeedFL": "speed_finish_line",
    "SpeedST": "speed_trap",
    "IsPersonalBest": "is_personal_best",
    "Compound": "compound",
    "TyreLife": "tyre_life",
    "FreshTyre": "fresh_tyre",
    "Team": "team",
    "LapStartTime": (
        "lap_start_time_nanoseconds"
    ),
    "LapStartDate": "lap_start_date_utc",
    "TrackStatus": "track_status",
    "Position": "position",
    "Deleted": "deleted",
    "DeletedReason": "deleted_reason",
    "FastF1Generated": "fastf1_generated",
    "IsAccurate": "is_accurate",
    "WeatherObservationTime": (
        "weather_observation_time_nanoseconds"
    ),
    "AirTemp": "air_temperature_celsius",
    "Humidity": "humidity_percent",
    "Pressure": "pressure_mbar",
    "Rainfall": "rainfall",
    "TrackTemp": "track_temperature_celsius",
    "WindDirection": "wind_direction_degrees",
    "WindSpeed": "wind_speed_mps",
    "WeatherMatched": "weather_matched",
    "WeatherAgeSeconds": "weather_age_seconds",
    "LapTimeSeconds": "lap_time_seconds",
    "Sector1TimeSeconds": (
        "sector1_time_seconds"
    ),
    "Sector2TimeSeconds": (
        "sector2_time_seconds"
    ),
    "Sector3TimeSeconds": (
        "sector3_time_seconds"
    ),
    "QualityFlags": "quality_flags",
    "ExclusionReasons": "exclusion_reasons",
    "QualityFlagCount": "quality_flag_count",
    "ExclusionReasonCount": (
        "exclusion_reason_count"
    ),
    "IsEligible": "is_eligible",
}


def _qualified_table(table_name: str) -> str:
    """Return one schema-qualified table name."""
    return (
        f"{DATABASE_SCHEMA_NAME}."
        f"{table_name}"
    )


class ProcessedLap(Base):
    """Preserve one normalized processed driver lap."""

    __tablename__ = PROCESSED_LAP_TABLE_NAME
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "processed_partition_id",
                "session_id",
            ],
            [
                (
                    f"{_qualified_table(
                        'processed_session_partitions'
                    )}.processed_partition_id"
                ),
                (
                    f"{_qualified_table(
                        'processed_session_partitions'
                    )}.session_id"
                ),
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "session_id",
                "driver_id",
            ],
            [
                (
                    f"{_qualified_table(
                        'session_participants'
                    )}.session_id"
                ),
                (
                    f"{_qualified_table(
                        'session_participants'
                    )}.driver_id"
                ),
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "processed_partition_id",
            "driver_id",
            "lap_number",
        ),
        CheckConstraint(
            "source_row_number >= 0",
            name="source_row_non_negative",
        ),
        CheckConstraint(
            (
                "round_number "
                "BETWEEN 1 AND 30"
            ),
            name="round_number_range",
        ),
        CheckConstraint(
            "session_type = 'R'",
            name="race_session_only",
        ),
        CheckConstraint(
            (
                "session_id = "
                "season::text || '-' || "
                "lpad("
                "round_number::text, "
                "2, '0'"
                ") || '-' || "
                "session_type"
            ),
            name="canonical_session_identity",
        ),
        CheckConstraint(
            "lap_number >= 1",
            name="lap_number_positive",
        ),
        CheckConstraint(
            "stint_number >= 1",
            name="stint_number_positive",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(event_name)"
                ") > 0"
            ),
            name="event_name_not_blank",
        ),
        CheckConstraint(
            (
                "driver = "
                "upper(btrim(driver))"
            ),
            name="driver_normalized",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(driver_number)"
                ") > 0"
            ),
            name="driver_number_not_blank",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(team)"
                ") > 0"
            ),
            name="team_not_blank",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(compound)"
                ") > 0"
            ),
            name="compound_not_blank",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(track_status)"
                ") > 0"
            ),
            name="track_status_not_blank",
        ),
        CheckConstraint(
            (
                "tyre_life IS NULL "
                "OR tyre_life >= 0"
            ),
            name="tyre_life_non_negative",
        ),
        CheckConstraint(
            (
                "position IS NULL "
                "OR position >= 1"
            ),
            name="position_positive",
        ),
        CheckConstraint(
            (
                "speed_i1 IS NULL "
                "OR speed_i1 >= 0"
            ),
            name="speed_i1_non_negative",
        ),
        CheckConstraint(
            (
                "speed_i2 IS NULL "
                "OR speed_i2 >= 0"
            ),
            name="speed_i2_non_negative",
        ),
        CheckConstraint(
            (
                "speed_finish_line IS NULL "
                "OR speed_finish_line >= 0"
            ),
            name="speed_finish_line_non_negative",
        ),
        CheckConstraint(
            (
                "speed_trap IS NULL "
                "OR speed_trap >= 0"
            ),
            name="speed_trap_non_negative",
        ),
        CheckConstraint(
            (
                "humidity_percent "
                "BETWEEN 0 AND 100"
            ),
            name="humidity_range",
        ),
        CheckConstraint(
            "pressure_mbar > 0",
            name="pressure_positive",
        ),
        CheckConstraint(
            (
                "wind_direction_degrees "
                "BETWEEN 0 AND 360"
            ),
            name="wind_direction_range",
        ),
        CheckConstraint(
            "wind_speed_mps >= 0",
            name="wind_speed_non_negative",
        ),
        CheckConstraint(
            "weather_age_seconds >= 0",
            name="weather_age_non_negative",
        ),
        CheckConstraint(
            (
                "weather_observation_time_nanoseconds "
                "<= lap_start_time_nanoseconds"
            ),
            name="weather_not_from_future",
        ),
        CheckConstraint(
            (
                "lap_time_seconds IS NULL "
                "OR lap_time_seconds > 0"
            ),
            name="lap_time_positive",
        ),
        CheckConstraint(
            (
                "sector1_time_seconds IS NULL "
                "OR sector1_time_seconds > 0"
            ),
            name="sector1_time_positive",
        ),
        CheckConstraint(
            (
                "sector2_time_seconds IS NULL "
                "OR sector2_time_seconds > 0"
            ),
            name="sector2_time_positive",
        ),
        CheckConstraint(
            (
                "sector3_time_seconds IS NULL "
                "OR sector3_time_seconds > 0"
            ),
            name="sector3_time_positive",
        ),
        CheckConstraint(
            "quality_flag_count >= 0",
            name="quality_count_non_negative",
        ),
        CheckConstraint(
            "exclusion_reason_count >= 0",
            name="exclusion_count_non_negative",
        ),
        CheckConstraint(
            (
                "("
                "is_eligible "
                "AND exclusion_reason_count = 0"
                ") OR ("
                "NOT is_eligible "
                "AND exclusion_reason_count > 0"
                ")"
            ),
            name="eligibility_exclusion_balance",
        ),
        Index(
            (
                "ix_processed_laps_"
                "session_driver_lap"
            ),
            "session_id",
            "driver_id",
            "lap_number",
        ),
        Index(
            (
                "ix_processed_laps_"
                "session_team"
            ),
            "session_id",
            "team",
        ),
        Index(
            "ix_processed_laps_eligible",
            "processed_partition_id",
            "source_row_number",
            postgresql_where=text(
                "is_eligible"
            ),
        ),
    )

    processed_partition_id: Mapped[int] = (
        mapped_column(
            BigInteger,
            primary_key=True,
        )
    )
    session_id: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    driver_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    source_row_number: Mapped[int] = (
        mapped_column(
            BigInteger,
            primary_key=True,
        )
    )
    season: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    round_number: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    session_type: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
    )
    event_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    session_time_nanoseconds: Mapped[
        int | None
    ] = mapped_column(
        BigInteger,
        nullable=True,
    )
    driver: Mapped[str] = mapped_column(
        String(16),
        ForeignKey(
            (
                f"{_qualified_table('drivers')}"
                ".driver_code"
            ),
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    driver_number: Mapped[str] = (
        mapped_column(
            String(8),
            nullable=False,
        )
    )
    lap_time_nanoseconds: Mapped[
        int | None
    ] = mapped_column(
        BigInteger,
        nullable=True,
    )
    lap_number: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    stint_number: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    pit_out_time_nanoseconds: Mapped[
        int | None
    ] = mapped_column(
        BigInteger,
        nullable=True,
    )
    pit_in_time_nanoseconds: Mapped[
        int | None
    ] = mapped_column(
        BigInteger,
        nullable=True,
    )
    sector1_time_nanoseconds: Mapped[
        int | None
    ] = mapped_column(
        BigInteger,
        nullable=True,
    )
    sector2_time_nanoseconds: Mapped[
        int | None
    ] = mapped_column(
        BigInteger,
        nullable=True,
    )
    sector3_time_nanoseconds: Mapped[
        int | None
    ] = mapped_column(
        BigInteger,
        nullable=True,
    )
    sector1_session_time_nanoseconds: Mapped[
        int | None
    ] = mapped_column(
        BigInteger,
        nullable=True,
    )
    sector2_session_time_nanoseconds: Mapped[
        int | None
    ] = mapped_column(
        BigInteger,
        nullable=True,
    )
    sector3_session_time_nanoseconds: Mapped[
        int | None
    ] = mapped_column(
        BigInteger,
        nullable=True,
    )
    speed_i1: Mapped[float | None] = (
        mapped_column(
            Double,
            nullable=True,
        )
    )
    speed_i2: Mapped[float | None] = (
        mapped_column(
            Double,
            nullable=True,
        )
    )
    speed_finish_line: Mapped[
        float | None
    ] = mapped_column(
        Double,
        nullable=True,
    )
    speed_trap: Mapped[float | None] = (
        mapped_column(
            Double,
            nullable=True,
        )
    )
    is_personal_best: Mapped[
        bool | None
    ] = mapped_column(
        Boolean,
        nullable=True,
    )
    compound: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    tyre_life: Mapped[float | None] = (
        mapped_column(
            Double,
            nullable=True,
        )
    )
    fresh_tyre: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    team: Mapped[str] = mapped_column(
        String(200),
        ForeignKey(
            (
                f"{_qualified_table('teams')}"
                ".team_name"
            ),
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    lap_start_time_nanoseconds: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    lap_start_date_utc: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    track_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    position: Mapped[int | None] = (
        mapped_column(
            SmallInteger,
            nullable=True,
        )
    )
    deleted: Mapped[bool | None] = (
        mapped_column(
            Boolean,
            nullable=True,
        )
    )
    deleted_reason: Mapped[str | None] = (
        mapped_column(
            Text,
            nullable=True,
        )
    )
    fastf1_generated: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    is_accurate: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    weather_observation_time_nanoseconds: Mapped[
        int
    ] = mapped_column(
        BigInteger,
        nullable=False,
    )
    air_temperature_celsius: Mapped[float] = (
        mapped_column(
            Double,
            nullable=False,
        )
    )
    humidity_percent: Mapped[float] = (
        mapped_column(
            Double,
            nullable=False,
        )
    )
    pressure_mbar: Mapped[float] = (
        mapped_column(
            Double,
            nullable=False,
        )
    )
    rainfall: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    track_temperature_celsius: Mapped[float] = (
        mapped_column(
            Double,
            nullable=False,
        )
    )
    wind_direction_degrees: Mapped[int] = (
        mapped_column(
            SmallInteger,
            nullable=False,
        )
    )
    wind_speed_mps: Mapped[float] = (
        mapped_column(
            Double,
            nullable=False,
        )
    )
    weather_matched: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    weather_age_seconds: Mapped[float] = (
        mapped_column(
            Double,
            nullable=False,
        )
    )
    lap_time_seconds: Mapped[
        float | None
    ] = mapped_column(
        Double,
        nullable=True,
    )
    sector1_time_seconds: Mapped[
        float | None
    ] = mapped_column(
        Double,
        nullable=True,
    )
    sector2_time_seconds: Mapped[
        float | None
    ] = mapped_column(
        Double,
        nullable=True,
    )
    sector3_time_seconds: Mapped[
        float | None
    ] = mapped_column(
        Double,
        nullable=True,
    )
    quality_flags: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    exclusion_reasons: Mapped[str] = (
        mapped_column(
            Text,
            nullable=False,
        )
    )
    quality_flag_count: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    exclusion_reason_count: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    is_eligible: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )