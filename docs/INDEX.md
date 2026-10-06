# Documentation guide

Start with the [project README](../README.md) for the live demonstration, checked-in scope and quickstart. This directory keeps the engineering and research detail without putting a phase log in front of a first-time visitor.

| Need | Read |
| --- | --- |
| What the public site actually serves | [Website source and export provenance](../website/README.md) |
| What the local API supports | [API/dashboard contract](API_DASHBOARD_CONTRACT.md) and [React client](../frontend/README.md) |
| How decisions are evaluated | [Evaluation plan](EVALUATION_PLAN.md), [optimizer contract](OPTIMIZER_CONTRACT.md) and [concurrent simulation contract](CONCURRENT_SIMULATION_CONTRACT.md) |
| How the model was selected | [Model contract](MODEL_CONTRACT.md) and [Phase 6 result](PHASE_6_COMPLETION.md) |
| What the final development audits established | [Phase 7 replay](PHASE_7_COMPLETION.md), [Phase 8 optimizer](PHASE_8_COMPLETION.md) and [Phase 9 scenarios](PHASE_9_COMPLETION.md) |
| What is implemented versus still open | [Current roadmap](ROADMAP.md), [research risk register](RISK_REGISTER.md) and [September 2026 UI/API review](REVIEW_2026-09-27.md) |
| Data provenance and leakage controls | [Data dictionary](DATA_DICTIONARY.md), [dataset contract](DATASET_CONTRACT.md), [cleaning rules](CLEANING_RULES.md) and [processed-data contract](PROCESSED_DATA_CONTRACT.md) |

The [development history](DEVELOPMENT_HISTORY.md) and [historical roadmap](ROADMAP_HISTORY.md) preserve earlier phase-by-phase notes. Their percentages describe old checkpoints, not the current site or research completion.

**Evidence boundary:** 2022–2024 is the development period. The 2025 temporal evaluation remains protected. Single-lap model error, observed replay error, controlled sensitivity and simulated scenario distributions are different measurements; none validates the unobserved alternative pit action as a real outcome.
