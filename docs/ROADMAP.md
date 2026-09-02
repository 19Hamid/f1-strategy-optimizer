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
- In progress: Phase 4 — Dataset and database design
- Overall completion: approximately 33%

Phase 4 begins with contract reconciliation so permanent datasets and database
tables are not built from stale or contradictory definitions.

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

## Development roadmap

| Phase | Weight | Status | Main result |
|---|---:|---|---|
| 0. Foundation | 3% | Completed | Development environment, repository, API skeleton and initial tests |
| 1. Research and feasibility | 8% | Completed | Define the research problem and confirm required data exists |
| 2. Raw-data pipeline | 10% | Completed | Download, validate, cache and version historical F1 data |
| 3. Data cleaning and exploration | 12% | Completed | Produce verified processed data and document development patterns |
| 4. Dataset and database design | 9% | In progress | Build leakage-safe datasets and the PostgreSQL persistence layer |
| 5. Baselines and evaluation | 8% | Planned | Establish simple baselines and race-level evaluation |
| 6. Tyre and lap-time modelling | 13% | Planned | Predict tyre degradation and future lap performance |
| 7. Race-strategy simulator | 14% | Planned | Simulate remaining laps and alternative pit strategies |
| 8. Pit-decision optimizer | 9% | Planned | Compare pit-now and stay-out expected remaining race time |
| 9. Concurrent simulation | 5% | Planned | Run uncertain race scenarios efficiently |
| 10. API and dashboard | 6% | Planned | Expose strategy analysis through FastAPI and React |
| 11. Final delivery | 3% | Planned | Complete integration, Docker, CI, documentation and presentation |

The phase weights total 100%. Completed Phases 0–3 account for 33%.

## Phase 4 objective

Phase 4 will transform verified Phase 3 processed data into reproducible,
decision-time-safe datasets and design the PostgreSQL layer that preserves
their identities, versions and relationships.

Phase 4 will not train or select predictive models.

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
- Comparison against simple baselines
- Whole-race temporal splits
- Small working milestones
- Git branches, pull requests and meaningful commits
- Honest reporting of weak or unsuccessful results