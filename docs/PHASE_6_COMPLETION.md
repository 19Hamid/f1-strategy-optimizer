# Phase 6 Completion — Tyre and Lap-Time Modelling

## Status

Phase 6 is complete.

The final development audit selected a leakage-safe XGBoost residual-hybrid
model that passed every frozen selection gate. The protected 2025 season
remained unopened by the modelling workflow.

Completion date: 15 September 2026

- Phase 6 completion: 100%
- Overall project completion: 63%
- Next phase: Phase 7 — Race-strategy simulator

## Objective achieved

Phase 6 trained models that estimate controlled next-lap time from information
available at the start of a lap.

The selected model provides the lap-performance component required by the
Phase 7 simulator. It does not itself choose whether to pit and it does not
claim that observed lap-time change is pure causal tyre degradation.

## Development population

| Measure | Verified value |
|---|---:|
| Development seasons | 2022–2024 |
| Verified race sessions | 68 |
| Sessions contributing eligible lap targets | 66 |
| Primary next-lap targets | 52,483 |
| Auxiliary lap-delta targets | 50,913 |
| Temporal split assignments | 204 |
| Protected 2025 rows | 0 |

Two verified development sessions contain no row eligible for the controlled
lap-time target. They remain part of the audited catalog and are not silently
removed from the dataset evidence.

## Evaluation design

The original whole-race temporal folds remained unchanged:

| Fold | Training races | Validation races |
|---|---|---|
| development_fold_1 | 2022 | 2023 |
| development_fold_2 | 2022–2023 | 2024 |

Every candidate used preprocessing fitted only on its training races.

The audit compared:

- 3 Ridge configurations
- 4 random-forest configurations
- 8 histogram-gradient-boosting configurations
- 8 XGBoost configurations
- 23 total configurations
- Direct absolute-lap-time prediction
- Residual-hybrid prediction with direct fallback
- The complete 26-feature contract
- A mandatory version without driver and team

This produced 184 fitted temporal candidates before final selection and refit.

## Selection history

The first direct-model audit correctly selected nothing. Its best candidate was
random_forest_02 with 0.413153-second comparable-row MAE, which did not beat the
0.410049-second frozen baseline.

The guarded residual-hybrid revision also correctly selected nothing. Its best
candidate was again random_forest_02 with 0.413596-second comparable-row MAE,
slightly worse than the matching direct model.

The acceptance criteria were not weakened. Contract version 1.2 added XGBoost
as a stronger challenger while preserving all earlier evidence.

## Selected model

| Property | Selected value |
|---|---|
| Formulation | RESIDUAL_HYBRID |
| Candidate | xgboost_02 |
| Model family | XGBoost |
| Objective | reg:absoluteerror |
| Number of trees | 800 |
| Learning rate | 0.03 |
| Maximum depth | 4 |
| Minimum child weight | 20 |
| Row subsampling | 0.9 |
| Column subsampling | 0.9 |
| L1 regularization | 0.1 |
| L2 regularization | 5.0 |
| Random seed | 42 |
| Tree method | hist |
| Execution device | CUDA |

The residual component predicts the change from the previous valid lap. The
absolute prediction is reconstructed as previous valid lap time plus predicted
change. If a usable previous lap is unavailable, the matching direct XGBoost
model provides the fallback prediction.

## Held-out result

| Measure | Result |
|---|---:|
| All-row pooled MAE | 0.410601 s |
| Comparable-row MAE | 0.392725 s |
| Frozen baseline comparable MAE | 0.410049 s |
| Relative comparable-row improvement | 4.22% |
| Identity-ablation comparable MAE | 0.392716 s |
| Coverage | 100.0000% |

The all-row pooled MAE and frozen baseline MAE are not directly comparable.
The selected model covers every eligible target, including rows where
previous_valid_lap cannot predict. The honest shared-row comparison is:

0.392725 seconds versus 0.410049 seconds.

That is a 0.017324-second or 4.22% reduction in mean absolute error on the
same validation rows.

Removing driver and team produced 0.392716-second comparable-row MAE. This
passed the frozen ablation gate and shows that the accepted improvement does
not depend on memorizing driver or constructor identity.

## Hardware execution

The audit used XGBoost 3.4.1 and verified the requested CUDA device before
candidate training:

- GPU: NVIDIA GeForce RTX 5070 Ti Laptop GPU
- Available memory: 12,227 MiB
- XGBoost initialized device: cuda:0
- NVIDIA driver: 610.57.01
- CUDA user-mode version: 13.3

Random forests continued to use all CPU cores through n_jobs=-1. Ridge and
scikit-learn histogram gradient boosting remained CPU estimators. GPU use was
limited to work XGBoost can actually accelerate instead of manufacturing a
fake utilization claim.

## Stored evidence

Evaluation report:

artifacts/model_evaluation/contract_version=1.2/run_id=phase-6-final-audit

Fitted model:

artifacts/models/contract_version=1.2/artifact_id=phase-6-final-audit-lap-time

The generated directories are intentionally excluded from Git. They are
reproducible local products tied to the verified dataset build.

The evaluation bundle contains seven report artifacts. The model bundle
contains:

- model.joblib
- provenance.json
- verification.parquet
- manifest.json

The final verification confirmed:

- Exact artifact file sets
- SHA-256 hashes and sizes
- Exact table schemas and counts
- Dataset, model, feature, target and session provenance
- Selected formulation and CUDA execution identity
- Zero protected 2025 rows
- Exact reproduction of 128 stored predictions after model reload
- Zero integrity issues

## Automated verification

The completion run recorded:

- 1,215 passing backend tests
- 5 expected PostgreSQL integration skips in the non-PostgreSQL suite
- Warnings treated as errors
- Ruff passing
- 68 valid dataset sessions
- Zero dataset-integrity issues
- Successful model-report verification
- Successful fitted-model verification
- Clean Git worktree

The XGBoost unit fixtures use tiny boosters to keep routine test execution
practical. Separate assertions freeze the real 800-tree production grid, and
the complete 800-tree CUDA configuration was exercised by the successful
68-race audit.

## Leakage and quality boundaries preserved

Phase 6 did not:

- Randomly split laps across training and validation
- Fit preprocessing on validation races
- Use post-decision labels or target-lap outcomes as inputs
- Relax the Phase 5 baseline after seeing model results
- Reduce coverage to obtain a lower error
- Accept dependence on driver and team identity
- Open the protected 2025 season
- Invent an optimal historical pit-decision label
- Treat observed association as causal tyre degradation

## Interpretation

The selected model predicts controlled next-lap performance more accurately
than the previous-valid-lap reference on the same rows while also supplying a
prediction when that reference is unavailable.

This is useful to the simulator because it can estimate the time cost of future
laps as tyre age and race state change. It is not yet a strategy recommendation.
Phase 7 must repeatedly call this lap-performance model while advancing a
simulated race under alternative pit plans.

## Known limitations

- Version one focuses on controlled dry green-flag conditions.
- Fuel load is represented indirectly rather than measured directly.
- Traffic, driver intent and team instructions remain partially unobserved.
- Lap-time change is not a pure causal estimate of tyre degradation.
- The model has not yet been evaluated on the protected 2025 season.
- The model does not estimate counterfactual race outcomes by itself.
- Professional live-race deployment remains outside the educational V1 scope.

## Reproduction

From the repository root:

    cd backend
    uv sync --frozen
    uv run pytest -q -W error
    uv run ruff check .
    cd ..
    bash ./scripts/run_development_model_audit.sh

The audit script requests CUDA by default, verifies actual CUDA initialization,
checks all 68 development partitions, rebuilds the temporal comparison, refits
the selected model and verifies both immutable artifact bundles.

## Phase 7 handoff

Phase 7 can now consume:

- A verified next-lap prediction interface
- Full-coverage direct fallback behavior
- Frozen preprocessing and feature order
- Selected model provenance
- Lap-time-change diagnostics by tyre and race state
- Known accuracy, coverage and identity-dependence evidence

Phase 7 must build the controlled race-strategy simulator before Phase 8
compares pit-now and stay-out decisions.
