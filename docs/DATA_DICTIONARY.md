# F1 Race Strategy Optimizer — Decision-Time Data Dictionary

## Purpose

This document classifies the Formula 1 variables considered for modelling and
defines when each value may be used.

It originated during Phase 1 and was reconciled before Phase 4 to reflect the
completed raw and processed pipelines.

This dictionary provides semantic guidance. The versioned Phase 4 dataset
contract will become the authoritative specification for stored decision rows,
features, targets and temporal splits.

## Decision timestamp

A decision occurs at the start of lap `t`.

For that decision, the system may use:

- Information known before the race
- Current state already known when lap `t` begins
- Historical information from completed laps up to lap `t - 1`

It must not use information generated during lap `t` or any later lap.

A value appearing on the historical source row for lap `t` is not automatically
safe. The dataset builder must prove that the value existed before the decision
timestamp.

## Usage classifications

| Classification | Meaning |
|---|---|
| Safe input | Known before the decision and permitted as a model feature |
| Conditional input | Permitted only when reconstructed exclusively from past information |
| Identifier or metadata | Preserved for traceability but not automatically a model feature |
| Target or label only | Created from information observed after the decision |
| Cleaning only | Used to assess target quality or construct an analytical population |
| Forbidden input | Contains future or evaluation information and must never be a prediction feature |

Time availability and modelling usefulness are separate questions. A variable
may be known at decision time while still being unsuitable because it creates
memorisation, instability or poor generalisation.

## Canonical decision identity

One Phase 4 decision row represents one driver at the start of one race lap.

Its proposed identity is:

```text
season + round_number + session_type + driver + decision_lap
```

For race sessions, `session_type` is `R`.

The decision identity must be unique in every stored dataset partition.

The decision lap is the lap the driver is about to begin. Therefore, historical
lap features for a decision on lap `t` may use only laps numbered below `t`.

## Separate analytical populations

Phase 4 must keep the following analytical populations distinct.

### Decision-row population

The decision-row population contains moments at which the system could
meaningfully compare pitting now with staying out.

Decision-row eligibility may consider whether:

- The driver has started the race
- A valid decision lap and driver identity exist
- Required pre-decision state can be reconstructed
- The race is still active for the driver
- The decision occurs under conditions supported by the first simulator
- Sufficient historical context exists for required rolling features

A decision row may still be valid even when lap `t` later becomes inaccurate,
interrupted or otherwise unsuitable as a lap-time target.

### Lap-time target population

The lap-time target population contains laps whose observed lap time is suitable
for supervised lap-performance modelling.

Phase 3 `IsEligible` and `ExclusionReasons` describe this target-quality
population.

`IsEligible(t)` must never be used as an input feature for the decision at the
start of lap `t`, because it depends on events that occur during that lap.

### Historical-action population

The historical-action population records whether the driver actually entered
the pits during lap `t`.

This label is useful for:

- Describing historical behaviour
- Comparing model recommendations with observed decisions
- Evaluating action-classification baselines
- Auditing decision coverage

It is not proof that the historical action was optimal.

### Pit-duration population

The pit-duration population contains complete, dry and sufficiently
uninterrupted pit events accepted by the Phase 3 candidate rules.

Observed pit-lane duration is a historical measurement. It is not automatically
the net race-time loss caused by a pit stop.

## Identity and metadata variables

| Variable | Availability | Classification | Phase 4 rule |
|---|---|---|---|
| `Season` / `season` | Known before the decision | Identifier or metadata | Preserve for identity, temporal splitting and auditing |
| `RoundNumber` / `round_number` | Known before the decision | Identifier or metadata | Preserve as part of race identity |
| `SessionType` / `session_type` | Known before the decision | Identifier or metadata | Must be `R` for the current scope |
| `EventName` / `event_name` | Known before the decision | Identifier or metadata | Preserve for reporting; any model use must be explicit |
| `Driver` / `driver` | Known before the decision | Identifier or metadata | Preserve for identity; model use requires justification |
| `DriverNumber` | Known before the decision | Identifier or metadata | Do not use as a numeric feature |
| `Team` / `team` | Known before the decision | Conditional input | May encode car or team effects, but must be evaluated for memorisation |
| `SourceRowNumber` | Pipeline provenance | Identifier or metadata | Preserve only for traceability |
| `LapNumber` | Known at the decision | Identifier or metadata | Becomes `decision_lap`; do not confuse it with a completed lap |
| `pit_event_id` | Created after reconstruction | Identifier or metadata | Preserve for pit-event traceability |
| `stint_number` | Historical source state | Conditional input | Current decision stint must be reconstructed from earlier evidence |

Identifiers must not silently enter a numerical feature matrix.

## Pre-race variables

| Variable or concept | Classification | Rule |
|---|---|---|
| Circuit or event identity | Conditional input | Known before the race; model encoding must support held-out-race evaluation |
| Scheduled race laps | Safe input | Use the scheduled value known before the decision |
| Scheduled laps remaining | Safe input | Derive from scheduled laps and `decision_lap` |
| Actual final race length | Forbidden input | May be changed by later race events |
| Starting grid position | Safe input | Permitted when sourced from information known before the start |
| Driver identity | Identifier or metadata | May be retained for analysis; model use requires explicit justification |
| Team identity | Conditional input | Permitted only with documented encoding and generalisation checks |
| Final classification | Forbidden input | Determined after the decision |
| Final points | Forbidden input | Determined after the race |
| Final status | Forbidden input | Determined after the decision |
| Total completed laps | Forbidden input | Future race outcome |
| Winner or podium status | Forbidden input | Future race outcome |

## Lap timing and performance variables

| Processed variable | Classification at decision lap `t` | Rule |
|---|---|---|
| `LapTime` | Target or label only for lap `t` | May be a feature only for completed laps below `t` |
| `LapTimeSeconds` | Target or label only for lap `t` | Canonical numerical lap-time target when eligible |
| `Sector1Time` | Target or label only for lap `t` | Historical sectors may be used only from completed earlier laps |
| `Sector2Time` | Target or label only for lap `t` | Historical sectors may be used only from completed earlier laps |
| `Sector3Time` | Target or label only for lap `t` | Historical sectors may be used only from completed earlier laps |
| `Sector1TimeSeconds` | Target or label only for lap `t` | Never copy the current-lap value into decision features |
| `Sector2TimeSeconds` | Target or label only for lap `t` | Never copy the current-lap value into decision features |
| `Sector3TimeSeconds` | Target or label only for lap `t` | Never copy the current-lap value into decision features |
| `Sector1SessionTime` | Forbidden input for lap `t` | Generated during the current lap |
| `Sector2SessionTime` | Forbidden input for lap `t` | Generated during the current lap |
| `Sector3SessionTime` | Forbidden input for lap `t` | Generated during the current lap |
| `Time` | Forbidden input when it marks current-lap completion | Use only an explicitly defined pre-decision timestamp |
| `SpeedI1` | Target or label only for lap `t` | Historical values may be aggregated from earlier laps |
| `SpeedI2` | Target or label only for lap `t` | Historical values may be aggregated from earlier laps |
| `SpeedFL` | Target or label only for lap `t` | Historical values may be aggregated from earlier laps |
| `SpeedST` | Target or label only for lap `t` | Historical values may be aggregated from earlier laps |
| `IsPersonalBest` | Forbidden input for lap `t` | Depends on the completed current lap |

Historical timing features must use an explicit lag or rolling window ending at
lap `t - 1`.

Examples include:

- Previous eligible lap time
- Median of the latest three eligible completed laps
- Median of the latest five eligible completed laps
- Recent lap-time trend
- Historical sector summaries
- Number of valid historical observations
- Laps since the last completed pit exit

Every rolling feature must document:

- Its source column
- Its window
- Its minimum required history
- Its missing-value behaviour
- Its strict upper bound of lap `t - 1`

## Tyre and stint variables

| Processed variable | Classification | Rule |
|---|---|---|
| `Compound` on lap `t` | Conditional input | Do not copy blindly; reconstruct the compound fitted before lap `t` begins |
| `TyreLife` on lap `t` | Conditional input | Reconstruct tyre age at the decision timestamp |
| `FreshTyre` on lap `t` | Conditional input | Use only if known from the current fitted set before the lap |
| `Stint` on lap `t` | Conditional input | Reconstruct current stint using evidence available before the decision |
| Reconstructed `compound` | Conditional input | May describe the decision-time tyre state |
| Reconstructed `start_tyre_life` | Conditional input | May support past-stint analysis |
| Reconstructed `end_tyre_life` | Cleaning or analysis only | Not available before earlier decisions within that stint |
| `start_lap` | Identifier or metadata | May derive current stint length when the stint has already started |
| `end_lap` | Forbidden input for an active stint | Known only after the stint ends |
| `recorded_laps` | Forbidden input for an active stint | Final stint length is future information |
| `is_last_stint` | Forbidden input | Depends on later race events |
| `is_complete` | Cleaning only | Used to select reliable historical stint records |
| `warnings` | Cleaning only | Must not enter a prediction feature matrix |
| `warning_count` | Cleaning only | Must not enter a prediction feature matrix |

The decision-time tyre state must be derived from past lap and pit evidence.
Historical source values attached to lap `t` may be used only after their
timestamp semantics are verified.

## Pit variables

| Variable | Classification at decision lap `t` | Rule |
|---|---|---|
| `PitInTime` on lap `t` | Target or label only | Indicates the observed historical pit action during lap `t` |
| `PitOutTime` on lap `t` | Forbidden input | Occurs after the decision |
| `pit_in_lap` | Target or label only for the corresponding decision | Used to construct historical action labels |
| `pit_out_lap` | Historical metadata after completion | May be used only for later decisions |
| `pit_in_time_seconds` | Target or label only for the current event | Generated after the decision |
| `pit_out_time_seconds` | Target or label only for the current event | Generated after the decision |
| `observed_pit_lane_duration_seconds` | Target or analysis only | Historical pit-duration measurement |
| `compound_before` | Conditional input | Safe only if reconstructed before the decision |
| `compound_after` | Forbidden input for a pit-now decision | The fitted compound may not yet be observed |
| `is_stint_change` | Cleaning or analysis only | Determined using the completed pit event |
| `is_compound_change` | Cleaning or analysis only | Determined after the stop |
| `is_complete` | Cleaning only | Selects reconstructable pit events |
| `is_duration_analysis_candidate` | Cleaning only | Selects the Phase 3 pit-duration population |
| Pit-event `warnings` | Cleaning only | Audit information, not model input |

Historical circuit-specific pit-duration estimates may be derived only from
events allowed by the active training fold.

A 2024 decision row must not use a pit-duration estimate calculated from other
2024 races when the evaluation design treats 2024 as the validation season.

## Position, traffic and race-state variables

| Variable or concept | Classification | Rule |
|---|---|---|
| `Position` on lap `t` | Forbidden input when it is the end-of-lap position | Reconstruct decision position from information available through lap `t - 1` |
| Position after lap `t - 1` | Conditional input | Permitted when timestamp semantics are explicit |
| Gap to driver ahead | Conditional input | Use only if reconstructable at or before the decision |
| Gap to driver behind | Conditional input | Use only if reconstructable at or before the decision |
| Traffic density | Conditional input | Must use only current or historical gaps available before the lap |
| Future overtakes | Forbidden input | Occur after the decision |
| Future retirements | Forbidden input | Occur after the decision |
| Future safety-car periods | Forbidden input | Occur after the decision |
| Final finishing position | Forbidden input | Race outcome |
| Actual remaining race laps | Forbidden input | Depends on future race duration |

The Phase 4 dataset contract may omit traffic features if their timing cannot be
verified reliably.

## Track-status variables

| Processed variable | Classification | Rule |
|---|---|---|
| `TrackStatus` on lap `t` | Conditional input | Do not assume the row value represents only the start of the lap |
| Latest known status before `LapStartTime(t)` | Conditional input | Permitted if reconstructed from timestamped historical evidence |
| Status changes during lap `t` | Forbidden input | Occur after the decision |
| `is_green_flag_pair` | Cleaning or analysis only | Describes a completed pit event |
| `is_interrupted_duration` | Cleaning only | Derived after a completed pit event |
| `NON_GREEN_TRACK` exclusion reason | Cleaning only | Describes target-lap quality, not decision-time state |

The initial simulator may restrict decision rows to reconstructable normal
green-flag conditions. Such filtering is decision eligibility, not a model
feature.

## Weather variables

Phase 3 aligns weather observations backward to lap start times without future
weather leakage. Phase 4 must still perform decision-time alignment explicitly
for each decision row.

| Processed variable | Classification | Rule |
|---|---|---|
| `WeatherObservationTime` | Identifier or metadata | Must be at or before the decision timestamp |
| `AirTemp` | Conditional input | Use the latest observation available by the decision |
| `Humidity` | Conditional input | Use the latest observation available by the decision |
| `Pressure` | Conditional input | Use the latest observation available by the decision |
| `Rainfall` | Conditional input | Use only rainfall already observed by the decision |
| `TrackTemp` | Conditional input | Use the latest observation available by the decision |
| `WindDirection` | Conditional input | Use the latest observation available by the decision |
| `WindSpeed` | Conditional input | Use the latest observation available by the decision |
| `WeatherMatched` | Cleaning only | Required for weather provenance validation |
| `WeatherAgeSeconds` | Conditional input | May be retained as an observation-staleness feature or quality indicator |
| Future rainfall | Forbidden input | Must not influence the current decision |
| Future temperature | Forbidden input | Must not influence the current decision |

Every accepted weather match must satisfy:

```text
WeatherObservationTime <= decision timestamp
```

The dataset builder must record or validate the weather observation age.

## Quality and provenance variables

| Processed variable | Classification | Rule |
|---|---|---|
| `Deleted` | Cleaning only | Describes source-lap validity |
| `DeletedReason` | Cleaning only | Describes why a source lap was deleted |
| `FastF1Generated` | Cleaning only | Identifies a generated source lap |
| `IsAccurate` | Cleaning only for lap `t` | May select lap-time targets but must not be a current-decision input |
| `QualityFlags` | Cleaning only | Audit information |
| `ExclusionReasons` | Cleaning only | Audit information |
| `QualityFlagCount` | Cleaning only | Must not enter the feature matrix |
| `ExclusionReasonCount` | Cleaning only | Must not enter the feature matrix |
| `IsEligible` | Cleaning only | Selects lap-time targets; never a decision feature |
| Stint warnings | Cleaning only | Select reliable historical stints |
| Pit warnings | Cleaning only | Select reliable historical pit events |
| Manifest hashes | Identifier or metadata | Used for integrity and reproducibility |
| Contract versions | Identifier or metadata | Stored with dataset artifacts |
| Source partition path | Identifier or metadata | Preserved for lineage |

Quality fields may be used when constructing past-only aggregates. For example,
the builder may exclude an inaccurate lap from a rolling historical median after
that lap has been completed and its quality is known.

They must not reveal the quality of the lap that has not happened yet.

## Candidate Phase 4 feature families

The exact stored feature list will be frozen in the Phase 4 dataset contract.

Candidate decision-time feature families are:

### Race context

- Season
- Round number or circuit encoding
- Decision lap
- Scheduled laps remaining
- Driver and team encodings when justified

### Current tyre state

- Reconstructed current compound
- Reconstructed tyre age
- Current stint length
- Compounds already used before the decision
- Number of completed stops

### Historical lap performance

- Previous eligible lap time
- Rolling median lap time
- Rolling lap-time variability
- Recent lap-time trend
- Historical sector summaries
- Count of valid prior observations

### Decision-time conditions

- Latest available air temperature
- Latest available track temperature
- Latest available humidity
- Latest available pressure
- Latest available wind information
- Rainfall already observed
- Weather observation age
- Reconstructed track condition

### Historical pit context

- Circuit-specific historical pit-duration estimate
- Uncertainty or sample count for that estimate
- Driver’s number of completed stops
- Previous-stop timing when already observed

No candidate becomes authoritative until the dataset contract defines its exact
source, type, nullability and construction rule.

## Targets and labels

### Lap-performance target

The primary supervised lap-performance target is expected to be:

```text
LapTimeSeconds(t)
```

It may be used only when lap `t` satisfies the frozen target-quality rules.

The target must never appear in the feature columns of its own row.

### Historical pit-action label

A diagnostic historical action label may be defined as:

```text
PIT_NOW if the driver enters the pit lane during lap t
STAY_OUT otherwise
```

This label describes what happened. It does not establish the
counterfactually optimal choice.

### Pit-duration target

For accepted historical pit events, the measured target is:

```text
observed_pit_lane_duration_seconds
```

This target supports pit-duration analysis. It must not be renamed or
interpreted as net race-time loss.

### Strategy recommendation target

There is no directly observed historical label proving whether `PIT_NOW` or
`STAY_OUT` was optimal.

The final recommendation must be produced by comparing simulated expected
remaining race times under explicitly defined assumptions.

## Forbidden-input summary

The following information must never enter a start-of-lap feature vector:

- Lap time from lap `t` or any later lap
- Sector time from lap `t` or any later lap
- Speed measurements generated during lap `t`
- Pit entry or pit exit information generated during or after lap `t`
- Compound fitted after a future stop
- End lap or final length of the active stint
- Position produced at the end of lap `t`
- Future track-status changes
- Future weather observations
- Future safety-car or red-flag periods
- Future retirements or incidents
- Final result, points, status or race length
- Current-lap `IsAccurate`
- Current-lap `IsEligible`
- Current-lap exclusion reasons
- Validation or evaluation targets
- Statistics calculated using validation or protected evaluation races

Any feature whose availability cannot be proven must be treated as forbidden
until its semantics are resolved.

## Missing-value rules

Missing values must not be silently replaced with information from the future.

Permitted approaches include:

- Leaving a value nullable
- Adding a missingness indicator
- Using a constant learned without evaluation data
- Using a statistic fitted only on the active training fold
- Marking the decision row ineligible when a required state cannot be reconstructed

Forward filling is permitted only when:

- The source observation predates the decision
- The variable remains semantically valid
- The maximum permitted age is documented
- No later observation is used

Backward filling across time is forbidden.

## Temporal separation

Development interfaces must use only the 2022–2024 processed partitions.

The protected 2025 temporal evaluation holdout must not influence:

- Feature definitions
- Eligibility rules
- Missing-value strategies
- Statistical thresholds
- Category encodings
- Pit-duration estimates
- Model selection
- Hyperparameters
- Simulator calibration

The frozen development folds are:

| Fold | Training seasons | Validation season |
|---|---|---|
| Development fold 1 | 2022 | 2023 |
| Development fold 2 | 2022–2023 | 2024 |
| Final development fit | 2022–2024 | None |

Splits must occur by complete race session. Random lap-level splitting is
forbidden.

The limited Phase 1 schema inspection of the 2025 Japanese Grand Prix remains
disclosed. No Phase 4 development interface may process or explore 2025.

## Dataset-builder audit requirements

For every generated decision dataset, Phase 4 must verify:

1. Decision identities are unique.
2. Every source session belongs to an allowed development season.
3. No 2025 partition is accessed.
4. Every historical rolling window ends at lap `t - 1`.
5. Every weather observation occurs at or before the decision timestamp.
6. Current-lap timing and sector values are absent from features.
7. Current-lap quality fields are absent from features.
8. Decision eligibility and lap-target eligibility are stored separately.
9. Historical action labels are not described as optimal decisions.
10. Pit-lane duration is not described as net pit loss.
11. Training statistics are fitted only on the active training fold.
12. Complete races remain together during splitting.
13. Feature columns and target columns are explicitly enumerated.
14. Stored dtypes and nullability match the dataset contract.
15. Source contract versions and lineage are recorded.

A dataset that fails any leakage or identity check must not be written as a
valid Phase 4 artifact.

## Authority and change control

This dictionary records the semantic boundary established before Phase 4.

The forthcoming dataset contract will freeze:

- Dataset names
- Stored schemas
- Feature columns
- Target and label columns
- Eligibility columns
- Dtypes
- Nullability
- Partition layout
- Temporal split assignments
- Integrity rules
- Versioning rules

If implementation evidence contradicts this dictionary, the conflict must be
resolved explicitly before the dataset contract is frozen. The code must not
quietly invent a different meaning.