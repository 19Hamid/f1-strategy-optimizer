# Formula 1 Data Cleaning Rules

## Purpose

This document defines how raw Formula 1 race data will be transformed into
reliable analysis-ready data.

The cleaning process must be deterministic, reproducible and auditable. Raw
records will never be modified or silently removed.

## Scope

Version one focuses on:

- Completed Formula 1 races
- Seasons 2022 to 2025
- Race sessions only
- Dry-weather conditions
- Normal green-flag racing
- Public FastF1 timing, tyre, pit-stop and weather data

Detailed telemetry remains optional and on demand.

## Dataset separation

The seasons have different purposes:

- Development and exploration: 2022 to 2024
- Final evaluation: 2025

Cleaning rules, eligibility rules and outlier decisions must be developed using
only the 2022 to 2024 races.

The 2025 season must not be explored or used to change cleaning decisions.
After the rules are frozen, they may be applied unchanged to the 2025 data for
final evaluation.

## Raw-data protection

Files under `data/raw/fastf1` are immutable source records.

The cleaning pipeline must:

- Never edit raw Parquet or JSON files
- Never replace raw values in place
- Write cleaned outputs under `data/processed`
- Preserve season, round and session provenance
- Record all exclusions and their reasons
- Produce identical results from identical inputs

## Cleaning principle

Records should be flagged before they are excluded.

A suspicious record must remain traceable to its original session, driver and
lap. Statistical outliers must not be removed automatically without a
documented reason.

## Required lap identity

Every lap must retain:

- Season
- Round number
- Session type
- Event name
- Driver
- Team
- Lap number

A lap without a valid session, driver or lap identity cannot be used for
analysis.

## Standardized values

The cleaning pipeline will normalize:

- Session types to uppercase
- Driver abbreviations to uppercase
- Team names to consistent text
- Tyre compounds to uppercase
- Boolean fields to consistent boolean values
- Lap and sector times to seconds
- Temperature values to degrees Celsius
- Distances to metres
- Speed values to kilometres per hour

Original source columns must remain available where appropriate.

## Supported dry compounds

The initial dry compounds are:

- SOFT
- MEDIUM
- HARD

INTERMEDIATE and WET tyres identify wet-running conditions and are not eligible
for the controlled version-one analysis.

Unknown or missing compounds must be flagged.

## Track-condition classification

The initial FastF1 track-status interpretation is:

- `1`: normal green-flag racing
- `2`: yellow-flag condition
- `4`: safety car
- `5`: red flag
- `6`: virtual safety car deployed
- `7`: virtual safety car ending

Only normal green-flag laps are initially eligible for version one.

Unknown, missing or combined track-status values must be preserved and flagged
for investigation rather than guessed.

## Weather classification

A lap must be flagged as wet when information available at that time indicates:

- Rainfall was recorded
- The driver used INTERMEDIATE tyres
- The driver used WET tyres

Weather must be joined to laps using the latest observation available at or
before the relevant lap timestamp.

Future weather observations must never be joined backward into an earlier race
decision.

## Lap-quality flags

The cleaning pipeline must be able to assign the following reason codes:

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

A lap may have more than one reason code.

Missing sector times should be recorded but should not automatically make a lap
unusable when total lap time remains valid.

## Initially eligible modelling lap

A lap is initially eligible for controlled lap-time analysis when:

- Its identity fields are complete
- It is not duplicated
- Lap time exists and is positive
- FastF1 marks it as accurate
- It is not the first lap of the race
- It is not a pit-entry lap
- It is not a pit-exit lap
- It occurred under normal green-flag conditions
- No rain was recorded
- It used SOFT, MEDIUM or HARD tyres
- Tyre life exists and is valid

These rules may only be changed after documented investigation of the
development seasons.

## Duplicate handling

An exact duplicate must be identified using its session, driver and lap number.

Duplicates must be reported before one copy is retained. Conflicting records
with the same identity must not be resolved automatically and must instead be
reported as a data-quality error.

## Missing-value handling

Missing values must not be replaced merely to make a table appear complete.

The pipeline must:

- Preserve legitimate missing values
- Report missingness by column and session
- Distinguish optional fields from required fields
- Avoid filling target values such as lap time
- Document any future imputation method

## Outlier handling

No lap will be excluded only because it is far from the overall average.

Potential outliers will first be investigated using relevant context such as:

- Circuit
- Season
- Driver
- Team
- Tyre compound
- Tyre age
- Stint
- Pit activity
- Track status
- Weather
- Race progress

Any final outlier threshold must be justified and documented using only the
development data.

## Tyre-stint reconstruction

A stint must preserve:

- Session identity
- Driver
- Stint number
- Compound
- Starting lap
- Ending lap
- Number of recorded laps
- Starting tyre life
- Ending tyre life
- Whether the stint is complete
- Any detected consistency problems

Compound changes and pit records must be checked against stint boundaries.

## Pit-stop reconstruction

A pit-stop record should identify:

- Session
- Driver
- Pit-entry lap
- Pit-exit lap
- Compound before the stop
- Compound after the stop
- Available pit-entry and pit-exit timestamps
- Any estimated pit-lane time loss
- Any reconstruction warning

Pit-loss estimation remains exploratory during Phase 3 and is not yet a final
simulation parameter.

## Decision-time leakage rule

The future pit-decision system will make a recommendation at the start of lap
`t`.

Inputs for that decision may only contain information available before lap `t`
begins.

Examples:

- Results from laps before `t` may be used
- Current compound and known tyre age may be used
- Weather observed before lap `t` may be used
- The lap time of lap `t` may be a prediction target
- Events occurring during or after lap `t` may not be input features

## Intermediate outputs

Phase 3 may produce the following development-only analysis tables:

- Clean laps
- Excluded or flagged laps
- Reconstructed tyre stints
- Reconstructed pit stops
- Weather-aligned laps
- Session-quality summaries

These are intermediate analytical outputs. Final modelling datasets and the
database design belong to Phase 4.

## Quality reporting

Each cleaning run must report:

- Input row count
- Output row count
- Eligible row count
- Flagged row count
- Excluded row count
- Counts for every reason code
- Missing values by important column
- Sessions containing validation failures
- Cleaning-rule version
- Source-data contract version

## Testing requirements

Automated tests must cover:

- Deterministic cleaning
- Raw-data immutability
- Duplicate detection
- Missing required values
- Track-status classification
- Wet-condition classification
- Pit-lap classification
- Tyre-stint reconstruction
- Weather alignment
- Decision-time leakage prevention
- Quality-report counts

Warnings must continue to be treated as errors.

## Phase 3 acceptance criteria

Phase 3 is complete when:

1. Development data from 2022 to 2024 can be cleaned reproducibly.
2. Every excluded record has a documented reason.
3. Race conditions and pit laps are classified consistently.
4. Tyre stints and pit stops can be reconstructed.
5. Weather is aligned without future leakage.
6. Important data patterns and limitations are documented.
7. The 2025 evaluation season has not influenced development decisions.
8. Automated tests and code-quality checks pass.
9. Cleaned outputs and reports can be recreated from the immutable raw data.