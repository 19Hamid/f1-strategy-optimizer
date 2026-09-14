# F1 Race Strategy Optimizer — Research Risk Register

## Purpose

This register identifies threats that could make the project inaccurate,
misleading, unreliable or impossible to complete.

It was reviewed after Phase 3 and before Phase 4 dataset and database design.

Risks remain active until their treatments are implemented and verified. A
documented mitigation does not mean that the risk has disappeared.

## Rating scale

| Rating | Meaning |
|---|---|
| Low | Unlikely or limited effect |
| Medium | Possible and capable of affecting results |
| High | Likely or capable of invalidating major conclusions |

## Status scale

| Status | Meaning |
|---|---|
| Open | Treatment has not yet been implemented |
| In progress | Treatment is being implemented or partially verified |
| Controlled | Current evidence shows that the treatment works, but it must continue |
| Deferred | Explicitly outside the current version-one scope |

## Risk register

| ID | Risk | Likelihood | Impact | Status | Current treatment |
|---|---|---|---|---|---|
| R01 | Alternative pit strategies have no directly observed historical outcome | High | High | Controlled | Use simulation, observed-strategy replay, synthetic recovery tests and sensitivity analysis; never claim that counterfactual outcomes are directly proven |
| R02 | Future information leaks into model inputs | High | High | In progress | Keep the start-of-lap `t` boundary, shift rolling features, reconstruct state from past data, use backward timestamp joins and add Phase 4 feature-level leakage tests |
| R03 | Random lap splitting produces unrealistic evaluation | High | High | In progress | Split chronologically by complete races using frozen temporal folds and reserve 2025 for final temporal evaluation |
| R04 | Missing or inconsistent FastF1 data affects training | Medium | High | Controlled | Preserve raw data, validate every partition, retain exclusions, publish quality reports and attach reason codes |
| R05 | FastF1 fields or APIs change | Medium | Medium | Controlled | Preserve immutable extracted data, record FastF1 versions, use the locked dependency environment and validate required columns |
| R06 | Regulation, car and tyre changes reduce cross-season relevance | Medium | High | Open | Retain season context, evaluate temporal folds and report performance separately by season and circuit |
| R07 | Fuel burn is confused with tyre degradation | High | High | Open | Use race progress as an explicit proxy, compare within stints and report that fuel load is unobserved |
| R08 | Traffic and driver behaviour distort lap pace | High | High | In progress | Use contextual summaries, preserve statistical outlier flags and introduce gap or traffic features only when their decision-time reliability is proven |
| R09 | Safety cars, red flags and incidents distort lap times | High | High | Controlled | Restrict controlled targets to dry exact-green laps while retaining excluded records and reasons |
| R10 | Driver and team identifiers cause memorisation | Medium | High | Open | Compare models with and without these identifiers and evaluate complete held-out races |
| R11 | Model error compounds across a simulated race | High | High | Open | Evaluate observed-strategy replay, error growth across horizon and propagated uncertainty |
| R12 | The simulator recommends impossible strategies | Medium | High | Open | Encode tyre, stint, lap and pit constraints explicitly and require deterministic validity tests |
| R13 | Historical team choices are treated as optimal labels | High | High | Controlled | Store actual pit actions only as diagnostic labels; evaluate recommendations through simulator assumptions rather than classification accuracy |
| R14 | Uncertainty is hidden behind one recommendation | Medium | High | Open | Report distributions, intervals, sensitivity and recommendation stability |
| R15 | Concurrent execution changes simulation results | Medium | High | Open | Use controlled seeds, independent scenario state and equivalence tests against sequential execution |
| R16 | Telemetry creates excessive storage and processing cost | Medium | Medium | Controlled | Keep telemetry optional and use it only when past-lap summaries demonstrate measurable improvement |
| R17 | Project scope becomes too large to finish | High | High | Controlled | Protect the dry green-flag V1 scope and defer wet strategy, safety cars, advanced traffic and multi-car game theory |
| R18 | API, database, model and dashboard contracts diverge | Medium | High | In progress | Introduce versioned dataset and database contracts, typed domain interfaces, migrations and integration tests |
| R19 | Public users interpret recommendations as guarantees | Medium | Medium | Open | Display assumptions, uncertainty, limitations and the unofficial educational purpose |
| R20 | Public data or branding is redistributed improperly | Low | High | Open | Keep generated source data outside Git, identify the project as unofficial and review source terms before deployment |
| R21 | Phase 3 processed columns are assumed to be decision-time safe | High | High | In progress | Build separate Phase 4 decision rows and prove feature availability relative to `LapStartTime(t)` |
| R22 | Target-quality filtering removes pit-decision examples or becomes a feature | High | High | In progress | Separate decision-row eligibility from lap-performance target eligibility and forbid `IsEligible(t)` as an input |
| R23 | Observed pit-lane duration is misreported as net pit loss | High | High | In progress | Maintain separate terminology, targets and evaluation rules; keep counterfactual pit loss as an explicit simulator assumption until defensibly defined |
| R24 | Weather or track status from during lap `t` leaks into start-of-lap features | High | High | In progress | Align decision weather at or before `LapStartTime(t)` and reconstruct track state from observations known before the decision |
| R25 | 2025 evaluation data influences development decisions | Medium | High | Controlled | Reject 2025 in Phase 3 and Phase 4 development interfaces, freeze decisions before final evaluation and disclose the limited Phase 1 schema inspection |
| R26 | Database migrations and ORM models drift apart | Medium | High | Open | Use Alembic migrations, database constraints, schema tests and migration-based integration environments |
| R27 | Database loading loses provenance or changes analytical values | Medium | High | Open | Preserve dataset versions and source identities, reconcile row counts and validate round-trip values |
| R28 | Python 3.14 or database-driver compatibility blocks Phase 4 | Medium | Medium | Open | Add dependencies through uv, preserve the lockfile and verify PostgreSQL integration before building repositories |

## Evidence through Phase 1

The feasibility investigation observed:

- Four sample races containing 4,284 lap records
- Fourteen missing lap times across those samples
- A FastF1 timing warning for one 2022 Bahrain driver
- Naturally sparse pit timing fields
- Different compound availability between races
- Detailed telemetry containing 703 samples for one representative lap
- One 2025 Japanese Grand Prix schema and availability inspection

The 2025 inspection was limited to feasibility information. It must remain
disclosed in final evaluation reporting.

## Evidence through Phase 2

The raw pipeline established:

- 92 completed race sessions
- 101,290 lap records
- 14,896 weather observations
- 1,838 driver-result records
- Versioned manifests and SHA-256 checksums
- Zero invalid final raw partitions
- A verified 92-session catalog
- Atomic replacement and fail-closed integrity behaviour
- A complete resume run that skipped all verified sessions
- Generated data excluded from Git

This evidence substantially controls source-corruption and reproducibility
risks but does not make the raw data modelling-ready.

## Evidence through Phase 3

The processed development audit established:

- 68 processed development races
- 74,601 preserved lap rows
- 57,871 eligible controlled laps
- 16,730 excluded laps with documented reasons
- 11,115 weather observations
- Zero future matches in Phase 3 lap-weather alignment
- 3,888 reconstructed stints
- 2,693 reconstructed pit events
- Complete accounting for 5,232 pit markers
- 1,465 dry, green and uninterrupted pit-duration candidates
- 541 contextual potential lap-time outliers
- A frozen `FLAG_ONLY` statistical-outlier policy
- Zero processed 2025 partitions
- 291 passing automated tests with warnings treated as errors

Phase 3 also revealed:

- `LapStartDate` is null for every development lap
- Two races contain no eligible controlled dry laps
- Fuel load remains unobserved
- Traffic and driver intent remain incomplete
- Restart-like laps cannot always be classified deterministically
- Observed pit-lane duration is not net pit loss
- Processed lap rows are not automatically decision-time feature rows

## Phase 4 priority risks

Phase 4 must resolve these issues before writing a permanent modelling dataset:

1. Canonical decision-row identity
2. Exact start-of-lap timestamp
3. Start-of-lap tyre-state reconstruction
4. Past-only position reconstruction
5. Decision-time weather alignment
6. Past-only track-condition reconstruction
7. Separate decision and target eligibility
8. Training-only historical aggregates
9. Whole-race temporal splits
10. Protected-2025 rejection
11. Dataset provenance and integrity
12. PostgreSQL constraints and migration reproducibility

## Scope-protection rules

Version one prioritizes:

1. Completed races
2. Dry conditions
3. Normal green-flag running
4. Lap-level and stint-level modelling
5. One decision at the start of each lap
6. Pit-now versus stay-out comparison
7. Expected remaining race time
8. Reproducible historical evaluation

The following must not delay the first controlled working version:

- Live race ingestion
- Wet-weather strategy
- Safety-car prediction
- Detailed overtaking simulation
- Two-car coordination
- Full-grid game theory
- Reinforcement learning
- Neural networks
- Bulk telemetry ingestion
- Professional-team deployment

## Stop conditions

Development must pause and the affected design must be reviewed if:

- A feature cannot be proven available before its decision timestamp
- Decision and target eligibility cannot be separated
- Validation or evaluation races influence fitted transformations
- Required source identities cannot be preserved
- Dataset integrity checks cannot reconcile source and output rows
- The PostgreSQL schema cannot preserve dataset provenance
- Candidate models cannot be evaluated against applicable baselines
- The simulator cannot reproduce observed strategies within reported error
- Counterfactual assumptions cannot be stated honestly
- Runtime or storage exceeds available hardware
- A data-source term prevents the intended public demonstration

A weak result must be documented rather than hidden or redefined after
evaluation.

## Protected evaluation disclosure

The complete 2025 season remains excluded from Phase 3 processing and Phase 4
development.

One 2025 session received limited schema inspection during Phase 1. Therefore,
the final report must describe 2025 as a protected temporal evaluation holdout,
not as data literally never viewed for any purpose.

No 2025 record may influence:

- Cleaning rules
- Feature definitions
- Dataset thresholds
- Model selection
- Hyperparameters
- Simulator calibration
- Acceptance thresholds

## Review schedule

This register is reviewed:

- After raw-pipeline completion
- After data cleaning and exploration
- After Phase 4 dataset construction
- After PostgreSQL integration
- After baseline evaluation
- After lap-time model evaluation
- After simulator validation
- Before final 2025 evaluation
- Before deployment

The next mandatory review occurs at Phase 4 completion.