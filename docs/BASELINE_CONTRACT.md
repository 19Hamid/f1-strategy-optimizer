# Phase 5 Baseline and Evaluation Contract

## Purpose

Phase 5 establishes simple, reproducible reference predictions and a fair
temporal evaluation process. It does not train or select Phase 6 model
families.

Contract version: `1.0`

## Protected-data boundary

Only the two development folds are evaluated:

| Fold | Training | Validation |
|---|---|---|
| `development_fold_1` | 2022 | 2023 |
| `development_fold_2` | 2022–2023 | 2024 |

The `final_development_fit` assignment is not a validation fold. The protected
2025 season must not be opened, summarized or used to revise baselines,
fallbacks, metrics or acceptance thresholds.

Every race remains wholly inside one fold role.

## Lap-time population

A scored lap-time row must satisfy both:

- `is_decision_eligible = true`
- `is_lap_time_target_eligible = true`

The frozen development population contains 52,483 such rows. Validation targets
may be used only for scoring after their predictions have been produced.

## Lap-time baselines

### Previous valid lap

Prediction: `previous_lap_time_seconds`.

The row is applicable only when `previous_lap_was_target_eligible` is true and
the stored previous lap time is finite and positive. No fallback is invented.

### Rolling median

Prediction: `rolling_lap_time_median_3`, computed only from eligible completed
laps available before the decision.

Fallback:

1. Previous valid lap
2. Unavailable if neither value exists

### Stint linear trend

Prediction:

```text
previous_lap_time_seconds + rolling_lap_time_trend_5
```

The stored trend uses completed earlier laps only.

Fallback:

1. Three-lap rolling median
2. Previous valid lap
3. Unavailable

### Circuit-compound median

The implementation uses the race event as the public-data circuit identity.

Fit hierarchy:

1. Training-only event and compound median
2. Training-only compound median
3. Training-only global median

Validation races never contribute to these estimates.

## Pit-duration population

A scored row must have
`is_pit_duration_target_eligible = true`.

The target is observed pit-lane duration. It must never be described as
stationary service time, net pit loss or a counterfactual simulator parameter.

## Pit-duration baselines

### Global median

Use the median eligible duration from training races.

### Circuit median

Use the training-only event median, with global-median fallback.

### Circuit-transition median

Use the training-only event, compound-before and compound-after median.

Fallback hierarchy:

1. Event median
2. Compound-transition median
3. Global median

## Metrics

Primary metric:

- Mean absolute error in seconds

Secondary metrics:

- Root mean squared error
- Median absolute error
- 90th-percentile absolute error
- Mean signed error

Lap-time reporting must include slices by race, event, compound, tyre-age band,
driver, team and race-progress band.

Pit-duration reporting must include slices by race, event, season and compound
transition.

Every slice must report its row count. Empty and unavailable prediction cases
must not disappear from the report.

## Baseline comparison rule

Baselines are compared on the same eligible target population where practical.
Coverage must always be reported.

The strongest baseline is selected primarily by pooled validation mean absolute
error across both development folds. Coverage, per-race stability and tyre-group
performance must accompany the pooled score.

A lower error achieved by silently dropping difficult rows is not considered an
improvement.

## Reproducibility

Every experiment records:

- Baseline contract version
- Dataset contract version
- Dataset-build identifier
- Fold identity
- Training and validation sessions
- Target and eligibility rule
- Baseline identity and parameters
- Fallback counts
- Random seed
- Dependency versions
- Execution time
- Aggregate and sliced metrics

## Phase boundary

Phase 5 establishes reference performance. Random forests, gradient boosting,
neural networks and other candidate predictive models belong to Phase 6.

No baseline definition may be revised after viewing protected 2025 results.
