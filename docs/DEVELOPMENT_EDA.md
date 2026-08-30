# Development Data Exploration — 2022 to 2024

## Purpose

This document records the Phase 3 exploration of processed Formula 1 race data.

Only the 2022, 2023 and 2024 development seasons were examined. The protected
2025 evaluation season did not influence cleaning rules, outlier decisions or
exploratory thresholds.

## Reproducibility

The exploration uses:

- Cleaning-rule version `1.0`
- Processed-data contract `1.0`
- Exploration version `1.0`
- Lap-outlier policy `FLAG_ONLY`

The permanent implementation is:

```text
backend/app/cleaning/exploration.py
```

It verifies every requested processed partition before analysis.

## Development dataset

| Season | Sessions |
|---|---:|
| 2022 | 22 |
| 2023 | 22 |
| 2024 | 24 |
| Total | 68 |

Raw development totals:

| Table | Rows |
|---|---:|
| Laps | 74,601 |
| Weather observations | 11,115 |
| Driver results | 1,359 |

## Initial quality profile

The raw development profile recorded:

| Condition | Rows |
|---|---:|
| Missing lap time | 1,187 |
| Non-positive lap time | 0 |
| Inaccurate lap | 10,122 |
| First lap | 1,350 |
| Pit-in marker | 2,628 |
| Pit-out marker | 2,604 |
| Missing at least one sector | 1,676 |
| Invalid or missing tyre life | 555 |
| FastF1-generated lap | 105 |
| Duplicate lap identity | 0 |

No conflicting duplicate lap identities were found.

## Weather alignment

Every development lap was aligned to the latest weather observation available
at or before its timestamp.

Results:

| Measure | Value |
|---|---:|
| Matched laps | 74,601 |
| Unmatched laps | 0 |
| Rain-aligned laps | 3,586 |
| Future weather matches | 0 |
| Reordered weather sessions | 0 |
| Median observation age | 30.049 seconds |
| 95th-percentile age | 57.072 seconds |
| Maximum age | 99.105 seconds |

Rainfall alignment added 1,042 `WET_CONDITION` reasons and newly excluded 650
laps that were not already excluded by another rule.

## Final lap eligibility

| Measure | Rows |
|---|---:|
| Processed laps | 74,601 |
| Eligible laps | 57,871 |
| Excluded laps | 16,730 |
| Eligibility rate | 77.57% |

Eligibility by season:

| Season | Eligible | Total | Rate |
|---|---:|---:|---:|
| 2022 | 16,830 | 23,577 | 71.38% |
| 2023 | 19,853 | 24,420 | 81.30% |
| 2024 | 21,188 | 26,604 | 79.64% |

## Exclusion and quality reasons

| Reason | Rows |
|---|---:|
| `INACCURATE_LAP` | 10,122 |
| `NON_GREEN_TRACK` | 7,835 |
| `WET_CONDITION` | 5,850 |
| `PIT_IN_LAP` | 2,628 |
| `PIT_OUT_LAP` | 2,604 |
| `MISSING_SECTOR_TIME` | 1,676 |
| `FIRST_LAP` | 1,350 |
| `MISSING_LAP_TIME` | 1,187 |
| `INVALID_TYRE_LIFE` | 555 |
| `UNSUPPORTED_COMPOUND` | 369 |

The remaining defined reason codes recorded zero development rows.

A lap may have multiple reasons, so reason counts do not sum to the number of
excluded laps.

## Sessions with no eligible dry laps

Two development races produced zero eligible laps:

- 2022 Japanese Grand Prix
- 2024 São Paulo Grand Prix

These sessions remain represented in the processed catalog and quality
reports. They provide no controlled dry green-flag lap-time samples.

## Eligible dry compounds

| Compound | Eligible laps | Median tyre life | Maximum tyre life |
|---|---:|---:|---:|
| HARD | 28,984 | 15 | 78 |
| MEDIUM | 21,733 | 12 | 77 |
| SOFT | 7,154 | 11 | 49 |

Raw lap-time medians differ across compounds, but they must not be interpreted
as causal compound effects. Compound selection is confounded by circuit,
driver, fuel load, race progress, stint purpose and track evolution.

Future modelling must retain this context.

## Tyre-stint reconstruction

The reconstruction produced:

| Measure | Value |
|---|---:|
| Driver-race combinations | 1,350 |
| Reconstructed stints | 3,888 |
| Complete stints | 3,845 |
| Incomplete stints | 43 |
| Completion rate | 98.89% |
| Dry-compound stints | 3,537 |

Dry-stint summaries:

| Compound | Stints | Complete | Median laps | Mean laps | 95th percentile | Maximum |
|---|---:|---:|---:|---:|---:|---:|
| MEDIUM | 1,462 | 1,456 | 17 | 18.10 | 35 | 77 |
| HARD | 1,332 | 1,314 | 24 | 25.16 | 45 | 77 |
| SOFT | 743 | 743 | 13 | 12.73 | 26 | 50 |

Non-zero warning counts were:

| Warning | Stints |
|---|---:|
| `UNSUPPORTED_COMPOUND` | 14 |
| `MISSING_TYRE_LIFE` | 35 |
| `MISSING_PIT_EVIDENCE_BEFORE` | 6 |
| `MISSING_PIT_EVIDENCE_AFTER` | 6 |

The unsupported normalized compound value was `NONE`.

No compound changes without a stint boundary were found. No tyre-life
decreases, tyre-life step mismatches, disjoint reused stint identifiers or lap
number gaps were found.

## Pit-event reconstruction

| Measure | Events |
|---|---:|
| Reconstructed pit events | 2,693 |
| Matched complete events | 2,539 |
| Entry-only events | 89 |
| Exit-only events | 65 |
| Incomplete events | 154 |
| Duration-analysis candidates | 1,465 |

All 5,232 raw pit markers were represented.

Non-zero warning counts included:

| Warning | Events |
|---|---:|
| `ENTRY_ONLY` | 89 |
| `EXIT_ONLY` | 65 |
| `NO_STINT_CHANGE` | 7 |
| `MISSING_COMPOUND_BEFORE` | 65 |
| `MISSING_COMPOUND_AFTER` | 89 |
| `UNSUPPORTED_COMPOUND_BEFORE` | 1 |
| `UNSUPPORTED_COMPOUND_AFTER` | 9 |
| `NON_GREEN_ENTRY` | 808 |
| `NON_GREEN_EXIT` | 713 |
| `INTERRUPTED_DURATION` | 202 |

## Candidate pit-duration distribution

For the 1,465 dry, green and uninterrupted candidates:

| Statistic | Seconds |
|---|---:|
| Minimum | 15.105 |
| 1st percentile | 17.675 |
| 5th percentile | 19.590 |
| Median | 23.245 |
| 95th percentile | 30.495 |
| 99th percentile | 39.712 |
| Maximum | 74.951 |

Event medians varied materially.

Examples:

| Event | Median seconds |
|---|---:|
| Australian Grand Prix | 18.078 |
| Dutch Grand Prix | 20.688 |
| Bahrain Grand Prix | 25.061 |
| Qatar Grand Prix | 28.688 |
| British Grand Prix | 29.143 |
| Singapore Grand Prix | 29.676 |
| Emilia Romagna Grand Prix | 30.160 |
| French Grand Prix | 36.788 |

## Pit-duration decision

No single global pit-duration or pit-loss constant will be used.

Future pit-loss estimation must retain at least:

- Circuit or event identity
- Season
- Entry and exit conditions
- Compound transition
- Available traffic context
- Timing-method limitations

Observed pit-lane duration is not yet a final simulator parameter.

## Contextual lap-time outliers

Potential outliers were evaluated within:

```text
session + driver + compound
```

The exploratory method uses:

- At least 5 contextual laps
- Context median
- Median absolute deviation
- Absolute robust-score threshold of 6.0

Results:

| Measure | Laps |
|---|---:|
| Potential contextual outliers | 541 |
| Share of eligible laps | 0.93% |
| Slow-direction outliers | 526 |
| Fast-direction outliers | 15 |
| Shared-lap-cluster outliers | 193 |
| Outliers outside shared clusters | 348 |

Large shared clusters occurred around laps such as:

- 2022 British Grand Prix lap 3
- 2023 Mexico City Grand Prix lap 36
- 2023 São Paulo Grand Prix lap 4

Other clusters occurred during changing weather, restart-like conditions,
traffic compression or unusual race progress.

## Frozen outlier decision

The final Phase 3 policy is:

```text
FLAG_ONLY
```

None of the 541 statistical outliers is automatically excluded.

Reasons:

- A robust score identifies unusual values, not their cause.
- Only 193 outliers belonged to shared lap clusters.
- Track status was often exactly green.
- Rainfall and generated-lap markers did not explain every case.
- Available relative timing did not provide a reliable deterministic restart
  indicator.
- Individual slow laps may represent traffic, mistakes, tyre management,
  changing grip or legitimate race events.

Potential outliers remain eligible unless an independent documented cleaning
reason applies.

## `LapStartDate` limitation

`LapStartDate` was null for all 74,601 development laps.

Relative timing remains available through session-duration columns, but Phase
4 must not create absolute-time features from `LapStartDate`.

## Additional limitations

Phase 3 does not resolve:

- Counterfactual lap performance
- Exact stationary pit-stop duration
- Net pit-loss under alternative traffic
- Fuel load directly
- Detailed traffic and dirty-air effects
- Driver intent or team instruction
- Restart classification when source status is insufficient
- Wet-weather strategy modelling
- Safety-car strategy modelling

These limitations must be handled explicitly in later dataset, modelling and
simulation phases.

## Protected evaluation season

No processed `season=2025` directory was created.

The exploration module rejects 2025, and no 2025 records influenced:

- Cleaning rules
- Eligibility
- Outlier thresholds
- Pit-duration decisions
- Stint decisions
- Documented limitations