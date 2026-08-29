# F1 Race Strategy Optimizer

A public-data Formula 1 decision-support system that predicts tyre and lap
performance, simulates alternative strategies and compares pitting now against
staying out.

## Project status

- Phase 0 — Foundation: completed
- Phase 1 — Research and feasibility: completed
- Next phase — Raw-data pipeline
- Overall progress: approximately 11%

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
- pytest and Ruff checks
- Documented research question and V1 boundaries
- FastF1 lap, tyre, pit-stop and weather validation
- Cross-season validation using selected 2022–2025 races
- Detailed telemetry validation
- Initial data dictionary and leakage-prevention rules
- Baseline and evaluation plan
- Research-risk register

## Data-feasibility results

Four sample races produced:

- 4,284 lap records
- 149 recorded pit entries
- 14 missing lap times
- Consistent required fields and data types
- Hard, Medium and Soft compound coverage

One representative lap produced 703 complete telemetry samples containing
speed, throttle, brake, RPM, gear, DRS, distance and position data.

## Planned capabilities

- Historical Formula 1 data pipeline
- PostgreSQL database
- Data cleaning and exploratory analysis
- Tyre-degradation and lap-time prediction
- Race-strategy simulator
- Pit-now-versus-stay-out optimizer
- Concurrent Monte Carlo simulation
- REST API
- Interactive React dashboard
- Model comparison and evaluation

## Technology stack

- Python
- pandas, NumPy and scikit-learn
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
├── backend/          FastAPI, data, modelling and simulation code
├── frontend/         Interactive web dashboard
├── data/             Raw and processed data locations
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

## Run the backend

From the repository root:

```bash
cd backend
uv sync
uv run uvicorn app.api.main:app --reload
```

Open:

- API health check: <http://127.0.0.1:8000/health>
- Interactive API documentation: <http://127.0.0.1:8000/docs>

Stop the server with `Ctrl + C`.

## Run the automated checks

From the `backend` directory:

```bash
uv run ruff check .
uv run pytest -q
```

## Reproduce the feasibility checks

From the `backend` directory:

```bash
uv run python ../scripts/check_fastf1_data.py
uv run python ../scripts/check_fastf1_coverage.py
uv run python ../scripts/check_fastf1_telemetry.py
```

FastF1 cache files are stored under `data/cache/` and are excluded from Git.

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