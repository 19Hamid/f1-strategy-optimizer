# Pitwall — F1 Race Strategy Optimizer

I built Pitwall to explore a question that comes up in almost every Formula 1 race: **is it better to pit now or wait one more lap?** The project combines historical race data, lap-time prediction and strategy simulation, with a dashboard that explains the comparison.

**[Live dashboard](https://pitwall-race-decision.vercel.app/)** · **[Dashboard and simulation source](https://github.com/19Hamid/f1-strategy-optimizer/tree/dashboard)** · **[Technical documentation](docs/INDEX.md)**

![Pitwall dashboard showing a historical race and pit-stop comparison](docs/images/pitwall-overview.jpg)

## The idea

A pit stop costs time immediately, but fresh tyres can make the remaining laps faster. Waiting avoids that immediate cost and leaves the driver on older tyres for another lap.

Pitwall estimates the remaining race time for both paths over the same distance. It also shows when the estimated difference is too small to support a clear recommendation.

## Explore the project

| Part | Where it stands |
| --- | --- |
| Public dashboard | Historical race picker and precomputed comparisons for 2022–2024. [Open the demo](https://pitwall-race-decision.vercel.app/). |
| Data and modelling pipeline | Available on `main`: extraction, cleaning, decision-time datasets, PostgreSQL storage, baselines and lap-time modelling. |
| Simulation, optimizer and dashboard source | Available on the [dashboard development branch](https://github.com/19Hamid/f1-strategy-optimizer/tree/dashboard). Its integration into `main` is pending. |

The public website serves saved research outputs. It does not run live race analysis or train a model in the browser. The React client and FastAPI analysis service are separate development components on the dashboard branch.

## What I worked on

- A resumable FastF1 pipeline with Parquet storage, file hashes and session checks.
- Data cleaning, tyre-stint and pit-event reconstruction across 68 development races.
- Start-of-lap features that use information available before each decision.
- PostgreSQL models, migrations and transaction-safe data loading.
- Temporal model evaluation against simple lap-time baselines.
- Strategy simulation, pit-timing comparisons and uncertainty analysis on the development branch.
- A public dashboard with race selection, recorded tyre stints and inspectable results.

## Development results

| Measure | Result |
| --- | ---: |
| Development period | 2022–2024 |
| Development races | 68 |
| Processed lap records | 74,601 |
| Eligible controlled-analysis laps | 57,871 |
| Selected model | XGBoost residual hybrid |
| Comparable-row lap-time MAE | 0.392725 seconds |
| Baseline MAE on the same rows | 0.410049 seconds |
| Relative MAE improvement | 4.22% |

MAE is the average absolute prediction error. These figures measure **single-lap time prediction on development-validation races**, not the accuracy of pit-stop recommendations. Full details are in the [model evaluation report](docs/PHASE_6_COMPLETION.md).

The dashboard lists 1,350 driver/race entries, with comparisons available for 1,023. Its 124 audited decision snapshots are separate from 1,916 additional exploratory estimates. All 124 audited snapshots return no clear advantage after their conservative uncertainty margin. The [dashboard source and export notes](https://github.com/19Hamid/f1-strategy-optimizer/blob/dashboard/website/README.md) explain those counts and assumptions.

The 2025 season is reserved for final temporal evaluation. The [project charter](docs/PROJECT_CHARTER.md#historical-study-period) records the limited early schema inspection and the evaluation boundary.

## Technology

| Area | Tools |
| --- | --- |
| Data | Python, FastF1, pandas, NumPy, PyArrow |
| Machine learning | scikit-learn, XGBoost, CUDA training |
| Database | PostgreSQL, SQLAlchemy, Alembic |
| API | FastAPI, Pydantic, Uvicorn |
| Dashboard branch | JavaScript, React, TypeScript, Vite |
| Development | uv, pytest, Ruff, Docker, Git |

## Run the backend on main

Requirements: **Python 3.14**, [uv](https://docs.astral.sh/uv/) and Git.

```bash
git clone https://github.com/19Hamid/f1-strategy-optimizer.git
cd f1-strategy-optimizer/backend
uv sync --locked
uv run uvicorn app.api.main:app --reload
```

Open the [health endpoint](http://127.0.0.1:8000/health) or [API documentation](http://127.0.0.1:8000/docs). The API on `main` currently exposes the health endpoint; the analysis routes are on the dashboard branch.

Run the backend checks from `backend/`:

```bash
uv run ruff check app tests
uv run pytest -q -W error
```

PostgreSQL integration tests require the isolated test database. Raw data, processed datasets and trained model files are excluded from Git, so a fresh clone does not include the evaluated research bundle.

For extraction, cleaning and model-audit commands, see the [pipeline guide](docs/GETTING_STARTED.md). To serve the static dashboard locally, follow the [dashboard branch quickstart](https://github.com/19Hamid/f1-strategy-optimizer/tree/dashboard#try-it-locally).

## Repository guide

| Path | Contents on main |
| --- | --- |
| `backend/app/pipeline/` | Historical race-data extraction and integrity checks |
| `backend/app/cleaning/` | Lap cleaning, weather alignment, stints and pit events |
| `backend/app/datasets/` | Decision-time features and temporal splits |
| `backend/app/db/` | Database models, loading and reconciliation |
| `backend/app/baselines/` | Reference predictors and evaluation |
| `backend/app/ml/` | Model training, selection and stored-artifact checks |
| `backend/tests/` | Unit and integration tests |
| `docs/` | Methods, contracts and recorded development results |
| `scripts/` | Data, database and model-audit utilities |

## Current limits

- The strategy prototype focuses on dry, green-flag historical decisions.
- Public comparisons assume a 20-second pit loss and use the historically fitted next tyre.
- Future rain, Safety Cars, detailed traffic and automatic tyre selection remain outside the current model.
- Historical data show only the action actually taken. The alternative is simulated, so a lower estimated time is not proof of a better real-world pit call.
- Protected-2025 strategy performance has not been established.

## Author and reuse

[Mouhamad Abdoul Hamid Siby](https://github.com/19Hamid) · BSc Computer Science (Artificial Intelligence), Asia Pacific University.

Original project code is shared for viewing as part of my portfolio. No open-source licence is granted. See [COPYRIGHT.md](COPYRIGHT.md). Third-party data, libraries and assets retain their own terms.

Independent educational project, unaffiliated with Formula 1, the FIA or any team.
