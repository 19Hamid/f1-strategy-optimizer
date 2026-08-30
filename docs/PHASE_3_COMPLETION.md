# Phase 3 Completion Report — Data Cleaning and Exploration

## Outcome

Phase 3 produced a deterministic, versioned, resumable and integrity-checked
processed Formula 1 development dataset.

It cleaned and explored all 68 development races from 2022 to 2024 while
preserving every raw lap and protecting the 2025 final-evaluation season.

Phase 3 was completed on 30 August 2026.

## Versioned deliverables

- Cleaning rules: `1.0`
- Processed-data contract: `1.0`
- Development exploration: `1.0`
- Lap statistical-outlier policy: `FLAG_ONLY`

## Dataset summary

| Season | Sessions |
|---|---:|
| 2022 | 22 |
| 2023 | 22 |
| 2024 | 24 |
| Total | 68 |

Processed totals:

| Measure | Value |
|---|---:|
| Processed lap rows | 74,601 |
| Eligible laps | 57,871 |
| Excluded laps | 16,730 |
| Eligibility rate | 77.57% |
| Reconstructed stints | 3,888 |
| Complete stints | 3,845 |
| Incomplete stints | 43 |
| Reconstructed pit events | 2,693 |
| Complete pit events | 2,539 |
| Incomplete pit events | 154 |
| Duration-analysis candidates | 1,465 |

The versioned processed dataset occupies approximately 13 MB.

## Cleaning workflow

For each session, the pipeline performs:

1. Raw-partition integrity verification
2. Required identity validation
3. Value normalization
4. Duplicate detection
5. Lap-quality classification
6. Backward-only weather alignment
7. Rainfall-aware eligibility finalization
8. Tyre-stint reconstruction
9. Pit-event reconstruction
10. Pit-event weather enrichment
11. Quality-report construction
12. Cross-table count validation
13. Atomic Parquet and JSON storage
14. Parquet readback comparison
15. SHA-256 manifest construction
16. Processed-partition integrity verification

## Stored session structure

```text
data/processed/fastf1/
└── cleaning_version=1.0/
    └── season=2024/
        └── round=01/
            └── session=R/
                ├── laps.parquet
                ├── stints.parquet
                ├── pit_events.parquet
                ├── quality_report.json
                └── manifest.json
```

A verified catalog contains one row per processed development race.

## Lap preservation

All 74,601 development lap rows were preserved.

Excluded laps remain stored with documented reasons. No row was silently
deleted or imputed merely to make the dataset appear complete.

The final eligibility result was:

- 57,871 eligible laps
- 16,730 excluded laps
- 77.57% eligibility

## Weather evidence

Weather alignment produced:

- 74,601 matched laps
- 0 unmatched laps
- 0 future weather matches
- 3,586 rain-aligned laps
- 30.049-second median observation age
- 99.105-second maximum observation age

Rainfall alignment newly excluded 650 laps.

## Stint evidence

The pipeline reconstructed 3,888 stints across 1,350 driver-race combinations.

Results:

- 3,845 complete stints
- 43 incomplete stints
- 3,537 dry-compound stints
- No disjoint reused stint identifiers
- No tyre-life decreases
- No tyre-life step mismatches
- No lap-number gaps
- No compound changes without a stint boundary

All processed laps were represented by reconstructed stints.

## Pit-event evidence

The pipeline reconstructed:

- 2,539 matched events
- 89 entry-only events
- 65 exit-only events
- 2,693 total events
- 1,465 duration-analysis candidates

All 5,232 source pit markers were represented.

Observed candidate pit-duration medians varied materially by event, confirming
that future pit-loss estimation must be circuit-specific.

## Exploration evidence

The permanent exploration module verified and analyzed all 68 processed
partitions.

It identified:

- 541 contextual potential lap-time outliers
- 526 slow-direction extremes
- 15 fast-direction extremes
- 193 outliers in shared lap clusters
- 348 outliers outside shared clusters

The final policy is `FLAG_ONLY`.

No lap was excluded merely because it was statistically unusual.

## Known limitations

Documented limitations include:

- `LapStartDate` is null for every development lap
- Two development races contain no eligible controlled dry laps
- Observed pit-lane duration is not final net pit loss
- Restart-like laps cannot always be identified deterministically
- Raw compound medians do not represent causal tyre effects
- Fuel load, traffic, driver intent and team instruction remain partially
  unobserved
- Wet, safety-car and red-flag strategy remain outside version one

## Protected holdout

The 2025 season remained untouched.

Final audit evidence:

- No processed `season=2025` directory
- Exploration accepts development seasons only
- No 2025 record influenced cleaning or outlier decisions
- 24 raw 2025 races remain available for later unseen evaluation

## Performance evidence

The first complete development processing run:

- Wrote 66 sessions
- Skipped 2 previously verified sessions
- Failed 0 sessions
- Completed in approximately 17.3 seconds

A complete resume run:

- Verified all 68 sessions
- Skipped all 68 sessions
- Read no raw race tables for skipped sessions
- Failed 0 sessions
- Completed in approximately 3.0 seconds

The permanent 68-race exploration completed in approximately 3.2 seconds.

## Automated quality evidence

Final Phase 3 implementation validation produced:

- Ruff checks passed
- 291 pytest tests passed
- Warnings treated as errors
- Unit coverage for profiling
- Unit coverage for lap classification
- Unit coverage for backward-only weather alignment
- Unit coverage for session cleaning
- Unit coverage for stint reconstruction
- Unit coverage for pit reconstruction
- Unit coverage for processed orchestration
- Unit coverage for atomic storage
- Unit coverage for processed integrity verification
- Unit coverage for resumable runners
- Unit coverage for resilient batch execution
- Unit coverage for processed catalog construction
- Unit coverage for the processed CLI
- Unit coverage for permanent development exploration
- Real 68-session processed integrity audit
- Real complete resume audit
- Real permanent exploration audit

## Acceptance criteria

Phase 3 acceptance criteria were satisfied:

1. Development data can be cleaned reproducibly.
2. Every excluded lap has at least one documented reason.
3. Race conditions and pit laps are classified consistently.
4. Tyre stints and pit events are reconstructed.
5. Weather is aligned without future leakage.
6. Important patterns and limitations are documented.
7. The 2025 evaluation season did not influence decisions.
8. Automated tests and code-quality checks pass.
9. Outputs can be recreated from immutable raw data.

## Phase 4 handoff

Phase 4 will use the frozen Phase 3 contract to:

1. Define leakage-safe decision-time rows
2. Create modelling targets and features
3. Separate descriptive columns from usable inputs
4. Build race-level development and validation splits
5. Design PostgreSQL tables and indexes
6. Version modelling datasets
7. Validate decision-time leakage automatically
8. Prepare simple baseline methods

Phase 4 must not reinterpret the 2025 season or modify Phase 3 cleaning rules
based on evaluation results.