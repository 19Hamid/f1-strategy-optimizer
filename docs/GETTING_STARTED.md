# Backend and data pipeline

These commands apply to `main`, which contains the data and modelling pipeline through Phase 6. The [dashboard branch](https://github.com/19Hamid/f1-strategy-optimizer/tree/dashboard) contains the later simulation and interface work.

## Environment

Install Python 3.14 and uv. From the repository root:

```bash
cd backend
uv sync --locked
```

Run the following Python commands from `backend/`. Generated data and models remain outside version control.

## Start the API

```bash
uv run uvicorn app.api.main:app --reload
```

- Health: <http://127.0.0.1:8000/health>
- OpenAPI: <http://127.0.0.1:8000/docs>

The main-branch service currently has a health endpoint. Stop it with `Ctrl+C`.

## Run checks

```bash
uv run ruff check app tests
uv run pytest -q -W error
```

The database integration suite needs Docker and its isolated PostgreSQL service. From the repository root:

```bash
bash scripts/run_postgresql_tests.sh
```

## Extract a development race

Discover the 2024 schedule and extract the first round:

```bash
uv run python -m app.pipeline.cli schedule --season 2024
uv run python -m app.pipeline.cli extract --season 2024 --round 1
uv run python -m app.pipeline.cli verify --season 2024 --round 1
uv run python -m app.pipeline.cli catalog
```

The extraction step downloads public timing data through FastF1 and needs network access.

## Clean and build decision rows

```bash
uv run python -m app.cleaning.cli process --season 2024 --round 1
uv run python -m app.cleaning.cli verify --season 2024 --round 1
uv run python -m app.cleaning.cli catalog
```

The full dataset build depends on the complete development inputs. Inspect the plan before building:

```bash
uv run python -m app.datasets.cli plan
uv run python -m app.datasets.cli build
uv run python -m app.datasets.cli verify
```

Development processing and model selection use 2022–2024. The 2025 season remains reserved for final evaluation under the [project charter](PROJECT_CHARTER.md#historical-study-period).

## Development audit scripts

These scripts run from the repository root and require the complete matching inputs and artifacts. They are not fresh-clone demo commands.

| Script | Purpose |
| --- | --- |
| `scripts/run_development_database_audit.sh` | Load and reconcile the development database |
| `scripts/run_development_baseline_audit.sh` | Evaluate and verify baseline artifacts |
| `scripts/run_development_model_audit.sh` | Evaluate and verify the model-selection run |

The model-audit script defaults to CUDA training. Its device setting is controlled by `F1_STRATEGY_XGBOOST_DEVICE`; see the [model contract](MODEL_CONTRACT.md) before changing an audited configuration.

The [archived Phase 6 notes](PHASE_6_DEVELOPMENT_NOTES.md) retain the original dataset counts, commands and checkpoint details.
