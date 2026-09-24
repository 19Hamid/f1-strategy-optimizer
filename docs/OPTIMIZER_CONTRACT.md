# Phase 8 Pit-Decision Optimizer Contract

## Status and identity

- Contract version: `1.0`
- Development seasons: 2022–2024
- Protected temporal evaluation season: 2025
- Current Phase 8 completion: 60%
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
comparison. The result exposes the minimum and maximum pit-now advantage but
does not yet convert that envelope into a stability or confidence label.

Both strategies make one stop, so direct additive pit cost may cancel. It is
still evaluated because the stop occurs on different laps and elapsed-time
changes can affect later model inputs such as weather-observation age. Phase 8
measures the resulting model behaviour rather than assuming either outcome.

## Historical-action boundary

The action a team actually took may be retained for diagnostics, but it is not
an optimal-decision label. Only the outcome of the chosen historical strategy
was observed. The unchosen counterfactual was not.

Phase 8 must therefore evaluate recommendation distributions, stability and
simulator-conditioned outcomes without reporting historical agreement as
decision accuracy.

## Current exclusions

The 60% milestone does not yet provide:

- Monte Carlo or probabilistic uncertainty
- Recommendation-stability thresholds beyond exact point-estimate equality
- Population-level historical decision diagnostics
- Immutable Phase 8 reports or a final development audit
- Wet-weather, safety-car or red-flag decisions
- Traffic interaction or adversarial responses from other cars
- Target-compound optimization or advanced multi-stop search
- Protected 2025 temporal evaluation

Those capabilities must be added explicitly and tested rather than inferred
from the deterministic comparison.

## Acceptance gates through the sensitivity milestone

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
14. Focused unit tests and repository-wide quality checks pass with warnings
    treated as errors.

Later Phase 8 milestones will add sensitivity, uncertainty, development
diagnostics, immutable reporting and the final audit before the optimizer is
declared complete.
