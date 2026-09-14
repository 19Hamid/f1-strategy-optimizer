#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="${repository_root}/compose.postgresql-test.yml"
compose_project="f1-strategy-phase-4-audit"
database_url="postgresql+psycopg://f1_strategy:f1_strategy_test@127.0.0.1:55432/f1_strategy_test"

compose() {
    docker compose \
        --project-name "${compose_project}" \
        --file "${compose_file}" \
        "$@"
}

cleanup() {
    compose down --volumes --remove-orphans
}

trap cleanup EXIT

compose up --detach --wait

cd "${repository_root}/backend"
export F1_STRATEGY_DATABASE_URL="${database_url}"

uv sync --frozen
uv run alembic -c alembic.ini upgrade head
uv run python -m app.db.cli load --run-id phase-4-final-audit
uv run python -m app.db.cli audit
uv run pytest -q -W error tests/integration/db

echo "Phase 4 PostgreSQL audit completed successfully."
