# Phase 6 Visual Model Review

## Purpose

The Phase 6 audit stores complete machine-readable evaluation evidence as
Parquet and JSON. The visual model review converts that evidence into a local
browser dashboard with readable tables and standalone SVG charts.

The review is a presentation layer only. It does not retrain a candidate,
change the selected model, modify an evaluation score or read the protected
2025 season.

## Build the dashboard

The completed Phase 6 model audit must already exist locally. From the
repository root, run:

```bash
bash ./scripts/build_phase_6_model_review.sh
```

The script verifies the immutable report and fitted model before reading any
evidence. It then opens:

```text
artifacts/model_review/format_version=1.0/
  run_id=phase-6-final-audit/index.html
```

When neither `wslview` nor Windows PowerShell is available, the script prints
the exact HTML path instead of failing the completed build.

To rebuild an existing dashboard atomically:

```bash
F1_STRATEGY_REPLACE_MODEL_REVIEW=1 \
  bash ./scripts/build_phase_6_model_review.sh
```

## Visual evidence

The dashboard contains:

- Selected-model summary cards
- The complete direct and residual-hybrid candidate leaderboard
- Top-candidate comparable-row MAE against the frozen baseline
- Selected-model performance on the 2023 and 2024 temporal folds
- Held-out error by dry tyre compound
- The fifteen most difficult held-out race sessions
- Observed and predicted lap-time change by compound and tyre-age band
- Driver/team identity-ablation performance
- Model, dataset, dependency, random-seed and execution-device provenance

Each graph is stored as a standalone SVG image. Opening an SVG directly in the
browser allows it to be viewed or saved without losing resolution.

## Honest interpretation

The review deliberately uses only persisted held-out evidence. It does not use
the final model, which was refitted on all 2022--2024 development rows, to draw
a misleading training-data prediction scatter plot.

The tyre-age graph compares aggregated observed and predicted lap-time change.
It is an association diagnostic rather than proof of pure causal tyre
degradation because fuel burn, traffic and track evolution remain partially
unobserved.

## Integrity boundaries

The generator:

1. Verifies the Phase 6 evaluation report.
2. Verifies and reload-checks the fitted model artifact.
3. Reads the existing Parquet and JSON evidence without modifying it.
4. Writes into the separate `artifacts/model_review` directory.
5. Publishes HTML and SVG files atomically.
6. Records file sizes and SHA-256 hashes in `manifest.json`.
7. Rejects missing columns, unsafe run identifiers and silent overwrites.

Generated reviews are excluded from Git because they are reproducible local
artifacts. The generator, tests and documentation remain version controlled.
