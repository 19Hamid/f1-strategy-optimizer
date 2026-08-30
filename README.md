# F1 Race Strategy Optimizer

A public-data Formula 1 decision-support system that predicts tyre and lap
performance, simulates alternative strategies and compares pitting now against
staying out.

## Project status

- Phase 0 — Foundation: completed
- Phase 1 — Research and feasibility: completed
- Phase 2 — Raw-data pipeline: completed
- Phase 3 — Data cleaning and exploration: completed
- Next phase — Dataset and database design
- Overall progress: approximately 33%

## Primary objective

At the start of lap `t`, the system will compare:

- Pitting at the end of lap `t`
- Staying out and reconsidering at the start of lap `t + 1`

The recommended action will minimize expected remaining race time.

Only information available before lap `t` begins may be used.

## Completed work

The project currently includes:

- WSL and Docker development environment
- Reproducible Python environment managed with uv
- FastAPI backend foundation
- Health-check endpoint and OpenAPI documentation
- pytest and Ruff quality checks
- Documented research question and V1 boundaries
- FastF1 data-feasibility and multi-season coverage validation
- Explicit data-leakage prevention rules
- Automatic 2022–2025 race-schedule discovery
- Resumable multi-session FastF1 extraction
- Structural validation for lap, weather and result tables
- Compressed Parquet storage using PyArrow and Zstandard
- Atomic writes with readback validation and recovery
- Versioned metadata and SHA-256 manifests
- Verified raw and processed catalogs
- Optional on-demand lap telemetry extraction
- Deterministic development-data profiling
- Lap-quality flags and documented exclusions
- Backward-only weather alignment
- Rainfall-aware lap eligibility
- Tyre-stint reconstruction
- Pit-event reconstruction and marker accounting
- Versioned processed-data partitions
- Processed-session integrity verification
- Resumable 68-race development processing
- Permanent development exploration
- Frozen statistical-outlier policy
- Command-line interfaces for raw and processed pipelines

## Phase 2 raw dataset

| Split | Seasons | Races |
|---|---|---:|
| Development | 2022–2024 | 68 |
| Final evaluation | 2025 | 24 |
| Total | 2022–2025 | 92 |

The raw audit recorded:

- 92 unique race sessions
- 101,290 lap records
- 14,896 weather records
- 1,838 driver-result records
- 0 invalid session partitions
- Approximately 13 MB of compressed raw data
- Approximately 731 MB of re-downloadable FastF1 cache data

All 2025 races remain reserved for final unseen evaluation.

## Phase 3 processed dataset

Phase 3 processed only the 68 development races from 2022 to 2024.

| Measure | Value |
|---|---:|
| Processed lap rows | 74,601 |
| Eligible laps | 57,871 |
| Excluded laps | 16,730 |
| Eligibility rate | 77.57% |
| Reconstructed stints | 3,888 |
| Complete stints | 3,845 |
| Reconstructed pit events | 2,693 |
| Complete pit events | 2,539 |
| Pit-duration candidates | 1,465 |

Every raw development lap remains represented. Excluded laps are retained with
documented reasons.

The final audit verified all 68 processed partitions and found zero invalid
sessions.

A complete resume run verified and skipped all 68 sessions in approximately
3.0 seconds.

## Development exploration

The permanent exploration module recorded:

- 3,537 reconstructed dry-compound stints
- 541 contextual potential lap-time outliers
- 526 slow-direction and 15 fast-direction outliers
- 193 outliers belonging to shared lap clusters
- Materially different pit-duration distributions by circuit

The frozen statistical-outlier policy is `FLAG_ONLY`.

Statistical extremes remain eligible unless an independent cleaning reason
applies.

No 2025 partition was processed or explored.

## On-demand telemetry

Detailed telemetry remains optional and requested per driver and lap.

A verified example for Verstappen, lap 39 of the 2024 Bahrain Grand Prix,
produced:

- 703 telemetry samples
- 24 stored columns
- 5,364 metres of recorded distance
- A speed range of 66–301 km/h
- Complete required speed, throttle, brake, RPM, gear, DRS and position fields

This avoids storing every sensor sample for every driver while preserving
detailed telemetry for selected investigations.

## Planned capabilities

- Leakage-safe modelling datasets
- PostgreSQL database
- Baseline lap-time and pit-decision methods
- Tyre-degradation and lap-time prediction
- Race-strategy simulator
- Pit-now-versus-stay-out optimizer
- Concurrent Monte Carlo simulation
- REST API
- Interactive React dashboard
- Model comparison and final unseen-race evaluation

## Technology stack

- Python
- pandas, NumPy, PyArrow and scikit-learn
- FastF1
- FastAPI
- PostgreSQL
- React and TypeScript
- Docker
- pytest and Ruff
- Git and GitHub Actions

## Repository structure

```text
f1-strategy-optimizer/
├── backend/          FastAPI, pipeline, cleaning, modelling and simulation
├── frontend/         Interactive web dashboard
├── data/             Ignored raw, cached and processed data
├── docs/             Research and technical documentation
├── scripts/          Reproducible project utilities
├── notebooks/        Optional exploratory notebooks
└── artifacts/        Trained model artifacts
```

## Documentation

- [Roadmap](docs/ROADMAP.md)
- [Project charter](docs/PROJECT_CHARTER.md)
- [Data feasibility](docs/DATA_FEASIBILITY.md)
- [Initial data dictionary](docs/DATA_DICTIONARY.md)
- [Evaluation plan](docs/EVALUATION_PLAN.md)
- [Research risk register](docs/RISK_REGISTER.md)
- [Raw-data contract](docs/RAW_DATA_CONTRACT.md)
- [Telemetry contract](docs/TELEMETRY_CONTRACT.md)
- [Cleaning rules](docs/CLEANING_RULES.md)
- [Processed-data contract](docs/PROCESSED_DATA_CONTRACT.md)
- [Development EDA](docs/DEVELOPMENT_EDA.md)
- [Phase 2 completion report](docs/PHASE_2_COMPLETION.md)
- [Phase 3 completion report](docs/PHASE_3_COMPLETION.md)

## Set up the backend

From the repository root:

```bash
cd backend
uv sync --locked
```

## Run the backend API

From the `backend` directory:

```bash
uv run uvicorn app.api.main:app --reload
```

Open:

- API health check: <http://127.0.0.1:8000/health>
- Interactive API documentation: <http://127.0.0.1:8000/docs>

Stop the server with `Ctrl + C`.

## Run automated checks

From the `backend` directory:

```bash
uv run ruff check app tests
uv run pytest -q -W error
```

## Use the raw-data pipeline

Run commands from the `backend` directory.

Discover the complete race schedule:

```bash
uv run python -m app.pipeline.cli schedule
```

Extract all 92 raw race sessions:

```bash
uv run python -m app.pipeline.cli extract
```

Extract selected rounds:

```bash
uv run python -m app.pipeline.cli extract \
  --season 2024 \
  --round 1 \
  --round 2
```

Verify a raw session:

```bash
uv run python -m app.pipeline.cli verify \
  --season 2024 \
  --round 1
```

Rebuild the raw catalog:

```bash
uv run python -m app.pipeline.cli catalog
```

Extract selected telemetry:

```bash
uv run python -m app.pipeline.cli telemetry \
  --season 2024 \
  --round 1 \
  --driver VER \
  --lap 39
```

## Use the processed-data pipeline

Run commands from the `backend` directory.

Show the protected development plan:

```bash
uv run python -m app.cleaning.cli plan
```

Process all 68 development races:

```bash
uv run python -m app.cleaning.cli process
```

Process selected development rounds:

```bash
uv run python -m app.cleaning.cli process \
  --season 2024 \
  --round 1 \
  --round 2
```

Verify a processed partition:

```bash
uv run python -m app.cleaning.cli verify \
  --season 2024 \
  --round 1
```

Rebuild the processed catalog:

```bash
uv run python -m app.cleaning.cli catalog
```

The processed CLI rejects the protected 2025 season.

Use `--force` only when an existing selected partition must be replaced.

## Reproduce feasibility checks

From the `backend` directory:

```bash
uv run python ../scripts/check_fastf1_data.py
uv run python ../scripts/check_fastf1_coverage.py
uv run python ../scripts/check_fastf1_telemetry.py
```

Generated datasets and FastF1 cache files are stored beneath `data/` and
excluded from Git.

## Current limitations

Version one focuses on completed dry races under normal green-flag conditions.

Wet-weather strategy, safety cars, red flags, advanced traffic, two-car
coordination and professional live-race use remain outside the initial scope.

Historical data cannot reveal exactly what would have happened under an
alternative strategy. Counterfactual outcomes will therefore be estimated
through simulation and reported with explicit assumptions and uncertainty.

Observed pit-lane duration is not yet equivalent to final net pit loss.

## Disclaimer

This is an independent educational project using publicly accessible data. It
is unofficial and is not associated with Formula 1, the FIA, any constructor or
any racing team.