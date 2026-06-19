# Running the full ClassifyOS system (website + API)

How to run the whole stack locally and use it in the browser. ClassifyOS is three layers —
**React frontend → FastAPI backend → Python ML engine** — and to see the website you run the
**two servers** below at the same time, each in its own terminal.

| # | Server | Runs from | Port | What it is |
|---|--------|-----------|------|------------|
| 1 | Backend API (FastAPI) | `backend/` | 8000 | The ML engine exposed over HTTP |
| 2 | Frontend (Vite dev server) | `frontend/` | 5173 | The website you open in the browser |

The frontend proxies every `/api` request to the backend on :8000 (see `frontend/vite.config.ts`).
So if the backend isn't running, the page still loads but the health banner turns **red
("API offline")** and no runs work.

> Just the engine, no website? See `RUNBOOK.md` (the CLI). Just the API? See `API_RUNBOOK.md`.

---

## Terminal 1 — start the backend API

```powershell
cd C:\Projects\classifyos\backend
.\.venv\Scripts\Activate.ps1
uvicorn api.main:app --reload --port 8000
```

Leave it running. On startup it prints the resolved `DATA_DIR` / `OUTPUT_DIR` and
`Uvicorn running on http://127.0.0.1:8000`. (Optional: open http://localhost:8000/docs for the
interactive API docs.)

> **First time only** (or if `backend/.venv` doesn't exist yet):
> ```powershell
> cd C:\Projects\classifyos\backend
> python -m venv .venv
> .\.venv\Scripts\Activate.ps1
> pip install -r requirements.txt
> ```

---

## Terminal 2 — start the frontend (the website)

```powershell
cd C:\Projects\classifyos\frontend
npm install   # first time only
npm run dev
```

It prints `Local: http://localhost:5173/`.

---

## See it in the browser

1. Open **http://localhost:5173**.
2. The banner at the top should be **green ("API connected")** — that confirms the backend
   (terminal 1) is reachable. Red means the backend isn't running.
3. **Upload Data** → drop in a CSV (samples live in `backend/data/samples/`, e.g.
   `policy_lapse.csv`).
4. **Configuration** → pick a target column + feature columns, choose algorithms/options.
5. **Run pipeline** → **Overview** shows the in-progress stages, then the results. Browse
   Feature Impact, Confusion Matrix, Class Report, ROC/PR Curves, Predictions, Interactions,
   Explainability, and the Setup Guide / Risk Register reference pages.

Stop either server with **Ctrl+C** in its terminal.

---

## Quick checklist

- [ ] Terminal 1: uvicorn says `Uvicorn running on http://127.0.0.1:8000`
- [ ] Terminal 2: vite says `Local: http://localhost:5173/`
- [ ] Browser: http://localhost:5173 open, health banner **green**

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Health banner is **red** ("API offline") | The backend isn't up — start terminal 1 (or it crashed; check that terminal). |
| Backend can't find the sample data | Compare the `DATA_DIR` path it prints on startup with where your CSVs are. See `API_RUNBOOK.md` §1 (`.env` / `DATA_DIR`). |
| `ModuleNotFoundError: api` or `classifyos` | You're not in `backend/`. `cd C:\Projects\classifyos\backend` first. |
| `npm run dev` fails / page is blank | Run `npm install` in `frontend/` first; make sure Node.js is installed. |
| Browser shows a CORS error | The Vite dev proxy avoids CORS in development; if you bypass it, add the origin to `CORS_ORIGINS` in `backend/.env` and restart uvicorn. |
| `/run` seems to hang on a big/tuning run | `/run` is synchronous (v1.0) — long runs can approach a gateway timeout. Use fewer algorithms / smaller data; background jobs are a v1.5 item. |

---

## Related docs

- `RUNBOOK.md` — run the ML engine standalone via the CLI (no web server).
- `API_RUNBOOK.md` — run and call the FastAPI layer (endpoints, curl / PowerShell examples).
- `docs/api_contract.md` — the locked `/api/v1/run` request/response schema.
- `frontend_short_desc.md` — what each page of the dashboard does.
- `CLAUDE.md` — conventions, hard rules, and the environment record.
