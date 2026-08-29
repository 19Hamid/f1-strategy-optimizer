# F1 Race Strategy Optimizer

A public-data Formula 1 decision-support system that predicts tyre and lap
performance, simulates alternative strategies and compares pitting now against
staying out.

## Project status

- Phase 0 — Foundation: completed
- Phase 1 — Research and feasibility: completed
- Phase 2 — Raw-data pipeline: completed
- Next phase — Data cleaning and exploration
- Overall progress: approximately 21%

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
- Baseline and evaluation plan
- Research-risk register
- Automatic 2022–2025 race-schedule discovery
- Resumable multi-session FastF1 extraction
- Structural validation for lap, weather and result tables
- Compressed Parquet storage using PyArrow and Zstandard
- Atomic writes with readback validation and recovery
- Versioned metadata and manifests
- SHA-256 file-integrity verification
- Per-run batch records and failure isolation
- Verified raw-data catalog generation
- Command-line pipeline interface
- Optional on-demand lap telemetry extraction
- Early telemetry skipping for verified existing requests
- End-to-end integration audit

## Phase 2 dataset

The completed raw dataset contains:

| Split | Seasons | Races |
|---|---|---:|
| Development | 2022–2024 | 68 |
| Final evaluation | 2025 | 24 |
| Total | 2022–2025 | 92 |

The final Phase 2 audit recorded:

- 92 unique race sessions
- 101,290 lap records
- 14,896 weather records
- 1,838 driver-result records
- 0 invalid session partitions
- Approximately 13 MB of compressed raw Parquet data
- Approximately 731 MB of re-downloadable FastF1 cache data

All 2025 races are stored but remain reserved for final unseen evaluation.
They must not be used for model training or development decisions.

A complete pipeline rerun verified and skipped all 92 sessions in approximately
2.7 seconds without loading FastF1 race data again.

## On-demand telemetry

Detailed telemetry is intentionally optional and requested per driver and lap.

A verified example for Verstappen, lap 39 of the 2024 Bahrain Grand Prix,
produced:

- 703 telemetry samples
- 24 stored columns
- 5,364 metres of recorded distance
- A speed range of 66–301 km/h
- Complete required speed, throttle, brake, RPM, gear, DRS and position fields

This avoids downloading and storing every sensor sample for every driver across
four seasons while preserving detailed telemetry for selected investigations.

## Planned capabilities

- Data cleaning and exploratory analysis
- Reproducible modelling datasets
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
├── backend/          FastAPI, pipeline, modelling and simulation code
├── frontend/         Interactive web dashboard
├── data/             Ignored raw, cached and processed data
├── docs/             Research and technical documentation
├── scripts/          Reproducible project utilities
├── notebooks/        Exploratory analysis
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
- [Phase 2 completion report](docs/PHASE_2_COMPLETION.md)

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

Run these commands from the `backend` directory.

Discover the V1 race schedule:

```bash
uv run python -m app.pipeline.cli schedule
```

Extract all 92 race sessions:

```bash
uv run python -m app.pipeline.cli extract
```

Extract one season:

```bash
uv run python -m app.pipeline.cli extract \
  --season 2024
```

Extract selected rounds:

```bash
uv run python -m app.pipeline.cli extract \
  --season 2024 \
  --round 1 \
  --round 2
```

Verify one stored session:

```bash
uv run python -m app.pipeline.cli verify \
  --season 2024 \
  --round 1
```

Rebuild the verified catalog:

```bash
uv run python -m app.pipeline.cli catalog
```

Extract detailed telemetry for one driver and lap:

```bash
uv run python -m app.pipeline.cli telemetry \
  --season 2024 \
  --round 1 \
  --driver VER \
  --lap 39
```

Use `--force` only when an existing selected partition must be replaced.

## Reproduce the feasibility checks

From the `backend` directory:

```bash
uv run python ../scripts/check_fastf1_data.py
uv run python ../scripts/check_fastf1_coverage.py
uv run python ../scripts/check_fastf1_telemetry.py
```

FastF1 cache files and generated raw datasets are stored under `data/` and are
excluded from Git.

## Current limitations

The first version focuses on completed dry races under normal green-flag
conditions. Wet-weather strategy, safety cars, red flags, advanced traffic,
two-car coordination and professional live-race use are outside the initial
scope.

Historical data cannot directly reveal what would have happened under an
alternative strategy. Counterfactual outcomes will therefore be estimated
through simulation and reported with explicit assumptions and uncertainty.

## Disclaimer

This is an independent educational project using publicly accessible data. It
is unofficial and is not associated with Formula 1, the FIA, any constructor or
any racing team.