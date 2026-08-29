# F1 Race Strategy Optimizer — Project Charter

## Project title

F1 Race Strategy Optimizer: A Public-Data Decision-Support System for
Pit-Stop Strategy

## Problem

During a Formula 1 race, staying out on ageing tyres can increase lap times,
but making a pit stop causes an immediate time loss. Choosing the wrong moment
can therefore increase the driver's total remaining race time.

Historical race data only records the strategy that actually happened. It does
not show what would have happened if the driver had made a different decision.
This project will address that limitation by combining lap-time prediction with
race-strategy simulation.

## Aim

To design, build and evaluate a public-data race-strategy system that recommends
whether a Formula 1 driver should pit now or stay out to minimize expected
remaining race time.

## Primary research question

At a decision lap during a Formula 1 race, can historical race data and
simulation be used to determine whether pitting now or staying out is expected
to produce a lower remaining race time?

## Supporting questions

1. How accurately can tyre degradation and future lap performance be predicted?
2. Which modelling method performs best on previously unseen races?
3. How closely can the simulator reproduce realistic race-time outcomes?
4. How does uncertainty affect the recommended pit decision?
5. How efficiently can thousands of possible race scenarios be simulated?

## Intended user

The system is designed as an educational and analytical decision-support tool
for motorsport analysts, students, sim racers and Formula 1 enthusiasts.

It is not intended to replace the private strategy systems used by professional
Formula 1 teams.

## Version-one decision

A decision point occurs at the start of lap `t`.

The system may only use information available before lap `t` begins, including
data from completed laps up to lap `t - 1` and current race conditions.

The system will compare:

- Pit now: complete lap `t`, enter the pits at the end of that lap and continue
  on a selected new tyre compound.
- Stay out: complete lap `t` without pitting and reconsider the decision at the
  start of lap `t + 1`.

The recommended action will be the one with the lowest expected remaining race
time from the start of lap `t`.

Lap times, sectors, telemetry, incidents or conditions from lap `t` or any
later lap must not be used as inputs for that decision.

## Proposed historical period

The initial dataset will use completed races from 2022 to 2025.

The proposed evaluation design is:

- Development data: races from 2022 to 2024
- Final evaluation data: selected unseen races from 2025

This separation may be adjusted after the data-feasibility investigation.

## Candidate information available at decision time

The system may use:

- Circuit and race
- Current lap and laps remaining
- Driver and team
- Current tyre compound
- Tyre age and stint length
- Recent lap times and sector performance
- Pit-lane time loss
- Track and air temperature
- Tyre compounds already used
- Basic traffic or gap information, if reliable data is available

Only information that would have been available at the decision moment may be
used. Future race information must not be included as a model input.

## System output

For each decision, the system should eventually return:

- Recommended action: pit now or stay out
- Expected remaining time for each option
- Expected time difference between the options
- Suggested tyre compound
- Suggested pit window
- Uncertainty or confidence information
- Important factors influencing the recommendation

## Initial scope

Version one will focus on:

- Publicly available historical Formula 1 data
- Completed races
- Dry-race and normal green-flag conditions
- Tyre degradation and lap-time prediction
- Pit-loss estimation
- Pit-now-versus-stay-out simulation
- Expected remaining race time
- Retrospective evaluation on unseen races

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

These features may be introduced after the controlled simulator works
correctly.

## Success criteria

The project will be considered successful if it:

1. Creates a repeatable historical-data pipeline.
2. Produces documented and cleaned modelling datasets.
3. Predicts lap performance more accurately than simple baseline methods on
   unseen races.
4. Simulates valid race strategies without using future information.
5. Compares pit-now and stay-out decisions using expected remaining race time.
6. Reports uncertainty instead of presenting every recommendation as certain.
7. Runs large scenario batches concurrently and records their execution time.
8. Provides results through a tested REST API and interactive dashboard.
9. Runs reproducibly using documented commands and Docker.
10. Clearly explains its assumptions, limitations and evaluation results.

Exact numerical performance targets will be selected after the data-feasibility
and baseline investigations.

## Constraints and limitations

- The project only has access to public data.
- Public timing and telemetry data may contain missing or inconsistent values.
- Historical races do not provide direct counterfactual outcomes.
- Formula 1 regulations, cars and tyres change between seasons.
- Simulation results depend on assumptions and model quality.
- Recommendations must be described as estimates rather than guaranteed
  optimal decisions.
