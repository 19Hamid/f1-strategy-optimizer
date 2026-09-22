# Phase 7 Race-Simulation Contract

## Status

Contract version: `1.2`

Phase 7 progress after this milestone: **92%**

This contract freezes the controlled inputs and safety boundaries of the
remaining-race simulator. The engine now replays observed development
strategies, measures both lap-level trajectory error and time-to-flag error and
stores reproducible integrity-checked reports.

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

## Deterministic state transitions

The pure transition engine records the start and end of every simulated lap.
An ordinary lap increments tyre age and stint progress by exactly one. A
scheduled stop applies the declared pit loss once, increments the completed-stop
count, changes compound and resets the new tyre and stint progress to zero for
the next lap.

Each transition records:

- Simulated lap identity
- Starting and next compound
- Starting and next tyre age
- Starting and next stint progress
- Predicted racing time
- Explicit pit-loss time
- Total charged time
- Accumulated elapsed time
- Terminal-race status

The engine rejects non-positive or non-finite predictions, mismatched race
identity and attempts to advance beyond the final lap. Equal inputs produce
equal immutable outputs.

## Circuit-aware pit-loss sensitivity

Phase 7 keeps counterfactual pit loss explicit through one profile per event.
Every profile declares low, nominal and high seconds, a source, evidence and,
when fitted, the exact development seasons used.

Two source types remain deliberately separate:

- Explicit assumptions carry no claimed training seasons.
- Training-only circuit estimates must identify canonical 2022–2024 seasons.

The registry has no global fallback. A missing circuit profile fails instead of
quietly borrowing another track's value. It also rejects duplicate event
identities and any protected 2025 calibration evidence.

Sensitivity affects only laps with a declared stop. Ordinary racing laps remain
unchanged. The transition engine applies the selected cost exactly once and
stores it separately from predicted racing time.

These values remain simulator parameters, not fake supervised net-pit-loss
targets. Observed-strategy replay will determine how useful the assumptions are.

## Phase 6 model adapter

The simulator loads the model only through the Phase 6 artifact verifier and
then requires the exact selected identity:

- Final 2022–2024 development refit
- `RESIDUAL_HYBRID / xgboost_02`
- Full approved feature set in frozen order
- XGBoost family with recorded CUDA training provenance
- No retained validation-session population

The first simulated lap reproduces the audited historical decision feature row.
Later rows update only state controlled by the simulator:

- Decision lap
- Compound, tyre age and current-stint progress
- Completed pit stops
- Previous simulated racing-lap time
- Eligible-lap count and rolling lap-time statistics
- Weather observation age based on simulated elapsed time

Measured weather values and previous position remain frozen because V1 does not
claim to forecast weather or traffic. Simulated sector times are unavailable and
therefore use the Phase 6 model's frozen missing-value handling.

The residual component is disabled for the first lap after a pit stop. That lap
uses the matching direct XGBoost fallback instead of forming a false lap-time
change across different tyre stints.

## Complete strategy rollout

One rollout accepts one validated request, one verified model adapter and one
historical feature seed. It then predicts and advances every lap from the
current decision lap through the scheduled final lap.

Every simulated lap stores:

- The exact ordered Phase 6 feature values used for inference
- Predicted racing time before any pit cost
- The immutable state transition
- Any executed planned stop and separately charged pit loss
- Cumulative elapsed time and terminal status

Predicted lap times feed the next simulated feature row. No future historical
lap, sector, weather or position value is read. The rollout preserves the
post-stop direct-model fallback defined by the adapter.

A completed result is accepted only when all lap numbers are consecutive, state
transitions connect, planned stops execute exactly once, only the final lap is
terminal and racing time plus pit loss reconciles exactly with engine elapsed
time. Identical requests, contexts and verified model artifacts produce
identical scalar trajectory evidence.

This milestone simulates one declared strategy. It does not compare strategies,
choose a pit action or claim counterfactual ground truth; those decisions remain
outside Phase 7.

## Observed-strategy replay

Replay compares one declared observed strategy with the matching 2022–2024
historical trajectory. It requires the exact session, event, driver, team,
start lap, race distance and planned stops to agree before simulation.

Builders accept the canonical Phase 4 decision-row and Phase 3 processed-lap schemas. They require exactly one eligible decision row, seed rolling history only from eligible laps before the decision and require a complete dry, green processed trajectory with exact pit-in laps and post-stop compounds. Ambiguous rows, missing laps or contradictory pit evidence fail before model inference.

The observed value remains total historical lap time. It is not decomposed into
an invented racing-time target and counterfactual net pit-loss target. The
simulated comparison remains transparent:

```text
predicted total lap time = Phase 6 racing-time prediction
                         + declared simulator pit loss on stop laps
```

Each replay stores signed lap error, cumulative predicted and observed time and
cumulative signed error. It reports the frozen MAE, RMSE, median, p90 and signed
error set at two distinct levels:

- Pooled lap error, where every aligned lap contributes once
- Remaining-time error, where every complete replay contributes once

Finish-time error is also sliced by short (1–10 laps), medium (11–25 laps) and
long (26 or more laps) start horizons. This exposes compounding trajectory error
without allowing longer races to dominate the replay-level result.

Replay accepts development seasons only, requires a complete consecutive
horizon and rejects duplicate replay identities. The protected 2025 season
remains closed.

## Reproducible reporting and immutable artifacts

One report normalizes the complete replay evaluation into three exact tables:

- Aggregate metrics for pooled laps and complete remaining-time trajectories
- Replay summaries with identities, plans, pit-loss assumptions and outcomes
- Complete lap trajectories with model features, state changes and errors

Remaining-time metrics are sliced by short, medium and long horizons. Lap and
remaining-time metrics are also sliced by event so weak circuits and
compounding error remain visible rather than disappearing inside one pooled
number.

Each stored run contains `metrics.parquet`, `replays.parquet`,
`trajectories.parquet` and `provenance.json`. The provenance records the
simulation and model contract versions, exact Phase 6 artifact, dataset build,
development-session count, zero protected rows, deterministic seed, dependency
versions and execution duration.

Publication occurs through a sibling temporary directory followed by one
atomic rename. A completed run identity cannot be overwritten. The manifest
records the exact artifact set, byte sizes and SHA-256 hashes. Verification
also reads every table back and recomputes population identities, lap
arithmetic, cumulative time, stop counts, pit-loss charges, feature order and
all aggregate metrics before accepting the report.

Reports contain only 2022–2024 observed replays. They preserve declared
pit-loss assumptions as assumptions and never relabel them as observed
counterfactual truth.

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
