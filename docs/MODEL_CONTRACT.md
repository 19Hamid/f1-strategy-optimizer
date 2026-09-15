# Phase 6 Tyre and Lap-Time Model Contract

## Purpose

Phase 6 trains reproducible machine-learning models that predict controlled
next-lap performance from information available at the start of the lap.

Model contract version: `1.0`

The models provide lap-performance estimates for the Phase 7 simulator. They do
not decide whether to pit; that decision remains Phase 8.

## Owner-approved design

Hamid approved:

- Ridge regression
- Random forest regression
- Histogram gradient boosting regression
- Actual next-lap time as the primary target
- Lap-time change from the previous valid lap as an auxiliary diagnostic
- All 26 Phase 4 leakage-approved model features
- Driver and team dependence measured through a mandatory ablation

## Targets

### Primary: next-lap time

Stored target:

`lap_time_target_seconds`

Eligible rows must satisfy both:

- `is_decision_eligible = true`
- `is_lap_time_target_eligible = true`

This is the simulator-facing prediction task.

### Auxiliary: lap-time change

Derived target:

`lap_time_target_seconds - previous_lap_time_seconds`

It is available only when the primary target and an eligible previous lap are
both available.

This target helps analyse how lap performance changes with tyre age and race
state. It is not interpreted as pure tyre degradation because fuel burn,
traffic, track evolution and driver effects remain potential contributors.

## Features

The primary experiment uses every column in the frozen Phase 4
`DECISION_MODEL_FEATURE_COLUMNS` contract.

Categorical features:

- Event
- Driver
- Team
- Current dry compound

Boolean feature:

- Previous-lap target eligibility

Numeric features include:

- Decision lap
- Tyre and stint age
- Completed pit stops
- Previous position
- Previous lap and sector times
- Past-only rolling lap statistics
- Past-only lap-time trend
- Weather age and measured weather conditions

“Use all features” does not include identities, provenance, labels, targets,
eligibility outcomes or exclusion reasons.

## Identity-dependence diagnostic

The approved primary models may use driver and team.

Every selected configuration must also be evaluated without driver and team.
The event feature remains because circuit context materially changes lap-time
scale and geometry.

The report must show whether identity features improve generalization or merely
memorize development participants.

## Candidate models

### Ridge regression

Purpose:

- Interpretable regularized linear reference
- Test whether mostly additive relationships are sufficient
- Provide stable coefficients after preprocessing

Frozen alpha candidates:

- 0.1
- 1.0
- 10.0

### Random forest

Purpose:

- Capture nonlinearities and feature interactions
- Provide a bagging comparison
- Test robustness without boosting

The bounded grid compares tree depth and minimum leaf size with 300 trees and a
fixed feature-sampling fraction.

### Histogram gradient boosting

Purpose:

- Provide the strongest planned nonlinear tabular candidate
- Learn sequential corrections to previous trees
- Capture interactions while keeping training practical

The bounded grid compares learning rate, leaf count and L2 regularization with
300 boosting iterations.

XGBoost is not included in contract version 1.0. It may be considered only
through a reviewed contract revision if the approved scikit-learn candidates
cannot establish a satisfactory result.

## Preprocessing

Preprocessing is fit on training races only.

Frozen transformation rules:

- Numeric missing values: training-fold median
- Categorical missing values: explicit missing category
- Unknown validation categories: all-zero known-category indicators
- Ridge numeric values: standardized using training-fold statistics
- Tree numeric values: imputed without standardization
- Boolean values: deterministic zero-or-one representation
- Categorical values: one-hot encoded using sorted training-fold categories
- Full and driver/team-ablation feature schemas are supported
- No transformation may fit on validation races

The model and preprocessing pipeline are stored together so inference cannot
silently use different transformations.

## Temporal evaluation

The two frozen development folds remain unchanged:

| Fold | Training | Validation |
|---|---|---|
| `development_fold_1` | 2022 | 2023 |
| `development_fold_2` | 2022–2023 | 2024 |

Whole races remain intact. Random lap splitting is forbidden.

The protected 2025 season must not influence feature definitions,
preprocessing, hyperparameters, model selection, thresholds or acceptance
criteria.

## Selection rule

Primary ranking uses pooled validation mean absolute error.

A candidate cannot be selected unless it:

1. Beats the 0.410049-second Phase 5 baseline on comparable rows.
2. Achieves at least 97.0376% coverage.
3. Reports performance on rows shared with `previous_valid_lap`.
4. Reports both temporal folds separately.
5. Reports per-race and required subgroup stability.
6. Records RMSE, median error, p90 error and signed error.
7. Passes the driver/team ablation.
8. Produces deterministic, integrity-checked artifacts.

The approved ablation pass rule removes both driver and team, retrains the
same candidate and requires its comparable-row MAE to remain below the frozen
0.410049-second baseline. This demonstrates that any accepted improvement is
not dependent on memorizing driver or constructor identity.

If no candidate meets the acceptance rule, Phase 6 must report that honestly
instead of selecting a worse model because it looks more sophisticated.

## Degradation diagnostics

The selected primary configuration is retrained separately for both temporal
folds. Diagnostics report residual stability by race, event, compound, tyre-age
band, race-progress band, driver and team. The primary model is also retrained
without driver and team so the identity-dependence penalty remains explicit.

The same selected configuration is fitted against the auxiliary lap-time-change
target. Observed and predicted changes are summarized by compound and tyre-age
band. These are association diagnostics rather than causal tyre-degradation
estimates because fuel burn, traffic, track evolution and driver pace remain
possible influences.

## Reproducibility

Every experiment records:

- Model contract and dataset versions
- Dataset build identity
- Target and eligibility rules
- Exact feature list
- Preprocessing configuration
- Model family and hyperparameters
- Training and validation race identities
- Random seed
- Dependency versions
- Fit and prediction durations
- Aggregate, fold, race and slice metrics
- Coverage and unavailable rows
- Identity-ablation results
- Artifact hashes

## Phase boundary

Phase 6 predicts lap performance and analyses tyre-related change.

It does not:

- Convert observed pit-lane duration into net pit loss
- Simulate remaining races
- Compare pit-now and stay-out strategies
- Open the protected 2025 evaluation season
