# Phase 5 Completion — Baselines and Evaluation

## Completion status

Phase 5 is complete.

The phase established deterministic reference methods for lap-time and observed
pit-lane-duration prediction, evaluated them on frozen whole-race temporal
folds, and stored integrity-checked experiment evidence.

Baseline contract version: `1.0`

Report format version: `1.1`

## Development boundary

Only 2022–2024 development races were used.

| Fold | Training seasons | Validation season |
|---|---|---|
| `development_fold_1` | 2022 | 2023 |
| `development_fold_2` | 2022–2023 | 2024 |

Each race remained wholly within one fold role. The final audit found zero 2025
rows in decision data, pit-duration data or split assignments.

The 2025 season remains protected for final project evaluation. One 2025
Japanese Grand Prix session received limited schema and availability inspection
during Phase 1; that exposure remains disclosed and did not influence Phase 5
baseline definitions or selection.

## Implemented baselines

### Lap time

1. Previous valid eligible lap
2. Past-only three-lap rolling median
3. Past-only five-lap stint linear trend
4. Training-only event-compound median with documented fallbacks

### Observed pit-lane duration

1. Training-only global median
2. Training-only event median with global fallback
3. Training-only event and compound-transition median with event, transition
   and global fallbacks

Observed pit-lane duration is not stationary service time, net pit loss or a
counterfactual simulator parameter.

## Frozen metrics

The primary metric is mean absolute error in seconds.

Secondary evidence includes:

- Root mean squared error
- Median absolute error
- 90th-percentile absolute error
- Mean signed error
- Prediction coverage
- Fallback counts
- Row-level residuals
- Required race, event, compound, tyre-age, driver, team and progress slices

## Real 68-race audit

The final development audit recorded:

| Measure | Result |
|---|---:|
| Requested development races | 68 |
| Valid development races | 68 |
| Dataset catalog rows | 68 |
| Temporal split assignments | 204 |
| Eligible lap-time targets | 52,483 |
| Eligible pit-duration targets | 1,465 |
| Protected 2025 rows | 0 |
| Stored report artifacts | 4 |
| Report integrity issues | 0 |

The warning-as-error backend suite recorded 1,099 passing tests. Five
PostgreSQL integration tests remained intentionally isolated from the unit
suite; their PostgreSQL workflow was completed during Phase 4.

## Selected reference baselines

Selection uses pooled temporal-validation mean absolute error. Coverage is
reported beside error and is never silently discarded.

| Task | Selected baseline | Pooled MAE | Coverage | Scored rows |
|---|---|---:|---:|---:|
| Lap time | `previous_valid_lap` | 0.410049 s | 97.0376% | 36,392 |
| Observed pit-lane duration | `pit_circuit_median` | 1.587942 s | 100.0000% | 1,048 |

The lap winner is deliberately described as a reference, not as proof that the
problem is solved. It cannot predict rows without an eligible previous lap, so
its 2.9624% unavailable share remains a material limitation.

## Stored evidence

The final report is generated locally below:

`artifacts/baseline_evaluation/contract_version=1.1/run_id=phase-5-final-audit`

It contains:

- `summary.parquet` — 14 fold-baseline aggregate results
- `slices.parquet` — required subgroup metrics with row counts
- `predictions.parquet` — row-level targets, predictions and residuals
- `provenance.json` — contracts, dataset identity, folds, rules, parameters,
  fallbacks, dependency versions, seed and execution time
- `manifest.json` — artifact sizes and SHA-256 hashes

Generated reports are ignored by Git because they are reproducible artifacts,
not source code.

## Reproduce the audit

From the repository root:

```bash
bash ./scripts/run_development_baseline_audit.sh
```

The command first verifies all 68 dataset partitions, evaluates the two frozen
development folds, writes the report atomically and verifies every artifact.

## Phase 6 acceptance threshold

Phase 6 may train and select tyre-degradation and lap-time models, but it must
not claim improvement merely from using a more complicated algorithm.

A candidate lap-time model must:

1. Be evaluated on the same two whole-race temporal folds.
2. Use only information available at the start of the decision lap.
3. Beat 0.410049 seconds pooled MAE on a directly comparable scored population.
4. Report coverage of at least 97.0376%.
5. Report performance on the common rows shared with
   `previous_valid_lap`.
6. Report all required slices and per-race stability.
7. Keep 2025 completely outside model selection and hyperparameter tuning.

A model with lower MAE caused by dropping difficult rows is not an
improvement. Full-coverage candidates must report both their full-population
score and their common-row comparison with the selected baseline.

The selected `pit_circuit_median` result remains the observed-duration
reference for later simulator work. It must not be treated as net pit loss
without an explicit later transformation and validation.

## Phase boundary

Phase 5 selected simple reference methods. It did not train random forests,
gradient boosting, neural networks or other Phase 6 candidates.

Phase 6 begins with model and feature contracts, training-only preprocessing,
and comparison against the thresholds recorded above.
