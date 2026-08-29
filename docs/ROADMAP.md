# F1 Race Strategy Optimizer — Project Roadmap

## Project objective

Build a public-data Formula 1 race-strategy decision-support system.

The first version will compare pitting now against staying out and recommend
the option with the lowest expected remaining race time.

## Current progress

- Completed: Phase 0 — Foundation
- Completed: Phase 1 — Research and feasibility
- Next: Phase 2 — Raw-data pipeline
- Overall completion: approximately 11%

## Phase 1 completion evidence

Phase 1 produced:

- A defined project aim and research question
- A precise start-of-lap decision timestamp
- A protected dry green-flag V1 scope
- Successful FastF1 validation using four races from 2022–2025
- Successful detailed telemetry validation
- An initial data dictionary
- Explicit data-leakage prevention rules
- Baseline and model-evaluation plans
- Simulator and concurrency evaluation plans
- A documented research-risk register

## Development roadmap

| Phase | Weight | Main result |
|---|---:|---|
| 0. Foundation | 3% | Development environment, repository, API skeleton and initial tests |
| 1. Research and feasibility | 8% | Define the research problem and confirm the required data exists |
| 2. Raw-data pipeline | 10% | Automatically download, cache and version historical F1 data |
| 3. Data cleaning and exploration | 12% | Clean the data and investigate tyres, laps, pit stops and race conditions |
| 4. Dataset and database design | 9% | Build reproducible datasets and design the PostgreSQL database |
| 5. Baselines and evaluation | 8% | Establish simple baselines and leakage-safe race-level evaluation |
| 6. Tyre and lap-time modelling | 13% | Predict tyre degradation and future lap performance |
| 7. Race-strategy simulator | 14% | Simulate remaining laps and alternative pit strategies |
| 8. Pit-decision optimizer | 9% | Compare pit-now and stay-out strategies using expected remaining race time |
| 9. Concurrent simulation | 5% | Run thousands of uncertain race scenarios efficiently |
| 10. API and dashboard | 6% | Provide strategy analysis through FastAPI and an interactive dashboard |
| 11. Final delivery | 3% | Complete integration, Docker, CI, documentation and portfolio presentation |

## Required development order

1. Collect the data
2. Clean and understand the data
3. Create simple baseline methods
4. Build the tyre and lap-time model
5. Build the race simulator
6. Build the pit-decision optimizer
7. Add concurrent scenario simulation
8. Connect the API and dashboard
9. Complete the final evaluation and presentation

The race simulator must be developed before the pit-decision optimizer because
historical data cannot show the outcome of a strategy that was not actually used.

## Version-one boundaries

The first working version will:

- Use publicly available historical Formula 1 data
- Focus initially on controlled dry-race conditions
- Compare pit now against staying out
- Optimize expected remaining race time
- Begin with simple assumptions before introducing greater uncertainty
- Produce recommendations rather than imitate team decisions

Weather, safety cars, complex traffic effects and advanced multi-stop strategy
logic will be introduced only after the core simulator works correctly.

## Standards followed throughout every phase

- Automated tests for important behaviour
- Ruff formatting and code-quality checks
- Clear documentation of decisions and assumptions
- Reproducible datasets and experiments
- Fixed random seeds where appropriate
- No training-data leakage into evaluation races
- Comparison against simple baseline methods
- Small, working milestones instead of one enormous final integration
- Git branches and meaningful commits for project changes