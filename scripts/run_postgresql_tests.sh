#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="${repository_root}/compose.postgresql-test.yml"
compose_project="f1-strategy-postgresql-test"

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
export F1_STRATEGY_TEST_DATABASE_URL="postgresql+psycopg://f1_strategy:f1_strategy_test@127.0.0.1:55432/f1_strategy_test"

uv sync --frozen
uv run pytest -q -W error tests/integration/db

