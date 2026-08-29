# On-Demand Telemetry Contract

## Purpose

Detailed FastF1 telemetry is an optional Phase 2 data source.

It is intended for selected investigations where speed, throttle, braking,
gear, RPM, DRS or position traces provide measurable value.

It is not downloaded in bulk as part of the 92-race core dataset.

## Contract version

Current telemetry contract version: `1.0`

## Request identity

One telemetry request is identified by:

| Field | Rule |
|---|---|
| Season | One V1 season from 2022 to 2025 |
| Round number | Positive championship round |
| Session type | Race (`R`) |
| Driver | Three-letter ASCII abbreviation |
| Lap number | Integer from 1 to 200 |

Example identifier:

```text
2024-01-R-VER-L039
```

## Storage location

Telemetry is stored separately from core race tables:

```text
data/raw/fastf1/
└── telemetry/
    └── season=2024/
        └── round=01/
            └── session=R/
                └── driver=VER/
                    └── lap=039/
                        ├── telemetry.parquet
                        ├── metadata.json
                        └── manifest.json
```

Telemetry partitions are not included in `catalog.parquet`.

## Required telemetry fields

Each extracted telemetry table must contain:

- `Time`
- `Distance`
- `RPM`
- `Speed`
- `nGear`
- `Throttle`
- `Brake`
- `DRS`
- `X`
- `Y`
- `Z`

Additional FastF1 fields are retained when available, including fields such as:

- `Date`
- `SessionTime`
- `Source`
- `Status`
- `RelativeDistance`

## Provenance fields

The following columns are attached to every stored sample:

- `Season`
- `RoundNumber`
- `SessionType`
- `EventName`
- `Driver`
- `LapNumber`

These fields identify exactly where every sensor sample originated.

## Stored files

### `telemetry.parquet`

Contains:

- One row per telemetry sample
- Provenance columns
- FastF1 telemetry columns
- PyArrow Parquet encoding
- Zstandard compression
- No DataFrame index

### `metadata.json`

Contains:

- Contract version
- Telemetry identifier
- Session identifier
- Season and round
- Driver and lap number
- Event name
- FastF1 version
- Sample count
- Available columns
- Storage format
- Compression method

### `manifest.json`

Contains:

- Contract version
- Telemetry identity
- Session identity
- File sizes
- Row count
- SHA-256 checksums

## Atomic storage process

Telemetry storage performs:

1. Write into a unique temporary directory.
2. Serialize telemetry as compressed Parquet.
3. Serialize deterministic JSON metadata.
4. Read the Parquet and JSON files back.
5. Compare shapes, columns, data types, null positions and non-null values.
6. Calculate file sizes and SHA-256 checksums.
7. Write the manifest.
8. Atomically promote the temporary directory.
9. Verify the final stored partition.
10. Remove temporary or backup directories.

Meaningless source DataFrame row labels are not stored or compared because the
Parquet contract deliberately uses `index=False`.

## Incremental behaviour

For a request without `--force`:

1. The expected partition path is resolved.
2. Required files are checked.
3. The contract version and telemetry identity are checked.
4. File sizes are verified.
5. SHA-256 checksums are recalculated.
6. The request is skipped if the partition is valid.
7. FastF1 is contacted only when the partition is missing.

A corrupt partition raises an error before FastF1 loading.

Using `--force` allows a corrupted or existing partition to be replaced
atomically.

## Command-line use

Run from the `backend` directory:

```bash
uv run python -m app.pipeline.cli telemetry \
  --season 2024 \
  --round 1 \
  --driver VER \
  --lap 39
```

Force replacement:

```bash
uv run python -m app.pipeline.cli telemetry \
  --season 2024 \
  --round 1 \
  --driver VER \
  --lap 39 \
  --force
```

## Verified example

The Phase 2 real-data validation used:

```text
Season: 2024
Round: 1
Event: Bahrain Grand Prix
Driver: VER
Lap: 39
```

Results:

- 703 samples
- 24 columns
- Maximum distance: 5,364 metres
- Speed range: 66–301 km/h
- No missing required telemetry fields
- Compressed Parquet size: 58,962 bytes
- Repeated request skipped before FastF1 loading

## Limitations

- Telemetry availability depends on FastF1 and its upstream sources.
- Telemetry channels have different original sampling rates.
- FastF1 merges and resamples car and position data.
- Distance may be calculated rather than directly measured.
- Public telemetry is not equivalent to private team telemetry.
- One selected lap does not automatically represent an entire stint or race.
- Detailed telemetry will only become a modelling input if later experiments
  demonstrate measurable improvement without leakage.