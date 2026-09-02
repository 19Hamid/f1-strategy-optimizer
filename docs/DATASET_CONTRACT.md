# F1 Race Strategy Optimizer — Dataset Contract

## Purpose

This document defines version `1.0` of the modelling-dataset contract for the
F1 Race Strategy Optimizer.

The contract converts Phase 3 processed race-session data into versioned,
leakage-controlled and baseline-ready Phase 4 datasets.

It defines:

- Dataset scope
- Decision identity
- Source normalization
- Decision-row eligibility
- Feature and label separation
- Stored schemas
- Pit-duration observations
- Whole-race temporal splits
- Partition layout
- Integrity requirements
- Versioning rules

The contract is authoritative for Phase 4 dataset construction.

## Contract version

```text
DATASET_CONTRACT_VERSION = "1.0"
```

A contract-version review is required when changing:

- Dataset identities
- Required files
- Stored columns
- Column semantics
- Dtypes or nullability
- Decision eligibility
- Target eligibility
- Feature availability rules
- Split definitions
- Manifest semantics
- Integrity requirements

Implementation details may change without a version bump only when the stored
meaning and outputs remain identical.

## Source contracts

Dataset contract `1.0` consumes:

```text
CLEANING_RULE_VERSION = "1.0"
PROCESSED_CONTRACT_VERSION = "1.0"
```

The authoritative source is:

```text
data/processed/fastf1/cleaning_version=1.0/
```

Relevant source documents are:

- [Decision-Time Data Dictionary](DATA_DICTIONARY.md)
- [Cleaning Rules](CLEANING_RULES.md)
- [Processed-Data Contract](PROCESSED_DATA_CONTRACT.md)
- [Evaluation Plan](EVALUATION_PLAN.md)
- [Development EDA](DEVELOPMENT_EDA.md)

Raw FastF1 partitions must not be read directly by the Phase 4 decision-row
builder.

If a required value is unavailable from the processed contract, it is omitted
from dataset version `1.0` rather than silently recovered from an uncontrolled
source.

## Scope

Dataset version `1.0` contains completed race sessions from:

| Purpose | Seasons | Sessions |
|---|---:|---:|
| Development and temporal validation | 2022–2024 | 68 |
| Protected final temporal evaluation | 2025 | 0 |

Development sessions are distributed as:

| Season | Sessions |
|---:|---:|
| 2022 | 22 |
| 2023 | 22 |
| 2024 | 24 |
| **Total** | **68** |

No Phase 4 development command may discover, read, normalize, aggregate or
write a 2025 partition.

The limited Phase 1 schema inspection of one 2025 race remains disclosed, but
2025 must not influence this contract or its implementation.

## Decision timestamp

A decision occurs at the start of lap `t`.

A decision feature may use only:

- Information known before the race
- State known when lap `t` begins
- Information from completed laps through lap `t - 1`
- Weather observations timestamped at or before `LapStartTime(t)`

A decision feature must not use:

- Lap time from lap `t`
- Sector times from lap `t`
- Pit events generated during lap `t`
- Position produced at the end of lap `t`
- Current-lap quality outcomes
- Future weather or track conditions
- Any later race outcome

## Dataset families

Version `1.0` stores three analytical tables per race session.

### Decision rows

`decision_rows.parquet` stores identity, context, past-only features and
decision-eligibility audit fields.

It must not contain supervised targets or historical action labels.

### Decision labels

`decision_labels.parquet` stores post-decision labels and target-quality fields.

It is separated physically from decision features to reduce accidental target
leakage.

### Pit-duration observations

`pit_duration_observations.parquet` stores normalized historical pit events and
their pit-duration target eligibility.

Observed pit-lane duration remains distinct from net race-time loss.

## Canonical decision identity

One candidate decision row represents one driver at the start of one recorded
race lap after that driver has completed at least one earlier recorded lap.

The identity is:

```text
session_id + driver + decision_lap
```

The deterministic string identifier is:

```text
{session_id}-{driver}-{decision_lap:03d}
```

Example:

```text
2024-01-R-VER-023
```

Required identity properties:

- `decision_id` is non-null.
- `decision_id` is unique across the complete dataset.
- `session_id` identifies exactly one source session.
- `driver` is non-null.
- `decision_lap` is a positive whole number.
- One decision row has exactly one matching label row.

## Candidate decision population

The first recorded lap for each driver-race is outside the candidate decision
population because no earlier completed driver lap exists.

The audited development totals are:

| Population | Rows |
|---|---:|
| Processed source laps | 74,601 |
| First recorded driver laps omitted | 1,350 |
| Candidate decision rows | 73,251 |

All 73,251 candidate rows are stored, including rows that fail final V1
decision eligibility.

This preserves exclusions for auditing while allowing model-ready consumers to
filter explicitly on `is_decision_eligible`.

## Start-of-lap reconstruction

For a candidate decision on lap `t`, the builder reconstructs current state
primarily from the completed source row for lap `t - 1`.

### Current compound

For an eligible decision:

```text
current_compound(t) = Compound(t - 1)
```

The supported dry compounds are:

- `HARD`
- `MEDIUM`
- `SOFT`

Wet compounds, missing compounds and unsupported values make the decision row
ineligible for V1.

### Tyre age

For an eligible decision:

```text
tyre_age_laps(t) = TyreLife(t - 1)
```

The value represents tyre usage completed before lap `t` begins.

It must be:

- Present
- Positive
- Whole-number valued

No future tyre-life value may be used.

### Current stint

For an eligible decision:

```text
current_stint_number(t) = Stint(t - 1)
```

`current_stint_laps_completed` is the number of recorded laps completed in the
same reconstructed stint through lap `t - 1`.

### Previous pit commitment

If lap `t - 1` contains a pit-in marker, the driver has already committed to the
pit sequence before the candidate state for lap `t` can be treated as an open
pit-now-versus-stay-out decision.

Such rows receive:

```text
PREVIOUS_LAP_PIT_COMMITMENT
```

They are not V1 decision-eligible.

### State consistency

When lap `t - 1` does not contain a pit-in marker, the current source row is
used only as a cleaning cross-check.

The following values must remain consistent across the boundary:

- Compound
- Stint number

The current source values are not copied into the past-only feature vector.

A mismatch receives:

```text
STATE_RECONSTRUCTION_CONFLICT
```

The development data contains six such conflicts:

| Session | Driver | Decision lap |
|---|---|---:|
| `2022-07-R` | LAT | 23 |
| `2022-11-R` | ALB | 43 |
| `2022-11-R` | BOT | 41 |
| `2022-11-R` | SAI | 52 |
| `2022-11-R` | VET | 46 |
| `2023-08-R` | TSU | 36 |

These rows remain stored but are decision-ineligible.

## Source normalization boundary

Phase 3 partitions remain immutable.

Phase 4 normalizes source tables in memory before cross-session combination or
feature construction.

No normalization step may change a non-null semantic value.

### Lap normalization

The builder validates and normalizes:

| Source column | Canonical pandas dtype | Rule |
|---|---|---|
| `SourceRowNumber` | `int64` | Required and non-null |
| `Season` | `int64` | Required and equal to partition season |
| `RoundNumber` | `int64` | Required and equal to partition round |
| `SessionType` | `string` | Required and equal to `R` |
| `Driver` | `string` | Required and non-empty |
| `DriverNumber` | `string` | Identifier, never numeric |
| `Team` | `string` | Required and non-empty |
| `LapNumber` | `Int64` | Must contain positive whole-number values |
| `Stint` | `Int64` | Nullable only when source semantics require it |
| `TyreLife` | `Int64` | Nullable; non-null values must be whole and positive |
| `Position` | `Int64` | Nullable; non-null values must be whole and positive |
| `Compound` | `string` | Normalized uppercase string |
| `TrackStatus` | `string` | Preserved as a status code |
| `Rainfall` | `boolean` | Nullable boolean at normalization boundary |
| `IsAccurate` | `boolean` | Target-quality field only |
| `IsEligible` | `bool` | Target-quality field only |

`LapStartDate` is entirely missing across the development processed partitions.
It is not a Phase 4 feature or identifier.

### Pit-event normalization

The development pit-event partitions contain four physical schema variants
caused only by nullable-value inference.

The following columns are normalized to nullable integers:

```text
pit_in_lap
pit_out_lap
stint_before
stint_after
```

Their canonical pandas dtype is:

```text
Int64
```

The following columns are normalized to nullable booleans:

```text
is_stint_change
is_compound_change
```

Their canonical pandas dtype is:

```text
boolean
```

Normalization was verified across all 68 sessions and 2,693 pit events.

The observed null counts are:

| Column | Nulls | Meaning |
|---|---:|---|
| `pit_in_lap` | 65 | Exit-only events |
| `pit_out_lap` | 89 | Entry-only events |
| `stint_before` | 65 | Exit-only events |
| `stint_after` | 89 | Entry-only events |
| `is_stint_change` | 154 | Incomplete events |
| `is_compound_change` | 154 | Incomplete events |

After normalization, the 68 pit-event partitions must produce exactly one
canonical in-memory schema.

## Decision eligibility

Decision eligibility is separate from lap-time target eligibility.

A candidate row is V1 decision-eligible only when all rules below pass.

| Order | Rule | Required condition | Exclusion reason |
|---:|---|---|---|
| 1 | Consecutive history | Previous recorded lap is exactly `t - 1` | `NON_CONSECUTIVE_PREVIOUS_LAP` |
| 2 | Weather timing | Matched observation exists at or before decision time | `WEATHER_NOT_AVAILABLE_BY_DECISION` |
| 3 | Open decision | Previous lap has no pit-in commitment | `PREVIOUS_LAP_PIT_COMMITMENT` |
| 4 | State consistency | Compound and stint reconstruction agree | `STATE_RECONSTRUCTION_CONFLICT` |
| 5 | Compound support | Reconstructed compound is hard, medium or soft | `UNSUPPORTED_CURRENT_COMPOUND` |
| 6 | Tyre-age validity | Prior tyre life is present, positive and whole | `INVALID_CURRENT_TYRE_AGE` |
| 7 | Stint validity | Prior stint is present, positive and whole | `MISSING_CURRENT_STINT` |
| 8 | Dry decision | Latest available rainfall is false | `WET_AT_DECISION` |
| 9 | Prior green state | Previous lap track status is exactly `1` | `PREVIOUS_LAP_NOT_GREEN` |
| 10 | Historical context | At least three earlier target-eligible laps exist | `INSUFFICIENT_ELIGIBLE_HISTORY` |
| 11 | Position availability | Previous completed-lap position exists | `MISSING_PREVIOUS_POSITION` |

`IsEligible(t)` is not a decision-eligibility rule.

`PitInTime(t)` is not a decision feature or decision-eligibility rule.

The audited V1 funnel produces:

| Population | Rows |
|---|---:|
| Candidate decisions | 73,251 |
| V1 decision-eligible | 55,943 |
| V1 decision-ineligible | 17,308 |

Eligible decisions by season are:

| Season | Eligible decisions | Historical `PIT_NOW` |
|---:|---:|---:|
| 2022 | 16,216 | 560 |
| 2023 | 19,239 | 620 |
| 2024 | 20,488 | 596 |
| **Total** | **55,943** | **1,776** |

## Decision exclusion encoding

`decision_exclusion_reasons` is a deterministic pipe-delimited string.

When multiple reasons apply, they appear in this order:

1. `NON_CONSECUTIVE_PREVIOUS_LAP`
2. `WEATHER_NOT_AVAILABLE_BY_DECISION`
3. `PREVIOUS_LAP_PIT_COMMITMENT`
4. `STATE_RECONSTRUCTION_CONFLICT`
5. `UNSUPPORTED_CURRENT_COMPOUND`
6. `INVALID_CURRENT_TYRE_AGE`
7. `MISSING_CURRENT_STINT`
8. `WET_AT_DECISION`
9. `PREVIOUS_LAP_NOT_GREEN`
10. `INSUFFICIENT_ELIGIBLE_HISTORY`
11. `MISSING_PREVIOUS_POSITION`

An eligible decision stores an empty string.

`decision_exclusion_count` must equal the number of encoded reasons.

## Historical lap features

Historical performance features use only target-eligible completed laps with lap
numbers below `decision_lap`.

### Immediate previous-lap fields

Immediate previous-lap performance fields are nullable.

They are populated only when lap `t - 1` is target-eligible.

The fields are:

- `previous_lap_time_seconds`
- `previous_sector1_time_seconds`
- `previous_sector2_time_seconds`
- `previous_sector3_time_seconds`

`previous_lap_was_target_eligible` records whether these immediate values are
available.

### Historical count

`eligible_laps_completed` is the number of target-eligible laps completed by the
driver before lap `t`.

Eligible V1 decisions require:

```text
eligible_laps_completed >= 3
```

### Rolling three-lap median

`rolling_lap_time_median_3` uses the latest three target-eligible completed
laps.

It requires three observations.

### Rolling five-lap statistics

The following fields use up to the latest five target-eligible completed laps:

- `rolling_lap_time_median_5`
- `rolling_lap_time_std_5`
- `rolling_lap_time_trend_5`

A minimum of three observations is required.

Standard deviation uses the population definition:

```text
ddof = 0
```

Trend is the ordinary least-squares slope of lap time against ordered positions
`0` through `n - 1` within the historical window.

A positive trend means lap times are becoming slower.

A negative trend means lap times are becoming faster.

No rolling window may include lap `t`.

## Weather features

Decision-time weather comes from the Phase 3 observation aligned to
`LapStartTime(t)`.

The builder must independently revalidate:

```text
WeatherMatched == True
WeatherObservationTime <= LapStartTime(t)
WeatherAgeSeconds >= 0
```

Stored decision-time weather fields are:

- `weather_observation_time_seconds`
- `weather_age_seconds`
- `air_temperature_celsius`
- `humidity_percent`
- `pressure_mbar`
- `track_temperature_celsius`
- `wind_direction_degrees`
- `wind_speed_mps`
- `rainfall`

No future weather observation may be substituted for a missing earlier one.

## Track-status boundary

The Phase 3 lap-level `TrackStatus(t)` may include conditions occurring during
lap `t`.

It is not copied into decision features.

Version `1.0` stores:

```text
previous_track_status = TrackStatus(t - 1)
```

V1 decision eligibility requires:

```text
previous_track_status == "1"
```

This is a conservative past-only approximation. It does not claim that no
status change can occur after lap `t` begins.

## Decision-row schema

`decision_rows.parquet` contains the columns below in this exact order.

### Identity and provenance

| # | Column | Pandas dtype | Nullable | Role |
|---:|---|---|---|---|
| 1 | `decision_id` | `string` | No | Primary identity |
| 2 | `session_id` | `string` | No | Session identity |
| 3 | `season` | `int64` | No | Temporal identity |
| 4 | `round_number` | `int64` | No | Race identity |
| 5 | `session_type` | `string` | No | Must equal `R` |
| 6 | `event_name` | `string` | No | Race context |
| 7 | `driver` | `string` | No | Driver identity |
| 8 | `driver_number` | `string` | No | Identifier |
| 9 | `team` | `string` | No | Team context |
| 10 | `decision_lap` | `int64` | No | Lap about to begin |
| 11 | `decision_time_seconds` | `float64` | No | Session-relative start time |
| 12 | `source_row_number` | `int64` | No | Source lineage |
| 13 | `dataset_contract_version` | `string` | No | Must equal `1.0` |
| 14 | `cleaning_rule_version` | `string` | No | Must equal `1.0` |
| 15 | `processed_contract_version` | `string` | No | Must equal `1.0` |

### Past-only context and candidate features

| # | Column | Pandas dtype | Nullable | Source |
|---:|---|---|---|---|
| 16 | `current_compound` | `string` | Yes | Compound from lap `t - 1` |
| 17 | `tyre_age_laps` | `Int64` | Yes | Tyre life from lap `t - 1` |
| 18 | `current_stint_number` | `Int64` | Yes | Stint from lap `t - 1` |
| 19 | `current_stint_laps_completed` | `Int64` | Yes | Past-only stint count |
| 20 | `completed_pit_stops` | `int64` | No | Completed pit exits before `t` |
| 21 | `previous_position` | `Int64` | Yes | Position after lap `t - 1` |
| 22 | `previous_lap_was_target_eligible` | `bool` | No | Historical quality |
| 23 | `previous_lap_time_seconds` | `float64` | Yes | Eligible lap `t - 1` |
| 24 | `previous_sector1_time_seconds` | `float64` | Yes | Eligible lap `t - 1` |
| 25 | `previous_sector2_time_seconds` | `float64` | Yes | Eligible lap `t - 1` |
| 26 | `previous_sector3_time_seconds` | `float64` | Yes | Eligible lap `t - 1` |
| 27 | `eligible_laps_completed` | `int64` | No | Eligible laps below `t` |
| 28 | `rolling_lap_time_median_3` | `float64` | Yes | Latest 3 eligible laps |
| 29 | `rolling_lap_time_median_5` | `float64` | Yes | Latest up to 5 eligible laps |
| 30 | `rolling_lap_time_std_5` | `float64` | Yes | Population standard deviation |
| 31 | `rolling_lap_time_trend_5` | `float64` | Yes | Past-only OLS slope |
| 32 | `previous_track_status` | `string` | Yes | Track status from lap `t - 1` |
| 33 | `weather_observation_time_seconds` | `float64` | No | Past-aligned weather time |
| 34 | `weather_age_seconds` | `float64` | No | Weather staleness |
| 35 | `air_temperature_celsius` | `float64` | No | Decision-time weather |
| 36 | `humidity_percent` | `float64` | No | Decision-time weather |
| 37 | `pressure_mbar` | `float64` | No | Decision-time weather |
| 38 | `track_temperature_celsius` | `float64` | No | Decision-time weather |
| 39 | `wind_direction_degrees` | `int64` | No | Decision-time weather |
| 40 | `wind_speed_mps` | `float64` | No | Decision-time weather |
| 41 | `rainfall` | `bool` | No | Decision-time rainfall |

### Decision eligibility audit

| # | Column | Pandas dtype | Nullable |
|---:|---|---|---|
| 42 | `has_consecutive_previous_lap` | `bool` | No |
| 43 | `weather_available_by_decision` | `bool` | No |
| 44 | `previous_lap_not_pit_commitment` | `bool` | No |
| 45 | `state_reconstruction_consistent` | `bool` | No |
| 46 | `supported_dry_compound` | `bool` | No |
| 47 | `valid_current_tyre_age` | `bool` | No |
| 48 | `current_stint_identified` | `bool` | No |
| 49 | `dry_at_decision` | `bool` | No |
| 50 | `previous_lap_green` | `bool` | No |
| 51 | `minimum_history_available` | `bool` | No |
| 52 | `previous_position_available` | `bool` | No |
| 53 | `is_decision_eligible` | `bool` | No |
| 54 | `decision_exclusion_count` | `int64` | No |
| 55 | `decision_exclusion_reasons` | `string` | No |

The table contains exactly 55 columns.

## Allowed model-feature columns

Dataset version `1.0` defines an allowlist rather than forcing every model to
use every available field.

Allowed candidate model features are:

```text
event_name
driver
team
decision_lap
current_compound
tyre_age_laps
current_stint_laps_completed
completed_pit_stops
previous_position
previous_lap_was_target_eligible
previous_lap_time_seconds
previous_sector1_time_seconds
previous_sector2_time_seconds
previous_sector3_time_seconds
eligible_laps_completed
rolling_lap_time_median_3
rolling_lap_time_median_5
rolling_lap_time_std_5
rolling_lap_time_trend_5
weather_age_seconds
air_temperature_celsius
humidity_percent
pressure_mbar
track_temperature_celsius
wind_direction_degrees
wind_speed_mps
```

Categorical encoders, imputers, scalers and learned statistics must be fitted
only on the active training fold.

The following stored fields are context or audit fields, not model features:

- Identities
- Contract versions
- Source row numbers
- Decision timestamps
- Eligibility flags
- Exclusion reasons
- `previous_track_status`
- `rainfall`

Because eligible V1 decisions are dry and follow a green previous lap,
`rainfall` and `previous_lap_green` are constants in the model-ready population.

## Decision-label schema

`decision_labels.parquet` contains the columns below in this exact order.

| # | Column | Pandas dtype | Nullable | Role |
|---:|---|---|---|---|
| 1 | `decision_id` | `string` | No | Join identity |
| 2 | `session_id` | `string` | No | Session identity |
| 3 | `season` | `int64` | No | Temporal identity |
| 4 | `round_number` | `int64` | No | Race identity |
| 5 | `session_type` | `string` | No | Must equal `R` |
| 6 | `driver` | `string` | No | Driver identity |
| 7 | `decision_lap` | `int64` | No | Decision lap |
| 8 | `historical_action` | `string` | No | `PIT_NOW` or `STAY_OUT` |
| 9 | `did_pit` | `bool` | No | Historical action indicator |
| 10 | `pit_event_id` | `string` | Yes | Matching pit event when available |
| 11 | `is_lap_time_target_eligible` | `bool` | No | Phase 3 target quality |
| 12 | `lap_time_target_seconds` | `float64` | Yes | Eligible current-lap target |
| 13 | `lap_target_exclusion_count` | `int64` | No | Target-quality reason count |
| 14 | `lap_target_exclusion_reasons` | `string` | No | Frozen Phase 3 reasons |
| 15 | `dataset_contract_version` | `string` | No | Must equal `1.0` |

The table contains exactly 15 columns.

`lap_time_target_seconds` must be null when
`is_lap_time_target_eligible` is false.

`did_pit` is derived from the source `PitInTime(t)` marker.

`historical_action` must satisfy:

```text
did_pit == True  -> PIT_NOW
did_pit == False -> STAY_OUT
```

Historical action is a diagnostic label. It is not an optimal-strategy label.

## Label separation

Feature builders must not read `decision_labels.parquet`.

Training-data assembly must:

1. Select an explicit temporal fold.
2. Select decision rows where `is_decision_eligible` is true.
3. Join labels by `decision_id`.
4. Select the required target population.
5. Select only allowlisted feature columns.
6. Fit transformations on training sessions only.
7. Apply frozen transformations to validation sessions.

A model matrix must never be created with a generic “all columns except target”
operation.

## Lap-time target population

Among the 55,943 V1 decision-eligible rows:

| Target population | Rows |
|---|---:|
| Lap-time target eligible | 52,483 |
| Lap-time target ineligible | 3,460 |

Target eligibility comes directly from Phase 3 cleaning version `1.0`.

It must not alter decision eligibility.

This distinction preserves historically meaningful `PIT_NOW` decisions whose
in-laps are intentionally unsuitable as ordinary lap-time targets.

## Pit-duration observation schema

`pit_duration_observations.parquet` contains one row for every normalized Phase
3 pit event.

| # | Column | Pandas dtype | Nullable |
|---:|---|---|---|
| 1 | `pit_event_id` | `string` | No |
| 2 | `session_id` | `string` | No |
| 3 | `season` | `int64` | No |
| 4 | `round_number` | `int64` | No |
| 5 | `session_type` | `string` | No |
| 6 | `event_name` | `string` | No |
| 7 | `driver` | `string` | No |
| 8 | `team` | `string` | No |
| 9 | `event_type` | `string` | No |
| 10 | `pit_in_lap` | `Int64` | Yes |
| 11 | `pit_out_lap` | `Int64` | Yes |
| 12 | `stint_before` | `Int64` | Yes |
| 13 | `stint_after` | `Int64` | Yes |
| 14 | `compound_before` | `string` | Yes |
| 15 | `compound_after` | `string` | Yes |
| 16 | `tyre_life_before` | `float64` | Yes |
| 17 | `tyre_life_after` | `float64` | Yes |
| 18 | `is_stint_change` | `boolean` | Yes |
| 19 | `is_compound_change` | `boolean` | Yes |
| 20 | `is_complete` | `bool` | No |
| 21 | `is_green_flag_pair` | `bool` | No |
| 22 | `is_dry_weather_pair` | `bool` | No |
| 23 | `is_interrupted_duration` | `bool` | No |
| 24 | `is_pit_duration_target_eligible` | `bool` | No |
| 25 | `pit_duration_target_seconds` | `float64` | Yes |
| 26 | `pit_duration_exclusion_count` | `int64` | No |
| 27 | `pit_duration_exclusion_reasons` | `string` | No |
| 28 | `dataset_contract_version` | `string` | No |

The table contains exactly 28 columns.

The source population is:

| Event type | Rows |
|---|---:|
| Matched | 2,539 |
| Entry-only | 89 |
| Exit-only | 65 |
| **Total** | **2,693** |

Exactly 1,465 rows are expected to be pit-duration target eligible.

For an eligible row:

```text
pit_duration_target_seconds
    = observed_pit_lane_duration_seconds
```

For an ineligible row, the target is null.

The stored target represents observed pit-lane duration, not net pit loss.

## Fold-specific pit-duration estimates

A single globally calculated circuit pit-duration estimate must not be stored in
decision rows.

Such an estimate would leak validation-race information.

When later modelling requires a circuit-specific estimate:

- Development fold 1 may fit only on 2022 pit observations.
- Development fold 2 may fit only on 2022–2023 pit observations.
- Final development fit may use 2022–2024 observations.
- Protected 2025 evaluation must use parameters frozen before evaluation.

The fitting code must record:

- Training sessions
- Observation count
- Estimator definition
- Fallback rule
- Uncertainty measure
- Fitted artifact hash

## Temporal split contract

Splits occur by complete race session.

Random lap-level or driver-level splitting is forbidden.

The global `splits.parquet` table contains:

| Column | Pandas dtype | Nullable |
|---|---|---|
| `fold_id` | `string` | No |
| `session_id` | `string` | No |
| `season` | `int64` | No |
| `round_number` | `int64` | No |
| `session_type` | `string` | No |
| `role` | `string` | No |

Allowed roles are:

- `TRAIN`
- `VALIDATION`
- `EXCLUDED`

The folds are:

### Development fold 1

| Season | Role |
|---:|---|
| 2022 | `TRAIN` |
| 2023 | `VALIDATION` |
| 2024 | `EXCLUDED` |

### Development fold 2

| Season | Role |
|---:|---|
| 2022 | `TRAIN` |
| 2023 | `TRAIN` |
| 2024 | `VALIDATION` |

### Final development fit

| Season | Role |
|---:|---|
| 2022 | `TRAIN` |
| 2023 | `TRAIN` |
| 2024 | `TRAIN` |

The fold identifiers are:

```text
development_fold_1
development_fold_2
final_development_fit
```

With 68 sessions and three fold definitions, `splits.parquet` contains exactly
204 rows.

Every session must appear once in every fold.

## Storage layout

The dataset root is:

```text
data/datasets/f1_strategy/
└── dataset_contract_version=1.0/
```

A session partition is:

```text
data/datasets/f1_strategy/
└── dataset_contract_version=1.0/
    └── season=YYYY/
        └── round=RR/
            └── session=R/
                ├── decision_rows.parquet
                ├── decision_labels.parquet
                ├── pit_duration_observations.parquet
                ├── quality_report.json
                └── manifest.json
```

Global files are:

```text
data/datasets/f1_strategy/
└── dataset_contract_version=1.0/
    ├── catalog.parquet
    ├── splits.parquet
    └── runs/
        └── <run-id>.json
```

Round directories use two-digit zero padding.

## Session catalog

`catalog.parquet` contains exactly these columns:

| # | Column |
|---:|---|
| 1 | `session_id` |
| 2 | `season` |
| 3 | `round_number` |
| 4 | `session_type` |
| 5 | `event_name` |
| 6 | `dataset_contract_version` |
| 7 | `cleaning_rule_version` |
| 8 | `processed_contract_version` |
| 9 | `created_at_utc` |
| 10 | `decision_rows` |
| 11 | `eligible_decisions` |
| 12 | `ineligible_decisions` |
| 13 | `decision_label_rows` |
| 14 | `lap_time_target_eligible_rows` |
| 15 | `pit_now_rows` |
| 16 | `stay_out_rows` |
| 17 | `pit_duration_rows` |
| 18 | `pit_duration_target_eligible_rows` |
| 19 | `total_size_bytes` |
| 20 | `session_directory` |

Catalog identities must be unique and sorted by:

```text
season, round_number, session_type
```

## Session manifest

Every completed session partition contains `manifest.json`.

Required top-level keys are:

```text
dataset_contract_version
created_at_utc
session
source
files
validation
```

### Session section

The session section contains:

- `identifier`
- `season`
- `round_number`
- `session_type`
- `event_name`

### Source section

The source section contains:

- `cleaning_rule_version`
- `processed_contract_version`
- Source session directory
- Source manifest SHA-256
- Source table SHA-256 values

### Files section

Every authoritative session file records:

- Relative path
- Row count when tabular
- Ordered columns when tabular
- File size
- SHA-256

### Validation section

The validation section contains:

- `status`
- `issue_count`
- Decision identity uniqueness
- Decision-label identity equality
- Feature/label row-count equality
- Future-weather-match count
- Leakage-check status
- 2025-access status

A session is valid only when validation status is `passed`.

## Quality report

`quality_report.json` contains:

### Source counts

- Processed source laps
- Candidate decision rows
- Omitted first recorded laps
- Source pit events

### Decision quality

- Eligible decisions
- Ineligible decisions
- Decision eligibility rate
- Exclusion-reason counts
- State-reconstruction conflicts
- Historical `PIT_NOW` actions
- Historical `STAY_OUT` actions

### Target quality

- Lap-time target-eligible rows
- Lap-time target-ineligible rows
- Pit-duration target-eligible rows
- Pit-duration target-ineligible rows

### Leakage validation

- Future weather matches
- Current-lap timing features detected
- Current-lap quality features detected
- Feature columns outside the allowlist
- Evaluation-season rows detected

## Atomic storage

A dataset session is written atomically.

The writer must:

1. Validate all in-memory tables.
2. Write to a temporary sibling directory.
3. Read the temporary files back.
4. Verify schemas, row counts and hashes.
5. Write the manifest.
6. Atomically rename the temporary directory.
7. Leave no partial authoritative partition after failure.

Existing valid partitions are skipped unless force rebuilding is explicitly
requested.

An existing invalid partition causes a fail-closed error unless force rebuilding
is explicitly requested.

## Integrity requirements

A valid complete development dataset must satisfy:

1. Exactly 68 session partitions exist.
2. Exactly 22 sessions belong to 2022.
3. Exactly 22 sessions belong to 2023.
4. Exactly 24 sessions belong to 2024.
5. No 2025 partition exists.
6. Decision identities are globally unique.
7. Decision and label identity sets are identical.
8. Candidate decision rows total 73,251.
9. V1 decision-eligible rows total 55,943.
10. V1 decision-ineligible rows total 17,308.
11. Eligible historical `PIT_NOW` rows total 1,776.
12. Eligible historical `STAY_OUT` rows total 54,167.
13. Eligible lap-time targets among eligible decisions total 52,483.
14. Ineligible lap-time targets among eligible decisions total 3,460.
15. Pit-duration observations total 2,693.
16. Pit-duration target-eligible rows total 1,465.
17. State-reconstruction conflicts total 6.
18. Future weather matches total 0.
19. Every weather observation predates or equals its decision timestamp.
20. Every rolling feature uses laps strictly below its decision lap.
21. No current-lap timing field exists in decision features.
22. No current-lap quality field exists in decision features.
23. No feature column exists outside the declared allowlist.
24. All three temporal folds cover all 68 sessions exactly once.
25. `splits.parquet` contains exactly 204 rows.
26. All file hashes match their manifests.
27. Catalog totals match session manifests.
28. Contract versions equal `1.0`.

## Explicitly unavailable V1 features

The following concepts are not stored as V1 decision features:

- Scheduled race laps
- Scheduled laps remaining
- Grid position
- Live gap to the driver ahead
- Live gap to the driver behind
- Traffic density
- Net pit loss
- Future safety-car probability
- Future rainfall
- Final race length
- Final race status
- Final classification

They are omitted because their processed, decision-time-safe source is not yet
available or their estimator belongs to a later modelling or simulation phase.

Absence is preferable to silently deriving them from future race outcomes.

## PostgreSQL relationship

Phase 4 will design PostgreSQL tables that preserve the identities and semantic
boundaries in this contract.

The database design must not redefine:

- Decision identity
- Feature availability
- Target eligibility
- Historical action meaning
- Pit-duration meaning
- Temporal folds

Database-specific types, indexes, foreign keys and loading behaviour will be
defined separately.

Parquet remains the versioned analytical artifact. PostgreSQL provides
queryable application storage and relational integrity.

## Failure behaviour

Dataset construction fails closed when:

- A source partition is invalid
- A source contract version is unsupported
- A required source column is absent
- A whole-number field contains a fractional value
- A canonical dtype cannot be produced safely
- A decision identity is duplicated
- A label identity is missing or duplicated
- A future weather match is detected
- A forbidden feature is detected
- An evaluation-season partition is encountered
- Stored files fail read-back validation
- A hash differs from the manifest

A failed session must not produce an authoritative partition.

A batch may continue with other sessions, but the final catalog must report the
failure and must not claim complete status.

## Change control

Changes requiring a dataset contract version review include:

- Adding or removing stored columns
- Changing column order
- Changing feature semantics
- Changing decision eligibility
- Changing target eligibility
- Changing temporal folds
- Changing partition identity
- Changing required files
- Changing integrity rules
- Changing source-version compatibility

Clarifications that do not change stored meaning may update this document
without a contract-version bump.

All decisions must remain frozen before protected 2025 evaluation.