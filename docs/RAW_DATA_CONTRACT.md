# F1 Race Strategy Optimizer — Raw-Data Contract

## Purpose

This document defines version `1.0` of the historical Formula 1 raw-data
contract.

The raw pipeline downloads, validates and stores FastF1 race-session data so
later cleaning, dataset, database, modelling and simulation phases receive
consistent and auditable source records.

Raw partitions are immutable after successful extraction.

## Contract version

The current raw-data contract version is:

```text
1.0
```

A change to required tables, identities, stored fields, manifest semantics or
integrity requirements requires a contract-version review.

## Scope

The core raw pipeline contains completed race sessions from:

- 2022
- 2023
- 2024
- 2025

The dataset contains:

| Purpose | Seasons | Sessions |
|---|---|---:|
| Development | 2022–2024 | 68 |
| Protected temporal evaluation | 2025 | 24 |
| Total | 2022–2025 | 92 |

For each race, the pipeline stores:

- Lap timing and tyre data
- Weather observations
- Driver and classification results
- Event and session metadata
- Extraction provenance
- Validation evidence
- File-integrity evidence

Detailed telemetry is stored separately and remains disabled for core
race-session extraction.

Raw collection and integrity verification of 2025 are permitted. Cleaning,
feature engineering, threshold selection and modelling decisions must not use
2025 during development.

## Storage format

Tabular data is stored as Parquet using PyArrow.

The storage rules are:

- Parquet engine: PyArrow
- Compression: Zstandard
- DataFrame index: excluded
- Raw FastF1 source columns: preserved
- Stable provenance columns: added
- Time and duration types: preserved
- JSON encoding: UTF-8
- File integrity: SHA-256
- Writes: atomic

JSON is used for metadata, manifests and pipeline-run records.

No source missing value is filled in the raw layer.

## Session identity

The canonical session identifier is:

```text
YYYY-RR-S
```

Where:

- `YYYY` is the season
- `RR` is the zero-padded championship round
- `S` is the uppercase session type

The version-one core scope uses race sessions, so `S` is `R`.

Example:

```text
2024-01-R
```

The session identity must agree across:

- Requested session
- Directory path
- Stored tables
- Metadata
- Manifest
- Catalog

## Directory structure

Core race sessions use Hive-style partitions:

```text
data/raw/fastf1/
├── catalog.parquet
├── runs/
│   └── <run-id>.json
├── telemetry/
│   └── ...
└── season=<year>/
    └── round=<number>/
        └── session=R/
            ├── laps.parquet
            ├── weather.parquet
            ├── results.parquet
            ├── metadata.json
            └── manifest.json
```

Example:

```text
data/raw/fastf1/season=2024/round=01/session=R/laps.parquet
```

Event names are stored as data rather than used as directory identities.

## Core provenance columns

The pipeline attaches stable event provenance to each tabular source where
required:

- `Season`
- `RoundNumber`
- `SessionType`
- `EventName`

These values must match the requested session and partition path.

## `laps.parquet`

The lap table preserves available FastF1 lap fields and event provenance.

Required fields include:

- `Season`
- `RoundNumber`
- `SessionType`
- `EventName`
- `Driver`
- `Team`
- `LapNumber`
- `LapTime`
- `Stint`
- `Compound`
- `TyreLife`
- `PitInTime`
- `PitOutTime`
- `TrackStatus`
- `LapStartTime`

Additional FastF1 fields are preserved when available, including sectors,
speeds, positions, accuracy indicators, generated-lap indicators and deletion
metadata.

The raw layer must not:

- Remove unusual laps
- Fill missing lap times
- Guess compounds
- Guess tyre life
- Normalize modelling values
- Apply eligibility rules
- Create model features

## `weather.parquet`

The weather table preserves FastF1 observations and event provenance.

Required fields include:

- `Season`
- `RoundNumber`
- `SessionType`
- `EventName`
- `Time`
- `AirTemp`
- `TrackTemp`
- `Humidity`
- `Pressure`
- `Rainfall`
- `WindDirection`
- `WindSpeed`

Weather remains an observation timeline. The raw layer does not align weather
to laps or decision timestamps.

## `results.parquet`

The results table preserves available driver and classification information
with event provenance.

Expected source identifiers and context include:

- `DriverNumber`
- `Abbreviation`
- `TeamName`
- `Position`
- `GridPosition`
- `Status`

Results are stored for context, reconstruction and later evaluation.

Final positions, classifications, statuses and race outcomes must never become
prediction inputs for earlier decision timestamps.

## `metadata.json`

A stored session metadata object contains exactly these top-level fields:

- `country`
- `event_date`
- `event_format`
- `event_name`
- `fastf1_version`
- `location`
- `official_event_name`
- `round_number`
- `season`
- `session_type`
- `telemetry_loaded`

The metadata records human-readable event context and source-library
provenance.

For core extraction, detailed telemetry is not loaded.

## `manifest.json`

The manifest is written only after the session tables and metadata have passed
validation and readback checks.

Its top-level structure is:

- `contract_version`
- `created_at_utc`
- `files`
- `session`
- `source`
- `validation`

### Session object

The `session` object contains:

- `event_name`
- `identifier`
- `round_number`
- `season`
- `session_type`

### Source object

The `source` object contains:

- `name`
- `version`

### Validation object

The `validation` object contains:

- `issue_count`
- `status`

### Files object

The `files` object records all required session files:

- `laps.parquet`
- `weather.parquet`
- `results.parquet`
- `metadata.json`

Every file entry contains:

- Relative `path`
- `size_bytes`
- `sha256`

Every Parquet entry additionally contains:

- `rows`
- `columns`

A session directory without a valid manifest and valid required files must not
be treated as a successful extraction.

## Validation rules

Before a raw partition is accepted, the pipeline verifies:

1. The lap table is not empty.
2. The weather table is not empty.
3. The results table is not empty.
4. Every required lap column exists.
5. Every required weather column exists.
6. Required event-provenance columns exist.
7. Session identities match the request.
8. At least one driver is recorded.
9. At least one valid lap time exists.
10. Stored Parquet files can be read back.
11. Readback tables match the written data.
12. Expected files have recorded sizes and SHA-256 checksums.
13. The validation status passes.
14. The manifest is written after the authoritative data files.

Naturally sparse values may remain missing. Missing required columns,
unreadable files or identity conflicts fail validation.

## Atomic storage

Raw-session storage follows this sequence:

1. Extract source tables.
2. Validate source identities and required fields.
3. Write files into a temporary session partition.
4. Read stored Parquet and JSON files back.
5. Compare readback data with the validated sources.
6. Calculate file sizes and SHA-256 checksums.
7. Write the manifest.
8. Promote the temporary partition atomically.
9. Verify the final stored partition.
10. Restore a recoverable previous partition if replacement fails.

An incomplete temporary write must never be presented as a completed session.

## Integrity verification

An existing raw partition is valid only when:

- Its directory exists
- Its manifest exists and is readable
- Contract version matches
- Session identity matches
- Every required file exists
- File paths match
- File sizes match
- SHA-256 checksums match
- Parquet tables are readable
- Required columns exist
- Row counts match
- Metadata identity matches
- Validation status passes

A single integrity failure makes the partition invalid.

## Incremental and restart behaviour

For a normal request without `--force`:

### Missing partition

If the expected session directory does not exist:

1. FastF1 extraction begins.
2. Data is validated.
3. The session is written atomically.
4. Final integrity is verified.

### Valid existing partition

If the expected directory exists:

1. Integrity verification runs before extraction.
2. The partition is skipped only when every check passes.
3. Its existing manifest is returned.
4. FastF1 session loading does not occur.

### Invalid existing partition

If the expected directory exists but integrity verification fails:

1. The pipeline fails closed.
2. Extraction does not begin.
3. The invalid partition is not silently replaced.
4. The caller receives the integrity failure.

An explicit `--force` request is required to rebuild or replace an existing
partition.

The force option does not bypass validation. Replacement data must still pass
the complete write, readback, manifest and integrity process.

## Batch execution

Batch processing:

- Accepts selected seasons and rounds
- Processes sessions independently
- Records written, skipped and failed outcomes
- Continues after an individual recoverable failure
- Records duration per session
- Produces one JSON run record
- Rebuilds the catalog from verified partitions

Core extraction is sequential. Project concurrency requirements are reserved
for the later Monte Carlo simulation phase, where concurrency provides a
meaningful measurable workload.

## Pipeline run records

Each batch execution writes a JSON record beneath:

```text
data/raw/fastf1/runs/
```

A run record captures:

- Run identity
- Start and completion timestamps
- Requested sessions
- Per-session status
- Per-session duration
- Written count
- Skipped count
- Failed count
- Failure information
- Relevant command options

Run records are generated artifacts and are not committed to Git.

## Raw-data catalog

`catalog.parquet` is rebuilt from verified core race partitions.

It contains exactly 13 columns:

1. `session_id`
2. `season`
3. `round_number`
4. `session_type`
5. `event_name`
6. `created_at_utc`
7. `fastf1_version`
8. `telemetry_loaded`
9. `laps_rows`
10. `weather_rows`
11. `results_rows`
12. `total_size_bytes`
13. `session_directory`

Catalog invariants are:

- One row per verified session
- Unique `session_id`
- Stable column order
- No append-created duplicates
- Session identity consistent with the partition
- Row counts consistent with stored tables
- Only integrity-valid partitions included

The completed version-one catalog contains 92 unique race sessions.

Detailed telemetry partitions are not included in this catalog.

## Telemetry policy

Detailed telemetry is disabled for core race extraction.

The optional telemetry interface selects:

- Season
- Round
- Race session
- Driver
- Lap number

Telemetry uses a separate identity, directory structure, manifest and contract.

Telemetry-derived features may enter later modelling only after:

- They use completed past laps
- Their decision-time availability is proven
- They demonstrate measurable value over simpler lap-level inputs

## Raw-layer rules

The raw layer must:

- Preserve source values
- Preserve source missingness
- Preserve unusual records
- Add only stable event provenance
- Avoid cleaning and imputation
- Avoid model-specific feature engineering
- Record the FastF1 version
- Remain reproducible and auditable
- Remain immutable after successful extraction

Cleaning belongs to Phase 3. Decision-time feature construction belongs to
Phase 4.

## Protected 2025 policy

The raw pipeline stores and verifies 2025 because final temporal evaluation must
be reproducible from the same source contract.

During development:

- Raw 2025 partitions must not be profiled for modelling decisions.
- Phase 3 processing interfaces reject 2025.
- Phase 4 dataset-development interfaces must reject 2025.
- Model and simulator decisions must be frozen before final 2025 evaluation.

One 2025 session received limited schema and availability inspection during
Phase 1. That exposure must be disclosed but does not permit later development
access.

## Git policy

Generated data is excluded from Git.

Ignored generated locations include:

- FastF1 cache
- Raw Parquet files
- Raw JSON files
- Raw catalogs
- Pipeline-run records
- Processed datasets
- Temporary and backup partitions
- Model artifacts

The repository preserves:

- Source code
- Tests
- Contracts
- Documentation
- Dependency configuration
- Reproducible commands
- Small synthetic test fixtures when required

## Completion evidence

Version `1.0` has been validated using:

- 92 completed race sessions
- 101,290 lap rows
- 14,896 weather rows
- 1,838 driver-result rows
- 92 unique catalog session identifiers
- Zero invalid final raw partitions
- A complete integrity audit
- A complete resume run that skipped all 92 verified sessions
- Automated unit and integration tests

The raw contract is complete and remains the immutable input boundary for later
phases.