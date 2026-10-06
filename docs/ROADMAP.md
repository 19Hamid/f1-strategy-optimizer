# Current project status and next work

The [public Pitwall site](https://pitwall-race-decision.vercel.app/) is an educational historical explorer, built from precomputed 2022–2024 development outputs. Its source, exported JSON and local catalog test are in [`website/`](../website/).

## Established development work

- Phases 2–6 prepared the historical data and selected the frozen lap-time model. See the [model result](PHASE_6_COMPLETION.md) and [data contracts](DATASET_CONTRACT.md).
- Phase 7 produced controlled race replay evidence; Phase 8 compared pit now with a one-lap wait and reported sensitivity; Phase 9 generated paired simulated scenarios. Their [completion reports](PHASE_7_COMPLETION.md), [optimizer report](PHASE_8_COMPLETION.md) and [scenario report](PHASE_9_COMPLETION.md) document the development audits.
- Phase 10 code includes a FastAPI contract, verified historical decision picker, deterministic analysis, bounded in-memory paired jobs and a separate React client. The [September UI/API review](REVIEW_2026-09-27.md) records local tests and limits. **The public Vercel site is static and does not host this API.**
- The current static export lists 1,350 driver/race records, with a usable comparison for 1,023 entries. Of its 2,040 decision snapshots, 124 are Phase 8 audited and 1,916 are exploratory point estimates. See [website provenance](../website/README.md).

These are completed development components, not a percentage of a finished research programme or proof of optimal real-world strategy.

## Open work

1. Evaluate the protected 2025 temporal holdout under the planned gate before making any unseen-season performance claim. Keep it outside development and public exports until then.
2. Test full-race adaptation to changing rain, Safety Car, traffic and rival behavior with available evidence. The current public site shows dry green-flag historical snapshots.
3. Validate counterfactual decision usefulness against appropriate baselines. Historical data contain only one observed action; an unobserved alternative has no measured ground truth.
4. Improve pit-loss assumptions and investigate tyre choice only after extending the verified model and scenario contract.
5. If hosting the API publicly, design persistent jobs, capacity limits, deployment of verified artifacts and operational monitoring. The current jobs live in one process's memory.
6. Keep the public website's precomputed exports, source and documentation in sync; review permissions for any third-party assets or redistributed data before changing GitHub visibility.

The [historical roadmap](ROADMAP_HISTORY.md) records the original milestone plan and dated completion percentages. It is not a current release-status indicator.
