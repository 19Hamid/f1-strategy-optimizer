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

## Multi-season coverage check

A second check examined four races across the proposed 2022–2025 period.

| Season | Event | Laps | Missing lap times | Pit entries | Compounds | Result |
|---:|---|---:|---:|---:|---|---|
| 2022 | Bahrain Grand Prix | 1,125 | 7 | 59 | Hard, Medium, Soft | Passed |
| 2023 | British Grand Prix | 971 | 5 | 26 | Hard, Medium, Soft | Passed |
| 2024 | Bahrain Grand Prix | 1,129 | 2 | 43 | Hard, Soft | Passed |
| 2025 | Japanese Grand Prix | 1,059 | 0 | 21 | Hard, Medium, Soft | Passed |

The four sessions contained 4,284 lap records, 149 pit entries and 14 missing
lap times. Missing lap times represented approximately 0.33% of the examined
records.

Every required lap and weather field existed in all four sessions.

The following data types were consistent across the samples:

| Field | Observed data type |
|---|---|
| Driver | object |
| Team | object |
| LapNumber | float64 |
| LapTime | timedelta64[ns] |
| Stint | float64 |
| Compound | object |
| TyreLife | float64 |
| PitInTime | timedelta64[ns] |
| PitOutTime | timedelta64[ns] |
| TrackStatus | object |
| LapStartTime | timedelta64[ns] |

FastF1 produced one timing warning for driver 16 during the 2022 Bahrain Grand
Prix. The warning did not prevent the session from loading, but it demonstrates
that source-data anomalies must be logged and handled during data cleaning.

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

## Telemetry feasibility

Detailed telemetry was tested using the fastest lap from the 2024 Bahrain
Grand Prix.

| Measurement | Result |
|---|---|
| Driver | VER |
| Lap number | 39 |
| Lap time | 1:32.608 |
| Telemetry samples | 703 |
| Median sampling interval | 0.122 seconds |
| Maximum recorded distance | 5,364 metres |
| Speed range | 66–301 km/h |
| Throttle range | 0–100% |

Every telemetry sample contained values for:

- Time
- Distance
- Engine RPM
- Speed
- Selected gear
- Throttle
- Brake status
- DRS status
- X, Y and Z position

**Result: Passed**

FastF1 provides sufficiently detailed car and position telemetry for optional
future feature engineering.

The initial model will prioritize lap-level and stint-level information.
Telemetry-derived features will only be included when they provide measurable
improvement over simpler models. This prevents unnecessary computation and
model complexity.

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

- Four sample races have been inspected, not every race from 2022–2025.
- All four examined races recorded dry conditions.
- Detailed telemetry has only been inspected for one representative lap.
- One source-data timing warning occurred in the 2022 Bahrain Grand Prix.
- Safety-car, red-flag and wet-race data have not been validated.
- Historical data cannot directly provide counterfactual strategy outcomes.

## Feasibility decision

**Result: Passed**

FastF1 provides sufficient core lap, tyre, pit-stop and weather data for the
project to continue.

The simulator remains necessary because historical data cannot reveal the
outcome of strategies that were not actually used.

## Phase 1 completion

The remaining feasibility requirements were completed:

- Detailed telemetry was successfully tested.
- Required fields were consistent across selected 2022–2025 races.
- The initial data dictionary was documented.
- Baseline methods were defined.
- Race-level temporal evaluation was defined.
- Research risks and planned treatments were documented.

The project may proceed to Phase 2: Raw-data pipeline development.