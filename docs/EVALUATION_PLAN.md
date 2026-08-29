# F1 Race Strategy Optimizer — Evaluation Plan

## Purpose

This document defines how models, simulations and strategy recommendations will
be evaluated.

The evaluation rules are defined before modelling to prevent data leakage,
metric cherry-picking and unrealistic claims.

## Primary objective

The system should recommend whether to pit at the end of lap `t` or stay out by
comparing the expected remaining race time of both actions.

The system is successful only if its predictive models outperform simple
methods on unseen races and its simulator produces valid, reproducible results.

## Eligible lap-time records

The initial lap-time evaluation will focus on laps that:

- Have a valid lap time
- Are marked accurate by FastF1
- Occurred under dry conditions
- Occurred under normal green-flag conditions
- Are not the opening lap
- Are not pit-entry or pit-exit laps
- Are not strongly affected by recorded incidents

The exact cleaning rules and number of removed records will be documented
during Phase 3.

## Lap-time baseline methods

Every candidate model must be compared against simple baselines.

| Baseline | Prediction |
|---|---|
| Previous lap | Predict that the next lap equals the driver's most recent valid lap |
| Rolling median | Use the median of the driver's three most recent valid laps |
| Stint linear trend | Fit a simple past-only linear relationship between tyre age and lap time |
| Circuit-compound median | Use the historical median pace for the circuit and tyre compound |

All baseline statistics must be calculated using training information only.

## Candidate model families

The initial candidate models may include:

- Linear regression
- Ridge regression
- Decision tree regression
- Random forest regression
- Histogram gradient boosting regression

The final selection will depend on data quality, accuracy, interpretability,
training cost and prediction speed.

A more complicated model will not be selected unless it provides measurable
improvement over simpler models.

## Temporal race-level splitting

Individual laps from the same race must not be randomly divided between
training and evaluation datasets.

Development will use expanding temporal race-level folds:

| Fold | Training seasons | Validation season |
|---|---|---|
| 1 | 2022 | 2023 |
| 2 | 2022–2023 | 2024 |

After model and feature decisions are frozen:

| Dataset | Seasons |
|---|---|
| Final training | 2022–2024 |
| Final untouched evaluation | 2025 |

Preprocessing, feature scaling, imputation and historical aggregates must be
fitted separately inside each training fold.

The 2025 evaluation data must not influence feature selection, model selection
or hyperparameter decisions.

## Lap-time model metrics

### Primary metric

**Mean absolute error in seconds**

This directly measures the typical difference between predicted and actual lap
time and is easy to interpret.

### Secondary metrics

- Root mean squared error
- Median absolute error
- 90th-percentile absolute error
- Mean signed error to detect systematic overprediction or underprediction
- Error by race
- Error by circuit
- Error by tyre compound
- Error by tyre-age range
- Error by driver and team

A single overall score is insufficient because a model may perform well on
average while failing badly on older tyres or particular circuits.

## Tyre-degradation evaluation

Tyre-degradation behaviour will be evaluated using:

- Lap-time prediction error across tyre ages
- Error in the estimated degradation slope
- Bias by tyre compound
- Bias between early, middle and late stint periods
- Performance on unseen races
- Comparison with the past-only linear degradation baseline

## Uncertainty evaluation

When prediction intervals or simulation distributions are introduced, the
system will report:

- Interval coverage
- Average interval width
- Error inside and outside the intervals
- Recommendation stability across repeated scenarios

A model should not report narrow confidence ranges if actual outcomes regularly
fall outside them.

## Pit-loss evaluation

Circuit pit-loss estimates will be evaluated using held-out pit events.

Metrics will include:

- Mean absolute pit-loss error in seconds
- Median absolute pit-loss error
- Error by circuit
- Error under different track-status conditions

Only prior training races may contribute to a circuit's expected pit loss.

## Simulator evaluation

### Observed-strategy replay

For a held-out race, the simulator will first replay the strategy that actually
occurred.

The simulated remaining time will be compared with the observed remaining time
at selected decision laps.

This tests whether the simulator can reproduce an observed race trajectory
before it is trusted to compare unobserved alternatives.

### Validity checks

Every simulated strategy must:

- Complete the required number of laps
- Use valid tyre compounds
- Respect the initial dry-race compound rules represented by the simulator
- Apply pit loss exactly when a pit stop occurs
- Increase tyre age correctly
- Avoid negative lap times or impossible lap numbers
- Produce identical deterministic results for identical inputs and seeds

Invalid simulations are software failures, not merely inaccurate predictions.

## Pit-decision evaluation

Historical data does not reveal the real outcome of a strategy that was not
used. Therefore, historical team decisions will not be treated as perfect
ground-truth labels.

The optimizer will be evaluated using:

- Expected remaining time for each action
- Expected time difference between the actions
- Regret relative to the best strategy under the same simulator assumptions
- Stability of the recommendation under uncertainty
- Sensitivity to tyre degradation and pit-loss assumptions
- Agreement with historical pit decisions as a diagnostic only

Historical agreement must not be described as decision accuracy.

## Concurrent-simulation evaluation

Sequential and concurrent simulation will use identical scenarios and random
seeds.

Evaluation will report:

- Total execution time
- Scenarios processed per second
- Speedup relative to sequential execution
- Output equality or statistical equivalence
- Behaviour across increasing scenario counts
- Peak memory usage when practical

The initial benchmark target is 10,000 scenarios. A strict time target will be
selected only after the sequential baseline has been measured.

## Reporting requirements

Results must be reported using:

- Aggregate tables
- Per-race results
- Error distributions
- Residual plots
- Predicted-versus-observed plots
- Tyre-degradation curves
- Strategy-time distributions
- Documented failure cases

Both strong and weak results must be shown.

## Acceptance gates

Before the final system is considered successful:

1. Every feature must pass decision-time leakage checks.
2. The selected lap-time model must beat the strongest simple baseline on
   overall mean absolute error.
3. Performance must also improve or remain competitive across most held-out
   races and tyre groups.
4. The simulator must pass all strategy-validity tests.
5. Observed-strategy replay must outperform the deterministic baseline.
6. Concurrent results must match sequential results under equivalent inputs.
7. The final 2025 evaluation must be reported without changing the model after
   viewing its results.
8. Limitations and unsuccessful experiments must be documented.

## Reproducibility

Every reported experiment must record:

- Dataset version
- Training and evaluation races
- Feature list
- Model type and parameters
- Random seed
- Software dependency versions
- Evaluation metrics
- Model artifact identifier
- Execution time