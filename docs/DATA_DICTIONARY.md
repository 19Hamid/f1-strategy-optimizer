# F1 Race Strategy Optimizer — Initial Data Dictionary

## Purpose

This document defines the initial variables considered for the project and
determines whether each variable may be used at prediction time.

It will be updated during data cleaning and feature engineering.

## Decision timestamp

A decision occurs at the start of lap `t`.

For that decision, the system may use:

- Information known before the race
- Current information available at the start of lap `t`
- Historical information from completed laps up to lap `t - 1`

It must not use information generated during lap `t` or any later lap.

## Usage classifications

| Classification | Meaning |
|---|---|
| Safe | Known at the decision time and suitable as a model input |
| Conditional | Safe only when constructed exclusively from past information |
| Cleaning or label only | Used to clean data, create targets or evaluate results |
| Forbidden | Contains future information and must never be a prediction input |

## Race and participant context

| Variable | Meaning | Usage |
|---|---|---|
| Season | Championship year | Safe |
| RoundNumber | Race number within the season | Safe |
| EventName | Grand Prix name | Safe |
| Circuit | Circuit identifier | Safe |
| TotalLaps | Scheduled race distance | Safe for the initial completed-race scope |
| Driver | Driver identifier | Safe, but models must also be tested without it |
| Team | Constructor identifier | Safe, but may reduce generalisation |
| LapNumber | Current decision lap `t` | Safe |
| LapsRemaining | Scheduled laps remaining, including lap `t` | Safe and derived |
| PositionAtStart | Driver position at the start of lap `t` | Conditional |
| CompoundsUsed | Dry compounds already used before lap `t` | Conditional |

`PositionAtStart` must come from the end of lap `t - 1`, not from lap `t`.

## Tyre and stint information

| FastF1 field or feature | Meaning | Usage |
|---|---|---|
| Compound | Current tyre compound | Safe |
| Stint | Current stint number | Safe |
| TyreLife | Number of laps already completed on the tyre set | Conditional |
| FreshTyre | Whether the tyre set was new when fitted | Safe |
| TyreAgeAtStart | Derived tyre age at the start of lap `t` | Safe when derived from past data |
| StintLengthSoFar | Completed laps in the current stint | Safe when derived from past data |
| PreviousCompounds | Compounds used before the current stint | Conditional |

Values attached to lap `t` must not be used directly if they were only recorded
after that lap was completed. Start-of-lap values will be reconstructed from
the previous completed lap and stint history.

## Lap timing

| FastF1 field or feature | Meaning | Usage |
|---|---|---|
| LapTime | Time required to complete a lap | Conditional or target |
| Sector1Time | First-sector time | Conditional |
| Sector2Time | Second-sector time | Conditional |
| Sector3Time | Third-sector time | Conditional |
| LapStartTime | Time when the lap started within the session | Safe as an alignment key |
| IsAccurate | FastF1 data-quality indicator | Cleaning only |
| TrackStatus | Track-condition code | Safe only if known at decision time |
| Position | Position recorded for a completed lap | Conditional |
| PitInTime | Time at which a driver entered the pits | Label or derivation only |
| PitOutTime | Time at which a driver left the pits | Label or derivation only |

For a decision at the start of lap `t`, only lap times and sector times from
lap `t - 1` or earlier may be used.

The time for lap `t` may be used as a prediction target, but never as an input
for the decision made at the start of lap `t`.

## Weather information

| FastF1 field | Meaning and unit | Usage |
|---|---|---|
| Time | Session time of the weather observation | Alignment key |
| AirTemp | Air temperature in degrees Celsius | Safe if already observed |
| TrackTemp | Track temperature in degrees Celsius | Safe if already observed |
| Humidity | Relative humidity percentage | Safe if already observed |
| Pressure | Atmospheric pressure in millibars | Safe if already observed |
| Rainfall | Boolean rainfall indicator | Safe, but wet conditions are initially excluded |
| WindDirection | Wind direction in degrees | Safe if already observed |
| WindSpeed | Wind speed in metres per second | Safe if already observed |

Weather must be joined using the latest observation at or before the decision
timestamp. A later or nearest-future weather observation must not be used.

## Optional telemetry information

| FastF1 field | Meaning | Usage |
|---|---|---|
| Time | Time within the selected lap | Conditional |
| Distance | Estimated distance around the lap | Conditional |
| RPM | Engine revolutions per minute | Conditional |
| Speed | Vehicle speed in kilometres per hour | Conditional |
| nGear | Selected gear | Conditional |
| Throttle | Throttle percentage | Conditional |
| Brake | Brake activation indicator | Conditional |
| DRS | DRS state code | Conditional |
| X | Relative horizontal position coordinate | Conditional |
| Y | Relative vertical position coordinate | Conditional |
| Z | Relative elevation coordinate | Conditional |

Telemetry may only come from completed laps before the decision.

The first model will not use raw telemetry samples directly. If telemetry is
introduced, past-lap summaries such as average speed or full-throttle
percentage will be compared against simpler lap-level models first.

## Planned derived features

| Feature | Definition | Usage |
|---|---|---|
| LapsRemaining | `TotalLaps - LapNumber + 1` | Safe |
| RecentPaceMean | Mean of recent valid completed lap times | Conditional |
| RecentPaceMedian | Median of recent valid completed lap times | Conditional |
| PaceTrend | Recent change in lap pace | Conditional |
| DegradationSlope | Estimated lap-time increase during the current stint | Conditional |
| CircuitPitLoss | Historical pit-lane time loss for the circuit | Conditional |
| FuelLoadProxy | Race progression represented by current lap | Safe approximation |
| IsGreenFlag | Whether normal racing conditions currently apply | Safe |
| IsDry | Whether dry conditions currently apply | Safe |
| ActualPitAction | Whether the driver actually pitted | Label only |
| PredictedLapTime | Model estimate for a future lap | Model output |
| ExpectedRemainingTime | Simulated time from lap `t` to the finish | Simulator output |
| StrategyTimeDelta | Difference between alternative strategy times | Optimizer output |

All rolling calculations must be shifted so that they contain only completed
past laps.

`CircuitPitLoss` must be calculated using training races only. Information
from an evaluation race must not be used to estimate its own expected pit loss.

## Prediction targets

### Tyre and lap-time model

The initial target will be the valid green-flag lap time for lap `t`, predicted
using information available at the start of that lap.

Alternative targets, such as pace relative to a driver or circuit baseline,
may be evaluated during modelling.

### Strategy simulator

The simulator will estimate remaining race time under alternative valid tyre
strategies.

### Pit-decision optimizer

The optimizer will select the action with the lowest expected remaining race
time and report the estimated difference between the actions.

## Forbidden prediction inputs

The following information must never be used as an input for a decision at the
start of lap `t`:

- Lap time or sector times from lap `t` or later
- Telemetry from lap `t` or later
- Future weather observations
- Future track-status changes
- Future safety cars or red flags
- The driver's actual future pit lap
- Future tyre compounds
- Final finishing position
- Final race time
- Final classification or retirement status
- Statistics calculated using the complete evaluation race
- Any preprocessing fitted using evaluation data

## Data-leakage prevention rules

1. Split training and evaluation data by race and time, not by random laps.
2. Fit preprocessing operations using training data only.
3. Shift every rolling feature by at least one completed lap.
4. Join weather using the latest past observation.
5. Calculate historical circuit, driver and team statistics using prior data.
6. Use pit timing and final results only for labels, derivations or evaluation.
7. Preserve timestamps so every feature can be audited.
8. Test feature generation with automated leakage checks.