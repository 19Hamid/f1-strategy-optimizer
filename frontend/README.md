# Split / Second

Historical race strategy interface for the existing FastAPI service. The race story has three levels: a plain-language answer, a race comparison and inspectable evidence.

## Develop

From this directory, run `npm ci` then `npm run dev`. The Vite development server forwards `/api` requests to FastAPI on `127.0.0.1:8000`. Run the API separately using the repository's backend setup. `npm run build` checks types and generates `dist/`.

The public static preview displays only the recorded 2024 Japanese Grand Prix Hamilton example, with its known point advantage and saved 100-scenario result. It explicitly marks that example as recorded. Other supported decisions and actual job progress require a hosted backend and a verified decision catalog endpoint at `GET /api/v1/analysis/decisions` returning `{ "decisions": [...] }`. The current backend does not yet provide that list. Configure `VITE_API_BASE_URL` before building if the API uses a different origin; configure the backend to permit the frontend origin.

The historical pit stop's recorded fitted compound is held fixed in both paths. Free tyre selection and pit lap optimization are outside the current V1 API.
