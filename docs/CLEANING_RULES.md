# Formula 1 Data Cleaning Rules

## Purpose

This document defines version 1.0 of the rules used to transform immutable raw
Formula 1 race data into reliable processed development data.

The process is deterministic, reproducible and auditable. Raw records are never
modified or silently removed.

## Scope

Version 1.0 focuses on:

- Completed Formula 1 races
- Development seasons 2022 to 2024
- Race sessions only
- Dry-weather conditions
- Normal green-flag racing
- Public FastF1 timing, tyre, pit-stop and weather data

Detailed telemetry remains optional and on demand.

The rules may later be applied unchanged to the protected 2025 evaluation
season.

## Dataset separation

The seasons have different purposes:

- Development and exploration: 2022 to 2024
- Final unseen evaluation: 2025

All cleaning, eligibility, outlier and interpretation decisions were developed
using only 2022–2024.

The 2025 season must not be explored or used to revise these rules.

## Versioning

The frozen cleaning-rule version is:

```text
1.0
```

A change to eligibility, exclusion reasons, weather interpretation, stint
completeness or pit-event classification requires a cleaning-version review
and, when outputs change, a new version.

## Raw-data protection

Files beneath `data/raw/fastf1` are immutable.

The cleaning pipeline must:

- Never edit raw Parquet or JSON files
- Never replace raw values in place
- Preserve every raw lap row
- Write processed outputs beneath `data/processed`
- Preserve session, driver and lap provenance
- Record every exclusion reason
- Produce identical results from identical inputs

## Cleaning principle

Records are flagged before exclusion.

A suspicious record remains traceable to its raw session, driver and lap.

Statistical unusualness alone is not an exclusion reason.

## Required lap identity

Every lap should retain:

- Season
- Round number
- Session type
- Event name
- Driver
- Team
- Lap number
- Source row number

A lap without valid session, driver or lap identity is preserved but cannot be
eligible.

## Standardized values

The pipeline normalizes:

- Session types to uppercase
- Driver abbreviations to uppercase
- Team text consistently
- Tyre compounds to uppercase
- Boolean fields to consistent boolean semantics
- Lap and sector times to seconds
- Temperature values to degrees Celsius
- Speed values to kilometres per hour

Original source columns remain available where appropriate.

## Supported dry compounds

Supported version-one compounds are:

- SOFT
- MEDIUM
- HARD

INTERMEDIATE and WET identify wet-running conditions and are ineligible for
controlled version-one analysis.

Unknown, absent and normalized `NONE` compounds are flagged.

## Track-condition classification

FastF1 track-status codes are interpreted as:

- `1`: normal green
- `2`: yellow
- `4`: safety car
- `5`: red flag
- `6`: virtual safety car deployed
- `7`: virtual safety car ending

Only a status exactly equal to `1` is eligible.

Combined, missing or unknown values are preserved and flagged rather than
guessed.

## Weather classification

A lap is wet when information available at that time indicates:

- Rainfall was recorded
- INTERMEDIATE tyres were used
- WET tyres were used

Weather is joined using the latest observation at or before the lap timestamp.

Future observations must never be joined backward.

## Lap-quality codes

Version 1.0 supports:

- `MISSING_IDENTITY`
- `DUPLICATE_LAP`
- `MISSING_LAP_TIME`
- `NON_POSITIVE_LAP_TIME`
- `INACCURATE_LAP`
- `FIRST_LAP`
- `PIT_IN_LAP`
- `PIT_OUT_LAP`
- `NON_GREEN_TRACK`
- `WET_CONDITION`
- `MISSING_COMPOUND`
- `UNSUPPORTED_COMPOUND`
- `INVALID_TYRE_LIFE`
- `MISSING_SECTOR_TIME`
- `UNKNOWN_TRACK_STATUS`

A lap may have multiple codes.

Missing sector times are recorded but do not independently make a lap unusable
when total lap time remains valid.

## Eligible modelling lap

A lap is eligible only when:

- Required identity fields are complete
- Its analytical identity is not duplicated
- Lap time exists and is positive
- FastF1 marks it as accurate
- It is not lap one
- It is not a pit-entry lap
- It is not a pit-exit lap
- Track status is exactly normal green
- Backward-aligned weather reports no rain
- Compound is SOFT, MEDIUM or HARD
- Tyre life exists and is valid

## Duplicate handling

Duplicates are identified using session, driver and lap number.

Every source row remains stored.

A conflicting duplicate is not resolved automatically. All affected rows are
flagged and made ineligible.

## Missing values

Missing values are not replaced merely to make a table complete.

The pipeline must:

- Preserve legitimate missing values
- Report important missingness
- Distinguish optional and required fields
- Never impute lap-time targets during cleaning
- Never guess compound or tyre life
- Document any later modelling-stage imputation

## Frozen statistical-outlier policy

The final Phase 3 policy is:

```text
FLAG_ONLY
```

Potential lap-time outliers are investigated within session, driver and
compound context.

Exploration version 1.0 uses:

- At least 5 contextual laps
- Context median
- Median absolute deviation
- Absolute robust-score threshold of 6.0
- A shared cluster indicator at 5 drivers

These values create exploratory indicators only.

They do not:

- Change `IsEligible`
- Create an exclusion reason
- Delete a lap
- Impute a lap time
- Prove that a value is erroneous

## Restart-like laps

Development exploration found shared slow-lap clusters around some restart,
traffic-compression and changing-condition periods.

No deterministic restart exclusion was added because the available processed
fields could not identify every restart reliably without manual event
blacklists or future knowledge.

Restart-like statistical extremes remain flagged for investigation.

## Tyre-stint reconstruction

A stint preserves:

- Session identity
- Driver
- Team
- Stint number
- Compound
- Starting and ending lap
- Number of recorded laps
- Starting and ending tyre life
- First- and last-stint indicators
- Boundary evidence
- Completeness
- Warnings

Compound changes and pit evidence are checked against stint boundaries.

Missing or contradictory information is warned rather than invented.

## Stint warnings

Version 1.0 supports:

- `TEAM_CONFLICT`
- `MISSING_COMPOUND`
- `UNSUPPORTED_COMPOUND`
- `MULTIPLE_COMPOUNDS`
- `MISSING_TYRE_LIFE`
- `INVALID_TYRE_LIFE`
- `TYRE_LIFE_DECREASE`
- `TYRE_LIFE_STEP_MISMATCH`
- `LAP_NUMBER_GAP`
- `DISJOINT_STINT`
- `NON_SEQUENTIAL_STINT`
- `MISSING_PIT_EVIDENCE_BEFORE`
- `MISSING_PIT_EVIDENCE_AFTER`

## Pit-event reconstruction

Pit reconstruction preserves:

- Session identity
- Driver and team
- Event type
- Pit-entry and pit-exit laps
- Stints before and after
- Compounds before and after
- Tyre life before and after
- Available timing markers
- Observed pit-lane duration
- Track and weather context
- Completeness and warnings

Matched, entry-only and exit-only events are retained.

All source pit markers must be accounted for.

## Pit-event warnings

Version 1.0 supports:

- `ENTRY_ONLY`
- `EXIT_ONLY`
- `NO_STINT_CHANGE`
- `TEAM_CONFLICT`
- `MISSING_COMPOUND_BEFORE`
- `MISSING_COMPOUND_AFTER`
- `UNSUPPORTED_COMPOUND_BEFORE`
- `UNSUPPORTED_COMPOUND_AFTER`
- `NON_GREEN_ENTRY`
- `NON_GREEN_EXIT`
- `NON_ADJACENT_LAPS`
- `NON_POSITIVE_DURATION`
- `INTERRUPTED_DURATION`

## Pit-duration decision

Observed pit-lane duration remains exploratory.

It is not treated as:

- Stationary service time
- Net race-time loss
- Counterfactual pit loss
- A final simulator constant

Development event medians ranged materially, including approximately 18.1
seconds in Australia and 36.8 seconds in France.

Future pit-loss estimation must therefore retain circuit context.

## Decision-time leakage

The future recommendation is made at the start of lap `t`.

Inputs may contain only information available before lap `t` begins.

Examples:

- Completed earlier laps may be used
- Current known compound and tyre age may be used
- Earlier weather observations may be used
- Lap `t` time may be a target
- Events during lap `t` may not be inputs
- Later laps and final race results may not be inputs

Processed tables are not automatically safe model-feature tables. Phase 4 must
construct decision-time rows explicitly.

## Intermediate outputs

Phase 3 produces:

- Weather-aligned processed laps
- Quality and exclusion indicators
- Reconstructed tyre stints
- Reconstructed pit events
- Session quality reports
- Integrity manifests
- Batch run records
- A verified processed catalog
- In-memory development exploration summaries
- Potential contextual outlier tables

Final modelling datasets and database tables belong to Phase 4.

## Known data limitations

Version 1.0 records these limitations:

- `LapStartDate` is null for all 74,601 development laps
- Two development races contain zero eligible dry laps
- Compound summaries are confounded by race context
- Observed pit duration is not final pit loss
- Some restart-like conditions cannot be classified deterministically
- Fuel load is not directly observed
- Traffic and driver intent are incompletely represented
- Wet and safety-car strategy are outside version one

## Quality reporting

Each processed session reports:

- Input lap count
- Eligible and excluded counts
- Counts for every reason
- Weather matching results
- Maximum weather age
- Stint counts and warnings
- Pit-event counts and warnings
- Duration-analysis candidates
- Contract versions
- Preservation and validation status

## Testing requirements

Automated tests cover:

- Deterministic profiling
- Raw-row preservation
- Duplicate detection
- Missing required values
- Track-status classification
- Wet-condition classification
- Pit-lap classification
- Backward-only weather alignment
- Tyre-stint reconstruction
- Pit-event reconstruction
- Processed count reconciliation
- Atomic storage
- Checksums and integrity verification
- Resume-before-raw-access behaviour
- Batch failure isolation
- Catalog uniqueness
- CLI season protection
- Statistical flag-only behaviour
- Protected evaluation-season rejection

Warnings are treated as errors.

## Phase 3 acceptance criteria

Phase 3 is complete because:

1. All 68 development races can be cleaned reproducibly.
2. Every excluded lap has documented reasons.
3. Race conditions and pit laps are classified consistently.
4. Tyre stints and pit events are reconstructed.
5. Weather alignment produced zero future matches.
6. Development patterns and limitations are documented.
7. The 2025 season did not influence decisions.
8. Automated checks pass.
9. Outputs can be recreated from immutable raw data.