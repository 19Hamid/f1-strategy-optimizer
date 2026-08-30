# F1 Race Strategy Optimizer — Project Roadmap

## Project objective

Build a public-data Formula 1 race-strategy decision-support system.

The first version will compare pitting now against staying out and recommend
the option with the lowest expected remaining race time.

## Current progress

- Completed: Phase 0 — Foundation
- Completed: Phase 1 — Research and feasibility
- Completed: Phase 2 — Raw-data pipeline
- Completed: Phase 3 — Data cleaning and exploration
- Next: Phase 4 — Dataset and database design
- Overall completion: approximately 33%

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
- Successful FastF1 validation using 2022–2025 races
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
- Atomic writes and readback validation
- Versioned metadata and SHA-256 manifests
- Session-level integrity verification
- Resumable extraction and early skipping
- Resilient batch execution
- A verified 92-session catalog
- Optional per-lap telemetry
- A command-line interface
- 134 passing tests at Phase 2 completion
- A successful 92-race integrity audit

### Phase 3 — Data cleaning and exploration

Phase 3 produced:

- Frozen cleaning-rule version `1.0`
- Processed-data contract version `1.0`
- Development-exploration version `1.0`
- Deterministic profiling of 68 development races
- Preservation of all 74,601 development lap rows
- 57,871 eligible controlled-analysis laps
- 16,730 excluded laps with documented reasons
- Backward-only alignment of 11,115 weather observations
- Zero future weather matches
- 3,888 reconstructed tyre stints
- 3,845 complete stints
- 2,693 reconstructed pit events
- Complete accounting for 5,232 pit markers
- 1,465 pit-duration candidates
- Atomic versioned processed storage
- Processed integrity verification
- Resumable batch processing
- A verified 68-session processed catalog
- A processed-data command-line interface
- Permanent development exploration
- A frozen `FLAG_ONLY` statistical-outlier policy
- 291 passing automated tests
- A real 68-race processed audit
- A complete 68-session resume test
- No processing or exploration of the 2025 holdout

## Development roadmap

| Phase | Weight | Status | Main result |
|---|---:|---|---|
| 0. Foundation | 3% | Completed | Development environment, repository, API skeleton and initial tests |
| 1. Research and feasibility | 8% | Completed | Define the research problem and confirm required data exists |
| 2. Raw-data pipeline | 10% | Completed | Download, validate, cache and version historical F1 data |
| 3. Data cleaning and exploration | 12% | Completed | Produce verified processed data and document development patterns |
| 4. Dataset and database design | 9% | Next | Build leakage-safe datasets and design the PostgreSQL database |
| 5. Baselines and evaluation | 8% | Planned | Establish simple baselines and race-level evaluation |
| 6. Tyre and lap-time modelling | 13% | Planned | Predict tyre degradation and future lap performance |
| 7. Race-strategy simulator | 14% | Planned | Simulate remaining laps and alternative pit strategies |
| 8. Pit-decision optimizer | 9% | Planned | Compare pit-now and stay-out expected remaining race time |
| 9. Concurrent simulation | 5% | Planned | Run uncertain race scenarios efficiently |
| 10. API and dashboard | 6% | Planned | Expose strategy analysis through FastAPI and React |
| 11. Final delivery | 3% | Planned | Complete integration, Docker, CI, documentation and presentation |

## Phase 4 objectives

Phase 4 will:

1. Define one canonical decision-time row.
2. Separate targets, identifiers, metadata and usable inputs.
3. Prevent future-lap and post-decision leakage.
4. Create reproducible development datasets.
5. Define race-level development and validation splits.
6. Design PostgreSQL entities and relationships.
7. Add database constraints and indexes.
8. Version dataset-building rules.
9. Validate table and feature contracts automatically.
10. Preserve the protected 2025 evaluation boundary.

## Required development order

1. Collect and verify raw data
2. Clean and understand development data
3. Design reproducible datasets and database structures
4. Create simple baseline methods
5. Build tyre and lap-time models
6. Build the race simulator
7. Build the pit-decision optimizer
8. Add concurrent scenario simulation
9. Connect the API and dashboard
10. Complete final evaluation and presentation

The simulator must precede the optimizer because historical data cannot show
the outcome of a strategy that was not actually used.

## Version-one boundaries

The first working version will:

- Use publicly available historical Formula 1 data
- Use 2022–2024 for development
- Reserve 2025 for final unseen evaluation
- Focus initially on controlled dry-race conditions
- Compare pit now against staying out
- Optimize expected remaining race time
- Begin with simple assumptions
- Produce recommendations rather than imitate team decisions

Weather transitions, safety cars, complex traffic and advanced multi-stop logic
will be introduced only after the controlled simulator works correctly.

Detailed telemetry remains optional and on demand unless later experiments
demonstrate measurable benefit from broader collection.

## Standards followed throughout every phase

- Automated tests for important behaviour
- Ruff code-quality checks
- Warnings treated as errors
- Clear documentation of assumptions
- Reproducible datasets and experiments
- Versioned data contracts
- Atomic writes for generated artifacts
- Integrity checks for stored datasets
- Fixed random seeds where appropriate
- No evaluation-data leakage
- Comparison against simple baselines
- Race-level splits where required
- Small working milestones
- Git branches, pull requests and meaningful commits