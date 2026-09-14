# Development Data Profile

## Purpose

This report records the initial quality profile of the Formula 1 development
data collected during Phase 2.

The profile was produced before the permanent Phase 3 cleaning pipeline was
completed. It documents the evidence that informed cleaning version `1.0`.

The investigation covers only:

- 2022
- 2023
- 2024

The protected 2025 temporal evaluation season was not inspected by the Phase 3
development profiler.

One 2025 session received a separate limited schema and availability inspection
during Phase 1. That earlier feasibility check did not determine the Phase 3
profile, cleaning rules or statistical thresholds.

## Reproducibility

The permanent profiler is implemented in:

```text
backend/app/cleaning/profile.py
```

It reads verified raw development partitions and reproduces the documented
counts without modifying source data.

## Dataset scale

The development dataset contains:

| Table | Records |
|---|---:|
| Race sessions | 68 |
| Lap records | 74,601 |
| Weather observations | 11,115 |
| Driver-result records | 1,359 |

The development seasons contain:

- 22 races from 2022
- 22 races from 2023
- 24 races from 2024

## Structural quality

The initial audit found:

- Zero duplicate lap identities
- Zero missing driver values
- Zero missing team values
- Zero missing lap numbers
- Zero missing stint numbers
- Zero missing track-status values
- Zero missing lap-start times
- Zero missing accuracy indicators
- Zero non-positive lap times
- Zero invalid non-null tyre-life values
- Zero deleted race laps

This indicates strong structural consistency while still leaving important
quality conditions that require explicit treatment.

## Lap-quality findings

| Finding | Records | Approximate share |
|---|---:|---:|
| Missing lap time | 1,187 | 1.6% |
| Marked inaccurate | 10,122 | 13.6% |
| First lap of race | 1,350 | 1.8% |
| Pit-entry lap | 2,628 | 3.5% |
| Pit-exit lap | 2,604 | 3.5% |
| Missing at least one sector time | 1,676 | 2.2% |
| Missing tyre life | 555 | 0.7% |
| FastF1-generated lap | 105 | 0.1% |

These categories overlap and must not be added together to calculate the number
of unusable laps.

A lap may simultaneously be inaccurate, contain a pit marker and have a
missing sector time.

## Missing lap times

Missing lap times appear in 54 of the 68 development races.

This does not make those complete sessions unusable. Missing times may be
associated with retirements, incomplete laps, timing interruptions or other
race events.

Rows with missing lap times remain traceable but cannot serve as lap-time
prediction targets.

## Accuracy indicator

FastF1 marks 10,122 laps as inaccurate.

Cleaning version `1.0` preserves these rows but excludes them from controlled
lap-time eligibility.

The accuracy flag is a completed-lap cleaning value. It must not become a
start-of-lap model input.

## Sector times

A total of 1,676 laps are missing at least one sector time.

A missing sector does not independently invalidate a lap when its complete lap
time remains available.

Sector availability is recorded separately from total lap-time eligibility.

## Track status

Exactly 66,766 laps, approximately 89.5% of the development data, have track
status `1`.

The remaining records include individual and combined status values.

The most common values include:

| Track status | Records |
|---|---:|
| `1` | 66,766 |
| `12` | 2,401 |
| `4` | 1,912 |
| `41` | 742 |
| `124` | 530 |
| `671` | 362 |
| `126` | 304 |
| `21` | 249 |
| `26` | 158 |
| `6` | 145 |

Combined values indicate that track conditions changed or that multiple
statuses applied during the recorded lap.

Cleaning version `1.0` considers only exact value `1` to be controlled
green-flag running. Other values are preserved and flagged.

The completed-lap status is suitable for target cleaning but is not
automatically safe as a start-of-lap Phase 4 feature.

## Tyre compounds

| Compound | Lap records | Approximate share |
|---|---:|---:|
| HARD | 33,514 | 44.9% |
| MEDIUM | 26,455 | 35.5% |
| SOFT | 9,455 | 12.7% |
| INTERMEDIATE | 4,347 | 5.8% |
| WET | 461 | 0.6% |
| NONE | 369 | 0.5% |

Dry compounds account for most of the dataset.

INTERMEDIATE and WET records are classified as wet-condition laps and excluded
from controlled version-one lap targets.

The `NONE` value is a normalized source category rather than a null value. It
is treated as an unsupported compound.

Raw compound summaries must not be interpreted as causal tyre effects because
compound selection depends on circuit, driver, race progress, fuel load,
traffic, stint purpose and track evolution.

## Rainfall observations

Rainfall was recorded during 16 development sessions:

- 2022-05-R
- 2022-07-R
- 2022-10-R
- 2022-13-R
- 2022-17-R
- 2022-18-R
- 2023-06-R
- 2023-09-R
- 2023-12-R
- 2023-13-R
- 2023-20-R
- 2024-09-R
- 2024-10-R
- 2024-11-R
- 2024-12-R
- 2024-21-R

A rainy session is not necessarily wet for its entire duration. Phase 3 aligned
weather observations to individual laps before applying rainfall exclusions.

## Wet-compound sessions

Wet-weather compounds were used during nine development sessions:

- 2022-04-R
- 2022-07-R
- 2022-17-R
- 2022-18-R
- 2023-06-R
- 2023-13-R
- 2024-09-R
- 2024-12-R
- 2024-21-R

The difference between rainfall sessions and wet-compound sessions confirms
that complete races should not be discarded merely because one rainfall
observation exists.

Lap-level classification is required.

## Data-type consistency

One lap column had inconsistent stored data types across sessions:

- `IsPersonalBest`: `bool` in some sessions and `object` in others

The Phase 3 processing pipeline normalizes this field to a nullable boolean
type.

No other lap-column data-type conflicts were detected.

## Result-status observations

The most common driver-result statuses are:

| Status | Driver results |
|---|---:|
| Finished | 870 |
| Lapped | 208 |
| Retired | 102 |
| +1 Lap | 80 |
| Collision damage | 14 |
| Accident | 11 |
| Collision | 10 |
| Engine | 7 |
| Power Unit | 6 |
| +2 Laps | 6 |
| Did not start | 6 |
| Gearbox | 4 |

Result status provides context for incomplete races and missing lap times.

It is not used to insert missing targets and must never become an input for an
earlier race decision.

## Initial decisions from the profile

The audit supported these Phase 3 decisions:

1. Preserve the raw dataset unchanged.
2. Classify eligibility at lap level instead of discarding complete races.
3. Treat only exact track status `1` as controlled green-flag running.
4. Align weather observations before applying rainfall exclusions.
5. Retain SOFT, MEDIUM and HARD for controlled analysis.
6. Preserve missing lap-time rows but do not use them as prediction targets.
7. Exclude inaccurate laps from controlled lap-time eligibility.
8. Retain laps with missing sectors when valid total lap time exists.
9. Normalize `IsPersonalBest` to a nullable boolean type.
10. Preserve FastF1-generated laps without creating an independent exclusion
    reason.

## Limitations of the initial profile

The initial individual-condition counts did not yet represent final eligibility
because:

- Several quality conditions overlap
- Weather required lap-level alignment
- Pit-entry and pit-exit classifications overlap other exclusions
- Statistical unusualness required contextual investigation
- Stint and pit-event consistency required reconstruction

These limitations were resolved through the permanent Phase 3 pipeline and
development exploration.

## Phase 3 resolution

The completed Phase 3 process produced:

| Measure | Value |
|---|---:|
| Processed laps | 74,601 |
| Eligible controlled laps | 57,871 |
| Excluded laps | 16,730 |
| Eligibility rate | 77.57% |
| Reconstructed stints | 3,888 |
| Reconstructed pit events | 2,693 |
| Duration-analysis candidates | 1,465 |
| Future matches in Phase 3 weather alignment | 0 |

Every excluded lap has at least one documented reason.

The final statistical-outlier policy is:

```text
FLAG_ONLY
```

Potential statistical outliers remain eligible unless an independent cleaning
reason applies.

## Phase 4 interpretation

This profile describes completed historical laps. It does not establish that
values stored on lap `t` were available at the start of that lap.

Phase 4 must separately construct:

- Start-of-lap decision rows
- Past-only features
- Decision-time weather
- Reconstructed tyre state
- Separate decision and target eligibility
- Whole-race temporal splits

The authoritative Phase 3 outcomes are documented in:

- `docs/CLEANING_RULES.md`
- `docs/PROCESSED_DATA_CONTRACT.md`
- `docs/DEVELOPMENT_EDA.md`
- `docs/PHASE_3_COMPLETION.md`