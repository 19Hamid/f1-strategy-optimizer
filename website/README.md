# Pitwall public website — source and evidence

A static research dashboard for **The Right Moment to Pit**. This is the source of the public Vercel page; the separate React/FastAPI dashboard lives in `frontend/` and `backend/`. The editable page files are `dist/index.html`, `dist/style.css` and `dist/app.js`; the four JSON files in `dist/` are precomputed research exports. No build step or hosted API is used for the public page.

The picker lists 1,350 recorded driver/race entries across 68 Grands Prix in 2022–2024, exported from hash-checked archived FastF1 race laps. Every entry shows the driver's recorded laps, pit entries and tyre stints. There are 1,023 driver/race entries with pit timing comparisons: 62 pairs (124 decisions) from the immutable Phase 8 audit, 514 additional pairs (1,028 decisions) from the development export, and 447 earlier dry pre-pit entries (888 decisions) reconstructed with the frozen development model.

## Run locally

```sh
python -m http.server 8000 --directory website/dist
```

Run that command from the repository root and open `http://localhost:8000/`. Check the picker with `node website/tools/test_catalog.mjs`. The site serves precomputed data; it does not retrain or run a model in the visitor's browser. Every recorded driver/race entry appears in the race it entered. A comparison is available only when an eligible dry decision lap, a recorded next tyre and a replay context can be reconstructed. The 327 remaining entries still show their recorded race context and explain why no pit estimate appears. Switching entries always clears the previous comparison.

To re-export, use the separately supplied, verified development bundle and the locked backend Python environment. The data partitions, model binary and audit reports are **not in a fresh Git clone**. From `website/`, with that environment active:

```sh
python tools/export_decisions.py /path/to/review-bundle
python tools/export_extended.py /path/to/review-bundle 4
python tools/export_pre_pit.py /path/to/review-bundle
python tools/export_catalog.py /path/to/review-bundle
```

The extended and pre-pit exports use the frozen model and verified 2022–2024 input partitions, but their extra point estimates have **not** gone through the immutable Phase 8 sensitivity audit. They are labeled exploratory in the interface. The 124 audited decisions remain unchanged in `dist/decisions.json`. The driver-name mapping for audited decisions comes from the API source; other names were checked against Formula 1 standings. If archive hashes differ, export fails. Commit changed JSON only after comparing counts, hashes and page behavior with the original exports.

## Proposal alignment

| Proposal goal | What this prototype actually demonstrates |
| --- | --- |
| Pit now versus wait one lap over equal remaining distance | 124 audited decisions and 1,916 additional exploratory point estimates, each with both full remaining times and a recorded next dry tyre. |
| Recalculate after each completed lap | Two adjacent checkpoints for 1,017 driver/race pairs; six earlier windows have a single usable checkpoint. Full-race, every-lap forecasts have not been implemented or validated. |
| Use current race context | Frozen XGBoost lap-time model uses tyre state, recent pace, prior position and measured weather. Every recorded starter has a lap and tyre-stint summary. The dashboard does not attribute causality or rank model features. |
| Weather, Safety Car, traffic gaps and event windows | Selected decision snapshots are dry and green flag. Rain and Safety Car responses and traffic-gap modeling are research work still to do. |
| Error range and explanation | Audited decisions show the Phase 8 conservative band. Exploratory decisions show only a symmetric Phase 7 replay-error allowance; they have not had the full sensitivity grid. Neither is a confidence interval or calibrated correctness probability. |
| Unseen historical race evaluation versus baselines | Protected 2025 evaluation remains sealed. Development validation exists for lap-time prediction, but unseen-race counterfactual strategy accuracy and static-baseline comparisons are not established by this Site. |

All shown comparisons assume **20 seconds of pit loss**, not a circuit-specific observed value. All 124 immutable audited decisions say **NO CLEAR ADVANTAGE** after their full review margin. Additional historical windows show only a first estimate and do not claim a stable recommendation. The alternative action was simulated; only one action was actually observed.

## Honest CV description

> Built an interactive Formula 1 pit-stop dashboard covering 1,350 recorded driver/race entries from 2022–2024, with 124 audited and 1,916 additional exploratory pit-timing estimates using a frozen XGBoost model. Exposed source provenance and model limits alongside historical checkpoint comparisons.

Do not claim live weather or Safety Car optimization, proven strategy improvement on unseen races, validated counterfactual outcomes or a fully adaptive full-race planner until these pieces are implemented and tested.

## Typography

The site bundles Titillium Web (Regular, SemiBold, Bold and Black) under the SIL Open Font License 1.1, included at `dist/fonts/OFL.txt`. It does not use Formula 1's licensed proprietary header typeface or official logos.
