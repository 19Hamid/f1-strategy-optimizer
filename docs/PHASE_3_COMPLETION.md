# Phase 3 Completion Report — Data Cleaning and Exploration

## Outcome

Phase 3 produced a deterministic, versioned, resumable and integrity-checked
processed Formula 1 development dataset.

It cleaned and explored all 68 development races from 2022 to 2024 while
preserving every raw lap and excluding the protected 2025 temporal holdout from
Phase 3 processing and exploration.

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

Phase 3 eligibility describes suitability for controlled lap analysis. It does
not prove that every processed column was available at the start of a future
decision lap.

## Weather evidence

Weather alignment produced:

- 74,601 matched laps
- Zero unmatched laps
- Zero future matches relative to the Phase 3 lap-alignment timestamp
- 3,586 rain-aligned laps
- 30.049-second median observation age
- 99.105-second maximum observation age

Rainfall alignment newly excluded 650 laps.

Phase 3 weather alignment was designed to classify completed laps. Phase 4 must
perform a separate decision-time check at or before `LapStartTime(t)` before
using weather as a start-of-lap feature.

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

Stint values attached to lap `t` are not automatically decision-time features.
Phase 4 must reconstruct the state known when that lap begins.

## Pit-event evidence

The pipeline reconstructed:

- 2,539 matched events
- 89 entry-only events
- 65 exit-only events
- 2,693 total events
- 1,465 duration-analysis candidates

All 5,232 source pit markers were represented.

Observed candidate pit-duration medians varied materially by event, confirming
that later estimation must retain circuit context.

Observed pit-lane duration is not automatically:

- Stationary service time
- Pit-lap time loss
- Net race-time loss
- Counterfactual pit loss
- A final simulator parameter

## Exploration evidence

The permanent exploration module verified and analyzed all 68 processed
partitions.

It identified:

- 541 contextual potential lap-time outliers
- 526 slow-direction extremes
- 15 fast-direction extremes
- 193 outliers in shared lap clusters
- 348 outliers outside shared clusters

The final policy is:

```text
FLAG_ONLY
```

No lap was excluded merely because it was statistically unusual.

## Known limitations

Documented limitations include:

- `LapStartDate` is null for every development lap
- Two development races contain no eligible controlled dry laps
- Observed pit-lane duration is not final net pit loss
- Restart-like laps cannot always be identified deterministically
- Raw compound medians do not represent causal tyre effects
- Fuel load remains unobserved
- Traffic, driver intent and team instruction remain partially unobserved
- Wet, safety-car and red-flag strategy remain outside version one
- Phase 3 processed rows are not automatically decision-time feature rows

## Protected temporal holdout

Phase 3 did not process or explore the 2025 season.

Final Phase 3 audit evidence includes:

- No processed `season=2025` directory
- Exploration accepts development seasons only
- No 2025 record influenced Phase 3 cleaning rules
- No 2025 record influenced eligibility rules
- No 2025 record influenced statistical outlier thresholds
- No 2025 record influenced stint or pit-duration decisions
- All 24 raw 2025 races remain reserved for final temporal evaluation

One 2025 Japanese Grand Prix session received limited schema and availability
inspection during Phase 1. That feasibility exposure occurred before Phase 3
and must be disclosed in final reporting.

The 2025 season should therefore be described as a protected temporal
evaluation holdout, not as data literally never viewed for any purpose.

## Performance evidence

The first complete development processing run:

- Wrote 66 sessions
- Skipped two previously verified sessions
- Failed zero sessions
- Completed in approximately 17.3 seconds

A complete resume run:

- Verified all 68 sessions
- Skipped all 68 sessions
- Read no raw race tables for skipped sessions
- Failed zero sessions
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

The 291 tests represent the complete backend suite at Phase 3 completion:

- 134 tests existed at Phase 2 completion
- 157 tests were added during Phase 3

Automated tests provide strong evidence of specified behaviour but do not prove
that software contains no possible defect.

## Acceptance criteria

Phase 3 acceptance criteria were satisfied:

1. Development data can be cleaned reproducibly.
2. Every excluded lap has at least one documented reason.
3. Race conditions and pit laps are classified consistently.
4. Tyre stints and pit events are reconstructed.
5. Phase 3 weather alignment contains no future observation relative to its
   cleaning timestamp.
6. Important development patterns and limitations are documented.
7. The protected 2025 season did not influence Phase 3 decisions.
8. Automated tests and code-quality checks pass.
9. Outputs can be recreated from immutable raw data.

## Phase 4 handoff

Phase 4 will use the frozen Phase 3 outputs to:

1. Define canonical start-of-lap decision rows.
2. Create modelling targets and past-only features.
3. Separate identifiers, metadata, inputs, targets and diagnostics.
4. Separate decision-row eligibility from lap-target eligibility.
5. Build whole-race temporal development folds.
6. Validate decision-time leakage automatically.
7. Version and verify modelling datasets.
8. Design PostgreSQL entities, relationships, constraints and indexes.
9. Add reproducible database migrations.
10. Load development datasets with provenance and row-count reconciliation.
11. Produce baseline-ready dataset interfaces.

Baseline implementation and model comparison belong to Phase 5.

Phase 4 must not:

- Reinterpret 2025
- Process 2025 for development
- Modify cleaning version `1.0` to improve later results
- Treat `IsEligible(t)` as an input
- Treat actual pit actions as optimal labels
- Treat observed pit-lane duration as final net pit loss
- Randomly split individual laps between training and validation