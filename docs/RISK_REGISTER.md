# F1 Race Strategy Optimizer — Research Risk Register

## Purpose

This register identifies threats that could make the project inaccurate,
misleading, unreliable or impossible to complete.

Risks will be reviewed at the end of every major phase.

## Rating scale

| Rating | Meaning |
|---|---|
| Low | Unlikely or limited effect |
| Medium | Possible and capable of affecting results |
| High | Likely or capable of invalidating major conclusions |

## Risk register

| ID | Risk | Likelihood | Impact | Planned treatment |
|---|---|---|---|---|
| R01 | Alternative pit strategies have no directly observed historical outcome | High | High | Use simulation, observed-strategy replay and synthetic recovery tests; never claim counterfactual outcomes are directly proven |
| R02 | Future information leaks into model inputs | High | High | Define the decision at the start of lap `t`, shift rolling features, use backward weather joins and add automated leakage tests |
| R03 | Random lap splitting produces unrealistic evaluation | High | High | Split chronologically by complete races and keep 2025 untouched until final evaluation |
| R04 | Missing or inconsistent FastF1 data affects training | Medium | High | Validate every session, log warnings, preserve raw data and document all cleaning decisions |
| R05 | FastF1 fields or APIs change | Medium | Medium | Pin dependency versions, cache source data and validate required columns before processing |
| R06 | Regulation, car and tyre changes reduce cross-season relevance | Medium | High | Focus initially on 2022–2025, include season context and report performance separately by season |
| R07 | Fuel burn is confused with tyre degradation | High | High | Include race progression as a fuel-load proxy and compare degradation within valid stints |
| R08 | Traffic and defensive driving distort lap pace | High | High | Detect abnormal laps using gaps, position, sectors and robust filtering where reliable data exists |
| R09 | Safety cars, red flags and incidents distort lap times | High | High | Begin with dry green-flag laps and exclude abnormal periods using track status and race-control information |
| R10 | Driver and team identifiers cause memorisation | Medium | High | Compare models with and without driver and team features and report unseen-race generalisation |
| R11 | Model error compounds across a full simulated race | High | High | Evaluate observed-strategy replay, propagate uncertainty and report error growth over the remaining distance |
| R12 | The simulator recommends impossible strategies | Medium | High | Encode tyre and lap constraints explicitly and require all validity tests to pass |
| R13 | Historical team choices are incorrectly treated as optimal labels | High | High | Use historical agreement only as a diagnostic, not as strategy-decision accuracy |
| R14 | Uncertainty is hidden behind a single recommendation | Medium | High | Report strategy-time distributions, confidence ranges and recommendation stability |
| R15 | Concurrent execution changes simulation results | Medium | High | Use controlled random seeds, independent scenario state and equivalence tests against sequential execution |
| R16 | Telemetry creates excessive storage and processing costs | Medium | Medium | Prioritize lap-level features and introduce telemetry summaries only after proving additional value |
| R17 | The project scope becomes too large to finish | High | High | Protect the dry green-flag V1 scope and move weather, safety cars and advanced multi-car strategy to later versions |
| R18 | API, database, model and dashboard components become incompatible | Medium | Medium | Define typed interfaces, integrate incrementally and test component contracts |
| R19 | Public users interpret recommendations as professional guarantees | Medium | Medium | Display assumptions, uncertainty and limitations with every recommendation |
| R20 | Public data or branding is redistributed improperly | Low | High | Do not commit raw caches, identify the project as unofficial and review applicable source terms before deployment |

## Current evidence

The following risk evidence has already been observed:

- Four test races contained 14 missing lap times across 4,284 records.
- FastF1 reported a timing anomaly for one driver in the 2022 Bahrain Grand
  Prix.
- Pit timing fields were naturally sparse because they only appear during pit
  events.
- Bahrain 2024 only used the Hard and Soft compounds.
- High-frequency telemetry produced 703 samples for one representative lap.
- Historical data contained only the strategy that actually occurred.

## Scope-protection rules

Version one will prioritize:

1. Completed races
2. Dry conditions
3. Normal green-flag running
4. Lap-level and stint-level modelling
5. One decision at the start of each lap
6. Pit-now versus stay-out comparison
7. Expected remaining race time

The following must not delay the first working version:

- Live race ingestion
- Wet-weather strategy
- Safety-car prediction
- Detailed overtaking simulation
- Two-car team coordination
- Full-grid game theory
- Reinforcement learning
- Neural networks
- Deployment at professional-team scale

## Stop conditions

Development must pause and the affected design must be reviewed if:

- Required fields disappear across a large portion of the dataset
- Leakage-safe evaluation cannot be implemented
- Candidate models cannot beat simple baselines
- The simulator cannot reproduce observed strategies within reported error
- Counterfactual assumptions become impossible to justify
- Runtime or storage requirements exceed the available hardware
- A data-source term prevents the intended public demonstration

A weak result will be documented honestly rather than hidden or redefined after
evaluation.

## Review schedule

This register will be reviewed:

- After the full data pipeline is built
- After exploratory analysis
- After baseline evaluation
- After tyre-model evaluation
- After simulator validation
- Before final deployment