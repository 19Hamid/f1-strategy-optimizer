# F1 Race Strategy Optimizer — Project Charter

## Project title

F1 Race Strategy Optimizer: A Public-Data Decision-Support System for
Pit-Stop Strategy

## Problem

During a Formula 1 race, staying out on ageing tyres can increase lap times,
but making a pit stop causes an immediate time loss. Choosing the wrong moment
can therefore increase the driver's total remaining race time.

Historical race data records only the strategy that actually happened. It does
not show what would have happened if the driver had made a different decision.
This project addresses that limitation by combining lap-time prediction with
race-strategy simulation.

## Aim

To design, build and evaluate a public-data race-strategy system that recommends
whether a Formula 1 driver should pit now or stay out to minimize expected
remaining race time.

## Primary research question

At a decision lap during a Formula 1 race, can historical race data and
simulation determine whether pitting now or staying out is expected to produce
a lower remaining race time?

## Supporting questions

1. How accurately can tyre degradation and future lap performance be predicted?
2. Which modelling method performs best on temporally held-out races?
3. How closely can the simulator reproduce realistic race-time outcomes?
4. How does uncertainty affect the recommended pit decision?
5. How efficiently can thousands of possible race scenarios be simulated?

## Intended user

The system is an educational and analytical decision-support tool for
motorsport analysts, students, sim racers and Formula 1 enthusiasts.

It is not intended to replace the private strategy systems used by professional
Formula 1 teams.

## Version-one decision

A decision point occurs at the start of lap `t`.

The system may use only information available before lap `t` begins, including
data from completed laps up to lap `t - 1` and current race conditions already
known at the decision timestamp.

The system will compare:

- Pit now: complete lap `t`, enter the pits at the end of that lap and continue
  on a selected new tyre compound.
- Stay out: complete lap `t` without pitting and reconsider the decision at the
  start of lap `t + 1`.

The recommended action will be the one with the lowest expected remaining race
time from the start of lap `t`.

Lap times, sectors, telemetry, incidents or conditions generated during lap
`t` or any later lap must not be used as inputs for that decision.

## Historical study period

The project uses completed race sessions from 2022 to 2025.

The frozen temporal separation is:

- Development, exploration and model selection: all races from 2022 to 2024
- Protected final temporal evaluation: all races from 2025

One 2025 session, the Japanese Grand Prix, received a limited schema and
availability inspection during Phase 1. That feasibility check examined
structural information such as field availability, record counts, missingness,
pit markers and available compounds.

The Phase 1 inspection did not determine cleaning rules, feature definitions,
statistical thresholds, model selection, hyperparameters or simulator
parameters.

After the feasibility check:

- Phase 2 collected and integrity-checked the 2025 raw partitions.
- Phase 3 did not process or explore any 2025 partition.
- Phase 4 development interfaces must reject 2025.
- Later modelling decisions must remain frozen before final 2025 evaluation.

The 2025 season is therefore a protected temporal evaluation holdout, with the
limited Phase 1 schema inspection disclosed. It must not be described as data
that was literally never viewed for any purpose.

## Candidate information available at decision time

The system may use:

- Circuit and race identity
- Current lap and scheduled laps remaining
- Driver and team
- Current tyre compound
- Tyre age and stint length at the start of the decision lap
- Lap and sector performance from completed earlier laps
- Historical circuit-specific pit-lane duration information
- Explicitly documented pit-loss assumptions
- Weather observations available before the decision
- Tyre compounds already used
- Basic traffic or gap information when it can be reconstructed reliably

Only information available at the decision moment may be used.

Values attached to lap `t` in a historical source table are not automatically
safe merely because they appear on the same row. Phase 4 must reconstruct each
start-of-lap feature from auditable past information.

## System output

For each decision, the system should eventually return:

- Recommended action: pit now or stay out
- Expected remaining time for each option
- Expected time difference between the options
- Suggested tyre compound
- Suggested pit window
- Uncertainty or confidence information
- Important factors influencing the recommendation

Historical agreement with a team's actual decision may be reported as a
diagnostic. It must not be presented as proof that the recommendation was
optimal.

## Initial scope

Version one focuses on:

- Publicly available historical Formula 1 data
- Completed races
- Dry and normal green-flag conditions
- Tyre degradation and lap-time prediction
- Circuit-aware pit-lane duration analysis
- Explicitly modelled pit-loss assumptions
- Pit-now-versus-stay-out simulation
- Expected remaining race time
- Retrospective evaluation on temporally held-out races

## Initially excluded

The first working version will not attempt to fully model:

- Live use during an active Formula 1 race
- Private team telemetry
- Wet-weather tyre strategy
- Safety cars, virtual safety cars and red flags
- Mechanical failures or crash risk
- Detailed wheel-to-wheel overtaking
- Team orders and coordinated two-car strategy
- Complete strategic game theory between every driver
- Advanced multi-stop optimisation

These capabilities may be introduced after the controlled simulator works
correctly.

## Success criteria

The project will be considered successful if it:

1. Creates a repeatable historical-data pipeline.
2. Produces documented, cleaned and versioned modelling datasets.
3. Predicts lap performance more accurately than simple baseline methods on
   temporally held-out races.
4. Simulates valid race strategies without using future information.
5. Compares pit-now and stay-out decisions using expected remaining race time.
6. Reports uncertainty instead of presenting every recommendation as certain.
7. Runs large scenario batches concurrently and records their execution time.
8. Provides results through a tested REST API and interactive dashboard.
9. Runs reproducibly using documented commands and Docker.
10. Clearly explains its assumptions, limitations and evaluation results.

Exact numerical performance targets will be selected through the predefined
baseline and evaluation process, without using the protected 2025 holdout to
revise them.

## Constraints and limitations

- The project has access only to public data.
- Public timing and telemetry data may contain missing or inconsistent values.
- Historical races do not provide direct counterfactual outcomes.
- Observed pit-lane duration is not automatically net race-time loss.
- Formula 1 regulations, cars and tyres change between seasons.
- Simulation results depend on assumptions and model quality.
- Recommendations must be described as estimates rather than guaranteed
  optimal decisions.
- The limited Phase 1 inspection of one 2025 session must be disclosed in final
  evaluation reporting.
