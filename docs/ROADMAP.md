# F1 Race Strategy Optimizer — Project Roadmap

## Project objective

Build a public-data Formula 1 race-strategy decision-support system.

The first version will compare pitting at the end of the current lap against
staying out and recommend the option with the lowest expected remaining race
time.

## Current progress

- Completed: Phase 0 — Foundation
- Completed: Phase 1 — Research and feasibility
- Completed: Phase 2 — Raw-data pipeline
- Completed: Phase 3 — Data cleaning and exploration
- Completed: Phase 4 — Dataset and database design
- Completed: Phase 5 — Baselines and evaluation
- Completed: Phase 6 — Tyre and lap-time modelling
- Completed: Phase 7 — Race-strategy simulator
- Completed: Phase 8 — Pit-decision optimizer
- In progress: Phase 9 — Concurrent simulation (60%)
- Overall completion: 89%

Phase 7 has frozen its controlled contract, implemented deterministic
lap-by-lap transitions, connected verified Phase 6 inference, added explicit
circuit pit-loss sensitivity, completed remaining-race rollouts, added
table-backed observed-strategy replay metrics and now stores immutable
trajectory, assumption, metric and provenance artifacts. The final 68-race
audit completed with 102 deterministic observed replays, 1,375 aligned laps,
zero report-integrity issues and zero protected 2025 rows.

Phase 8 has frozen its decision boundary and implemented deterministic,
symmetric full-horizon comparison of `PIT_NOW` and a one-lap `STAY_OUT`
deferral. The two actions share the same state, target compound, model, feature
seed, pit-loss assumption, random seed and horizon. Point-estimate advantage,
recommendation and regret are available. A canonical nine-case grid now varies
low, nominal and high circuit pit loss against younger, nominal and older
current-stint tyre exposure while holding recent pace fixed. Recommendation
stability now widens that complete envelope with an explicit evidence-backed
margin for each action and returns no clear advantage whenever the conservative
interval can cross zero. Development-only historical diagnostics now report
overall and event-level recommendation distributions, interval width and
observed-action alignment without treating the observed action as optimal.
Those comparisons, assumptions and aggregate diagnostics now have normalized
tables plus atomic immutable storage with exact-schema, row-count, arithmetic
and SHA-256 verification. The final development audit verifies all 68 input
partitions, selects complete paired historical pit windows, evaluates every
accepted decision twice and publishes one independently verified report with
zero protected 2025 rows. Calibrated probabilistic execution remains Phase 9
scope.

Phase 9 has frozen its paired-scenario contract, deterministic standardized
generation and development-only uncertainty scaling. Each scenario is applied
to complete `PIT_NOW` and `STAY_OUT` trajectories using the same
absolute-lap evidence. Canonically ordered sequential aggregation now reports
complete action-time and paired-advantage distributions, scenario preference
shares and an abstaining central-interval stability result. These remain
descriptive simulated-world summaries, not calibrated correctness
probabilities. Concurrent execution is not yet implemented.

## Completed-phase evidence

### Phase 0 — Foundation

Phase 0 produced:

- A WSL-based development environment
- Docker and Git configuration
- A reproducible uv-managed Python backend
- A FastAPI application foundation
- A health-check endpoint
- Initial Ruff and pytest checks
- A structured GitHub repository

### Phase 1 — Research and feasibility

Phase 1 produced:

- A defined project aim and research question
- A precise start-of-lap decision timestamp
- A protected dry green-flag V1 scope
- Successful FastF1 validation across 2022–2025 samples
- Successful detailed telemetry validation
- An initial data dictionary
- Explicit data-leakage prevention rules
- Baseline and model-evaluation plans
- Simulator and concurrency evaluation plans
- A documented research-risk register

One 2025 Japanese Grand Prix session received limited schema and availability
inspection during Phase 1. This exposure must be disclosed during final
evaluation.

### Phase 2 — Raw-data pipeline

Phase 2 produced:

- Automatic 2022–2025 race-schedule discovery
- A complete 92-race raw dataset
- 68 development races from 2022–2024
- 24 protected evaluation races from 2025
- 101,290 lap records
- 14,896 weather records
- 1,838 driver-result records
- Compressed Parquet storage
- Atomic writes and readback validation
- Versioned metadata and SHA-256 manifests
- Session-level integrity verification
- Fail-closed handling of invalid existing partitions
- Explicit forced replacement
- Resumable extraction and early skipping
- Resilient batch execution
- A verified 92-session catalog
- Optional per-lap telemetry
- A command-line interface
- 134 passing tests at Phase 2 completion
- A successful 92-race integrity audit

### Phase 3 — Data cleaning and exploration

Phase 3 produced:

- Frozen cleaning-rule version `1.0`
- Processed-data contract version `1.0`
- Development-exploration version `1.0`
- Deterministic profiling of 68 development races
- Preservation of all 74,601 development lap rows
- 57,871 eligible controlled-analysis laps
- 16,730 excluded laps with documented reasons
- Backward-only alignment of 11,115 weather observations
- Zero future matches in Phase 3 weather alignment
- 3,888 reconstructed tyre stints
- 3,845 complete stints
- 2,693 reconstructed pit events
- Complete accounting for 5,232 pit markers
- 1,465 pit-duration candidates
- Atomic versioned processed storage
- Processed integrity verification
- Resumable batch processing
- A verified 68-session processed catalog
- A processed-data command-line interface
- Permanent development exploration
- A frozen `FLAG_ONLY` statistical-outlier policy
- 291 passing automated tests
- A real 68-race processed audit
- A complete 68-session resume test
- No Phase 3 processing or exploration of the 2025 holdout

### Phase 4 — Dataset and database design

Phase 4 produced:

- Frozen dataset contract version `1.0`
- 73,251 canonical start-of-lap decision rows
- 55,943 eligible decisions and 17,308 documented exclusions
- 52,483 leakage-controlled eligible lap-time targets
- 2,693 separated pit-duration observations
- 1,465 eligible pit-duration targets
- Deterministic whole-race temporal folds with 204 assignments
- Atomic Parquet storage, manifests, catalogs and integrity verification
- A 26-table PostgreSQL schema with reproducible Alembic migration
- Immutable repositories and transaction-safe session loading
- Complete 68-session database build orchestration and CLI
- Exact physical database reconciliation
- Zero future weather matches
- Zero protected 2025 database rows
- 1,030 passing backend tests at the final unit-suite checkpoint
- A successful real 68-race PostgreSQL load and audit

Full evidence is recorded in `docs/PHASE_4_COMPLETION.md`.

### Phase 5 — Baselines and evaluation

Phase 5 produced:

- Frozen baseline contract version `1.0`
- Four deterministic lap-time baselines
- Three training-only observed pit-duration baselines
- Whole-race evaluation on 2023 and 2024 validation folds
- MAE, RMSE, median, p90 and signed-error reporting
- Complete prediction coverage and fallback accounting
- Required race, event, tyre, driver, team and progress slices
- Atomic versioned report storage with SHA-256 verification
- A successful real 68-race development audit
- 52,483 eligible lap-time targets
- 1,465 eligible pit-duration targets
- Selected 0.410049-second MAE lap-time reference
- Selected 1.587942-second MAE pit-duration reference
- Zero protected 2025 rows
- 1,099 passing backend tests at the final audit checkpoint

Full evidence is recorded in `docs/PHASE_5_COMPLETION.md`.

### Phase 6 — Tyre and lap-time modelling

Phase 6 produced:

- Frozen model contract version `1.2`
- Leakage-safe primary and auxiliary training matrices
- Training-only preprocessing for numeric, boolean and categorical features
- 23 bounded Ridge, random-forest, histogram-boosting and XGBoost configurations
- Direct and residual-hybrid comparison across both temporal folds
- Mandatory driver/team identity ablation for every candidate
- Verified XGBoost execution on `cuda:0`
- Selected `RESIDUAL_HYBRID / xgboost_02`
- 0.392725-second comparable-row MAE versus the 0.410049-second baseline
- 4.22% relative comparable-row MAE improvement
- 0.392716-second identity-ablation comparable-row MAE
- 100% simulator-facing prediction coverage
- Immutable model and evaluation bundles with exact prediction verification
- 52,483 primary and 50,913 auxiliary target rows
- Zero protected 2025 rows
- 1,215 passing backend tests and five expected PostgreSQL skips
- A successful real 68-race development model audit

Full evidence is recorded in `docs/PHASE_6_COMPLETION.md`.

## Development roadmap

| Phase | Weight | Status | Main result |
|---|---:|---|---|
| 0. Foundation | 3% | Completed | Development environment, repository, API skeleton and initial tests |
| 1. Research and feasibility | 8% | Completed | Define the research problem and confirm required data exists |
| 2. Raw-data pipeline | 10% | Completed | Download, validate, cache and version historical F1 data |
| 3. Data cleaning and exploration | 12% | Completed | Produce verified processed data and document development patterns |
| 4. Dataset and database design | 9% | Completed | Build leakage-safe datasets and the PostgreSQL persistence layer |
| 5. Baselines and evaluation | 8% | Completed | Establish simple baselines and race-level evaluation |
| 6. Tyre and lap-time modelling | 13% | Completed | Predict tyre degradation and future lap performance |
| 7. Race-strategy simulator | 14% | Completed | Simulate remaining laps and alternative pit strategies |
| 8. Pit-decision optimizer | 9% | Completed | Compare pit-now and stay-out expected remaining race time |
| 9. Concurrent simulation | 5% | In progress (60%) | Run uncertain race scenarios efficiently |
| 10. API and dashboard | 6% | Planned | Expose strategy analysis through FastAPI and React |
| 11. Final delivery | 3% | Planned | Complete integration, Docker, CI, documentation and presentation |

The phase weights total 100%. Completed Phases 0–8 account for 86%. The first
60% of Phase 9 contributes 3 percentage points, producing 89% overall.

## Phase 4 objective

Phase 4 transformed verified Phase 3 processed data into reproducible,
decision-time-safe datasets and implemented the PostgreSQL layer that preserves
their identities, versions and relationships.

Phase 4 did not train or select predictive models.

## Phase 4 milestones

| Milestone | Result | Phase 4 completion |
|---|---|---:|
| 0. Contract reconciliation | Correct evaluation, decision-time and source-contract definitions | 5% |
| 1. Dataset contract | Freeze canonical identities, timestamps, features, targets and reason codes | 15% |
| 2. Decision-row construction | Build start-of-lap state from past information | 35% |
| 3. Leakage validation | Reject future, target-lap and cross-split information | 50% |
| 4. Temporal splits | Assign deterministic whole-race development folds | 60% |
| 5. Dataset storage | Add versioned files, manifests, integrity, catalog and CLI | 72% |
| 6. PostgreSQL design | Define entities, relationships, constraints, indexes and migrations | 85% |
| 7. Database loading | Add repositories, loaders and PostgreSQL integration tests | 93% |
| 8. Final audit | Build and verify all 68 development races and documentation | 100% |

These percentages measure completion within Phase 4. Phase 4 itself contributes
9% to overall project completion.

## Phase 4 dataset requirements

Phase 4 must:

1. Define one canonical decision row at the start of lap `t`.
2. Preserve source and processed-data provenance.
3. Separate identifiers, metadata, inputs, targets and diagnostics.
4. Reconstruct current tyre and stint state from past evidence.
5. Reconstruct position from the end of lap `t - 1`.
6. Align decision weather at or before `LapStartTime(t)`.
7. Reconstruct track state from information known before the decision.
8. Shift every rolling feature to completed earlier laps.
9. Separate decision-row eligibility from lap-target eligibility.
10. Prevent `IsEligible(t)` and other post-decision values from becoming inputs.
11. Fit historical aggregates using training races only.
12. Assign whole races to deterministic temporal folds.
13. Reject protected 2025 records from development interfaces.
14. Version dataset-building rules and stored outputs.
15. Produce deterministic quality reports and integrity evidence.

## Phase 4 analytical populations

### Decision-state rows

A decision row represents reconstructable information available when lap `t`
begins.

The row may remain present even when lap `t` later becomes a pit-entry,
interrupted, wet, inaccurate or otherwise excluded target lap.

### Lap-performance targets

A decision row may train or evaluate the controlled lap-time model only when
lap `t` satisfies the frozen Phase 3 eligibility rules and all required
past-context features are available.

Target suitability must not be confused with information that was available at
prediction time.

### Historical pit actions

The actual pit action at the end of lap `t` may be stored as a diagnostic label.

It is not an optimal-decision ground truth because the counterfactual strategy
outcome was not observed.

## Phase 4 temporal folds

Development uses expanding whole-race temporal folds:

| Fold | Training | Validation |
|---|---|---|
| 1 | 2022 | 2023 |
| 2 | 2022–2023 | 2024 |

After all development decisions are frozen:

| Purpose | Seasons |
|---|---|
| Final training | 2022–2024 |
| Protected temporal evaluation | 2025 |

No individual race may be divided across the two sides of a fold.

The 2025 season must not influence feature definitions, preprocessing,
thresholds, model selection, hyperparameters, simulator calibration or
acceptance criteria.

## Phase 4 database requirements

The PostgreSQL design must preserve:

- Seasons
- Events and circuits
- Race sessions
- Drivers
- Teams
- Session participation
- Processed laps
- Reconstructed stints
- Reconstructed pit events
- Dataset versions
- Dataset builds
- Decision rows
- Temporal split assignments
- Quality reasons
- Source provenance

The database layer must provide:

- Primary keys
- Foreign keys
- Uniqueness constraints
- Check constraints
- Appropriate indexes
- UTC-aware timestamps
- Reproducible Alembic migrations
- Transaction-safe loading
- Row-count reconciliation
- Dataset-version traceability
- Integration tests using PostgreSQL

Generated Parquet datasets remain authoritative analytical artifacts. The
database must not silently alter their values or become an undocumented second
cleaning pipeline.

## Phase 4 package boundaries

Phase 4 may activate:

```text
backend/app/datasets/
backend/app/domain/
backend/app/db/
```

Responsibilities are:

- `app.datasets`: decision-row construction, splits, storage and integrity
- `app.domain`: pure identities, enums and decision-time rules
- `app.db`: PostgreSQL configuration, models, sessions, repositories and loaders

Phase 4 must not place:

- Dataset construction inside `app.cleaning`
- SQLAlchemy models inside domain logic
- Model training inside `app.datasets`
- Database queries directly inside API routes
- Phase 5 modelling code inside `app.ml`

The Phase 2 pipeline and Phase 3 cleaning packages remain stable upstream
boundaries.

## Pit-duration boundary

Phase 3 observed pit-lane duration is not automatically net pit loss.

Phase 4 must preserve separate meanings for:

- Observed pit-lane duration
- Stationary service time
- Pit-lap time delta
- Estimated net race-time loss
- Counterfactual simulator pit loss

A supervised net-pit-loss target must not be invented merely because the
simulator will eventually need a parameter.

## Protected evaluation disclosure

One 2025 Japanese Grand Prix session received limited schema and availability
inspection during Phase 1.

The full 2025 season remains excluded from Phase 3 processing and Phase 4
development. Final reporting must describe it as a protected temporal
evaluation holdout rather than data literally never viewed for any purpose.

## Phase 4 acceptance criteria

Phase 4 is complete when:

1. Canonical decision rows are defined and versioned.
2. Every input feature has an auditable decision-time source.
3. Decision and target eligibility are separate.
4. Whole-race temporal folds are deterministic.
5. Leakage tests reject forbidden target-lap and future values.
6. Protected 2025 records are rejected during development.
7. Dataset outputs are written atomically and verified.
8. Dataset manifests, quality reports and catalogs reconcile.
9. PostgreSQL entities and relationships are documented.
10. Migrations create the expected schema reproducibly.
11. Database constraints reject invalid identities and relationships.
12. Development datasets load transactionally with matching row counts.
13. Unit and PostgreSQL integration tests pass with warnings treated as errors.
14. Real 68-race dataset and database audits pass.
15. Documentation records assumptions, limitations and reproducible commands.

## Required development order

1. Collect and verify raw data
2. Clean and understand development data
3. Define decision-time contracts
4. Build leakage-safe datasets
5. Design and verify database persistence
6. Create simple baseline methods
7. Build tyre and lap-time models
8. Build the race simulator
9. Build the pit-decision optimizer
10. Add concurrent scenario simulation
11. Connect the API and dashboard
12. Complete final temporal evaluation and presentation

The simulator must precede the optimizer because historical data cannot reveal
the outcome of a strategy that was not actually used.

## Version-one boundaries

The first working version will:

- Use public historical Formula 1 data
- Use 2022–2024 for development
- Reserve 2025 for protected temporal evaluation
- Focus on controlled dry-race conditions
- Compare pit now against staying out
- Optimize expected remaining race time
- Begin with simple assumptions
- Produce recommendations rather than imitate historical team decisions

Weather transitions, safety cars, complex traffic and advanced multi-stop logic
will be introduced only after the controlled simulator works correctly.

Detailed telemetry remains optional unless later experiments demonstrate
measurable benefit from past-lap summaries.

## Phase 5 objective

Phase 5 established deterministic lap-time and pit-duration baselines and
evaluated them on the frozen whole-race temporal development folds.

Phase 5 did not train or select the advanced predictive models assigned to
Phase 6.

## Phase 5 milestones

| Milestone | Result | Phase 5 completion |
|---|---|---:|
| 1. Baseline contract | Freeze methods, fallbacks, metrics and provenance | 10% |
| 2. Lap-time baselines | Implement four decision-time-safe reference methods | 35% |
| 3. Pit-duration baselines | Implement three training-only duration estimators | 50% |
| 4. Temporal evaluation | Score both development folds without leakage | 70% |
| 5. Reporting and storage | Persist reproducible aggregate and sliced results | 85% |
| 6. Final audit | Run all 68 races and document the Phase 6 threshold | 100% |

Detailed rules are recorded in `docs/BASELINE_CONTRACT.md`.

## Phase 6 objective

Phase 6 trains leakage-safe models for controlled next-lap time and analyses
lap-time change associated with tyre and race state.

The phase did not simulate strategies or open the protected 2025 season.

## Phase 6 milestones

| Milestone | Result | Phase 6 completion |
|---|---|---:|
| 1. Model contract | Freeze targets, features, candidates and selection rules | 10% |
| 2. Training matrix | Build verified primary and auxiliary populations | 25% |
| 3. Preprocessing | Fit missing-value, scaling and encoding rules on training races only | 40% |
| 4. Candidate training | Train Ridge, random forest, histogram boosting and guarded XGBoost candidates | 60% |
| 5. Temporal selection | Tune and compare candidates on both development folds | 75% |
| 6. Degradation diagnostics | Analyse tyre age, lap change and identity dependence | 85% |
| 7. Model artifacts | Store reproducible preprocessing and inference bundles | 93% |
| 8. Final audit | Run all 68 races and document the selected model | 100% |

Detailed rules are recorded in `docs/MODEL_CONTRACT.md`; final evidence is in `docs/PHASE_6_COMPLETION.md`.

## Standards followed throughout every phase

- Automated tests for important behaviour
- Ruff code-quality checks
- Warnings treated as errors
- Clear documentation of assumptions
- Reproducible datasets and experiments
- Versioned data contracts
- Atomic writes for generated artifacts
- Integrity checks for stored data
- Fixed random seeds where appropriate
- No evaluation-data leakage

## Phase 7 objective

Phase 7 builds a deterministic controlled race-strategy simulator that advances
the remaining laps of one explicit tyre and pit-stop plan. It consumes the
verified Phase 6 model but does not retrain it or decide which strategy is best.

Pit-now-versus-stay-out comparison remains Phase 8. This separation prevents
the optimizer from being built on an unverified counterfactual engine.

## Phase 7 milestones

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

The final audit verified all 68 dataset and processed partitions, scanned fixed
5-, 15- and 30-lap suffixes, executed all 102 selected replays twice and
published one immutable report covering 1,375 aligned laps. Full evidence is
recorded in `docs/PHASE_7_COMPLETION.md`.

Detailed rules are recorded in `docs/SIMULATION_CONTRACT.md`.

## Phase 8 objective

Phase 8 turns the verified Phase 7 simulator into a controlled decision
comparison. At the start of lap `t`, it compares pitting after lap `t` with
staying out for exactly one additional lap and pitting after lap `t + 1`.

The optimizer minimizes predicted time from the start of lap `t` to the flag.
It does not treat the historical team action as an optimal label and does not
use protected 2025 data during development.

## Phase 8 milestones

| Milestone | Result | Phase 8 completion |
|---|---|---:|
| 1. Optimizer contract | Freeze action timing, shared assumptions, objective and tie policy | 10% |
| 2. Action construction | Build legal full-horizon pit-now and one-lap-deferral strategies | 25% |
| 3. Deterministic comparison | Return point-estimate advantage, recommendation and regret | 40% |
| 4. Sensitivity analysis | Measure circuit pit-loss and current-stint tyre-age sensitivity | 60% |
| 5. Stability and uncertainty | Quantify recommendation stability and no-clear-advantage cases | 75% |
| 6. Historical diagnostics | Evaluate development decision populations without claiming optimal labels | 85% |
| 7. Reporting and artifacts | Store reproducible comparisons, assumptions and aggregate metrics | 92% |
| 8. Final audit | Verify the development population and complete documentation | 100% |

The final audit requires all 68 dataset and processed partitions, the exact
verified Phase 6 model artifact and the matching immutable Phase 7 report. It
selects at most one complete consecutive `STAY_OUT`/`PIT_NOW` pair per race,
evaluates each selected decision twice and publishes a readback-verified
optimizer report. The completed audit selected 62 pairs and 124 decisions:
106 nominal `PIT_NOW` calls, 18 nominal `STAY_OUT` calls and 123/124 decisions
with one action ahead throughout the nine-case sensitivity grid. The final
conservative layer classified all 124 as `NO_CLEAR_ADVANTAGE` after applying
the `8.963436s` paired-action replay-error margin. These are separate claims:
directional robustness is not decision accuracy or calibrated confidence.

Detailed rules are recorded in `docs/OPTIMIZER_CONTRACT.md`.

## Phase 9 objective

Phase 9 turns the deterministic Phase 8 comparison into paired uncertain race
scenarios and then executes those scenarios concurrently without changing the
result. Both actions must experience the same underlying possible race world
so uncertainty in their difference is measured directly.

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

The completed 60% milestone uses a frozen SHA-256 and Box–Muller generator,
development-only uncertainty scales and complete paired action rollouts.
Sequential execution now preserves scenario order and reports frozen
descriptive distributions, empirical action shares and a central-interval
stability recommendation with mandatory abstention below 100 scenarios.
It does not claim calibrated correctness probability or concurrent execution.

Detailed rules are recorded in `docs/CONCURRENT_SIMULATION_CONTRACT.md`.
