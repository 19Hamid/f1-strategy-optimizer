# Phase 9 Concurrent Simulation Contract

## Status and identity

- Contract version: `1.0`
- Current Phase 9 completion: 93%
- Development seasons: 2022–2024
- Protected temporal evaluation season: 2025
- Scope: controlled dry-race, green-flag pit-now versus stay-out decisions
- Default benchmark population: 10,000 paired scenarios

Phase 9 adds probabilistic scenario execution around the verified Phase 8
decision comparison. It does not retrain the Phase 6 model, change the Phase 7
state-transition rules or rewrite the immutable Phase 8 audit.

The current milestone executes complete paired scenario batches either
sequentially or through a bounded thread pool. Both paths produce exactly the
same canonically ordered outcomes and descriptive summaries. A frozen scaling
benchmark measures complete-call wall time without assuming concurrency is
faster. Normalized scenario, decision, benchmark and provenance evidence can
now be published atomically and verified after read-back. These summaries are
not calibrated probabilities of choosing the correct action.

## Why scenarios are paired

One scenario represents one possible future race world. The `PIT_NOW` and
`STAY_OUT` actions must be evaluated inside that same world.

Both actions therefore receive the same:

- Shared race-pace draw
- Pit-loss draw
- Absolute-lap residual draw for every remaining lap
- Root seed, scenario identity and uncertainty calibration

This common-random-number design prevents the action comparison from being
polluted by two unrelated sets of random luck. The two strategies may respond
differently because they create different tyre and stint states, but the
underlying scenario evidence remains paired.

## Scenario request

A `ScenarioBatchRequest` contains:

- One complete verified Phase 8 `PitDecisionRequest`
- A scenario count from 1 through 100,000
- An explicit root seed from 0 through `2^32 - 1`

The default count is 10,000 because the frozen evaluation plan names that as
the first concurrency benchmark. Smaller populations remain legal for unit
tests, diagnostics and progressive benchmark measurements.

The inherited Phase 8 request preserves the start-of-lap timestamp, exact two
actions, shared target compound and protected-season boundary.

## Standardized scenario evidence

The scenario generator produces dimensionless standard-normal coordinates:

| Draw | Purpose |
|---|---|
| `shared_pace_z` | A scenario-level pace component shared across the remaining race |
| `pit_loss_z` | A paired perturbation coordinate for the explicit pit-loss mechanism |
| `lap_time_residual_z` | One coordinate keyed by each absolute remaining race lap |

The generator itself remains dimensionless. The stochastic rollout layer maps
these coordinates to seconds only through an explicit development calibration.
The mapping is stored separately so an arbitrary standard deviation cannot be
disguised as model knowledge.

Weather transitions, Safety Cars, traffic interactions, failures and rival
team reactions are not silently represented by these coordinates.

## Development-only uncertainty calibration

The frozen calibration method is:

`development-replay-decomposition-and-pit-range-v1`

It consumes signed observed-minus-predicted lap errors from verified
development replays and explicit development-only circuit pit-loss ranges.

- The population standard deviation of replay-level mean signed errors becomes
  the shared pace scale.
- The population standard deviation of lap errors after subtracting their
  replay mean becomes the absolute-lap residual scale.
- The root mean square distance of declared low/high pit loss from nominal
  becomes the pit-loss sensitivity scale.

Every observation carries a development season. Protected 2025 observations,
unknown seasons, duplicate replay-lap identities, duplicate circuit-profile
identities, insufficient populations and zero or non-finite scales fail
closed.

The pit-loss value is a sensitivity scale from declared circuit ranges. It is
not mislabeled observed pit-lane duration and is not claimed to be a fitted
probability distribution.

## Calibrated stochastic action rollout

For one scenario, both `PIT_NOW` and `STAY_OUT` receive the same:

- Shared pace adjustment in seconds on every absolute remaining lap
- Absolute-lap residual adjustment in seconds
- Pit-loss adjustment in seconds
- Scenario seed and calibration identity

Each action still follows its own complete Phase 8 strategy timing and
tyre-state evolution. Adjusted lap time is fed back into later model features,
so the actions may react differently to the same possible race world.

Every rollout preserves the nominal model prediction beside each adjustment,
reaches the flag and reconciles the complete remaining time. Physically
impossible negative lap or pit-loss values are bounded at zero-safe floors and
the clipping is explicitly recorded instead of hidden.

## Sequential aggregation

The frozen sequential aggregator identity is:

`ordered-paired-scenario-aggregation-v1`

It evaluates scenarios in contiguous generated order and stores one compact
outcome per scenario containing both complete remaining times, their paired
difference, the scenario seed and the action that was faster inside that
world.

Three distributions are reported:

- Complete `PIT_NOW` remaining time
- Complete `STAY_OUT` remaining time
- Paired pit-now advantage, defined as stay-out time minus pit-now time

Each distribution reports count, mean, population standard deviation, minimum,
5th percentile, median, 95th percentile and maximum. Percentiles use frozen
linear interpolation.

Action shares count the simulated worlds favouring `PIT_NOW`, `STAY_OUT` or
a numerical tie. They must be named scenario shares, not correctness
probabilities.

A stability recommendation is allowed only with at least 100 paired scenarios.
It returns `PIT_NOW` when the complete central 90% empirical advantage
interval is above zero, `STAY_OUT` when it is below zero and
`NO_CLEAR_ADVANTAGE` otherwise. This is interval stability under the declared
scenario model. It is not a 90% confidence statement about the real race.

## Concurrent execution

The frozen concurrent executor identity is:

`thread-pool-paired-scenario-v1`

It evaluates independent paired scenarios in a bounded thread pool. The worker
count is explicit, defaults to four and must remain between one and 32. Workers
share only the verified read-only model adapter, immutable scenario batch,
calibration and initial feature context. Each worker runs both actions for one
scenario so the paired evidence is never split across workers.

Thread completion order is not evidence order. Every result is checked against
the scenario identity assigned to its worker and then restored to contiguous
scenario-index order before aggregation. A worker exception, missing result or
wrong scenario identity fails the complete execution instead of publishing a
partial batch.

The concurrent result must equal the sequential result exactly: the batch,
calibration, ordered outcome objects, complete action times, paired advantages,
preference shares, distributions and recommendation are identical. Unit tests
prove this with one, two and four workers and with deliberately scrambled
completion order.

This semantic-equivalence guarantee remains mandatory for every timed run.

## Performance benchmark

The frozen benchmark identity is:

`paired-scenario-wall-clock-scaling-v1`

The default scaling plan measures 100, 1,000 and 10,000 paired scenarios with
one, two, four and eight workers. All populations use the same decision,
calibration, feature context, model artifact, root seed and deterministic
scenario prefix.

Before timing, one scenario warms the sequential path and every requested
concurrent path. Warm-up time is excluded. Each recorded duration measures one
complete public evaluation call with a monotonic wall clock. Concurrent timing
therefore includes thread-pool construction, task submission, result ordering
and shutdown rather than hiding orchestration overhead.

The sequential path is the baseline at every population size. Every concurrent
measurement must reproduce its complete sequential evidence exactly before its
timing is accepted. The benchmark records every positive duration and derives:

- Median wall-clock duration
- Paired scenarios completed per second
- Speedup as sequential median divided by measured-path median
- Worker efficiency as speedup divided by worker count

One repetition is the default because a complete 10,000-scenario run is
expensive; up to five explicit repetitions are legal and the full duration
vector remains visible. These measurements describe runtime on the machine and
software configuration that produced them. They are not universal performance
claims or statistical confidence intervals.

A concurrent result may honestly have speedup below one and efficiency below
one. The benchmark never converts a slowdown into success.

## Reporting and immutable artifacts

The report format version is `1.0`. One run is stored below
`artifacts/concurrent_simulation_evaluation` in a format-version and run-ID
directory. An existing run directory is never overwritten.

Each report has exactly four payload artifacts:

- `scenarios.parquet` stores the largest benchmark population in canonical
  scenario-index order, including standardized draws, absolute-lap residual
  coordinates, complete action times, paired advantage, preference and seed.
- `decision.parquet` stores the decision state, assumptions, calibration,
  descriptive distributions, empirical action shares and stability result.
- `benchmarks.parquet` stores every population and execution-path measurement,
  including raw duration vectors and recomputed performance metrics.
- `provenance.json` stores contract and artifact identities, development-data
  boundary, root seed, population and worker grids, dependency versions,
  machine identity, CPU count, execution duration and exact row counts.

A fifth file, `manifest.json`, records the report format, contract version,
run identity, exact payload file set, byte sizes and SHA-256 hashes. Publication
uses a temporary directory followed by one atomic rename. A report is accepted
only after all payloads are reloaded and their schemas, counts, scenario
arithmetic, distributions, shares, recommendation, benchmark arithmetic,
provenance and hashes are independently verified.

Machine provenance makes benchmark evidence attributable; it does not make one
machine's timing a universal performance guarantee. The report also records
zero protected-evaluation rows and rejects any decision outside the declared
2022–2024 development seasons.

## Deterministic generation

The frozen generator identity is:

`sha256-box-muller-standard-normal-v1`

For each root seed, scenario index and draw channel, SHA-256 creates an
independent deterministic byte stream. Two open-interval uniform values are
converted to one standard-normal value with the Box–Muller transform.

The contract guarantees:

- Identical requests generate identical scenarios in identical order.
- Scenario indices are contiguous from zero.
- Scenario seeds are unique within a batch.
- Increasing the requested batch size does not change the existing prefix.
- Every scenario covers the complete absolute-lap decision horizon.
- Changing the root seed produces a different reproducible stream.
- Scenario generation never mutates the deterministic Phase 8 request.

The generator identity, contract version, root seed and scenario index must be
stored with later execution and reporting evidence. Any deliberate generator
change requires a contract revision.

## Recommendation boundary

The 93% milestone reports empirical scenario distributions, action shares and
an abstaining interval-stability recommendation through sequential or exactly
equivalent bounded concurrent execution. It also stores measured runtime,
throughput, speedup and worker efficiency with normalized scenario and decision
evidence in an immutable, integrity-checked report. Runtime performance and
artifact integrity do not prove that an action is correct.

Before any stronger language is permitted:

1. Interval coverage and width must be evaluated on development evidence.
2. A final recommendation threshold must be frozen before protected evaluation.
3. Protected 2025 performance must remain unseen until final evaluation.

A result such as 70% `PIT_NOW` means only that `PIT_NOW` was faster in 70%
of the generated race worlds under the declared calibration and assumptions.

## Phase 9 milestones

| Milestone | Result | Phase 9 completion |
|---|---|---:|
| 1. Scenario contract | Freeze pairing, scope, seed and uncertainty coordinates | 10% |
| 2. Deterministic scenario generation | Produce complete reproducible standardized scenario batches | 25% |
| 3. Stochastic action rollout | Apply calibrated paired perturbations to both complete strategies | 45% |
| 4. Sequential aggregation | Report distributions, intervals and recommendation stability | 60% |
| 5. Concurrent executor | Prove concurrent and sequential equivalence | 75% |
| 6. Performance benchmark | Measure throughput, speedup and scaling through 10,000 scenarios | 85% |
| 7. Reporting and artifacts | Store immutable scenario, decision and benchmark evidence | 93% |
| 8. Final audit | Verify development calibration, coverage, performance and documentation | 100% |

## Final audit runner

The final-audit implementation is ready, but Phase 9 remains at 93% until the
real run succeeds and its measured output is reviewed. From the repository
root, run:

```bash
bash scripts/run_development_concurrent_simulation_audit.sh
```

The runner fails closed unless the complete 68-race development catalog, the
matching processed catalog, the final Phase 6 model, the immutable Phase 7
replay report and the immutable Phase 8 optimizer report all verify. It then
reconstructs the Phase 8 candidate population and requires its exact decision
keys to match all 124 stored Phase 8 decisions.

The expensive scaling benchmark uses one representative decision selected by
a frozen rule: sort the reconciled decisions by remaining-lap count and then
decision key, and choose the lower median. This makes the selection typical by
horizon and deterministic; it does not select the decision with the most
favourable recommendation or fastest runtime.

Development replay coverage is reported separately for replay-level mean
errors and within-replay lap residuals against zero-centred central-90% normal
intervals from the fitted scales. This is an in-sample diagnostic of the
declared perturbation model. It is not out-of-sample coverage, strategy
accuracy, or a probability that `PIT_NOW` or `STAY_OUT` is correct.

## Acceptance gates through 93%

1. Phase 9 consumes a complete Phase 8 decision request without weakening it.
2. Scenario populations are bounded and have an explicit root seed.
3. Scenario indices are canonical, ordered and unique.
4. Every scenario has one unique deterministic seed.
5. Every scenario covers every remaining absolute race lap exactly once.
6. All standardized draws are finite.
7. Identical requests reproduce identical complete batches.
8. Batch-size changes preserve the existing scenario prefix.
9. Root-seed changes produce a different stream.
10. The generator algorithm and draw order are protected by snapshot tests.
11. Generated values pass a deterministic basic distribution-shape check.
12. The base Phase 8 request remains immutable.
13. The protected 2025 season remains rejected by inherited contracts.
14. No probability, interval coverage or accuracy claim is introduced.
15. Calibration consumes development seasons only and rejects protected 2025.
16. Replay-level mean error and within-replay lap residual are separated.
17. Pit-loss scale uses declared circuit sensitivity, not pit-lane duration.
18. Both actions receive identical absolute-lap and pit-loss perturbations.
19. Nominal model output remains visible beside every applied adjustment.
20. Both perturbed actions run to the flag and reconcile remaining time.
21. Any physical floor clipping is explicit in returned evidence.
22. Sequential evaluation preserves canonical scenario order and seeds.
23. Every paired advantage reconciles with its two complete action times.
24. Distribution quantiles use frozen deterministic linear interpolation.
25. Scenario preference shares reconcile exactly to one.
26. Fewer than 100 scenarios can never produce a stable recommendation.
27. Stability requires the central 90% paired-advantage interval to exclude zero.
28. Scenario shares and interval stability are not called correctness probability.
29. Concurrent worker counts are bounded from one through 32.
30. Worker completion order cannot change canonical evidence order.
31. Worker failures, missing results and wrong scenario identities fail closed.
32. One-, two- and four-worker output exactly equals sequential output.
33. Warm-up execution is excluded from recorded benchmark durations.
34. Timings cover complete calls including concurrent orchestration overhead.
35. Every timed concurrent run passes exact sequential-equivalence verification.
36. Scenario and worker grids are unique, increasing and explicitly bounded.
37. Throughput, speedup and worker efficiency reconcile from recorded durations.
38. Slow concurrent results remain valid evidence and are never relabeled success.
39. The default scaling grid reaches 10,000 paired scenarios.
40. Scenario, decision and benchmark tables have exact normalized schemas.
41. Stored scenario rows use the largest benchmark population in canonical order.
42. Stored distributions, shares and recommendation recompute from scenario rows.
43. Stored medians, throughput, speedup and efficiency recompute from raw timings.
44. Provenance freezes contracts, artifacts, data, calibration and machine identity.
45. Reports publish atomically and an existing run can never be overwritten.
46. The manifest verifies the exact payload set, byte sizes and SHA-256 hashes.
47. Read-back reconstructs and revalidates every normalized report table.
48. Reports reject protected rows and decisions outside 2022–2024 development.
49. Focused tests and repository-wide quality checks pass with warnings as
    errors.

## Current exclusions

The milestone does not yet provide:

- Calibrated action-correctness probabilities
- Development-wide interval coverage and recommendation calibration
- Weather, Safety Car, traffic or failure processes
- Protected 2025 evaluation

Those capabilities remain explicit later milestones rather than being implied
by the stored scenario summaries.
