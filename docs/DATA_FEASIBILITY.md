# F1 Race Strategy Optimizer — Data Feasibility Report

## Purpose

This investigation checks whether publicly available Formula 1 data contains
the information required to build the tyre model, race simulator and
pit-decision optimizer.

## Test environment

- Test date: 2026-08-29
- Data source: FastF1
- FastF1 version: 3.8.3
- Python version: 3.14.4
- pandas version: 2.3.3
- NumPy version: 2.5.2
- Event: 2024 Bahrain Grand Prix
- Session: Race
- Telemetry loading: Disabled
- Weather loading: Enabled

## Reproduction

From the `backend` directory, run
`uv run python ../scripts/check_fastf1_data.py`.

FastF1 caching is enabled under `data/cache/fastf1`.

## Session summary

| Measurement | Result |
|---|---:|
| Drivers | 20 |
| Recorded laps | 1,129 |
| Recorded pit entries | 43 |
| Recorded pit exits | 43 |
| Weather observations | 157 |
| Tyre compounds used | Hard and Soft |
| Rainfall recorded | No |

## Required lap-field availability

| Field | Non-null | Total | Result |
|---|---:|---:|---|
| Driver | 1,129 | 1,129 | Available |
| Team | 1,129 | 1,129 | Available |
| LapNumber | 1,129 | 1,129 | Available |
| LapTime | 1,127 | 1,129 | Available with 2 missing values |
| Stint | 1,129 | 1,129 | Available |
| Compound | 1,129 | 1,129 | Available |
| TyreLife | 1,129 | 1,129 | Available |
| PitInTime | 43 | 1,129 | Available on pit-entry laps |
| PitOutTime | 43 | 1,129 | Available on pit-exit laps |
| TrackStatus | 1,129 | 1,129 | Available |
| LapStartTime | 1,129 | 1,129 | Available |

## Additional useful lap fields

| Field | Non-null | Total | Result |
|---|---:|---:|---|
| Sector1Time | 1,108 | 1,129 | Available with missing values |
| Sector2Time | 1,129 | 1,129 | Available |
| Sector3Time | 1,129 | 1,129 | Available |
| Position | 1,129 | 1,129 | Available |
| FreshTyre | 1,129 | 1,129 | Available |
| IsAccurate | 1,129 | 1,129 | Available |

## Weather availability

All 157 weather observations contained:

- Session time
- Air temperature
- Track temperature
- Humidity
- Atmospheric pressure
- Rainfall status
- Wind direction
- Wind speed

No rainfall was recorded, making this race suitable for the initial dry-race
investigation.

## Interpretation

FastF1 provides the main information required for version one:

- Lap times for pace modelling
- Tyre compounds, tyre life and stints for degradation modelling
- Pit entry and exit times for identifying pit events
- Track status for detecting abnormal race conditions
- Driver position for basic race context
- Weather measurements for environmental context

The two missing lap times represent a small portion of the session and can be
handled during data cleaning.

Pit-entry and pit-exit fields are naturally sparse because values only exist
when a pit event occurs. They are not ordinary missing-data errors.

Pit-lane time loss is not provided as one final value. It must be derived from
pit timing, lap timing and circuit context.

## Limitations

- Only one race has been inspected.
- Only a dry race has been inspected.
- Only the Hard and Soft compounds were used.
- Detailed telemetry was intentionally not loaded.
- Field consistency across 2022–2025 has not been tested.
- Safety-car, red-flag and wet-race data have not been investigated.
- Historical data cannot directly provide counterfactual strategy outcomes.

## Feasibility decision

**Result: Passed**

FastF1 provides sufficient core lap, tyre, pit-stop and weather data for the
project to continue.

The simulator remains necessary because historical data cannot reveal the
outcome of strategies that were not actually used.

## Remaining Phase 1 checks

1. Inspect several races and seasons.
2. Test one telemetry sample.
3. Document the initial data dictionary.
4. Define baseline methods.
5. Define race-level evaluation.
6. Record research risks and planned treatments.