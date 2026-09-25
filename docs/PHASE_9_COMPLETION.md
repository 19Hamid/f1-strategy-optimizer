# Phase 9 Completion — Concurrent Simulation

## Status

Phase 9 is complete.

The final development audit succeeded on the project machine and published one
immutable Phase 9 report. The report was independently reloaded and verified
with zero integrity issues and zero protected 2025 rows.

Phase 9 contributes 5% of the project roadmap. Completing it moves overall
project progress to 91%.

## Verified scope

The audit verified:

- The complete 68-race 2022–2024 development dataset and processed catalogs
- The final Phase 6 model artifact
- The immutable Phase 7 simulation report
- The immutable Phase 8 optimizer report
- Exact reconstruction of all 124 Phase 8 historical decisions from 62 races
- Development-only uncertainty calibration
- Sequential and concurrent scenario equivalence
- Scaling across 100, 1,000 and 10,000 paired scenarios
- Atomic four-artifact publication and independent read-back verification
- Zero protected 2025 rows

The deterministic representative decision was:

- Season: 2024
- Session: `2024-04-R`
- Driver: `HAM`
- Decision lap: 38
- Target compound: `MEDIUM`
- Remaining horizon: 16 laps

## Calibration and coverage

The uncertainty calibration used 102 verified development replays, 1,375
aligned replay laps and 68 declared circuit pit-loss profiles.

| Quantity | Verified value |
|---|---:|
| Shared-pace scale | 0.439048 s |
| Lap-residual scale | 3.523793 s |
| Pit-loss sensitivity scale | 5.000000 s |
| Replay-mean central-90% coverage | 94/102 (92.16%) |
| Lap-residual central-90% coverage | 1321/1375 (96.07%) |

Coverage is an in-sample diagnostic of the declared perturbation model. It is
not strategy accuracy, out-of-sample coverage or a probability that either
action is correct.

## Scenario result

The final report stored 10,000 paired scenarios.

| Result | Verified value |
|---|---:|
| Recommendation | `NO_CLEAR_ADVANTAGE` |
| `PIT_NOW` scenario share | 59.50% |
| `STAY_OUT` scenario share | 40.50% |
| Tie scenario share | 0.00% |
| Central 90% pit-now advantage interval | [-44.462827 s, 71.892230 s] |

Positive advantage means `PIT_NOW` was faster. Although `PIT_NOW` won more
generated worlds, the central interval crossed zero. The frozen decision rule
therefore abstained. Scenario shares describe generated worlds under the
development calibration; they are not correctness probabilities.

## Scaling benchmark

Every concurrent measurement reproduced the complete sequential evidence
exactly before its timing was accepted.

| Scenarios | Mode | Workers | Duration (s) | Throughput (/s) | Speedup |
|---:|---|---:|---:|---:|---:|
| 100 | Sequential | — | 122.924860 | 0.81 | 1.000x |
| 100 | Concurrent | 1 | 98.122822 | 1.02 | 1.253x |
| 100 | Concurrent | 2 | 71.736344 | 1.39 | 1.714x |
| 100 | Concurrent | 4 | 69.494198 | 1.44 | 1.769x |
| 100 | Concurrent | 8 | 72.134901 | 1.39 | 1.704x |
| 1,000 | Sequential | — | 1149.825862 | 0.87 | 1.000x |
| 1,000 | Concurrent | 1 | 842.027522 | 1.19 | 1.366x |
| 1,000 | Concurrent | 2 | 739.803517 | 1.35 | 1.554x |
| 1,000 | Concurrent | 4 | 691.194263 | 1.45 | 1.664x |
| 1,000 | Concurrent | 8 | 701.879253 | 1.42 | 1.638x |
| 10,000 | Sequential | — | 11614.121804 | 0.86 | 1.000x |
| 10,000 | Concurrent | 1 | 9096.441903 | 1.10 | 1.277x |
| 10,000 | Concurrent | 2 | 7329.651890 | 1.36 | 1.585x |
| 10,000 | Concurrent | 4 | 7075.189679 | 1.41 | 1.642x |
| 10,000 | Concurrent | 8 | 7209.080433 | 1.39 | 1.611x |

Four workers was fastest at every measured population. Eight workers was
slightly slower, proving that additional threads did not produce unlimited
scaling on the audited machine. These timings are machine-specific evidence,
not universal performance claims.

## Stored evidence

The immutable report contains:

- `scenarios.parquet`
- `decision.parquet`
- `benchmarks.parquet`
- `provenance.json`
- `manifest.json` for exact payload identities, sizes and SHA-256 hashes

The report root is:

`artifacts/concurrent_simulation_evaluation/format_version=1.0/run_id=phase-9-final-audit`

Generated audit artifacts remain outside version control.

## Quality gates

The completion gate passed:

- 143 focused Phase 9 tests
- 1,584 repository-wide tests
- 5 expected PostgreSQL skips
- Ruff with no issues
- Dataset and Phase 6–8 upstream integrity checks
- Phase 9 report read-back verification
- Git whitespace validation
- Clean tracked worktree
- Zero protected 2025 rows

## Remaining limitations

Phase 9 does not claim:

- Calibrated probabilities that an action is correct
- Counterfactual strategy ground-truth accuracy
- Weather-transition, Safety Car, traffic, failure or rival-response modelling
- Universal performance outside the audited machine
- Protected 2025 evaluation performance

Those boundaries remain explicit inputs to Phase 10 presentation and Phase 11
final evaluation rather than being hidden behind a scenario share.
