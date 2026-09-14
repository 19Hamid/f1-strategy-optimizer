#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root/backend"

uv run python -m app.datasets.cli verify
uv run python -m app.baselines.cli audit \
  --run-id phase-5-final-audit
uv run python -m app.baselines.cli verify \
  --run-id phase-5-final-audit

printf '%s\n' "Phase 5 development baseline audit completed successfully."
