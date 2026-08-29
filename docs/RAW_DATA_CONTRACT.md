# F1 Race Strategy Optimizer — Raw-Data Contract

## Purpose

This contract defines how Phase 2 downloads, validates and stores historical
Formula 1 data.

Every extraction script must follow this contract so later cleaning, modelling
and database phases receive consistent inputs.

## Phase 2 scope

The core pipeline will collect race-session data for the proposed 2022–2025
study period.

For each race, it will collect:

- Lap timing and tyre data
- Weather observations
- Driver and race results
- Event and session metadata
- Extraction provenance
- Validation results

Detailed telemetry will be supported separately and disabled by default.

## Storage format

Tabular data will be stored as Parquet using PyArrow.

Initial settings:

- Parquet engine: PyArrow
- Compression: Zstandard
- DataFrame index: excluded
- Raw source column names: preserved
- Time and duration types: preserved where possible
- Text encoding for JSON: UTF-8

JSON will be used for metadata, validation details and pipeline-run summaries.

## Directory structure

```text
data/raw/fastf1/
├── catalog.parquet
├── runs/
│   └── <run-id>.json
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

Using stable season, round and session identifiers avoids depending on event
names inside directory paths.

## Core tables

### laps.parquet

This table will preserve the available FastF1 lap columns and add:

| Added field | Meaning |
|---|---|
| Season | Championship year |
| RoundNumber | Event round |
| SessionType | FastF1 session identifier |
| EventName | Event name supplied by FastF1 |

Required source fields include:

- Driver
- Team
- LapNumber
- LapTime
- Stint
- Compound
- TyreLife
- PitInTime
- PitOutTime
- TrackStatus
- LapStartTime

No missing values will be filled in the raw layer.

### weather.parquet

This table will preserve FastF1 weather observations and add the same event
identity fields.

Required weather fields include:

- Time
- AirTemp
- TrackTemp
- Humidity
- Pressure
- Rainfall
- WindDirection
- WindSpeed

### results.parquet

This table will preserve available driver and classification information.

Expected identifiers include:

- DriverNumber
- Abbreviation
- TeamName
- Position
- GridPosition
- Status

Results are stored for context and later evaluation. Final results must never
be used as prediction inputs.

## metadata.json

Session metadata will include:

| Field | Meaning |
|---|---|
| schema_version | Version of this raw-data contract |
| season | Championship year |
| round_number | Event round |
| event_name | FastF1 event name |
| country | Event country |
| location | Event location |
| session_type | Requested session identifier |
| session_name | Human-readable session name |
| session_date | Recorded session date |
| total_laps | Scheduled or recorded race distance |
| data_source | FastF1 |
| fastf1_version | Installed FastF1 version |
| extracted_at_utc | Extraction timestamp in UTC |
| telemetry_included | Whether detailed telemetry was requested |

## manifest.json

The manifest will be written only after extraction and validation succeed.

It will include:

| Field | Meaning |
|---|---|
| schema_version | Raw-data contract version |
| extraction_status | Complete or failed |
| session_key | Stable season-round-session identifier |
| extracted_at_utc | Completion timestamp |
| files | Output filenames and their statistics |
| row_counts | Rows stored for each table |
| column_counts | Columns stored for each table |
| checksums | SHA-256 checksum for each stored file |
| validation | Passed checks and warnings |
| telemetry_included | Whether telemetry was included |

A session directory without a valid completed manifest must not be treated as a
successful extraction.

## Dataset catalog

`catalog.parquet` will contain one row per successfully extracted session.

Planned fields include:

- Schema version
- Season
- Round number
- Event name
- Session type
- Session date
- Lap rows
- Weather rows
- Result rows
- Pit-entry count
- Missing lap-time count
- Rainfall observed
- Available tyre compounds
- Extraction timestamp
- Session path
- Manifest checksum

The catalog allows later phases to discover available sessions without opening
every Parquet file.

## Pipeline run records

Each execution will create a JSON record under `data/raw/fastf1/runs/`.

The record will contain:

- Run identifier
- Start and completion timestamps
- Requested seasons and sessions
- Successful extractions
- Skipped sessions
- Failed sessions
- Error messages
- Installed dependency versions
- Command options

## Validation rules

Before a session is marked complete, the pipeline must verify:

1. The lap table is not empty.
2. The weather table is not empty.
3. The results table is not empty.
4. Every required lap column exists.
5. Every required weather column exists.
6. Required event identifiers are present.
7. At least one driver is recorded.
8. At least one valid lap time exists.
9. Parquet files can be read back successfully.
10. Read-back row counts match the original row counts.
11. Every expected file has a recorded checksum.
12. The manifest is written last.

Missing values may produce warnings without failing extraction when the field
is naturally sparse or partially missing.

Missing required columns or unreadable output files must fail extraction.

## Raw-layer rules

The raw layer must:

- Preserve source values without imputation
- Preserve missing values
- Avoid removing unusual laps
- Avoid model-specific feature engineering
- Add only stable provenance and event identifiers
- Record source-library versions
- Remain reproducible and auditable
- Be treated as immutable after successful extraction

Cleaning and feature engineering belong to later phases.

## Incremental and restart behaviour

Default behaviour:

- Skip a session when a valid completed manifest already exists
- Reprocess an incomplete or invalid session
- Continue processing other requested sessions after a recoverable failure
- Record every failure in the pipeline-run summary
- Never mark partially written data as complete

A force option will allow an exact session to be rebuilt intentionally.

New files will be written to a temporary location, validated and then moved
into their final session directory. Existing valid data must remain available
until its replacement passes validation.

## Telemetry policy

Telemetry is disabled by default.

The optional telemetry interface will eventually support selecting:

- Specific seasons and races
- Specific drivers
- Specific laps
- Full sessions only when explicitly requested

Telemetry outputs will use a separate subdirectory so the core lap pipeline
remains lightweight.

Telemetry-derived features will only enter modelling after comparison with
lap-level baselines.

## Git policy

Generated data must not be committed to Git.

The repository will preserve only placeholder files, source code, tests,
configuration and small synthetic test fixtures.

The following generated locations must be ignored:

- FastF1 cache
- Raw Parquet and JSON outputs
- Processed datasets
- Temporary extraction files
- Failed partial outputs

## Phase 2 completion criteria

Phase 2 is complete when:

1. A command can extract one selected race.
2. Required tables and metadata are stored according to this contract.
3. Validation failures produce clear errors.
4. Re-running a completed extraction safely skips it.
5. An explicit force option can rebuild it.
6. Multi-race and multi-season selection works.
7. Pipeline runs produce manifests and a dataset catalog.
8. Unit tests do not require network access.
9. Integration tests validate a controlled sample extraction.
10. The documented command can build the complete core 2022–2025 raw dataset.