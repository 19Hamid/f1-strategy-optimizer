"""Tests for processed-lap database persistence."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.db import (
    DATABASE_SCHEMA_NAME,
    PROCESSED_LAP_SOURCE_COLUMN_MAP,
    PROCESSED_LAP_TABLE_NAME,
    Base,
    ProcessedLap,
)

EXPECTED_SOURCE_COLUMNS = (
    "SourceRowNumber",
    "Season",
    "RoundNumber",
    "SessionType",
    "EventName",
    "Time",
    "Driver",
    "DriverNumber",
    "LapTime",
    "LapNumber",
    "Stint",
    "PitOutTime",
    "PitInTime",
    "Sector1Time",
    "Sector2Time",
    "Sector3Time",
    "Sector1SessionTime",
    "Sector2SessionTime",
    "Sector3SessionTime",
    "SpeedI1",
    "SpeedI2",
    "SpeedFL",
    "SpeedST",
    "IsPersonalBest",
    "Compound",
    "TyreLife",
    "FreshTyre",
    "Team",
    "LapStartTime",
    "LapStartDate",
    "TrackStatus",
    "Position",
    "Deleted",
    "DeletedReason",
    "FastF1Generated",
    "IsAccurate",
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
    "QualityFlags",
    "ExclusionReasons",
    "QualityFlagCount",
    "ExclusionReasonCount",
    "IsEligible",
)


def _table():
    """Return the registered processed-lap table."""
    return Base.metadata.tables[
        (
            f"{DATABASE_SCHEMA_NAME}."
            f"{PROCESSED_LAP_TABLE_NAME}"
        )
    ]


def _check_names() -> set[str]:
    """Return deterministic check names."""
    return {
        str(constraint.name)
        for constraint in _table().constraints
        if isinstance(
            constraint,
            CheckConstraint,
        )
    }


def test_processed_lap_table_is_registered() -> None:
    """The model maps to the frozen table name."""
    assert (
        ProcessedLap.__tablename__
        == "processed_laps"
    )
    assert (
        PROCESSED_LAP_TABLE_NAME
        == "processed_laps"
    )
    assert _table().name == "processed_laps"


def test_source_column_map_is_complete() -> None:
    """All 55 processed source fields map exactly once."""
    assert tuple(
        PROCESSED_LAP_SOURCE_COLUMN_MAP
    ) == EXPECTED_SOURCE_COLUMNS
    assert (
        len(PROCESSED_LAP_SOURCE_COLUMN_MAP)
        == 55
    )
    assert (
        len(
            set(
                PROCESSED_LAP_SOURCE_COLUMN_MAP.values()
            )
        )
        == 55
    )


def test_every_source_mapping_targets_a_column() -> None:
    """No source field maps to an imaginary database column."""
    database_columns = set(
        _table().columns.keys()
    )

    assert set(
        PROCESSED_LAP_SOURCE_COLUMN_MAP.values()
    ) <= database_columns
    assert len(database_columns) == 58


def test_processed_lap_primary_key_is_exact() -> None:
    """Partition and source-row identity form the key."""
    assert tuple(
        column.name
        for column in _table().primary_key.columns
    ) == (
        "processed_partition_id",
        "source_row_number",
    )


def test_processed_lap_natural_identity_is_unique() -> None:
    """A driver cannot have duplicate laps in a partition."""
    unique_column_sets = {
        tuple(
            column.name
            for column in constraint.columns
        )
        for constraint in _table().constraints
        if isinstance(
            constraint,
            UniqueConstraint,
        )
    }

    assert (
        "processed_partition_id",
        "driver_id",
        "lap_number",
    ) in unique_column_sets


def test_processed_lap_foreign_keys_are_exact() -> None:
    """Lap rows reference provenance and participation."""
    targets = {
        foreign_key.target_fullname
        for foreign_key in _table().foreign_keys
    }

    assert targets == {
        (
            "f1_strategy.drivers."
            "driver_code"
        ),
        (
            "f1_strategy."
            "processed_session_partitions."
            "processed_partition_id"
        ),
        (
            "f1_strategy."
            "processed_session_partitions."
            "session_id"
        ),
        (
            "f1_strategy."
            "session_participants."
            "driver_id"
        ),
        (
            "f1_strategy."
            "session_participants."
            "session_id"
        ),
        (
            "f1_strategy.teams."
            "team_name"
        ),
    }

    composite_foreign_keys = {
        tuple(
            element.parent.name
            for element in constraint.elements
        )
        for constraint in _table().constraints
        if isinstance(
            constraint,
            ForeignKeyConstraint,
        )
    }

    assert (
        "processed_partition_id",
        "session_id",
    ) in composite_foreign_keys
    assert (
        "session_id",
        "driver_id",
    ) in composite_foreign_keys


def test_elapsed_durations_use_integer_nanoseconds() -> None:
    """Source timedelta values retain exact resolution."""
    duration_columns = (
        "session_time_nanoseconds",
        "lap_time_nanoseconds",
        "pit_out_time_nanoseconds",
        "pit_in_time_nanoseconds",
        "sector1_time_nanoseconds",
        "sector2_time_nanoseconds",
        "sector3_time_nanoseconds",
        (
            "sector1_session_"
            "time_nanoseconds"
        ),
        (
            "sector2_session_"
            "time_nanoseconds"
        ),
        (
            "sector3_session_"
            "time_nanoseconds"
        ),
        "lap_start_time_nanoseconds",
        (
            "weather_observation_"
            "time_nanoseconds"
        ),
    )

    for column_name in duration_columns:
        assert isinstance(
            _table().c[column_name].type,
            BigInteger,
        )


def test_lap_start_date_requires_timezone() -> None:
    """A future wall-clock lap timestamp uses UTC-aware storage."""
    column = _table().c.lap_start_date_utc

    assert isinstance(column.type, DateTime)
    assert column.type.timezone is True
    assert column.nullable is True


def test_leakage_and_eligibility_checks_exist() -> None:
    """Weather and cleaning boundaries fail closed."""
    required = {
        (
            "ck_processed_laps_"
            "canonical_session_identity"
        ),
        (
            "ck_processed_laps_"
            "weather_not_from_future"
        ),
        (
            "ck_processed_laps_"
            "weather_age_non_negative"
        ),
        (
            "ck_processed_laps_"
            "eligibility_exclusion_balance"
        ),
        (
            "ck_processed_laps_"
            "lap_time_positive"
        ),
    }

    assert required <= _check_names()


def test_processed_lap_indexes_cover_access_paths() -> None:
    """Driver-lap and eligibility queries are indexed."""
    index_names = {
        str(index.name)
        for index in _table().indexes
        if isinstance(index, Index)
    }

    assert index_names == {
        "ix_processed_laps_eligible",
        (
            "ix_processed_laps_"
            "session_driver_lap"
        ),
        (
            "ix_processed_laps_"
            "session_team"
        ),
    }

    eligible_index = next(
        index
        for index in _table().indexes
        if index.name
        == "ix_processed_laps_eligible"
    )

    assert (
        eligible_index.dialect_options[
            "postgresql"
        ]["where"]
        is not None
    )


def test_processed_lap_compiles_for_postgresql() -> None:
    """The complete lap table produces PostgreSQL DDL."""
    ddl = str(
        CreateTable(
            _table()
        ).compile(
            dialect=postgresql.dialect()
        )
    )

    assert "CREATE TABLE" in ddl
    assert (
        "f1_strategy.processed_laps"
        in ddl
    )
    assert "BIGINT" in ddl
    assert (
        "TIMESTAMP WITH TIME ZONE"
        in ddl
    )
    assert (
        "weather_observation_time_nanoseconds "
        "<= lap_start_time_nanoseconds"
        in ddl
    )
    assert (
        "REFERENCES "
        "f1_strategy."
        "processed_session_partitions"
        in ddl
    )