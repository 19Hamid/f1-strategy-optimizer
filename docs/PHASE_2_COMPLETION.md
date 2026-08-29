# Phase 2 Completion Report — Raw-Data Pipeline

## Outcome

Phase 2 produced a reproducible, resumable and integrity-checked historical
Formula 1 raw-data pipeline.

The pipeline discovered and extracted all completed race sessions from 2022 to
2025 using FastF1. Detailed telemetry remains optional and is extracted only
for explicitly requested drivers and laps.

Phase 2 was completed on 29 August 2026.

## Dataset summary

| Purpose | Seasons | Sessions |
|---|---|---:|
| Development | 2022–2024 | 68 |
| Final unseen evaluation | 2025 | 24 |
| Total | 2022–2025 | 92 |

The final catalog audit recorded:

| Table | Rows |
|---|---:|
| Laps | 101,290 |
| Weather | 14,896 |
| Driver results | 1,838 |

Additional audit results:

- 92 unique session identifiers
- 0 invalid session partitions
- Approximately 13 MB of compressed raw data
- Approximately 731 MB of re-downloadable FastF1 cache data
- All session file sizes and SHA-256 checksums verified
- All 2025 data reserved for final evaluation

## Pipeline workflow

The core race pipeline performs:

1. Race-schedule discovery
2. Session selection
3. FastF1 extraction
4. Provenance attachment
5. Raw-data contract validation
6. Compressed Parquet serialization
7. Parquet readback comparison
8. Metadata and manifest creation
9. SHA-256 checksum calculation
10. Atomic partition promotion
11. Session-integrity verification
12. Catalog reconstruction
13. Batch run-record creation

Only the external FastF1 extraction step requires network access.

## Stored session structure

Each race is stored using Hive-style partitions:

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

The manifest records:

- Contract version
- Session identity
- Event identity
- FastF1 source version
- Validation result
- Row counts
- File sizes
- Relative paths
- SHA-256 checksums

## Incremental behaviour

Before extraction, the pipeline checks whether the requested partition already
exists.

If it exists:

1. The manifest is loaded.
2. Required files are checked.
3. File sizes are compared.
4. SHA-256 checksums are recalculated.
5. The session is skipped only when every integrity check passes.

A corrupted partition fails before extraction unless `--force` is explicitly
used.

After the full dataset was created, a complete four-season rerun:

- Verified all 92 sessions
- Skipped all 92 sessions
- Loaded no FastF1 race data
- Reported zero failures
- Completed in approximately 2.7 seconds

## Batch execution

Batch execution:

- Processes sessions independently
- Continues after an individual failure
- Records written, skipped and failed counts
- Records execution time per session
- Saves a JSON run record
- Rebuilds the catalog from verified sessions

The extraction is deliberately sequential because FastF1 retrieval is mainly
network and cache bound. Project concurrency requirements will be demonstrated
later through Monte Carlo strategy simulation, where concurrency provides more
meaningful value.

## Raw-data catalog

The generated `catalog.parquet` contains one row per verified race session.

It records:

- Session identity
- Event name
- Row counts
- Source version
- Contract version
- File sizes
- Total partition size

The catalog is rebuilt rather than appended, preventing duplicate session rows.

Detailed telemetry partitions are stored separately and are not included in
the race-session catalog.

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

## Quality evidence

Final Phase 2 validation produced:

- Ruff checks passed
- 134 pytest tests passed with warnings treated as errors
- Unit tests for configuration, paths, schedules and models
- Unit tests for extraction and validation
- Unit tests for serialization and atomic storage
- Unit tests for manifests and integrity checking
- Unit tests for batch execution and catalog construction
- Unit tests for the CLI
- Unit tests for telemetry selection, extraction, storage and skipping
- An end-to-end integration audit using the real internal pipeline
- A real 92-race checksum audit
- A successful full incremental rerun

## Data-management policy

Generated data is deliberately excluded from Git:

- `data/raw/`
- `data/processed/`
- `data/cache/`
- Trained model artifacts

Only code, schemas, documentation and reproducible commands are versioned.

The FastF1 cache can be deleted and recreated. The raw dataset can also be
reconstructed through the documented CLI.

## Phase 3 handoff

Phase 3 will use the verified raw catalog to:

1. Profile missing and inconsistent values
2. Define dry and green-flag filtering rules
3. Identify inaccurate, pit, formation and abnormal laps
4. Explore tyre compounds and stint behaviour
5. Investigate fuel-load and track-evolution effects
6. Estimate circuit-specific pit loss
7. Produce cleaned exploratory datasets
8. Document every exclusion and transformation

The 2025 evaluation races will remain protected from modelling decisions.