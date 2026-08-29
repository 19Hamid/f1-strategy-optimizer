"""Required schemas for raw Formula 1 session tables."""

from dataclasses import dataclass

from app.pipeline.source import PROVENANCE_COLUMNS


@dataclass(frozen=True, slots=True)
class TableContract:
    """Describe the required structure of one raw table."""

    name: str
    required_columns: frozenset[str]


PROVENANCE_COLUMN_SET = frozenset(PROVENANCE_COLUMNS)

LAPS_CONTRACT = TableContract(
    name="laps",
    required_columns=PROVENANCE_COLUMN_SET
    | frozenset(
        {
            "Driver",
            "Team",
            "LapNumber",
            "LapTime",
            "Stint",
            "Compound",
            "TyreLife",
            "PitInTime",
            "PitOutTime",
            "TrackStatus",
            "LapStartTime",
        }
    ),
)

WEATHER_CONTRACT = TableContract(
    name="weather",
    required_columns=PROVENANCE_COLUMN_SET
    | frozenset(
        {
            "Time",
            "AirTemp",
            "TrackTemp",
            "Humidity",
            "Pressure",
            "Rainfall",
            "WindDirection",
            "WindSpeed",
        }
    ),
)

RESULTS_CONTRACT = TableContract(
    name="results",
    required_columns=PROVENANCE_COLUMN_SET
    | frozenset(
        {
            "Abbreviation",
            "TeamName",
            "Position",
            "ClassifiedPosition",
            "GridPosition",
            "Status",
            "Points",
        }
    ),
)

RAW_TABLE_CONTRACTS = (
    LAPS_CONTRACT,
    WEATHER_CONTRACT,
    RESULTS_CONTRACT,
)