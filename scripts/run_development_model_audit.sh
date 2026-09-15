#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root/backend"

uv run python -m app.datasets.cli verify
uv run python -m app.ml.cli audit \
  --run-id phase-6-final-audit
uv run python -m app.ml.cli verify \
  --run-id phase-6-final-audit

printf '%s\n' "Phase 6 development model audit completed successfully."
