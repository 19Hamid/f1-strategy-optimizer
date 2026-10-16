# Phase 8 Completion — Pit-Decision Optimizer

## Status

Phase 8 is complete under the frozen deterministic development contract.

The final audit verifies the complete 68-race development input population,
selects complete historical pit-window pairs, evaluates every accepted
decision twice and stores one immutable optimizer report. The protected 2025
season remains outside the development workflow.

Completion date: 24 September 2026

- Phase 8 completion: 100%
- Overall project completion: 86%
- Next phase: Phase 9 — Concurrent simulation

## Objective achieved

At the start of a controlled dry-race lap, the optimizer compares two complete
remaining-race strategies:

- `PIT_NOW`: finish the current lap and pit after it.
- `STAY_OUT`: defer exactly one lap and then pit.

Both actions use the same immutable race state, target compound, verified
Phase 6 model, feature-history seed, pit-loss assumption, random seed and
finish lap. Only the declared stop lap differs. The comparison reports
predicted remaining time, pit-now advantage, point-estimate recommendation
and regret.

## Sensitivity and stability

Every accepted decision is evaluated across nine canonical cases:

| Axis | Cases |
|---|---|
| Current-stint tyre exposure | Younger by 2 laps, nominal, older by 2 laps |
| Explicit pit-loss assumption | 15 seconds, 20 seconds, 25 seconds |

The full advantage envelope is widened by twice the per-action Phase 7
remaining-time MAE. An action is recommended only when that conservative
interval stays entirely on one side of zero. Otherwise the optimizer reports
`NO_CLEAR_ADVANTAGE`.

The replay MAE is a declared robustness margin. It is not a probability,
confidence interval or calibrated coverage claim.

## Historical audit population

The audit examines every verified development race and accepts at most one
historical pit window per race. A selected window requires consecutive
eligible decisions immediately before and on the observed pit lap, a dry and
green-flag three-lap processed window, a supported next compound and a driver
whose processed history reaches the race distance.

The two selected rows form one mechanically labelled pair:

| Decision row | Observed action | Shared observed stop |
|---|---|---|
| Lap before the pit lap | `STAY_OUT` | Pit after the next lap |
| Pit lap | `PIT_NOW` | Pit after the current lap |

Observed action remains diagnostic context. It is not an optimal-strategy
label, because the unchosen counterfactual outcome was never observed.

The completed audit produced the following real development population:

| Audit result | Value |
|---|---:|
| Development races checked | 68 |
| Races contributing a complete decision pair | 62 |
| Candidate pair slots | 68 |
| Selected decision pairs | 62 |
| Excluded pair slots | 6 |
| Historical decisions evaluated | 124 |
| Observed `PIT_NOW` / `STAY_OUT` rows | 62 / 62 |
| Deterministic executions per decision | 2 |
| Protected 2025 rows | 0 |

The result must be read as three separate layers:

| Layer | Result |
|---|---|
| Nominal point estimate | 106 `PIT_NOW`, 18 `STAY_OUT` |
| Direction across the nine-case sensitivity grid | 123 decisive, 1 crosses zero |
| Final result after the replay-error margin | 0 `PIT_NOW`, 0 `STAY_OUT`, 124 `NO_CLEAR_ADVANTAGE` |

The nominal absolute advantage averaged `2.027643s`, had a median of
`1.718351s` and reached a maximum of `8.121554s`. In 123 of 124 decisions the
same action remained ahead throughout the complete sensitivity grid; one
decision's grid crossed zero. That is a `99.19%` direction-consistency result,
not a claim that 123 historical decisions were objectively correct.

The Phase 7 remaining-time MAE contributes `4.481718s` of uncertainty to each
action. Comparing two actions therefore uses a deliberately conservative
`8.963436s` difference margin. No decision cleared that final bar, so all 124
final classifications are `NO_CLEAR_ADVANTAGE`. This does not mean that the
model had no preference: it means Phase 8 declines to promote any preference
to a high-confidence recommendation under this margin.

## Determinism and provenance

The audit requires:

- All 68 Phase 4 dataset partitions and matching Phase 3 processed partitions
- The exact final Phase 6 `RESIDUAL_HYBRID / xgboost_02` model artifact
- The verified Phase 7 final-audit report
- Matching dataset contract and catalog build identity across all inputs
- Simulation random seed 42
- Zero protected 2025 rows and no protected partition directories

Each accepted decision is evaluated twice. Any difference in the complete
stability output fails the run before publication.

## Stored evidence

The reproducible local report is written below:

`artifacts/optimizer_evaluation/format_version=1.0/run_id=phase-8-final-audit`

It contains four payload artifacts:

- `decisions.parquet` — decision identity, assumptions, nominal action times,
  sensitivity bounds, stable recommendation and observed-action diagnostic
- `cases.parquet` — all nine sensitivity cases per decision
- `summaries.parquet` — reconciled overall and event-level diagnostics
- `provenance.json` — contracts, model, dataset, seed, runtime and row counts

`manifest.json` binds the payload set to byte sizes and SHA-256 hashes. Report
verification independently checks exact schemas, identities, nine-case
coverage, arithmetic, summary reconciliation and zero protected rows.

Generated audit artifacts remain outside Git because they are reproducible
from the verified development dataset, model and simulator report.

## Reproduction

From the repository root:

```bash
cd backend
uv sync --frozen
uv run pytest -q -W error
uv run ruff check .
cd ..
bash ./scripts/run_development_optimizer_audit.sh
```

After the audit succeeds, regenerate the read-only evidence viewer:

```bash
cd backend
uv run python -m app.progress_viewer.cli build
```

The viewer will report 86% overall project completion and expose the verified
Phase 8 nominal calls, sensitivity consistency, final conservative outcomes
and event diagnostics without changing the source report.

## Acceptance gates satisfied by the audit

The final runner fails closed unless it demonstrates:

- Complete 68-race input integrity
- Matching dataset, model and simulator provenance
- Deterministic, complete historical action pairs
- Full nine-case sensitivity coverage for every decision
- Stable recommendations only when the conservative interval excludes zero
- Identical output from two executions of every selected decision
- Reconciled immutable report tables and hashes
- Zero protected 2025 rows

## Known limitations

- Version one covers dry, green-flag decisions only.
- Pit-loss values are explicit controlled assumptions rather than observed net
  counterfactual race-time losses.
- Weather measurements, pace context and position are not forecast forward.
- The target compound is supplied by the accepted observed pit window; Phase 8
  does not search every compound or multi-stop plan.
- Observed-action alignment is descriptive and must not be read as accuracy.
- The final Phase 8 policy abstains on all 124 development decisions because
  the paired-action margin is wider than every observed advantage. This is an
  honest conservative baseline, not evidence of calibrated confidence.
- Probabilistic uncertainty and concurrent scenario execution remain Phase 9.
- Live API and dashboard delivery remain Phase 10.
- The protected 2025 season remains unevaluated.

## Phase 9 handoff

Phase 9 can now consume:

- A frozen pit-now versus one-lap-deferral decision contract
- Deterministic complete action trajectories
- Canonical sensitivity cases and conservative stability classification
- Immutable development decision and event diagnostics
- Verified model, simulator and report provenance

Phase 9 must add concurrent uncertain scenarios without weakening the
decision-time boundary, deterministic seed control, report reconciliation or
protected-season isolation established through Phase 8.
