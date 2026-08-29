"""Check detailed FastF1 telemetry availability for one representative lap."""

from pathlib import Path

import fastf1

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIRECTORY = PROJECT_ROOT / "data" / "cache" / "fastf1"

YEAR = 2024
ROUND_NUMBER = 1

REQUIRED_TELEMETRY_COLUMNS = [
    "Time",
    "Distance",
    "RPM",
    "Speed",
    "nGear",
    "Throttle",
    "Brake",
    "DRS",
    "X",
    "Y",
    "Z",
]


def main() -> None:
    """Load a representative lap and inspect its telemetry channels."""
    CACHE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(CACHE_DIRECTORY))

    print(f"Loading telemetry for {YEAR} round {ROUND_NUMBER}...")

    session = fastf1.get_session(YEAR, ROUND_NUMBER, "R")
    session.load(telemetry=True, weather=False, messages=False)

    fastest_lap = session.laps.pick_fastest()

    if fastest_lap is None:
        print("TELEMETRY CHECK FAILED: no fastest lap was found")
        raise SystemExit(1)

    telemetry = fastest_lap.get_telemetry()
    missing_columns = [
        column
        for column in REQUIRED_TELEMETRY_COLUMNS
        if column not in telemetry.columns
    ]

    print(f"\nEvent: {YEAR} {session.event['EventName']}")
    print(f"Driver: {fastest_lap['Driver']}")
    print(f"Lap number: {int(fastest_lap['LapNumber'])}")
    print(f"Lap time: {fastest_lap['LapTime']}")
    print(f"Telemetry samples: {len(telemetry)}")

    print("\nTelemetry field coverage:")

    for column in REQUIRED_TELEMETRY_COLUMNS:
        if column not in telemetry.columns:
            print(f"  [MISSING] {column}")
            continue

        non_null = int(telemetry[column].notna().sum())
        data_type = str(telemetry[column].dtype)
        print(
            f"  [OK] {column:<10} "
            f"{non_null}/{len(telemetry)} non-null "
            f"({data_type})"
        )

    if "Time" in telemetry.columns and len(telemetry) > 1:
        intervals = (
            telemetry["Time"]
            .diff()
            .dropna()
            .dt.total_seconds()
        )
        median_interval = float(intervals.median())
        print(f"\nMedian sampling interval: {median_interval:.3f} seconds")

    if "Distance" in telemetry.columns:
        maximum_distance = float(telemetry["Distance"].max())
        print(f"Maximum recorded distance: {maximum_distance:.1f} metres")

    if "Speed" in telemetry.columns:
        minimum_speed = float(telemetry["Speed"].min())
        maximum_speed = float(telemetry["Speed"].max())
        print(f"Speed range: {minimum_speed:.1f}–{maximum_speed:.1f} km/h")

    if "Throttle" in telemetry.columns:
        minimum_throttle = float(telemetry["Throttle"].min())
        maximum_throttle = float(telemetry["Throttle"].max())
        print(
            f"Throttle range: "
            f"{minimum_throttle:.1f}–{maximum_throttle:.1f}%"
        )

    if telemetry.empty or missing_columns:
        print(f"\nMissing telemetry fields: {missing_columns}")
        print("TELEMETRY CHECK FAILED")
        raise SystemExit(1)

    print("\nTELEMETRY CHECK PASSED")
    print("Detailed car and position telemetry is available.")


if __name__ == "__main__":
    main()