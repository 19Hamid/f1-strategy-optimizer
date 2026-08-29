"""Check whether FastF1 provides the data required by the project."""

from pathlib import Path

import fastf1

YEAR = 2024
ROUND_NUMBER = 1
SESSION_TYPE = "R"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIRECTORY = PROJECT_ROOT / "data" / "cache" / "fastf1"


def print_coverage(name: str, frame, columns: list[str]) -> list[str]:
    """Print column availability and return any missing columns."""
    print(f"\n{name}:")

    missing = []

    for column in columns:
        if column not in frame.columns:
            print(f"  [MISSING] {column}")
            missing.append(column)
            continue

        non_null = int(frame[column].notna().sum())
        print(f"  [OK] {column:<16} {non_null}/{len(frame)} non-null")

    return missing


def main() -> None:
    """Load one race and report the available strategy data."""
    CACHE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(CACHE_DIRECTORY))

    print(f"Loading round {ROUND_NUMBER} of the {YEAR} season...")

    session = fastf1.get_session(YEAR, ROUND_NUMBER, SESSION_TYPE)
    session.load(telemetry=False, weather=True, messages=False)

    laps = session.laps
    weather = session.weather_data

    required_lap_columns = [
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

    useful_lap_columns = [
        "Sector1Time",
        "Sector2Time",
        "Sector3Time",
        "Position",
        "FreshTyre",
        "IsAccurate",
    ]

    weather_columns = [
        "Time",
        "AirTemp",
        "TrackTemp",
        "Humidity",
        "Pressure",
        "Rainfall",
        "WindDirection",
        "WindSpeed",
    ]

    print(f"\nSession: {YEAR} {session.event['EventName']}")
    print(f"Drivers: {laps['Driver'].nunique()}")
    print(f"Recorded laps: {len(laps)}")
    print(f"Recorded pit entries: {int(laps['PitInTime'].notna().sum())}")

    compounds = sorted(laps["Compound"].dropna().unique().tolist())
    print(f"Tyre compounds: {', '.join(compounds)}")

    missing_required = print_coverage(
        "Required lap fields",
        laps,
        required_lap_columns,
    )

    print_coverage(
        "Additional useful lap fields",
        laps,
        useful_lap_columns,
    )

    missing_weather = print_coverage(
        "Weather fields",
        weather,
        weather_columns,
    )

    rainfall_recorded = (
        bool(weather["Rainfall"].eq(True).any())
        if "Rainfall" in weather.columns
        else "unknown"
    )
    print(f"\nRainfall recorded: {rainfall_recorded}")

    if missing_required or missing_weather:
        print("\nFEASIBILITY CHECK FAILED")
        print(f"Missing required lap fields: {missing_required}")
        print(f"Missing weather fields: {missing_weather}")
        raise SystemExit(1)

    print("\nFEASIBILITY CHECK PASSED")
    print("FastF1 provides the core lap, tyre, pit-stop and weather data.")


if __name__ == "__main__":
    main()