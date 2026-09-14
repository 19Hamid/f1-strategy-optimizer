# Phase 2 Completion Report — Raw-Data Pipeline

## Outcome

Phase 2 produced a reproducible, resumable and integrity-checked historical
Formula 1 raw-data pipeline.

The pipeline discovered and extracted all completed race sessions from 2022 to
2025 using FastF1.

Detailed telemetry remains optional and is extracted only for explicitly
requested drivers and laps.

Phase 2 was completed on 29 August 2026.

## Dataset summary

| Purpose | Seasons | Sessions |
|---|---|---:|
| Development | 2022–2024 | 68 |
| Protected temporal evaluation | 2025 | 24 |
| Total | 2022–2025 | 92 |

The final catalog audit recorded:

| Table | Rows |
|---|---:|
| Laps | 101,290 |
| Weather | 14,896 |
| Driver results | 1,838 |

Additional results:

- 92 unique session identifiers
- Zero invalid final session partitions
- Approximately 13 MB of compressed raw data
- Approximately 731 MB of re-downloadable FastF1 cache data
- All authoritative file sizes and SHA-256 checksums verified
- All 24 raw 2025 races reserved for final temporal evaluation

## Evaluation-boundary disclosure

One 2025 session, the Japanese Grand Prix, received limited schema and
availability inspection during Phase 1.

The inspection examined structural information such as:

- Required field availability
- Record counts
- Missing lap-time count
- Pit-entry count
- Available tyre compounds

It did not determine later cleaning rules, feature definitions, statistical
thresholds, models, hyperparameters or simulator parameters.

Phase 2 collected and integrity-checked all 2025 raw partitions. Raw collection
is permitted because final temporal evaluation must remain reproducible.

Later development phases must reject 2025 until the system is frozen for final
evaluation.

## Pipeline workflow

The core race pipeline performs:

1. Race-schedule discovery
2. Session selection
3. FastF1 extraction
4. Provenance attachment
5. Raw-data contract validation
6. Compressed Parquet serialization
7. Parquet readback comparison
8. Metadata creation
9. SHA-256 checksum calculation
10. Manifest construction
11. Atomic partition promotion
12. Session-integrity verification
13. Catalog reconstruction
14. Batch run-record creation

Only external FastF1 extraction requires network access.

## Stored session structure

Each race uses Hive-style partitions:

```text
data/raw/fastf1/
└── season=2024/
    └── round=01/
        └── session=R/
            ├── laps.parquet
            ├── weather.parquet
            ├── results.parquet
            ├── metadata.json
            └── manifest.json
```

The metadata records:

- Season and round
- Session type
- Event name
- Official event name
- Country
- Location
- Event date
- Event format
- FastF1 version
- Whether detailed telemetry was loaded

The manifest records:

- Raw contract version
- Creation timestamp
- Session identity
- Event identity
- FastF1 source name and version
- Validation status and issue count
- Required file paths
- Parquet row counts and columns
- File sizes
- SHA-256 checksums

## Incremental behaviour

Before extraction, the pipeline checks whether the requested partition already
exists.

### Missing partition

A missing partition is extracted, validated, written atomically and verified.

### Valid existing partition

When a directory exists without `--force`:

1. The manifest is loaded.
2. Contract and session identities are checked.
3. Required files are checked.
4. File sizes are compared.
5. SHA-256 checksums are recalculated.
6. Parquet structure and counts are verified.
7. The session is skipped only when every integrity check passes.

A verified session is skipped before FastF1 race loading.

### Invalid existing partition

An invalid existing partition fails closed.

The pipeline does not silently rebuild it and does not begin FastF1 extraction.

Explicit `--force` is required to replace an existing or corrupted partition.
The replacement must still pass the complete validation, readback, manifest
and integrity process.

After the complete raw dataset was created, a four-season resume run:

- Verified all 92 sessions
- Skipped all 92 sessions
- Loaded no FastF1 race data
- Reported zero failures
- Completed in approximately 2.7 seconds

## Atomic storage

Session writes:

1. Use a temporary partition.
2. Serialize compressed Parquet and deterministic JSON.
3. Read authoritative files back.
4. Compare restored values with validated sources.
5. Calculate file sizes and SHA-256 checksums.
6. Write the manifest after authoritative data files.
7. Promote the temporary partition atomically.
8. Preserve recoverable prior data until replacement succeeds.
9. Verify the final partition.

A partially written directory must never be presented as complete.

## Batch execution

Batch execution:

- Processes sessions independently
- Continues after an individual recoverable failure
- Records written, skipped and failed counts
- Records execution time per session
- Saves a JSON run record
- Rebuilds the catalog from verified sessions

Core extraction is deliberately sequential because FastF1 retrieval is
primarily network and cache bound.

Project concurrency requirements will be demonstrated later through Monte Carlo
strategy simulation, where concurrency provides a meaningful measurable
workload.

## Raw-data catalog

The generated `catalog.parquet` contains one row per verified race session.

Its 13 columns are:

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

The catalog is rebuilt rather than appended, preventing duplicate session rows.

Final evidence:

- 92 catalog rows
- 92 unique session identifiers
- Exact declared and stored column agreement
- Only verified partitions represented

Detailed telemetry partitions are stored separately and are not included in the
core race catalog.

## On-demand telemetry

Telemetry is requested using:

- Season
- Championship round
- Session type
- Driver abbreviation
- Lap number

Example:

```bash
uv run python -m app.pipeline.cli telemetry \
  --season 2024 \
  --round 1 \
  --driver VER \
  --lap 39
```

The verified example produced:

- 703 samples
- 24 stored columns
- 5,364 metres of distance
- 66–301 km/h speed range
- A 58,962-byte compressed Parquet file

Verified telemetry requests skip before FastF1 session loading.

Telemetry remains optional because bulk extraction would create significant
storage and processing cost without guaranteed modelling benefit.

## Quality evidence

Final Phase 2 validation produced:

- Ruff checks passed
- 134 pytest tests passed with warnings treated as errors
- Unit tests for configuration, paths, schedules and identities
- Unit tests for extraction and validation
- Unit tests for serialization and atomic storage
- Unit tests for manifests and integrity checking
- Unit tests for batch execution and catalog construction
- Unit tests for the command-line interface
- Unit tests for telemetry selection, extraction, storage and skipping
- An end-to-end integration audit using the internal pipeline
- A real 92-race checksum audit
- A successful complete resume run

## Data-management policy

Generated data is excluded from Git:

- `data/raw/`
- `data/processed/`
- `data/cache/`
- Trained model artifacts

Only code, contracts, tests, documentation and reproducible commands are
version-controlled.

The FastF1 cache can be deleted and recreated.

The raw dataset can be reconstructed through the documented command-line
interface, subject to upstream data availability.

## Phase 3 handoff and resolution

Phase 2 handed verified raw development data to Phase 3 for:

1. Missingness and consistency profiling
2. Dry and green-flag classification
3. Inaccurate, pit, first and abnormal lap classification
4. Weather alignment
5. Tyre-stint reconstruction
6. Pit-event and observed pit-duration reconstruction
7. Processed dataset construction
8. Exclusion and transformation documentation

Phase 3 subsequently completed all 68 development races and produced:

- 74,601 preserved processed lap rows
- 57,871 eligible controlled laps
- 16,730 excluded laps
- 3,888 reconstructed stints
- 2,693 reconstructed pit events
- 1,465 pit-duration candidates
- Zero processed 2025 partitions

Phase 3 established that observed pit-lane duration is not automatically net
pit loss. Later simulator assumptions must preserve that distinction.

## Phase 4 relevance

The raw layer remains the immutable source boundary.

Phase 4 primarily consumes verified Phase 3 processed development data but may
use verified raw observation timelines when a decision-time reconstruction
cannot be safely derived from a completed-lap field.

Any Phase 4 raw access must:

- Use 2022–2024 only
- Preserve source immutability
- Verify the raw partition first
- Record source provenance
- Avoid creating a second undocumented cleaning pipeline
- Reject protected 2025 records during development

The Phase 2 raw contract remains version `1.0`.