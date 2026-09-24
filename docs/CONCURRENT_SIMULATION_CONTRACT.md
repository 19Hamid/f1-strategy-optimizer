# Phase 9 Concurrent Simulation Contract

## Status and identity

- Contract version: `1.0`
- Current Phase 9 completion: 60%
- Development seasons: 2022–2024
- Protected temporal evaluation season: 2025
- Scope: controlled dry-race, green-flag pit-now versus stay-out decisions
- Default benchmark population: 10,000 paired scenarios

Phase 9 adds probabilistic scenario execution around the verified Phase 8
decision comparison. It does not retrain the Phase 6 model, change the Phase 7
state-transition rules or rewrite the immutable Phase 8 audit.

The current milestone now executes complete paired scenario batches in
canonical order and reports descriptive action-time and paired-advantage
distributions. These summaries are not calibrated probabilities of choosing
the correct action.

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

The 60% milestone reports empirical scenario distributions, action shares and
an abstaining interval-stability recommendation. It does not claim that an
action's scenario share is its probability of being correct.

Before any stronger language is permitted:

1. Concurrent execution must be proven exactly equivalent to sequential output.
2. Interval coverage and width must be evaluated on development evidence.
3. A final recommendation threshold must be frozen before protected evaluation.
4. Protected 2025 performance must remain unseen until final evaluation.

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

## Acceptance gates through 60%

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
29. Focused tests and repository-wide quality checks pass with warnings as
    errors.

## Current exclusions

The milestone does not yet provide:

- Calibrated action-correctness probabilities
- Concurrent workers or performance claims
- Immutable Phase 9 reports
- Weather, Safety Car, traffic or failure processes
- Protected 2025 evaluation

Those capabilities remain explicit later milestones rather than being implied
by the sequential scenario summaries.
