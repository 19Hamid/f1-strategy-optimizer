#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root/backend"

uv run python -m app.datasets.cli verify
uv run python -m app.ml.cli verify \
  --run-id phase-6-final-audit
uv run python -m app.simulation.cli verify \
  --run-id phase-7-final-audit
uv run python -m app.optimizer.cli verify \
  --run-id phase-8-final-audit
uv run python -m app.concurrent_simulation.cli audit \
  --run-id phase-9-final-audit \
  --model-artifact-id phase-6-final-audit-lap-time \
  --simulation-run-id phase-7-final-audit \
  --optimizer-run-id phase-8-final-audit
uv run python -m app.concurrent_simulation.cli verify \
  --run-id phase-9-final-audit

printf '%s\n' "Phase 9 development concurrent simulation audit completed successfully."

