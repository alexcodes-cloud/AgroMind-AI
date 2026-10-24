# AgroMind AI

AgroMind is a hackathon demo that combines synthetic farm sensor data, weather
context, and Gemini analysis to produce hydration and fertilization guidance.

## Repository ownership

The code is divided into four working areas. The root `contracts/` directory is
a shared boundary and should be changed only when the team agrees on a contract
change.

```text
front-end/   React + TypeScript + Tailwind dashboard
back-end/    FastAPI routes, configuration, orchestration, and tests
ai/          Gemini provider, prompts, analyzers, adapters, validators, diagnostics
data-set/    Synthetic farm generator, farm fixture, and offline evaluation labels
contracts/   Shared JSON Schemas and example weather snapshot
```

The old `agromind-*` directories are no longer used. Deployment configuration
is kept for later; this refactor does not deploy anything.

## Install

From the repository root:

```powershell
python -m pip install -r requirements-dev.txt
```

Create a local environment file only when needed:

```powershell
Copy-Item .env.example .env
```

Put the real `GEMINI_API_KEY` only in the uncommitted `.env` file. Never commit
it or print it. Environment variables override `.env` values.

## Run the backend

From the repository root:

```powershell
$env:PYTHONPATH = "$PWD\back-end;$PWD"
python -m uvicorn backend.api.main:app --app-dir back-end --reload
```

Useful endpoints:

```text
GET  /health
GET  /api/v1/farm
GET  /api/v1/weather
POST /api/v1/analysis/zones
POST /api/v1/analysis/plan
POST /api/v1/dashboard
```

The farm and weather endpoints are fixture-backed. AI endpoints use Gemini and
validate every model response against the shared schemas. For the compact
low-quota demo, use `AGROMIND_ANALYSIS_ZONE_LIMIT=4` and
`AGROMIND_ANALYSIS_RECORD_LIMIT=2`. `AGROMIND_DEMO_MODE=true` enables a small
compatibility adapter for common Gemma output variations; it does not fabricate
evidence. `AGROMIND_DEMO_FALLBACK=true` is an explicit local fallback for a
presentation when Gemini is unavailable, and is clearly marked as fallback.

## Run the frontend

In a second terminal:

```powershell
Set-Location .\front-end
npm install
Copy-Item .env.example .env -ErrorAction SilentlyContinue
npm run dev
```

Open `http://localhost:5173`. The frontend uses `VITE_API_BASE_URL` from its
`.env` file and defaults to the local API.

## Test

Backend tests are offline and do not call Gemini:

```powershell
Set-Location C:\Users\Oblivion\Downloads\AgroSupervisor-AI
$env:PYTHONPATH = "$PWD\back-end;$PWD"
python -m unittest discover -s back-end/tests -v
```

Frontend production build:

```powershell
Set-Location .\front-end
npm run build
```

## AI diagnostics

These scripts are owned by the AI section and never print the API key or full
prompts:

```powershell
Set-Location C:\Users\Oblivion\Downloads\AgroSupervisor-AI
python ai/scripts/diagnose_gemini_stage1.py
python ai/scripts/diagnose_gemini_stage2.py
python ai/scripts/list_gemma_models.py
```

## Dataset and evaluation labels

Regenerate the deterministic compact fixture with:

```powershell
python data-set/generate_dataset.py --seed 42 --zones 12
```

`data-set/evaluation_labels.json` is offline-only evaluation data. It is not
loaded by the batch builder, prompts, API endpoints, or either AI stage.

## Team boundaries

- Frontend consumes `contracts/dashboard-response.schema.json` and calls API endpoints.
- Backend owns HTTP, configuration, orchestration, and integration tests.
- AI owns provider calls, prompts, response normalization, and semantic validation.
- Dataset owns synthetic farm/weather inputs and keeps evaluation labels separate.
- Contracts are shared and must remain compatible with all four areas.

Recommendations are informational only; the project does not automatically
operate irrigation or fertilization equipment.
