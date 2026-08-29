# F1 Race Strategy Optimizer — Project Roadmap

## Project objective

Build a public-data Formula 1 race-strategy decision-support system.

The first version will compare pitting now against staying out and recommend
the option with the lowest expected remaining race time.

## Current progress

- Completed: Phase 0 — Foundation
- Completed: Phase 1 — Research and feasibility
- Completed: Phase 2 — Raw-data pipeline
- Next: Phase 3 — Data cleaning and exploration
- Overall completion: approximately 21%

## Completed-phase evidence

### Phase 0 — Foundation

Phase 0 produced:

- A WSL-based development environment
- Docker and Git configuration
- A reproducible uv-managed Python backend
- A FastAPI application foundation
- A health-check endpoint
- Initial Ruff and pytest checks
- A structured GitHub repository

### Phase 1 — Research and feasibility

Phase 1 produced:

- A defined project aim and research question
- A precise start-of-lap decision timestamp
- A protected dry green-flag V1 scope
- Successful FastF1 validation using races from 2022–2025
- Successful detailed telemetry validation
- An initial data dictionary
- Explicit data-leakage prevention rules
- Baseline and model-evaluation plans
- Simulator and concurrency evaluation plans
- A documented research-risk register

### Phase 2 — Raw-data pipeline

Phase 2 produced:

- Automatic 2022–2025 race-schedule discovery
- A complete 92-race raw dataset
- 68 development races from 2022–2024
- 24 reserved evaluation races from 2025
- 101,290 lap records
- 14,896 weather records
- 1,838 driver-result records
- Compressed Parquet storage
- Atomic writes and Parquet readback validation
- Versioned metadata and SHA-256 manifests
- Session-level integrity verification
- Resumable extraction and early skipping
- Resilient batch execution with run records
- A verified 92-session catalog
- Optional per-lap telemetry extraction and storage
- A command-line interface
- 134 passing automated tests
- A successful end-to-end pipeline audit
- A full rerun that skipped all 92 verified sessions

## Development roadmap

| Phase | Weight | Status | Main result |
|---|---:|---|---|
| 0. Foundation | 3% | Completed | Development environment, repository, API skeleton and initial tests |
| 1. Research and feasibility | 8% | Completed | Define the research problem and confirm the required data exists |
| 2. Raw-data pipeline | 10% | Completed | Automatically download, validate, cache and version historical F1 data |
| 3. Data cleaning and exploration | 12% | Next | Clean the data and investigate tyres, laps, pit stops and race conditions |
| 4. Dataset and database design | 9% | Planned | Build reproducible datasets and design the PostgreSQL database |
| 5. Baselines and evaluation | 8% | Planned | Establish simple baselines and leakage-safe race-level evaluation |
| 6. Tyre and lap-time modelling | 13% | Planned | Predict tyre degradation and future lap performance |
| 7. Race-strategy simulator | 14% | Planned | Simulate remaining laps and alternative pit strategies |
| 8. Pit-decision optimizer | 9% | Planned | Compare pit-now and stay-out strategies using expected remaining race time |
| 9. Concurrent simulation | 5% | Planned | Run thousands of uncertain race scenarios efficiently |
| 10. API and dashboard | 6% | Planned | Provide strategy analysis through FastAPI and an interactive dashboard |
| 11. Final delivery | 3% | Planned | Complete integration, Docker, CI, documentation and portfolio presentation |

## Required development order

1. Collect and verify the raw data
2. Clean and understand the data
3. Design reproducible datasets and database structures
4. Create simple baseline methods
5. Build the tyre and lap-time model
6. Build the race simulator
7. Build the pit-decision optimizer
8. Add concurrent scenario simulation
9. Connect the API and dashboard
10. Complete the final evaluation and presentation

The race simulator must be developed before the pit-decision optimizer because
historical data cannot show the outcome of a strategy that was not actually
used.

## Version-one boundaries

The first working version will:

- Use publicly available historical Formula 1 data
- Use 2022–2024 for development
- Reserve 2025 for final unseen evaluation
- Focus initially on controlled dry-race conditions
- Compare pit now against staying out
- Optimize expected remaining race time
- Begin with simple assumptions before introducing greater uncertainty
- Produce recommendations rather than imitate team decisions

Weather, safety cars, complex traffic effects and advanced multi-stop strategy
logic will be introduced only after the core simulator works correctly.

Detailed telemetry will remain optional and on demand unless a later
experiment demonstrates that broader telemetry collection provides measurable
value.

## Standards followed throughout every phase

- Automated tests for important behaviour
- Ruff formatting and code-quality checks
- Clear documentation of decisions and assumptions
- Reproducible datasets and experiments
- Versioned data contracts
- Atomic writes for important generated artifacts
- Integrity checks for stored datasets
- Fixed random seeds where appropriate
- No training-data leakage into evaluation races
- Comparison against simple baseline methods
- Small, working milestones instead of one enormous final integration
- Git branches, pull requests and meaningful commits