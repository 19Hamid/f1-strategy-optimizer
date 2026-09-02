# F1 Race Strategy Optimizer — Evaluation Plan

## Purpose

This document defines how datasets, predictive models, simulations and strategy
recommendations will be evaluated.

The rules are defined before modelling to prevent data leakage, metric
cherry-picking and unrealistic claims.

## Primary objective

At the start of lap `t`, the system should compare the expected remaining race
time of:

- Pitting at the end of lap `t`
- Staying out and reconsidering at the start of lap `t + 1`

The project succeeds only if its predictive components outperform appropriate
simple methods on temporally held-out races and its simulator produces valid,
reproducible and honestly reported results.

## Decision-time boundary

Every prediction or recommendation is defined at the start of lap `t`.

Inputs may use only:

- Information known before the race
- State already known when lap `t` begins
- Information from completed laps up to lap `t - 1`

Information generated during lap `t` or later may be used only as a target,
diagnostic label or evaluation outcome.

The Phase 4 dataset contract must provide automated evidence that every feature
respects this boundary.

## Protected temporal evaluation policy

Development uses:

- 2022 for initial training
- 2023 for the first temporal validation fold
- 2022–2023 for expanded training
- 2024 for the second temporal validation fold
- 2022–2024 for final training after all development decisions are frozen
- 2025 for final protected temporal evaluation

One 2025 session, the Japanese Grand Prix, received limited schema and
availability inspection during Phase 1. That inspection did not determine
cleaning rules, feature definitions, statistical thresholds, models,
hyperparameters or simulator parameters.

This limited exposure must be disclosed in final reporting. The 2025 season
remains prohibited during Phase 4 development, model selection and
hyperparameter selection.

## Separate analytical populations

Phase 4 must distinguish between decision-state rows and lap-performance target
rows.

### Decision-state population

A row may represent the state at the start of lap `t` when that state can be
constructed from past information.

The row may remain present even when lap `t` later becomes:

- A pit-entry lap
- Inaccurate
- Interrupted
- Wet
- Non-green
- Otherwise unsuitable as a controlled lap-time target

Those post-decision outcomes remain labels or metadata.

### Lap-performance target population

A decision row may train or evaluate the controlled lap-time model only when
lap `t` satisfies the frozen Phase 3 eligibility rules.

Phase 3 produced:

- 74,601 processed development laps
- 57,871 eligible controlled laps
- 16,730 excluded laps

The final Phase 4 target population may be smaller when a row lacks sufficient
past context for required features. Every additional removal must have a
documented dataset-level reason.

## Lap-time baseline methods

Every candidate lap-time model must be compared against simple baselines.

| Baseline | Prediction |
|---|---|
| Previous valid lap | Predict that lap `t` equals the driver's most recent valid completed lap |
| Rolling median | Use the median of the driver's three most recent valid completed laps |
| Stint linear trend | Fit a past-only linear relationship between tyre age and lap time |
| Circuit-compound median | Use a training-only historical median for the circuit and compound |

All baseline statistics must use training information only.

The dataset and baseline contracts must define deterministic fallback behaviour
when:

- A driver has insufficient recent valid laps
- A stint has insufficient observations
- A circuit-compound combination is absent from training
- A historical aggregate is unavailable

Validation or evaluation races must not contribute to their own baseline
statistics.

## Candidate lap-time model families

Initial candidates may include:

- Linear regression
- Ridge regression
- Decision tree regression
- Random forest regression
- Histogram gradient boosting regression

The final selection will depend on:

- Validation accuracy
- Stability across races and tyre groups
- Interpretability
- Training cost
- Prediction latency
- Reproducibility

A more complicated model will not be selected unless it provides measurable
value over simpler alternatives.

Model implementation and selection belong to the later modelling phases, not
Phase 4.

## Temporal race-level splitting

Individual laps from the same race must never be randomly divided between
training and validation datasets.

Development uses expanding temporal race-level folds:

| Fold | Training seasons | Validation season |
|---|---|---|
| 1 | 2022 | 2023 |
| 2 | 2022–2023 | 2024 |

After feature, model and hyperparameter decisions are frozen:

| Dataset | Seasons |
|---|---|
| Final training | 2022–2024 |
| Protected temporal evaluation | 2025 |

Every race belongs wholly to one side of a fold.

Preprocessing, feature scaling, imputation, encoders and historical aggregates
must be fitted separately inside each training fold.

The protected 2025 data must not influence:

- Feature selection
- Target design
- Preprocessing decisions
- Model selection
- Hyperparameters
- Statistical thresholds
- Simulator calibration
- Acceptance thresholds

## Lap-time model metrics

### Primary metric

**Mean absolute error in seconds**

This measures the typical absolute difference between predicted and observed
lap time in an interpretable unit.

### Secondary metrics

- Root mean squared error
- Median absolute error
- 90th-percentile absolute error
- Mean signed error
- Error by race
- Error by circuit
- Error by tyre compound
- Error by tyre-age range
- Error by driver
- Error by team
- Error by race-progress range

A single overall score is insufficient because a model may appear strong while
failing badly on particular circuits, tyre ages or race stages.

## Tyre-degradation evaluation

Tyre-degradation behaviour will be evaluated using:

- Lap-time error across tyre ages
- Error in the estimated degradation slope
- Bias by tyre compound
- Bias across early, middle and late stint periods
- Performance on temporally held-out races
- Comparison with the past-only linear degradation baseline
- Stability when driver and team identifiers are removed

Raw compound averages must not be interpreted as causal tyre effects because
compound selection is confounded by circuit, driver, fuel load, traffic, race
progress and stint purpose.

## Uncertainty evaluation

When prediction intervals or simulation distributions are introduced, the
system will report:

- Interval coverage
- Average interval width
- Error inside and outside intervals
- Recommendation stability across repeated scenarios
- Sensitivity to model and simulator assumptions

A model must not report narrow confidence ranges when actual outcomes regularly
fall outside them.

## Pit-lane duration evaluation

Phase 3 reconstructed observed pit-lane durations from pit-entry and pit-exit
timing markers.

These observations are not automatically:

- Stationary service time
- Pit-lap time loss
- Net race-time loss
- Counterfactual pit loss
- A final simulator parameter

The 1,465 Phase 3 duration-analysis candidates are complete, dry, green,
uninterrupted events using supported dry compounds.

A historical pit-lane-duration estimator may be evaluated on held-out candidate
events using:

- Mean absolute duration error
- Median absolute duration error
- Root mean squared duration error
- Error by circuit
- Error by season
- Error by compound transition
- Error across duration quantiles

Only training races may contribute to the estimate used for a held-out event.

## Net pit-loss evaluation

Net pit loss represents a counterfactual quantity: the difference between
pitting and continuing at racing speed under comparable conditions.

It is not directly supplied by FastF1 and cannot be treated as identical to
observed pit-lane duration.

Before a net-pit-loss model is evaluated, its contract must define:

- The exact target or simulator parameter
- Which observed quantities contribute to it
- Its counterfactual assumptions
- How normal racing time is estimated
- How traffic and interruptions are treated
- How training and held-out races are separated
- The uncertainty attached to the estimate

If no defensible observed target can be constructed, net pit loss will remain
an explicitly documented simulator assumption evaluated through replay,
sensitivity analysis and uncertainty—not through fake supervised accuracy.

## Simulator evaluation

### Observed-strategy replay

For a held-out race, the simulator will first replay the strategy that actually
occurred.

The simulated remaining time will be compared with observed remaining time at
selected decision laps.

This tests whether the simulator can reproduce an observed trajectory before it
is trusted to compare unobserved alternatives.

### Validity checks

Every simulated strategy must:

- Complete the required number of laps
- Use supported compounds
- Respect the encoded tyre-use rules
- Apply the configured pit-loss mechanism exactly when a stop occurs
- Increase tyre age correctly
- Avoid negative lap times
- Avoid impossible lap numbers
- Avoid impossible stint transitions
- Produce deterministic results for identical inputs and seeds

Invalid simulations are software failures, not merely inaccurate predictions.

### Replay metrics

Observed-strategy replay may report:

- Remaining-time absolute error
- Per-lap trajectory error
- Error growth across simulation horizon
- Error by circuit
- Error by tyre strategy
- Calibration of simulated uncertainty intervals

## Pit-decision evaluation

Historical data does not reveal the actual outcome of a strategy that was not
used. Historical team choices are therefore not optimal ground-truth labels.

The optimizer will be evaluated using:

- Expected remaining time for each action
- Expected difference between actions
- Regret relative to the best action under identical simulator assumptions
- Recommendation stability under uncertainty
- Sensitivity to degradation and pit-loss assumptions
- Observed-strategy replay
- Historical agreement as a diagnostic only

Historical agreement must not be reported as decision accuracy.

A disagreement with the historical team decision does not prove that either
the optimizer or the team was wrong because the alternative outcome remains
counterfactual.

## Concurrent-simulation evaluation

Sequential and concurrent simulation must use equivalent scenarios and random
seeds.

Evaluation will report:

- Total execution time
- Scenarios processed per second
- Speedup relative to sequential execution
- Output equality or statistical equivalence
- Behaviour across increasing scenario counts
- Peak memory use when practical

The initial benchmark target is 10,000 scenarios. A strict runtime target will
be selected only after the sequential baseline has been measured.

## Reporting requirements

Results must include:

- Aggregate metrics
- Per-race metrics
- Error distributions
- Residual plots
- Predicted-versus-observed plots
- Tyre-degradation curves
- Strategy-time distributions
- Uncertainty calibration
- Documented fallback cases
- Documented failures and weak results

Both strong and weak results must be shown.

## Acceptance gates

Before the final system is considered successful:

1. Every feature must pass decision-time leakage checks.
2. Every validation and evaluation split must contain complete races.
3. Preprocessing must be fitted using training data only.
4. The selected lap-time model must beat the strongest applicable simple
   baseline on overall validation mean absolute error.
5. Performance must improve or remain competitive across most held-out races
   and tyre groups.
6. Pit-lane duration must not be misreported as net pit loss.
7. The simulator must pass all strategy-validity tests.
8. Observed-strategy replay must outperform its declared deterministic
   baseline.
9. Concurrent results must match sequential results under equivalent inputs.
10. Final 2025 evaluation must be reported without changing the frozen system
    after viewing its results.
11. The limited Phase 1 inspection of one 2025 session must be disclosed.
12. Limitations and unsuccessful experiments must be documented.

If an acceptance gate fails, the result must be reported honestly. The target,
metric or population must not be redefined after evaluation merely to create a
successful-looking result.

## Reproducibility

Every reported experiment must record:

- Dataset contract version
- Dataset-build identifier
- Training and evaluation races
- Temporal fold
- Feature list
- Target definition
- Target-eligibility rule
- Model type and parameters
- Preprocessing configuration
- Random seed
- Software dependency versions
- Evaluation metrics
- Model artifact identifier
- Execution time
- Relevant simulator assumptions

## Phase 4 requirements

Phase 4 must provide:

- Canonical decision-row identity
- Decision timestamp
- Feature availability classifications
- Separate decision and target eligibility
- Deterministic temporal fold assignments
- Dataset-level reason codes
- Provenance for derived values
- Automated leakage validation
- Protected-2025 rejection
- Versioned dataset storage and integrity evidence

Phase 4 prepares baseline-ready datasets. Baseline implementation and model
comparison begin only after the dataset contract is frozen.