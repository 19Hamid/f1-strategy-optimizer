# Pitwall — F1 decision lab

A new, static research dashboard for the verified development slice of **The Right Moment to Pit**. The interface is written from scratch in HTML, CSS and JavaScript. Its 124 decisions are exported from the frozen Phase 8 optimizer report and joined to the exact eligible historical decision rows. The exporter verifies report and per-race table hashes before writing `dist/decisions.json`.

## Run locally

```sh
python -m http.server 8000 --directory dist
```

Open `http://localhost:8000/`. It does not call a live API, retrain a model or run a new analysis in the visitor's browser. Its source data comes from the private development archive and includes only verified 2022–2024 race decisions. Every race shown has exactly two recorded decision laps one lap apart. No raw historical partition or trained model binary is shipped with the Site.

To re-export with Python, pandas and pyarrow available:

```sh
python tools/export_decisions.py /path/to/review-bundle
```

The official driver-name mapping is read from the verified API source. If the archive or hashes differ, the exporter fails instead of publishing numbers it cannot verify.

## Proposal alignment

| Proposal goal | What this prototype actually demonstrates |
| --- | --- |
| Pit now versus wait one lap over equal remaining distance | 124 frozen deterministic comparisons with both full remaining times and the recorded planned dry tyre. |
| Recalculate after each completed lap | Two adjacent verified checkpoints for each of 62 driver/race pairs. Full-race, every-lap forecasts have not been implemented or validated. |
| Use current race context | Frozen XGBoost lap-time model uses tyre state, recent pace, prior position and measured weather. Dashboard shows observed changes in a pair. It does not attribute causality or rank model features. |
| Weather, Safety Car, traffic gaps and event windows | Selected decision snapshots are dry and green flag. Rain and Safety Car responses and traffic-gap modeling are research work still to do. |
| Error range and explanation | Displays the Phase 7 development replay MAE as a descriptive per-path margin and the Phase 8 conservative band. This is not a confidence interval or calibrated correctness probability. |
| Unseen historical race evaluation versus baselines | Protected 2025 evaluation remains sealed. Development validation exists for lap-time prediction, but unseen-race counterfactual strategy accuracy and static-baseline comparisons are not established by this Site. |

The Phase 8 report assumes **20 seconds of pit loss** at every shown decision, explicitly as an assumption rather than a circuit-specific observed pit loss. All 124 final conservative recommendations say **NO CLEAR ADVANTAGE**. The point estimate can favor one action, but it does not overturn the broad review margin. The alternative action in any historical decision is simulated; only one action was actually observed.

## Honest CV description

> Built an interactive Formula 1 pit-stop decision dashboard with 124 verified 2022–2024 historical comparisons, a frozen XGBoost lap-time model, two-lap race-context updates and transparent uncertainty evidence. Designed fail-closed data export and source integrity checks.

Do not claim live weather or Safety Car optimization, proven strategy improvement on unseen races, validated counterfactual outcomes or a fully adaptive full-race planner until these pieces are implemented and tested.
