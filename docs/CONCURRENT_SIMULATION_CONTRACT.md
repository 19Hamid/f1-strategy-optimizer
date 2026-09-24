# Phase 9 Concurrent Simulation Contract

## Status and identity

- Contract version: `1.0`
- Current Phase 9 completion: 25%
- Development seasons: 2022–2024
- Protected temporal evaluation season: 2025
- Scope: controlled dry-race, green-flag pit-now versus stay-out decisions
- Default benchmark population: 10,000 paired scenarios

Phase 9 adds probabilistic scenario execution around the verified Phase 8
decision comparison. It does not retrain the Phase 6 model, change the Phase 7
state-transition rules or rewrite the immutable Phase 8 audit.

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

The current milestone generates dimensionless standard-normal coordinates:

| Draw | Purpose |
|---|---|
| `shared_pace_z` | A scenario-level pace component shared across the remaining race |
| `pit_loss_z` | A paired perturbation coordinate for the explicit pit-loss mechanism |
| `lap_time_residual_z` | One coordinate keyed by each absolute remaining race lap |

These values are not seconds and are not confidence claims. A later milestone
must map them to time perturbations using development-only calibration
evidence. Keeping generation separate from calibration prevents an arbitrary
standard deviation from being disguised as model knowledge.

Weather transitions, Safety Cars, traffic interactions, failures and rival
team reactions are not silently represented by these coordinates.

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

This 25% milestone does not yet simulate perturbed actions or issue
probabilistic recommendations. Later Phase 9 work may report quantities such
as the paired remaining-time difference distribution and the proportion of
scenarios favouring each action only after:

1. Uncertainty scales are calibrated on development evidence.
2. Both actions use the same scenario objects.
3. Sequential and concurrent execution are proven equivalent.
4. Interval coverage and width are evaluated honestly.
5. A recommendation threshold is frozen before protected evaluation.

A proportion such as 70% may be described as a scenario proportion. It must
not be called a 70% chance of being correct unless calibration evidence
supports that interpretation.

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

## Acceptance gates through 25%

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
15. Focused tests and repository-wide quality checks pass with warnings as
    errors.

## Current exclusions

The milestone does not yet provide:

- Calibrated conversion from standardized draws to seconds
- Perturbed full-race trajectories
- Monte Carlo action-time distributions or probabilities
- Concurrent workers or performance claims
- Immutable Phase 9 reports
- Weather, Safety Car, traffic or failure processes
- Protected 2025 evaluation

Those capabilities remain explicit later milestones rather than being implied
by scenario generation alone.
