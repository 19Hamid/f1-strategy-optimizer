"""Check FastF1 data-field consistency across multiple seasons."""

from pathlib import Path

import fastf1

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIRECTORY = PROJECT_ROOT / "data" / "cache" / "fastf1"

SESSIONS = [
    (2022, 1),
    (2023, 10),
    (2024, 1),
    (2025, 3),
]

REQUIRED_LAP_COLUMNS = [
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
]

REQUIRED_WEATHER_COLUMNS = [
    "Time",
    "AirTemp",
    "TrackTemp",
    "Humidity",
    "Pressure",
    "Rainfall",
    "WindDirection",
    "WindSpeed",
]


def inspect_session(
    year: int,
    round_number: int,
    data_types: dict[str, set[str]],
) -> bool:
    """Load one race and check the required fields."""
    print(f"\nLoading {year} round {round_number}...")

    session = fastf1.get_session(year, round_number, "R")
    session.load(telemetry=False, weather=True, messages=False)

    laps = session.laps
    weather = session.weather_data
    event_name = str(session.event["EventName"])

    missing_lap_columns = [
        column for column in REQUIRED_LAP_COLUMNS if column not in laps.columns
    ]
    missing_weather_columns = [
        column
        for column in REQUIRED_WEATHER_COLUMNS
        if column not in weather.columns
    ]

    for column in REQUIRED_LAP_COLUMNS:
        if column in laps.columns:
            data_types[column].add(str(laps[column].dtype))

    compounds = sorted(
        str(compound) for compound in laps["Compound"].dropna().unique()
    )
    rainfall_recorded = bool(weather["Rainfall"].eq(True).any())
    missing_lap_times = int(laps["LapTime"].isna().sum())
    pit_entries = int(laps["PitInTime"].notna().sum())

    passed = not missing_lap_columns and not missing_weather_columns
    result = "PASS" if passed else "FAIL"

    print(f"[{result}] {year} {event_name}")
    print(f"  Drivers: {laps['Driver'].nunique()}")
    print(f"  Laps: {len(laps)}")
    print(f"  Missing lap times: {missing_lap_times}")
    print(f"  Pit entries: {pit_entries}")
    print(f"  Compounds: {', '.join(compounds)}")
    print(f"  Rainfall recorded: {rainfall_recorded}")

    if missing_lap_columns:
        print(f"  Missing lap fields: {missing_lap_columns}")

    if missing_weather_columns:
        print(f"  Missing weather fields: {missing_weather_columns}")

    return passed


def main() -> None:
    """Run the coverage check across the selected races."""
    CACHE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(CACHE_DIRECTORY))

    data_types = {
        column: set() for column in REQUIRED_LAP_COLUMNS
    }
    failed_sessions = []

    for year, round_number in SESSIONS:
        passed = inspect_session(year, round_number, data_types)

        if not passed:
            failed_sessions.append((year, round_number))

    print("\nObserved lap-field data types:")

    for column, observed_types in data_types.items():
        formatted_types = ", ".join(sorted(observed_types))
        print(f"  {column:<16} {formatted_types}")

    if failed_sessions:
        print(f"\nFailed sessions: {failed_sessions}")
        print("MULTI-SEASON COVERAGE CHECK FAILED")
        raise SystemExit(1)

    print("\nMULTI-SEASON COVERAGE CHECK PASSED")


if __name__ == "__main__":
    main()