# F1 Race Strategy Optimizer

An AI-powered Formula 1 strategy system that analyses historical race data,
predicts tyre degradation, compares pit-now-versus-stay-out decisions and
simulates alternative race strategies.

## Current Status

Phase 0: Development environment and backend foundation.

The project currently includes:

- FastAPI backend
- Health-check endpoint
- Interactive OpenAPI documentation
- Automated API test
- Ruff code-quality checks
- Reproducible Python environment managed with uv

## Planned Capabilities

- Historical Formula 1 data pipeline
- PostgreSQL database
- Data cleaning and exploratory analysis
- Tyre-degradation prediction
- Pit-now-versus-stay-out decision model
- Race-strategy simulation
- Concurrent Monte Carlo simulation
- REST API
- Interactive React dashboard
- Model comparison and evaluation

## Technology Stack

- Python
- Pandas, NumPy and scikit-learn
- FastAPI
- PostgreSQL
- React and TypeScript
- Docker
- pytest
- Git and GitHub Actions

## Run the Backend

```bash
cd backend
uv sync
uv run uvicorn app.api.main:app --reload