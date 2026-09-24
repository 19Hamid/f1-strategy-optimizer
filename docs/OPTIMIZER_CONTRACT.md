# Phase 8 Pit-Decision Optimizer Contract

## Status and identity

- Contract version: `1.0`
- Development seasons: 2022–2024
- Protected temporal evaluation season: 2025
- Current Phase 8 completion: 100%
- Decision scope: controlled dry-race, green-flag conditions

This contract defines the first decision comparison built on the verified
Phase 7 simulator. It does not retrain the Phase 6 model and does not change
the Phase 7 simulation contract.

## Decision timestamp and objective

The decision is made at the start of lap `t`, before any information produced
during lap `t` is available.

The objective is to minimize expected remaining race time from the start of
lap `t` to the flag. The current milestone compares deterministic model point
estimates. It does not yet claim calibrated decision uncertainty.

## Actions

Phase 8 version 1 compares exactly two actions:

| Action | Complete remaining-race strategy |
|---|---|
| `PIT_NOW` | Complete lap `t`, pit after lap `t`, then run to the flag on the declared target compound |
| `STAY_OUT` | Complete laps `t` and `t + 1`, pit after lap `t + 1`, then run to the flag on the same declared target compound |

`STAY_OUT` is a fixed one-lap deferral, not an open-ended instruction to stay
out indefinitely. Both strategies contain exactly one future stop in this
controlled milestone. At least three laps, including lap `t`, must remain so
both stop schedules are legal under the Phase 7 contract.

## Symmetric comparison requirements

The two actions must use the same:

- Immutable start-of-lap race state
- Explicit target dry compound
- Verified Phase 6 model artifact
- Feature-history seed
- Pit-loss assumption and evidence
- Random seed
- Start lap and final race lap
- Simulation mode and model feature contract

Only the declared stop lap may differ. A comparison is invalid if either
trajectory changes a shared assumption or fails to reach the flag.

The target compound is an input to the comparison. Phase 8 does not silently
choose a compound in this milestone. A fresh set of the current compound is
allowed only when the inherited two-dry-compound race rule is already
satisfied.

## Point-estimate outputs

For each action, the optimizer stores the complete Phase 7 trajectory and its
predicted remaining time. Define:

```text
pit_now_advantage_seconds = stay_out_time - pit_now_time
```

- Positive values favor `PIT_NOW`.
- Negative values favor `STAY_OUT`.
- Values equal within an absolute tolerance of `1e-9` seconds produce
  `NO_CLEAR_ADVANTAGE`.

Point-estimate regret is:

```text
regret(action) = action_time - min(pit_now_time, stay_out_time)
```

The faster action therefore has zero point-estimate regret. These values are
conditional on the declared model and simulator assumptions; they are not
observed counterfactual truth.

## Sensitivity grid

The 60% milestone evaluates a canonical nine-case grid:

| Axis | Cases | Meaning |
|---|---|---|
| Circuit pit loss | `LOW`, `NOMINAL`, `HIGH` | The exact event profile and evidence already governed by the Phase 7 registry |
| Current tyre exposure | `YOUNGER`, `NOMINAL`, `OLDER` | Current tyre age and stint progress shifted together by -2, 0 or +2 laps |

The tyre-age axis changes the current `tyre_age_laps` and
`current_stint_laps_completed` values in both the immutable race state and the
first Phase 6 feature row. Recent lap times and every other feature remain
fixed. This is a one-factor-at-a-time model-response diagnostic, not a claim
that the driver's real history could have changed while its observed pace
remained identical.

The full younger case is available only after at least two completed laps on
the current tyre and stint. The analyzer fails rather than silently clamping
an invalid negative age.

Each of the nine cells contains a complete symmetric pit-now-versus-stay-out
comparison. The raw sensitivity result exposes the minimum and maximum pit-now
advantage. The following 75% stability layer consumes that envelope without
altering any cell.

Both strategies make one stop, so direct additive pit cost may cancel. It is
still evaluated because the stop occurs on different laps and elapsed-time
changes can affect later model inputs such as weather-observation age. Phase 8
measures the resulting model behaviour rather than assuming either outcome.

## Recommendation stability and explicit uncertainty

The 75% milestone accepts one symmetric action-time margin `u` in seconds. The
margin must be finite, non-negative and accompanied by non-empty evidence. It
is an explicit assumption, not an automatically calibrated confidence level.

Because either action estimate may move by `u` in the opposite direction, the
pit-now advantage requires a difference margin of `2u`. If the nine-case
sensitivity envelope is `[a, b]`, the conservative advantage interval is:

```text
[a - 2u, b + 2u]
```

The stable recommendation is:

- `PIT_NOW` only when the complete interval is strictly positive beyond the
  frozen numerical tolerance.
- `STAY_OUT` only when the complete interval is strictly negative beyond the
  frozen numerical tolerance.
- `NO_CLEAR_ADVANTAGE` whenever the interval contains or touches zero.

The nominal centre-cell recommendation remains visible for diagnosis, but it
cannot override an unstable conservative interval. The optimizer does not
report a probability, confidence percentage or statistically calibrated
coverage claim at this milestone.

## Historical decision diagnostics

The 85% milestone accepts a development-only population of complete stability
assessments. Each record derives its identity from the optimizer request:

- Season and race session
- Driver
- Start-of-lap decision number
- Declared target compound

The population rejects duplicate identities so one historical decision cannot
receive accidental extra weight. Protected 2025 records remain impossible
because the inherited race-state contract accepts only development seasons.

The overall and event-level summaries report:

- Stable `PIT_NOW`, stable `STAY_OUT` and `NO_CLEAR_ADVANTAGE` counts
- Mean and median nominal pit-now advantage
- Mean conservative advantage-interval width
- Optional observed immediate-action counts
- Comparable observed-action alignment and difference counts

Observed action means only whether the driver pitted after the decision lap.
It is optional context, not an optimal-decision target. Alignment is calculated
only when an observed action and a stable recommendation both exist. The field
is explicitly named `observed_action_alignment_rate`; no accuracy metric is
defined. No counterfactual outcome is invented for the historical action that
was not taken.

## Historical-action boundary

The action a team actually took may be retained for diagnostics, but it is not
an optimal-decision label. Only the outcome of the chosen historical strategy
was observed. The unchosen counterfactual was not.

Phase 8 must therefore evaluate recommendation distributions, stability and
simulator-conditioned outcomes without reporting historical agreement as
decision accuracy.

## Immutable reporting and storage

The 92% milestone normalizes every accepted historical diagnostic population
into three exact-schema Parquet tables:

- `decisions.parquet` stores decision identity, shared inputs, nominal action
  times, sensitivity bounds, uncertainty evidence, stable recommendation and
  optional observed-action alignment.
- `cases.parquet` stores all nine canonical tyre-age and pit-loss cases for
  every decision, including pit-loss source evidence, action times,
  recommendation and point-estimate regret.
- `summaries.parquet` stores the reconciled overall and event-level diagnostic
  populations.

`provenance.json` binds those tables to the optimizer, simulator and model
contract versions; model artifact; development dataset build; dependency
versions; random seed; execution duration; exact row counts; and zero
protected-evaluation rows. `manifest.json` records the run identity, format
version, byte size and SHA-256 hash of every report artifact.

Publication is atomic and a run identity cannot overwrite an existing report.
Readback verification requires the exact file set, hashes, schemas, identities,
row counts, complete nine-case coverage, recommendation and regret arithmetic,
conservative bounds, observed-action alignment and aggregate summaries to
reconcile. Any mismatch invalidates the report.

## Final development audit

The 100% milestone scans the complete verified 68-race development catalog.
Each race may contribute at most one historical pit window. A window is
accepted only when one finishing driver has:

- Consecutive eligible decision rows at laps `p - 1` and `p`
- A dry, green-flag processed window covering `p - 1`, `p` and `p + 1`
- An observed pit after lap `p`
- A supported dry compound before and after the stop
- At least two completed current-stint laps at both decisions
- Enough laps remaining for both optimizer actions to be legal

The lap `p - 1` row is labelled observed `STAY_OUT`, because the driver did
not stop after that lap and the one-lap deferral stops after `p`. The lap `p`
row is labelled observed `PIT_NOW`. Both rows therefore refer to the same
observed stop and next compound without inventing an optimal counterfactual.
When multiple windows qualify, selection is deterministic: latest pit lap,
then previous position, driver and team.

Every selected decision is evaluated twice through the full nine-case
sensitivity and stability path. All immutable outputs must compare equal. The
per-action uncertainty margin is the verified Phase 7 development replay
`OVERALL_REMAINING` MAE. It is preserved as a descriptive robustness
assumption, not a calibrated probability, confidence interval or accuracy
claim. The audit also requires the Phase 6 model, Phase 7 report and Phase 4
dataset to share the same dataset-build identifier.

The audit fails unless accepted pairs cover every development season, every
represented race contains exactly one complete action pair, the report passes
independent readback verification and no protected 2025 row or directory is
observed. Exact selected-pair and outcome counts are data-dependent report
evidence and are printed by the audit CLI.

## Current exclusions

The completed deterministic Phase 8 scope does not provide:

- Monte Carlo or probabilistic uncertainty
- Wet-weather, safety-car or red-flag decisions
- Traffic interaction or adversarial responses from other cars
- Target-compound optimization or advanced multi-stop search
- Protected 2025 temporal evaluation

Those capabilities must be added explicitly and tested rather than inferred
from the deterministic comparison.

## Acceptance gates

The deterministic comparison milestone is accepted only when:

1. Both actions are constructed from one immutable request.
2. `PIT_NOW` stops after lap `t` and `STAY_OUT` after lap `t + 1`.
3. Both trajectories use the same target compound and shared assumptions.
4. Both trajectories simulate the complete remaining horizon.
5. The inherited dry-compound and protected-season rules remain enforced.
6. Positive advantage values favor `PIT_NOW` and negative values favor
   `STAY_OUT`.
7. Exact ties return `NO_CLEAR_ADVANTAGE` rather than an undocumented
   preference.
8. Point-estimate regret reconciles with the lower remaining-time estimate.
9. Repeated executions with identical inputs return identical evidence.
10. The sensitivity grid contains all nine canonical cases exactly once.
11. Every pit-loss case uses the matching circuit profile and evidence.
12. Tyre-age perturbation changes only current tyre and stint exposure while
    preserving recent pace and all other feature evidence.
13. The base request and feature context remain immutable.
14. Every uncertainty margin is finite, non-negative and carries evidence.
15. The conservative advantage interval uses twice the per-action margin.
16. An action is recommended only when the full interval excludes zero.
17. Unstable intervals return `NO_CLEAR_ADVANTAGE` without a confidence claim.
18. Historical decision identities are unique and development-only.
19. Overall and event summaries reconcile recommendation and observed counts.
20. Observed action is reported as alignment, never optimal-label accuracy.
21. Missing observed actions and no-clear recommendations are excluded from
    the alignment denominator.
22. Every decision contains exactly the canonical nine stored sensitivity
    cases and their action times, advantages, recommendations and regrets
    reconcile.
23. Stored conservative bounds, stable recommendations, observed alignment
    and aggregate summaries reconcile from lower-level evidence.
24. Optimizer report publication is atomic and run identities are immutable.
25. The exact report file set, row counts, schemas, hashes and zero protected
    rows pass readback verification.
26. Focused unit tests and repository-wide quality checks pass with warnings
    treated as errors.
27. All 68 development dataset and processed partitions pass integrity checks.
28. Every selected historical stop produces one consecutive, symmetric
    `STAY_OUT`/`PIT_NOW` pair and no race contributes more than one pair.
29. Accepted pairs cover all three development seasons and every decision is
    evaluated twice with identical immutable output.
30. The Phase 7 remaining-time MAE is used only as the documented per-action
    robustness margin.
31. The final report passes independent verification with zero protected 2025
    rows.

Phase 8 is complete under this deterministic, development-only contract.
Probabilistic scenario execution remains Phase 9 scope.
