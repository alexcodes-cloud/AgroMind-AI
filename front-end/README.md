# AgroMind AI frontend

React + TypeScript + Tailwind dashboard for the AgroMind FastAPI backend.

## Run locally

From this directory:

```bash
npm install
Copy-Item .env.example .env
npm run dev
```

The development command includes a small supervisor that restarts Vite if it
exits unexpectedly. The dashboard API client also retries temporary backend
startup and gateway failures automatically.

Open `http://localhost:5173`.

Start the backend first from the repository root. For a reliable hackathon presentation, run it with:

```bash
$env:PYTHONPATH = "$PWD\back-end;$PWD"
$env:AGROMIND_DEMO_FALLBACK = "true"
python -m uvicorn backend.api.main:app --app-dir back-end --host 127.0.0.1 --port 8000
```

The dashboard calls `GET /api/v1/farm`, `GET /api/v1/weather`, and the combined
`POST /api/v1/dashboard` endpoint. `VITE_API_BASE_URL` can point to another
backend host. `VITE_DEMO_FALLBACK=true` displays the explicit local-fallback
banner in the UI; it does not control the backend.

## Build

```bash
npm run build
```
