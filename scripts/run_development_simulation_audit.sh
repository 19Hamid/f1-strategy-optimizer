#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root/backend"

uv run python -m app.datasets.cli verify
uv run python -m app.ml.cli verify \
  --run-id phase-6-final-audit
uv run python -m app.simulation.cli audit \
  --run-id phase-7-final-audit \
  --model-artifact-id phase-6-final-audit-lap-time
uv run python -m app.simulation.cli verify \
  --run-id phase-7-final-audit

printf '%s\n' "Phase 7 development simulation audit completed successfully."
