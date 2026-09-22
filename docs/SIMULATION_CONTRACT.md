# Phase 7 Race-Simulation Contract

## Status

Contract version: `1.0`

Phase 7 progress after this milestone: **10%**

This contract freezes the controlled inputs and safety boundaries of the
remaining-race simulator before its transition engine is implemented.

## Purpose

Phase 7 will simulate the remaining laps of one explicit tyre strategy. It will
repeatedly call the verified Phase 6 lap-time model while advancing lap number,
tyre age, stint state and pit-stop state.

Phase 7 does **not** choose whether to pit now or stay out. That comparison is
Phase 8, after the simulator has passed validity and observed-strategy replay
checks.

## Version-one scope

The simulator accepts:

- A start-of-lap race state
- A complete remaining-race pit schedule
- Supported dry compounds: soft, medium and hard
- One explicit additive pit-loss assumption
- One deterministic random seed
- Observed-strategy replay or counterfactual-strategy mode
- Development seasons 2022–2024 only

The simulator rejects protected 2025 inputs during development.

## Decision boundary

A request begins at the start of lap `t`. The state may contain only
information already known at that time.

A planned stop after lap `t` means the driver completes lap `t`, enters the
pit lane at the end of that lap and begins the next lap on the declared
compound.

## Pit-loss boundary

Observed pit-lane duration is not silently renamed as net race-time loss.

Every request carries a non-negative additive pit-loss value, a source identity
and human-readable evidence. Version 1.0 permits only:

- An explicit V1 assumption used transparently in sensitivity analysis
- A circuit estimate fitted from training races only

Later milestones will evaluate the assumption through replay and sensitivity
analysis. A supervised target will not be invented where no defensible
counterfactual label exists.

## Validity rules

Every accepted request must:

1. Use a 2022–2024 development race.
2. Begin on a legal lap within the scheduled race distance.
3. Use a supported dry compound.
4. Keep non-negative tyre age and pit-stop count.
5. Keep the current compound in the used-compound history.
6. Sort planned stops and assign at most one stop after a lap.
7. Place every future stop from the current lap through the penultimate lap.
8. Finish with at least two dry compounds represented across used and planned
   stints.
9. Use a finite, non-negative pit-loss assumption.
10. Use a deterministic 32-bit random seed.

Invalid requests are software errors and must fail before model inference.

## Phase 6 handoff

The engine will consume the immutable Phase 6 artifact:

- Contract version `1.2`
- `RESIDUAL_HYBRID / xgboost_02`
- 0.392725-second comparable-row MAE
- 100% prediction coverage
- Frozen preprocessing and 26-feature order
- Direct XGBoost fallback where no valid previous lap exists

Phase 7 does not retrain, weaken or replace that model.

## Planned milestones

| Milestone | Result | Phase 7 completion |
|---|---|---:|
| 1. Simulation contract | Freeze state, strategy, pit loss, tyre rules and holdout boundary | 10% |
| 2. State-transition engine | Advance laps, tyre age, stints and planned stops deterministically | 25% |
| 3. Model adapter | Build valid future feature rows and call the verified Phase 6 artifact | 40% |
| 4. Pit-loss mechanism | Apply explicit circuit-aware pit costs and sensitivity inputs | 55% |
| 5. Strategy rollout | Simulate complete remaining-race trajectories | 70% |
| 6. Observed replay | Measure trajectory and remaining-time error on development races | 82% |
| 7. Reporting and artifacts | Store reproducible trajectories, metrics and assumptions | 92% |
| 8. Final audit | Verify all development scenarios and documentation | 100% |

## Acceptance direction

Phase 7 will not be complete merely because it runs. It must:

- Complete exactly the required laps
- Apply every declared stop exactly once
- Advance tyre age and compound state correctly
- Produce positive finite lap and remaining times
- Return identical results for identical inputs and seeds
- Replay observed strategies with documented error
- Report weak circuits and long-horizon error growth
- Preserve zero protected 2025 development rows
