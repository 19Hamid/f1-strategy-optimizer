"""Database model for leakage-controlled decision rows."""

from typing import Final

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
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

DECISION_ROW_TABLE_NAME: Final = "decision_rows"

DECISION_ROW_SOURCE_COLUMN_MAP: Final[
    dict[str, str]
] = {
    "decision_id": "decision_id",
    "session_id": "session_id",
    "season": "season",
    "round_number": "round_number",
    "session_type": "session_type",
    "event_name": "event_name",
    "driver": "driver",
    "driver_number": "driver_number",
    "team": "team",
    "decision_lap": "decision_lap",
    "decision_time_seconds": "decision_time_seconds",
    "source_row_number": "source_row_number",
    "dataset_contract_version": (
        "dataset_contract_version"
    ),
    "cleaning_rule_version": "cleaning_rule_version",
    "processed_contract_version": (
        "processed_contract_version"
    ),
    "current_compound": "current_compound",
    "tyre_age_laps": "tyre_age_laps",
    "current_stint_number": "current_stint_number",
    "current_stint_laps_completed": (
        "current_stint_laps_completed"
    ),
    "completed_pit_stops": "completed_pit_stops",
    "previous_position": "previous_position",
    "previous_lap_was_target_eligible": (
        "previous_lap_was_target_eligible"
    ),
    "previous_lap_time_seconds": (
        "previous_lap_time_seconds"
    ),
    "previous_sector1_time_seconds": (
        "previous_sector1_time_seconds"
    ),
    "previous_sector2_time_seconds": (
        "previous_sector2_time_seconds"
    ),
    "previous_sector3_time_seconds": (
        "previous_sector3_time_seconds"
    ),
    "eligible_laps_completed": "eligible_laps_completed",
    "rolling_lap_time_median_3": (
        "rolling_lap_time_median_3"
    ),
    "rolling_lap_time_median_5": (
        "rolling_lap_time_median_5"
    ),
    "rolling_lap_time_std_5": "rolling_lap_time_std_5",
    "rolling_lap_time_trend_5": (
        "rolling_lap_time_trend_5"
    ),
    "previous_track_status": "previous_track_status",
    "weather_observation_time_seconds": (
        "weather_observation_time_seconds"
    ),
    "weather_age_seconds": "weather_age_seconds",
    "air_temperature_celsius": (
        "air_temperature_celsius"
    ),
    "humidity_percent": "humidity_percent",
    "pressure_mbar": "pressure_mbar",
    "track_temperature_celsius": (
        "track_temperature_celsius"
    ),
    "wind_direction_degrees": "wind_direction_degrees",
    "wind_speed_mps": "wind_speed_mps",
    "rainfall": "rainfall",
    "has_consecutive_previous_lap": (
        "has_consecutive_previous_lap"
    ),
    "weather_available_by_decision": (
        "weather_available_by_decision"
    ),
    "previous_lap_not_pit_commitment": (
        "previous_lap_not_pit_commitment"
    ),
    "state_reconstruction_consistent": (
        "state_reconstruction_consistent"
    ),
    "supported_dry_compound": "supported_dry_compound",
    "valid_current_tyre_age": "valid_current_tyre_age",
    "current_stint_identified": "current_stint_identified",
    "dry_at_decision": "dry_at_decision",
    "previous_lap_green": "previous_lap_green",
    "minimum_history_available": (
        "minimum_history_available"
    ),
    "previous_position_available": (
        "previous_position_available"
    ),
    "is_decision_eligible": "is_decision_eligible",
    "decision_exclusion_count": (
        "decision_exclusion_count"
    ),
    "decision_exclusion_reasons": (
        "decision_exclusion_reasons"
    ),
}


def _qualified_table(table_name: str) -> str:
    """Return one schema-qualified table name."""
    return (
        f"{DATABASE_SCHEMA_NAME}."
        f"{table_name}"
    )


class DecisionRow(Base):
    """Preserve one supplied start-of-lap decision state."""

    __tablename__ = DECISION_ROW_TABLE_NAME
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "dataset_contract_version",
                "session_id",
            ],
            [
                (
                    f"{_qualified_table(
                        'dataset_sessions'
                    )}.dataset_contract_version"
                ),
                (
                    f"{_qualified_table(
                        'dataset_sessions'
                    )}.session_id"
                ),
            ],
            ondelete="RESTRICT",
        ),
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
        ForeignKeyConstraint(
            [
                "processed_partition_id",
                "source_row_number",
            ],
            [
                (
                    f"{_qualified_table(
                        'processed_laps'
                    )}.processed_partition_id"
                ),
                (
                    f"{_qualified_table(
                        'processed_laps'
                    )}.source_row_number"
                ),
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "dataset_contract_version",
            "session_id",
            "driver_id",
            "decision_lap",
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
            (
                "decision_id = "
                "session_id || '-' || "
                "driver || '-' || "
                "lpad("
                "decision_lap::text, "
                "3, '0'"
                ")"
            ),
            name="canonical_decision_identity",
        ),
        CheckConstraint(
            "decision_lap >= 2",
            name="decision_lap_positive",
        ),
        CheckConstraint(
            "decision_time_seconds >= 0",
            name="decision_time_non_negative",
        ),
        CheckConstraint(
            "source_row_number >= 0",
            name="source_row_non_negative",
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
                "btrim(cleaning_rule_version)"
                ") > 0"
            ),
            name="cleaning_version_not_blank",
        ),
        CheckConstraint(
            (
                "char_length("
                "btrim(processed_contract_version)"
                ") > 0"
            ),
            name="processed_version_not_blank",
        ),
        CheckConstraint(
            (
                "current_compound IS NULL "
                "OR char_length("
                "btrim(current_compound)"
                ") > 0"
            ),
            name="current_compound_not_blank",
        ),
        CheckConstraint(
            (
                "previous_track_status IS NULL "
                "OR char_length("
                "btrim(previous_track_status)"
                ") > 0"
            ),
            name="previous_track_status_not_blank",
        ),
        CheckConstraint(
            "completed_pit_stops >= 0",
            name="completed_pit_stops_non_negative",
        ),
        CheckConstraint(
            "eligible_laps_completed >= 0",
            name="eligible_laps_non_negative",
        ),
        CheckConstraint(
            (
                "previous_position IS NULL "
                "OR previous_position >= 1"
            ),
            name="previous_position_positive",
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
            (
                "("
                "valid_current_tyre_age "
                "AND tyre_age_laps IS NOT NULL "
                "AND tyre_age_laps > 0"
                ") OR ("
                "NOT valid_current_tyre_age "
                "AND ("
                "tyre_age_laps IS NULL "
                "OR tyre_age_laps <= 0"
                ")"
                ")"
            ),
            name="tyre_age_validity",
        ),
        CheckConstraint(
            (
                "("
                "current_stint_identified "
                "AND current_stint_number IS NOT NULL "
                "AND current_stint_number > 0 "
                "AND current_stint_laps_completed "
                "IS NOT NULL "
                "AND current_stint_laps_completed >= 1"
                ") OR ("
                "NOT current_stint_identified "
                "AND ("
                "current_stint_number IS NULL "
                "OR current_stint_number <= 0"
                ") "
                "AND current_stint_laps_completed IS NULL"
                ")"
            ),
            name="current_stint_availability",
        ),
        CheckConstraint(
            (
                "("
                "previous_position_available "
                "AND previous_position IS NOT NULL"
                ") OR ("
                "NOT previous_position_available "
                "AND previous_position IS NULL"
                ")"
            ),
            name="previous_position_availability",
        ),
        CheckConstraint(
            (
                "minimum_history_available "
                "= (eligible_laps_completed >= 3)"
            ),
            name="minimum_history_balance",
        ),
        CheckConstraint(
            (
                "("
                "minimum_history_available "
                "AND rolling_lap_time_median_3 IS NOT NULL "
                "AND rolling_lap_time_median_3 > 0 "
                "AND rolling_lap_time_median_5 IS NOT NULL "
                "AND rolling_lap_time_median_5 > 0 "
                "AND rolling_lap_time_std_5 IS NOT NULL "
                "AND rolling_lap_time_std_5 >= 0 "
                "AND rolling_lap_time_trend_5 IS NOT NULL"
                ") OR ("
                "NOT minimum_history_available "
                "AND rolling_lap_time_median_3 IS NULL "
                "AND rolling_lap_time_median_5 IS NULL "
                "AND rolling_lap_time_std_5 IS NULL "
                "AND rolling_lap_time_trend_5 IS NULL"
                ")"
            ),
            name="rolling_history_availability",
        ),
        CheckConstraint(
            (
                "("
                "previous_lap_was_target_eligible "
                "AND previous_lap_time_seconds IS NOT NULL "
                "AND previous_lap_time_seconds > 0 "
                "AND previous_sector1_time_seconds IS NOT NULL "
                "AND previous_sector1_time_seconds > 0 "
                "AND previous_sector2_time_seconds IS NOT NULL "
                "AND previous_sector2_time_seconds > 0 "
                "AND previous_sector3_time_seconds IS NOT NULL "
                "AND previous_sector3_time_seconds > 0"
                ") OR ("
                "NOT previous_lap_was_target_eligible "
                "AND previous_lap_time_seconds IS NULL "
                "AND previous_sector1_time_seconds IS NULL "
                "AND previous_sector2_time_seconds IS NULL "
                "AND previous_sector3_time_seconds IS NULL"
                ")"
            ),
            name="previous_target_availability",
        ),
        CheckConstraint(
            (
                "NOT weather_available_by_decision OR ("
                "weather_observation_time_seconds "
                "<= decision_time_seconds "
                "AND weather_age_seconds >= 0"
                ")"
            ),
            name="weather_availability_boundary",
        ),
        CheckConstraint(
            (
                "dry_at_decision = (NOT rainfall)"
            ),
            name="dry_decision_balance",
        ),
        CheckConstraint(
            (
                "("
                "previous_lap_green "
                "AND previous_track_status = '1'"
                ") OR ("
                "NOT previous_lap_green "
                "AND ("
                "previous_track_status IS NULL "
                "OR previous_track_status <> '1'"
                ")"
                ")"
            ),
            name="previous_green_balance",
        ),
        CheckConstraint(
            (
                "("
                "supported_dry_compound "
                "AND current_compound IN ("
                "'HARD', 'MEDIUM', 'SOFT'"
                ")"
                ") OR ("
                "NOT supported_dry_compound "
                "AND ("
                "current_compound IS NULL "
                "OR current_compound NOT IN ("
                "'HARD', 'MEDIUM', 'SOFT'"
                ")"
                ")"
                ")"
            ),
            name="dry_compound_balance",
        ),
        CheckConstraint(
            (
                "is_decision_eligible = ("
                "has_consecutive_previous_lap "
                "AND weather_available_by_decision "
                "AND previous_lap_not_pit_commitment "
                "AND state_reconstruction_consistent "
                "AND supported_dry_compound "
                "AND valid_current_tyre_age "
                "AND current_stint_identified "
                "AND dry_at_decision "
                "AND previous_lap_green "
                "AND minimum_history_available "
                "AND previous_position_available"
                ")"
            ),
            name="eligibility_conditions",
        ),
        CheckConstraint(
            "decision_exclusion_count >= 0",
            name="exclusion_count_non_negative",
        ),
        CheckConstraint(
            (
                "("
                "is_decision_eligible "
                "AND decision_exclusion_count = 0 "
                "AND decision_exclusion_reasons = ''"
                ") OR ("
                "NOT is_decision_eligible "
                "AND decision_exclusion_count > 0 "
                "AND char_length("
                "decision_exclusion_reasons"
                ") > 0"
                ")"
            ),
            name="eligibility_exclusion_balance",
        ),
        Index(
            (
                "ix_decision_rows_"
                "session_driver_lap"
            ),
            "session_id",
            "driver_id",
            "decision_lap",
        ),
        Index(
            "ix_decision_rows_eligible",
            "dataset_contract_version",
            "session_id",
            "decision_lap",
            postgresql_where=text(
                "is_decision_eligible"
            ),
        ),
    )

    processed_partition_id: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    driver_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    dataset_contract_version: Mapped[str] = (
        mapped_column(
            String(32),
            primary_key=True,
        )
    )
    decision_id: Mapped[str] = mapped_column(
        String(96),
        primary_key=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
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
    driver_number: Mapped[str] = mapped_column(
        String(8),
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
    decision_lap: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    decision_time_seconds: Mapped[float] = (
        mapped_column(
            Double,
            nullable=False,
        )
    )
    source_row_number: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    cleaning_rule_version: Mapped[str] = (
        mapped_column(
            String(32),
            nullable=False,
        )
    )
    processed_contract_version: Mapped[str] = (
        mapped_column(
            String(32),
            nullable=False,
        )
    )
    current_compound: Mapped[str | None] = (
        mapped_column(
            String(32),
            nullable=True,
        )
    )
    tyre_age_laps: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
    )
    current_stint_number: Mapped[int | None] = (
        mapped_column(
            SmallInteger,
            nullable=True,
        )
    )
    current_stint_laps_completed: Mapped[
        int | None
    ] = mapped_column(
        BigInteger,
        nullable=True,
    )
    completed_pit_stops: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    previous_position: Mapped[int | None] = (
        mapped_column(
            SmallInteger,
            nullable=True,
        )
    )
    previous_lap_was_target_eligible: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    previous_lap_time_seconds: Mapped[
        float | None
    ] = mapped_column(
        Double,
        nullable=True,
    )
    previous_sector1_time_seconds: Mapped[
        float | None
    ] = mapped_column(
        Double,
        nullable=True,
    )
    previous_sector2_time_seconds: Mapped[
        float | None
    ] = mapped_column(
        Double,
        nullable=True,
    )
    previous_sector3_time_seconds: Mapped[
        float | None
    ] = mapped_column(
        Double,
        nullable=True,
    )
    eligible_laps_completed: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    rolling_lap_time_median_3: Mapped[
        float | None
    ] = mapped_column(
        Double,
        nullable=True,
    )
    rolling_lap_time_median_5: Mapped[
        float | None
    ] = mapped_column(
        Double,
        nullable=True,
    )
    rolling_lap_time_std_5: Mapped[
        float | None
    ] = mapped_column(
        Double,
        nullable=True,
    )
    rolling_lap_time_trend_5: Mapped[
        float | None
    ] = mapped_column(
        Double,
        nullable=True,
    )
    previous_track_status: Mapped[str | None] = (
        mapped_column(
            String(32),
            nullable=True,
        )
    )
    weather_observation_time_seconds: Mapped[float] = (
        mapped_column(
            Double,
            nullable=False,
        )
    )
    weather_age_seconds: Mapped[float] = (
        mapped_column(
            Double,
            nullable=False,
        )
    )
    air_temperature_celsius: Mapped[float] = (
        mapped_column(
            Double,
            nullable=False,
        )
    )
    humidity_percent: Mapped[float] = mapped_column(
        Double,
        nullable=False,
    )
    pressure_mbar: Mapped[float] = mapped_column(
        Double,
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
    wind_speed_mps: Mapped[float] = mapped_column(
        Double,
        nullable=False,
    )
    rainfall: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    has_consecutive_previous_lap: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    weather_available_by_decision: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    previous_lap_not_pit_commitment: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    state_reconstruction_consistent: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    supported_dry_compound: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    valid_current_tyre_age: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    current_stint_identified: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    dry_at_decision: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    previous_lap_green: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    minimum_history_available: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    previous_position_available: Mapped[bool] = (
        mapped_column(
            Boolean,
            nullable=False,
        )
    )
    is_decision_eligible: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    decision_exclusion_count: Mapped[int] = (
        mapped_column(
            BigInteger,
            nullable=False,
        )
    )
    decision_exclusion_reasons: Mapped[str] = (
        mapped_column(
            Text,
            nullable=False,
        )
    )
