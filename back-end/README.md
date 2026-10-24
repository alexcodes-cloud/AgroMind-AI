# Backend

The backend owns the FastAPI application, configuration, HTTP orchestration,
weather adapter, batch builder, and automated tests. AI provider and analysis
code lives in the repository-level `ai/` directory so it can be developed
without coupling it to HTTP routes.

Run from the repository root:

```powershell
$env:PYTHONPATH = "$PWD\back-end;$PWD"
python -m uvicorn backend.api.main:app --app-dir back-end --reload
```

Install dependencies with `python -m pip install -r requirements-dev.txt`.
Run tests with `python -m unittest discover -s back-end/tests -v` after setting
the same `PYTHONPATH`.

The backend reads the shared fixtures from `data-set/` and schemas from
`contracts/`. It never loads `data-set/evaluation_labels.json` into an API or
AI request.
