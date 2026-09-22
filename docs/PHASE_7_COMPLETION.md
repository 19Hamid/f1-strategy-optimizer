# Phase 7 Completion — Race-Strategy Simulator

## Status

Phase 7 is complete.

The final development audit verified the complete 68-race development catalog,
replayed every accepted historical suffix twice and stored an immutable report
with zero integrity issues. The protected 2025 season remained unopened by the
simulation workflow.

Completion date: 23 September 2026

- Phase 7 completion: 100%
- Overall project completion: 77%
- Next phase: Phase 8 — Pit-decision optimizer

## Objective achieved

Phase 7 built a deterministic remaining-race simulator for one explicit tyre
and pit-stop plan. It repeatedly calls the verified Phase 6 model while
advancing lap number, compound, tyre age, stint progress and completed pit
stops to the flag.

The simulator can replay an observed development-race strategy and measure both
lap-level and complete remaining-time error. It does not yet compare pit-now
and stay-out alternatives or recommend a strategy; that decision belongs to
Phase 8.

## Final development population

| Measure | Verified value |
|---|---:|
| Development seasons | 2022–2024 |
| Audited race sessions | 68 |
| Candidate race/horizon slots | 204 |
| Sessions contributing valid replays | 47 |
| Selected observed replays | 102 |
| Excluded candidate slots | 102 |
| Short-horizon replays, 5 laps | 47 |
| Medium-horizon replays, 15 laps | 34 |
| Long-horizon replays, 30 laps | 21 |
| Aligned simulated and observed laps | 1,375 |
| Executions per selected replay | 2 |
| Protected 2025 rows | 0 |

Every one of the 68 races remained inside the integrity audit. A candidate slot
was selected only when one driver had an eligible start row and a complete,
consecutive, dry, green-flag suffix with consistent compound and pit evidence.

The 102 excluded slots are therefore an honest scope result, not missing audit
work. They were not replaced with shorter horizons, wet-race assumptions,
safety-car laps, retired-driver pseudo-finishes or data from another race.

## Deterministic selection and replay

Each race contributed up to three exact remaining-race suffixes:

- 5 laps for the short slice
- 15 laps for the medium slice
- 30 laps for the long slice

Eligible drivers were ranked by previous position, driver and team. Only a
driver whose processed laps reached the session's actual final lap could be
selected. This prevents a retirement or lapped finish from being treated as a
shortened race distance.

Each accepted replay was executed twice with the same request, historical
feature seed, verified model and random seed. All immutable scalar trajectory
evidence compared equal. Any difference would have failed the audit before
report publication.

## Model, data and pit-loss provenance

The audit required:

- All 68 Phase 4 dataset partitions to pass integrity verification
- The matching 68 Phase 3 processed partitions and catalog
- The exact final Phase 6 `RESIDUAL_HYBRID / xgboost_02` artifact
- A model dataset-build identifier equal to the verified catalog SHA-256
- Simulation seed 42
- Zero protected 2025 rows or partition directories

Pit loss remained an explicit sensitivity assumption. The controlled range was
15, 20 and 25 seconds per stop. Observed replay used the nominal 20-second case
and preserved the full range and source evidence in every replay record. The
audit did not mislabel pit-lane duration as observed net race-time loss.

## Observed-replay result

| Measure | Result |
|---|---:|
| Pooled total-lap-time MAE | 1.103651 s |
| Complete remaining-time MAE | 4.481718 s |

The pooled lap metric weights each of the 1,375 aligned laps once. The
remaining-time metric weights each of the 102 complete replay trajectories
once.

These are descriptive simulator errors, not a newly invented acceptance
threshold. They combine recursive model rollout with the declared pit-loss
assumption and therefore are not directly comparable with the Phase 6
single-step held-out MAE.

The stored metric table also contains short, medium and long remaining-time
slices plus lap and remaining-time slices by event. This preserves
long-horizon error growth and weak-circuit evidence instead of hiding them in
one pooled value. Report verification recomputed every aggregate from the
stored replay and trajectory rows.

## Stored evidence

The final report is generated locally below:

`artifacts/simulation_evaluation/format_version=1.0/run_id=phase-7-final-audit`

It contains four payload artifacts:

- `metrics.parquet` — overall, horizon and event error metrics
- `replays.parquet` — 102 replay identities, plans, assumptions and outcomes
- `trajectories.parquet` — 1,375 complete lap transitions and model inputs
- `provenance.json` — contracts, model, dataset, seed, dependencies and counts

`manifest.json` records the exact payload set, byte sizes and SHA-256 hashes.
The generated report remains intentionally outside Git because it is a
reproducible local artifact tied to the verified development dataset and model.

Independent readback verification confirmed:

- Exact artifact file set, hashes and sizes
- Exact schemas and population counts
- Complete consecutive horizons
- Every declared stop applied exactly once
- Compound, tyre-age and stint state transitions
- Positive finite lap and remaining times
- Racing time, pit loss and cumulative-time arithmetic
- Frozen Phase 6 feature order on every simulated lap
- Recomputed overall, horizon and event metrics
- Zero report-integrity issues

## Automated verification

The completion checkpoint recorded:

- 1,356 passing backend tests
- 5 expected PostgreSQL integration skips
- 141 passing simulation tests
- 4 passing final-audit-specific tests
- Ruff passing
- Shell audit entry point passing syntax validation
- 68 valid dataset sessions and zero dataset-integrity issues
- Valid Phase 6 report and model bundles with zero issues
- Valid Phase 7 report with four payload artifacts and zero issues

## Acceptance gates satisfied

Phase 7 now demonstrably:

- Completes exactly the required remaining laps
- Applies every declared stop exactly once
- Advances tyre, compound, stint and stop state consistently
- Produces positive finite lap and remaining-race times
- Returns identical results for identical inputs and seeds
- Replays observed strategies with documented error
- Stores long-horizon and circuit-level diagnostics
- Preserves zero protected 2025 development rows

## Known limitations

- Version one covers dry, green-flag remaining-race suffixes only.
- Only 47 of 68 races supplied at least one valid controlled suffix.
- Pit-loss values are explicit sensitivity assumptions rather than observed
  counterfactual net losses.
- Weather measurements and position remain frozen during a rollout because
  version one does not forecast weather or traffic.
- Recursive error can grow across longer simulated horizons.
- One deterministic driver is selected per race/horizon slot rather than every
  possible driver and start lap.
- The protected 2025 season remains unevaluated.
- The simulator evaluates one declared plan; it does not yet choose the best
  plan or provide live professional race guidance.

## Reproduction

From the repository root:

```bash
cd backend
uv sync --frozen
uv run pytest -q -W error
uv run ruff check .
cd ..
bash ./scripts/run_development_simulation_audit.sh
```

The audit script verifies the complete dataset and final Phase 6 artifact,
selects controlled replay suffixes, executes every selected trajectory twice,
writes the report atomically and independently verifies its stored evidence.

## Phase 8 handoff

Phase 8 can now consume:

- A validated remaining-race rollout engine
- Verified Phase 6 model inference and frozen feature order
- Deterministic state transitions and complete trajectory evidence
- Explicit circuit-keyed pit-loss sensitivity
- Honest replay error by lap, horizon and event
- Immutable simulation report and provenance interfaces

Phase 8 must compare pit-now and stay-out plans without inventing historical
optimal-action labels or opening the protected 2025 evaluation season.
