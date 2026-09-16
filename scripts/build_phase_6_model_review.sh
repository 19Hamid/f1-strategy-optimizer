#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root/backend"

arguments=(
  --run-id phase-6-final-audit
)
if [[ "${F1_STRATEGY_REPLACE_MODEL_REVIEW:-0}" == "1" ]]; then
  arguments+=(--replace)
fi

uv run python -m app.ml.visualization "${arguments[@]}"

dashboard="$project_root/artifacts/model_review/format_version=1.0"
dashboard="$dashboard/run_id=phase-6-final-audit/index.html"
printf '\n%s\n' "Opening Phase 6 model review: $dashboard"

if command -v wslview >/dev/null 2>&1; then
  wslview "$dashboard"
elif command -v powershell.exe >/dev/null 2>&1 \
  && command -v wslpath >/dev/null 2>&1; then
  windows_dashboard="$(wslpath -w "$dashboard")"
  powershell.exe -NoProfile -Command "Start-Process '$windows_dashboard'"
else
  printf '%s\n' "Open the dashboard path above in your browser."
fi
