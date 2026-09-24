# Development Progress Viewer

## Purpose

The development progress viewer provides a read-only browser report before the
production React dashboard is built in Phase 10. It does not add strategy
decisions or create substitute evaluation evidence.

The viewer reads the existing immutable Phase 6, Phase 7 and Phase 8 artifacts.
Before generating any page it verifies:

- The complete Phase 6 evaluation report
- The fitted Phase 6 model and its exact prediction fingerprint
- The complete Phase 7 simulation report
- The complete Phase 8 optimizer report
- Artifact file sets, hashes, schemas and provenance
- The protected 2025 row count

Generation fails if any required artifact is missing, altered or invalid.

## What it shows

The generated page contains:

- Overall progress calculated from the canonical roadmap weights
- Completed, in-progress and planned phases
- Model candidates, the selected model and its parameters
- Frozen-baseline versus selected-model accuracy
- Target counts, coverage and identity-ablation evidence
- Predicted versus observed tyre-age behaviour
- Model error sliced by event
- Observed-replay counts and lap totals
- Remaining-time error by replay horizon and event
- An interactive predicted-versus-observed replay trajectory selector
- Audited optimizer decision and nine-case sensitivity counts
- Nominal `PIT_NOW` versus `STAY_OUT` model preferences
- Sensitivity-direction consistency, explicitly separated from accuracy
- Final conservative recommendation distribution after the replay-error margin
- Descriptive observed-action alignment
- Event-level optimizer diagnostics

The page is self-contained. It loads no external scripts, styles, fonts or
analytics.

## Run it

From the repository root:

```bash
bash scripts/run_progress_viewer.sh
```

The command regenerates the page from the current verified evidence, starts a
local server and attempts to open:

```text
http://localhost:8765/
```

If the browser does not open automatically, open that address manually. Press
`Ctrl+C` in the terminal to stop the server.

Useful alternatives:

```bash
# Serve without attempting to open a browser
bash scripts/run_progress_viewer.sh --no-browser

# Use a different local port
bash scripts/run_progress_viewer.sh --port 9000

# Generate the file without starting a server
cd backend
uv run python -m app.progress_viewer.cli build
```

The generated file is stored at:

```text
artifacts/progress_viewer/index.html
```

Generated viewer output is excluded from Git because it is reproducible from
the local immutable artifacts.

## Scope boundary

The viewer presents completed evidence only. It does not:

- Retrain the Phase 6 model
- Change any stored report or model artifact
- Claim that historical team choices were optimal
- Treat historical action alignment as optimal-decision accuracy
- Open or evaluate the protected 2025 season
- Replace the production API and React dashboard planned for Phase 10
