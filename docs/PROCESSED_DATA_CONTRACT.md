# Formula 1 Processed-Data Contract

## Purpose

This document defines version 1.0 of the processed Formula 1 race-data
contract.

Processed data is derived deterministically from immutable raw FastF1
partitions. It supports development exploration and the later construction of
leakage-safe modelling datasets.

## Versions

The Phase 3 dataset uses:

| Component | Version |
|---|---|
| Raw source-data contract | `1.0` |
| Cleaning rules | `1.0` |
| Processed-data contract | `1.0` |
| Development exploration | `1.0` |

A change to required columns, column meaning, eligibility rules, stored
identities or table invariants requires a new applicable contract or cleaning
version.

## Dataset separation

Phase 3 processes development seasons only:

| Purpose | Seasons | Sessions |
|---|---|---:|
| Development and exploration | 2022–2024 | 68 |
| Protected final evaluation | 2025 | 24 |

The 2025 season is not processed or explored during Phase 3.

Cleaning and exploration interfaces reject unsupported seasons. Version 1.0
rules may be applied unchanged to 2025 only during a later final-evaluation
stage.

## Source immutability

Files beneath `data/raw/fastf1` are immutable source records.

The processed pipeline:

- Never edits raw Parquet or JSON files
- Preserves every raw lap row
- Preserves session, driver and lap provenance
- Records exclusions instead of deleting records
- Writes only beneath `data/processed`
- Produces identical outputs from identical inputs and versions

## Partition layout

Processed sessions use Hive-style partitioning:

```text
data/processed/fastf1/
└── cleaning_version=1.0/
    ├── catalog.parquet
    ├── runs/
    │   └── <run-id>.json
    └── season=2024/
        └── round=01/
            └── session=R/
                ├── laps.parquet
                ├── stints.parquet
                ├── pit_events.parquet
                ├── quality_report.json
                └── manifest.json
```

Temporary and recoverable replacement partitions use `.tmp` and `.backup`
directories below the version root.

## Session identity

The canonical session identifier is:

```text
YYYY-RR-S
```

For the Phase 3 race-only scope, `S` is `R`.

Example:

```text
2024-01-R
```

A partition must contain exactly one season, round, session type and event
name matching its path and manifest.

## Processed lap identity

Every lap preserves:

- `SourceRowNumber`
- `Season`
- `RoundNumber`
- `SessionType`
- `EventName`
- `Driver`
- `Team`
- `LapNumber`

`SourceRowNumber` preserves the row's position in the raw session table.

The analytical lap identity is season, round, session type, driver and lap
number. A duplicated analytical identity is flagged; source rows are still
preserved.

## `laps.parquet`

The processed lap table contains 55 columns.

### Integer columns

- `SourceRowNumber`
- `Season`
- `RoundNumber`
- `WindDirection`
- `QualityFlagCount`
- `ExclusionReasonCount`

### Nullable numeric columns

- `LapNumber`
- `Stint`
- `SpeedI1`
- `SpeedI2`
- `SpeedFL`
- `SpeedST`
- `TyreLife`
- `Position`
- `AirTemp`
- `Humidity`
- `Pressure`
- `TrackTemp`
- `WindSpeed`
- `WeatherAgeSeconds`
- `LapTimeSeconds`
- `Sector1TimeSeconds`
- `Sector2TimeSeconds`
- `Sector3TimeSeconds`

Time-derived numeric columns use seconds. Speed columns use kilometres per
hour. Temperatures use degrees Celsius.

### Duration columns

- `Time`
- `LapTime`
- `PitOutTime`
- `PitInTime`
- `Sector1Time`
- `Sector2Time`
- `Sector3Time`
- `Sector1SessionTime`
- `Sector2SessionTime`
- `Sector3SessionTime`
- `LapStartTime`
- `WeatherObservationTime`

These columns use pandas/Parquet duration semantics and are normalized to
nanosecond resolution during processing.

### Datetime column

- `LapStartDate`

`LapStartDate` is retained for source compatibility. It is null throughout all
74,601 Phase 3 development lap rows and must not currently be used as a
feature.

### Text and source-object columns

- `SessionType`
- `EventName`
- `Driver`
- `DriverNumber`
- `Compound`
- `Team`
- `TrackStatus`
- `Deleted`
- `DeletedReason`
- `QualityFlags`
- `ExclusionReasons`

Session types, driver abbreviations and supported compounds are normalized to
uppercase.

`QualityFlags` and `ExclusionReasons` contain deterministic collections of
reason codes. Consumers must use the accompanying count columns rather than
infer counts from display formatting.

### Boolean columns

- `IsPersonalBest`
- `FreshTyre`
- `FastF1Generated`
- `IsAccurate`
- `Rainfall`
- `WeatherMatched`
- `IsEligible`

Source-derived booleans may be nullable where FastF1 does not provide a value.
`WeatherMatched` and `IsEligible` are non-null processing decisions.

## Lap preservation invariant

For every session:

```text
processed lap rows = raw lap rows
```

No lap is removed during processing.

Each unsuitable lap remains stored with:

- Its source identity
- Applicable quality flags
- Applicable exclusion reasons
- `IsEligible = False`

## Quality flags and exclusions

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

`QualityFlags` contains all detected quality conditions.

`ExclusionReasons` contains the subset that makes the lap ineligible.
`MISSING_SECTOR_TIME` is recorded as a quality flag but does not independently
exclude a lap when total lap time remains valid.

## Eligibility invariant

A lap is eligible for controlled version-one analysis only when:

- Required identity fields exist
- Its analytical identity is not duplicated
- Lap time exists and is positive
- FastF1 marks the lap as accurate
- It is not the first race lap
- It is not a pit-entry lap
- It is not a pit-exit lap
- Track status is exactly normal green
- Backward-aligned weather does not report rain
- Compound is SOFT, MEDIUM or HARD
- Tyre life exists and is valid

For every session:

```text
eligible laps + excluded laps = processed lap rows
```

## Weather alignment

Weather is joined using the latest observation whose timestamp is less than or
equal to the lap timestamp.

The contract forbids:

- Joining future weather backward
- Guessing an unavailable weather observation
- Filling rainfall using later race knowledge
- Using weather after the decision timestamp as an input

Each lap records:

- Whether a weather match exists
- The matched observation time
- The observation age in seconds
- Air, track, humidity, pressure, wind and rainfall values

## `stints.parquet`

The reconstructed stint table contains 20 columns:

- `season`
- `round_number`
- `session_type`
- `event_name`
- `driver`
- `team`
- `stint_number`
- `compound`
- `start_lap`
- `end_lap`
- `recorded_laps`
- `start_tyre_life`
- `end_tyre_life`
- `is_first_stint`
- `is_last_stint`
- `boundary_before_verified`
- `boundary_after_verified`
- `is_complete`
- `warning_count`
- `warnings`

The logical stint identity is:

```text
season + round + session type + driver + stint number
```

A reconstructed stint records its observed lap range, row count, tyre-life
range, compound, boundary evidence and warnings.

Collectively, reconstructed stints must represent every processed lap exactly
once.

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

Warnings are deterministic and auditable. They are not silently corrected.

## `pit_events.parquet`

The pit-event table contains 33 columns:

- `pit_event_id`
- `season`
- `round_number`
- `session_type`
- `event_name`
- `driver`
- `team`
- `event_type`
- `pit_in_lap`
- `pit_out_lap`
- `stint_before`
- `stint_after`
- `compound_before`
- `compound_after`
- `tyre_life_before`
- `tyre_life_after`
- `pit_in_time_seconds`
- `pit_out_time_seconds`
- `observed_pit_lane_duration_seconds`
- `entry_track_status`
- `exit_track_status`
- `is_stint_change`
- `is_compound_change`
- `is_green_flag_pair`
- `is_dry_compound_pair`
- `is_interrupted_duration`
- `is_complete`
- `is_duration_analysis_candidate`
- `warning_count`
- `warnings`
- `entry_rainfall`
- `exit_rainfall`
- `is_dry_weather_pair`

`pit_event_id` is unique within the processed dataset.

Events may be:

- Matched entry and exit
- Entry-only
- Exit-only

The global pit-marker accounting invariant is:

```text
2 × matched events + entry-only events + exit-only events
= source pit-in markers + source pit-out markers
```

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

## Pit-duration meaning

`observed_pit_lane_duration_seconds` is the observed interval between available
pit-entry and pit-exit timing markers.

It is not automatically:

- Stationary service time
- Net racing-time loss
- Counterfactual time loss
- A final simulator parameter

A duration-analysis candidate must be complete, dry, green, uninterrupted and
use supported dry compounds.

Circuit identity must remain attached because pit-lane geometry and speed
limits create materially different duration distributions.

## `quality_report.json`

The quality report must be a JSON object containing:

- `cleaning_rule_version`
- `processed_contract_version`
- `source_contract_version`
- `session`
- `tables`
- `lap_quality`
- `stint_quality`
- `pit_event_quality`
- `validation`

Required validation evidence includes:

- Raw lap preservation
- Future weather match count
- Pit-weather context completeness
- Final validation status

## `manifest.json`

The manifest must be a JSON object containing:

- Contract versions
- Session identity
- Creation timestamp
- Required output files
- Row counts
- File sizes
- SHA-256 checksums

A partition is accepted only after its tables pass Parquet readback comparison
and its manifest is written successfully.

## Atomic storage

Storage follows this sequence:

1. Write to a temporary partition.
2. Read every Parquet table back.
3. Compare restored tables with their sources.
4. Write the quality report.
5. Calculate file sizes and SHA-256 checksums.
6. Write the manifest.
7. Promote the temporary partition atomically.
8. Restore a recoverable backup if replacement fails.

## Integrity verification

A processed partition is valid only when:

- Its directory and manifest exist
- Required files exist
- Contract versions match
- Session identity matches
- File sizes match
- SHA-256 checksums match
- Parquet tables are readable
- Required columns exist
- Row counts reconcile
- Quality-report totals reconcile
- Eligibility totals cover every lap
- Complete pit events contain weather context

## Resumable execution

Before loading raw data, the runner verifies an existing processed partition.

If verification passes:

- The partition is skipped
- Raw files are not read
- Cleaning is not repeated

An invalid existing partition fails closed unless explicit forced replacement
is requested.

## Processed catalog

`catalog.parquet` contains one row per verified development session and these
22 columns:

- `session_id`
- `season`
- `round_number`
- `session_type`
- `event_name`
- `processed_contract_version`
- `cleaning_rule_version`
- `source_contract_version`
- `created_at_utc`
- `laps_rows`
- `eligible_laps`
- `excluded_laps`
- `eligibility_rate`
- `stints_rows`
- `complete_stints`
- `incomplete_stints`
- `pit_events_rows`
- `complete_pit_events`
- `incomplete_pit_events`
- `duration_analysis_candidates`
- `total_size_bytes`
- `session_directory`

The catalog is rebuilt from verified partitions rather than appended.

## Exploration outputs

Exploration version 1.0 produces in-memory tables for:

- Session eligibility
- Dry-compound lap summaries
- Dry-stint summaries
- Circuit-specific pit-duration summaries
- Potential contextual lap-time outliers

Exploration never edits stored processed partitions.

## Statistical outlier contract

The frozen policy is:

```text
FLAG_ONLY
```

Potential outliers are identified within session, driver and compound context
using a robust median absolute deviation score.

Version 1.0 exploratory parameters are:

- Minimum contextual laps: 5
- Robust-score threshold: 6.0
- Shared-lap cluster threshold: 5 drivers

These indicators do not alter `IsEligible` and are not exclusion reasons.

## Decision-time safety

Processed data is analysis-ready but is not automatically a safe model-feature
table.

Phase 4 must enforce the start-of-lap decision boundary:

- Earlier completed laps may be inputs
- State known before lap `t` may be input
- Lap `t` time may be a prediction target
- Events during or after lap `t` may not be input features

## Generated-data policy

Processed Parquet, JSON, catalogs, logs and run records are excluded from Git.

Only code, contracts, tests and reproducible commands are version-controlled.