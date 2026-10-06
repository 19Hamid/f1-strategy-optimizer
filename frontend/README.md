# F1 Race Strategy Optimizer frontend

Historical race strategy interface for the existing FastAPI service. The race story has three levels: a plain-language answer, a race comparison and inspectable evidence.

This is a separate development client. The [public Pitwall website](../website/) is a static, precomputed dashboard; it does not serve this React build or the FastAPI backend.

## Develop

Install Python 3.14, uv and Node.js/npm. From the repository root, run `bash scripts/run_dashboard_local.sh` and open `http://localhost:5173`. The helper runs FastAPI and the Vite frontend together. The Vite development server forwards `/api` requests to FastAPI on `127.0.0.1:8000`. The complete verified development data, model and Phase 6–9 reports must be supplied separately for the decision catalog and analyses to work. They are not checked into Git. `npm test` runs UI tests; `npm run build` checks types and generates `dist/`.

Without the API, this React client can display only the recorded 2024 Japanese Grand Prix Hamilton example, with its known point advantage and saved 100-scenario result. It explicitly marks that example as recorded. Other supported decisions and actual job progress require the backend and the verified decision catalog endpoint at `GET /api/v1/analysis/decisions` returning `{ "decisions": [...] }`. The browser waits for that catalog before sending an analysis request. An unreachable API or missing catalog is shown as unavailable rather than as a working multi-driver site.

For a separately hosted API, set `VITE_API_BASE_URL` to its HTTPS origin **before** building the frontend. Set `F1_DASHBOARD_ORIGINS` on the backend to the exact frontend origin (or a comma-separated allowlist for multiple dashboards) and start FastAPI with **one worker**, because job state is currently in memory. The backend also needs the complete verified development datasets and Phase 6–9 artifacts, which are not included in the static preview or the Git repository. For local development, the Vite proxy handles same-origin `/api` requests without CORS configuration.

The historical pit stop's recorded fitted compound is held fixed in both paths. Free tyre selection and pit lap optimization are outside the current V1 API.
