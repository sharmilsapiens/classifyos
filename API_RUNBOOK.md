# ClassifyOS — API Runbook

> A plain, command-first operator's guide to running and calling the **FastAPI layer**
> (Phase 8) on a local machine. Companion to `RUNBOOK.md` (which covers the engine/CLI).
> Every command and response below was verified against a live server.
>
> The API is a thin HTTP translator over the ML engine — it adds no ML logic. Think of it as
> "the CLI, but the caller is a browser instead of a terminal." All routes live under
> `/api/v1/`. The `POST /api/v1/run` response shape is **LOCKED** — the authoritative schema
> is `docs/api_contract.md`; this runbook shows how to *drive* it.

---

## 1. Prerequisites & setup

- Python venv installed at `backend/.venv` (see `RUNBOOK.md` §1 / CLAUDE.md for setup).
- `backend/.env` present with `DATA_DIR`, `OUTPUT_DIR` (and optionally `CORS_ORIGINS`). The API
  calls `load_dotenv()` at startup, so it reads `.env` automatically — **but** if a variable is
  already exported in your shell, that exported value wins (`load_dotenv` does not override).
  If `.env` is missing and nothing is exported, storage silently falls back to the relative
  `./data` and `./classification_output` defaults (same caveat as the CLI).
- **Always run from the `backend/` directory** so the `api` and `classifyos` packages import.
- Datasets are referenced by a **logical key relative to `DATA_DIR`** (e.g. `policy_lapse.csv`).
  Uploaded files are stored under the `uploads/` sub-key (e.g. `uploads/myfile.csv`).

> Sample data note: the bundled CSVs are **synthetic** (plan_tweak #5), so the metric values in
> the examples below are illustrative, not representative of real insurance data.

---

## 2. Start the server

```powershell
cd C:\Projects\classifyos\backend
.\.venv\Scripts\Activate.ps1
uvicorn api.main:app --reload --port 8000
```

- `uvicorn` is the always-on server process that holds the imported engine in memory and hands
  it incoming HTTP requests. `api.main:app` is the FastAPI application object.
- `--reload` restarts the server when you edit code (development only). Drop it in production.
- On startup it logs the resolved **absolute** `DATA_DIR` / `OUTPUT_DIR` and the CORS allowlist —
  glance at those to confirm it's reading/writing where you expect:

```
INFO:     ClassifyOS API starting — DATA_DIR=... OUTPUT_DIR=...
INFO:     CORS allowlist: (none configured)
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Leave it running; open a **second** terminal for the calls below. Stop it with `Ctrl+C`.

> Without activating the venv you can also run it directly:
> `.\.venv\Scripts\python.exe -m uvicorn api.main:app --reload --port 8000`

---

## 3. Easiest way to explore: the interactive docs

Open **http://localhost:8000/docs** — FastAPI auto-generates a Swagger UI from the Pydantic
models. Expand any endpoint, fill in the body, click **Execute**, and see the live response and
the exact `curl` it ran. (CORS does not apply to this page, so it always works.)
`http://localhost:8000/redoc` is a read-only alternative.

---

## 4. Endpoint reference

All paths are prefixed with `/api/v1/`. Examples are given for both **PowerShell**
(`Invoke-RestMethod`) and **curl** (works in Git Bash / WSL / macOS / Linux).

### `GET /health` — liveness check

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/health
```
```bash
curl http://localhost:8000/api/v1/health
```
Response:
```json
{"status":"ok","service":"ClassifyOS API","version":"1.0"}
```

### `POST /upload` — upload a dataset and inspect it

Multipart upload. Saves the file under `DATA_DIR/uploads/<name>` (via the storage layer) and
immediately profiles it, so the UI can populate column pickers and a class preview. The optional
`target` form field adds `class_distribution` + `suggested_problem_type`.

```powershell
$resp = Invoke-RestMethod http://localhost:8000/api/v1/upload -Method Post `
  -Form @{ file = Get-Item .\data\samples\risk_tier.csv; target = "risk_tier" }
$resp.server_path            # → "uploads/risk_tier.csv"  (pass this to /run as input_file)
$resp.suggested_problem_type # → "multiclass"
```
```bash
curl -X POST http://localhost:8000/api/v1/upload \
  -F "file=@data/samples/risk_tier.csv" -F "target=risk_tier"
```
Selected response fields (verified):
```jsonc
{
  "columns": ["age", "bmi", "is_smoker", "..."],
  "numeric_cols": ["age", "bmi", "is_smoker", "annual_income"],
  "categorical_cols": ["..."], "binary_cols": ["..."], "datetime_cols": [],
  "n_rows": 3000,
  "n_missing": {"age": 0, "...": 0},
  "sample": [ { "...": "..." } ],            // first 5 rows
  "class_distribution": {"Low": 1350, "Medium": 1050, "High": 600},
  "suggested_problem_type": "multiclass",
  "server_path": "uploads/risk_tier.csv"     // ← use as input_file in /run
}
```
Returns **422** for an unsupported file type, or if `target` isn't a column in the file.

### `POST /run` — execute the full pipeline (the main endpoint)

Body is a `RunConfig`. Three fields are **required** (`input_file`, `target`, `feature_cols`);
everything else defaults to the engine defaults. The endpoint runs the whole pipeline on a worker
thread and returns the **locked** result envelope. `input_file` can be a `DATA_DIR` key
(e.g. `policy_lapse.csv`) or an upload's `server_path`.

```powershell
$body = @{
  input_file    = "policy_lapse.csv"
  target        = "will_lapse"
  feature_cols  = @("age","annual_premium","num_late_payments","has_agent","claims_count")
  problem_type  = "binary"
  algorithms    = @("LogisticRegression","RandomForest")
  class_balance = "class_weight"
} | ConvertTo-Json

$r = Invoke-RestMethod http://localhost:8000/api/v1/run -Method Post `
  -ContentType 'application/json' -Body $body

$r.result.models                       # per-model scoreboard (a list)
$r.result.run                          # run metadata
$r.result.predictions.full_csv         # → classification_results.csv (full table via /outputs)
```
```bash
curl -X POST http://localhost:8000/api/v1/run -H "Content-Type: application/json" -d '{
  "input_file":"policy_lapse.csv","target":"will_lapse",
  "feature_cols":["age","annual_premium","num_late_payments","has_agent","claims_count"],
  "problem_type":"binary","algorithms":["LogisticRegression","RandomForest"],
  "class_balance":"class_weight"}'
```

Shape of a successful response (verified — values illustrative):
```jsonc
{
  "status": "ok",
  "schema_version": "1.0",
  "result": {
    "run": { "target": "will_lapse", "problem_type": "binary",
             "features": [...], "active_features": [...], "interaction_cols": [...],
             "class_distribution": {"0": 1995, "1": 1005},
             "n_rows": 3000, "n_train": 2400, "n_test": 600,
             "class_balance": "class_weight", "class_weight": {"0": 0.75, "1": 1.49},
             "models_succeeded": 2, "timestamp": "2026-06-17T..Z" },
    "models": [ {"name":"LogisticRegression","status":"ok","f1_weighted":0.602, "...": 0.0},
                {"name":"RandomForest","status":"ok","f1_weighted":0.612, "...": 0.0} ],
    "predictions": { "sampled": true, "rows_returned": 200, "rows_total": 1200,
                     "full_csv": "classification_results.csv", "sample_rows": [ {...} ] },
    "confusion_matrix": { "RandomForest": {"labels":["0","1"], "matrix":[[..],[..]]} },
    "class_report":     { "RandomForest": [ {"class":"0","precision":0.0, "...":0} ] },
    "feature_impact":   [ {"feature":"...","composite_score":0.0,"id_like":false,"rank":1} ],
    "curves":           { "RandomForest": {"roc":{"1":{"fpr":[..],"tpr":[..],"auc":0.0}},
                                            "pr": {"1":{"precision":[..],"recall":[..],"ap":0.0}}} },
    "artifacts":        [ {"name":"plot2_roc_pr_curves.png","suffix":".png","size_bytes":0} ]
  }
}
```

Key contract points (full detail in `docs/api_contract.md`):
- `models` is a **list** (renders with `.map`) and **includes failed algorithms** as
  `{"status":"failed","error":"..."}` — a bad model is shown, never silently dropped.
- `predictions` is **sampled** (first 100 rows per model) for display; the **full** table is
  `classification_results.csv`, fetched via `/outputs/{name}`.
- `confusion_matrix` and `curves` are always computed on the **full** test set.
- `curves`: binary → one entry keyed by the positive class; multiclass → one-vs-rest per class.
- Chart **PNGs are referenced by name only** (in `artifacts`) — fetch them from `/outputs/{name}`.
- All numbers are JSON-safe (any `NaN`/`Infinity`/undefined metric is `null`).

Errors:
- **422** — invalid config (missing/empty required field, bad enum, target listed in features, …).
- **400** with `{"status":"error","result":null,"error":"..."}` — a known failure while running
  (e.g. `input_file` not found).

### `POST /explain` — single-row SHAP (v1.0 stub)

v1.0 has no model persistence, so this returns a **structured placeholder** (it never trains).
The field shape is final so v2.0 can fill it in once a model registry / MLflow exists.

```bash
curl -X POST http://localhost:8000/api/v1/explain -H "Content-Type: application/json" \
  -d '{"input_file":"policy_lapse.csv","target":"will_lapse","feature_cols":["age"],
       "model":"RandomForest","sample_index":3}'
```
Response (verified):
```jsonc
{ "status": "unavailable", "schema_version": "1.0",
  "model": "RandomForest", "sample_index": 3,
  "method": null, "shap_values": null, "base_value": null,
  "reason": "no_persisted_model",
  "message": "Single-row SHAP explanations require a fitted model ... deferred to v2.0 ..." }
```

### `GET /outputs` — list run artifacts

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/outputs
```
```bash
curl http://localhost:8000/api/v1/outputs
```
Response (verified — 11 files after a run):
```jsonc
[ {"name":"classification_results.csv","suffix":".csv","size_bytes":83957},
  {"name":"metrics_comparison.csv","suffix":".csv","size_bytes":487},
  {"name":"plot2_roc_pr_curves.png","suffix":".png","size_bytes":126841}, ... ]
```

### `GET /outputs/{name}` — download one artifact (CSV or PNG)

```powershell
Invoke-WebRequest http://localhost:8000/api/v1/outputs/plot2_roc_pr_curves.png -OutFile roc_pr.png
Invoke-WebRequest http://localhost:8000/api/v1/outputs/classification_results.csv -OutFile preds.csv
```
```bash
curl -o roc_pr.png http://localhost:8000/api/v1/outputs/plot2_roc_pr_curves.png
```
PNGs return `content-type: image/png`, CSVs `text/csv`. A path-traversal attempt
(e.g. `..%2f..%2fsecret.txt`) is rejected by the storage guard (never served); a missing file
is `404`.

---

## 5. Typical end-to-end flow

1. **`POST /upload`** your CSV → note `server_path`, columns, and `suggested_problem_type`.
2. **`POST /run`** with `input_file = server_path`, your `target`, chosen `feature_cols`,
   `problem_type`, `algorithms`, `class_balance` → read the metrics + sampled predictions + curves
   from the JSON.
3. **`GET /outputs`** then **`GET /outputs/{name}`** → download the full predictions CSV and the
   chart PNGs for display.

(If your data already lives in `DATA_DIR`, skip step 1 and pass the bare key as `input_file`.)

---

## 6. The locked response contract

`docs/api_contract.md` is the **frozen** source of truth for the `RunConfig` request and the
`/run` response (`schema_version` `1.0`). The Phase 9 React frontend is generated against it.
Any change must be additive and bump the version — never mutate `1.0` in place.

---

## 7. CORS & `.env` (for the browser frontend)

Browsers block a page on one origin from calling an API on another unless the API allows it. The
allowlist comes from `CORS_ORIGINS` (comma-separated) in `backend/.env`; it is **never** `["*"]`
unless the explicit local-dev marker `CLASSIFYOS_CORS_DEV=1` is set. For the Vite dev frontend:

```
# backend/.env
CORS_ORIGINS=http://localhost:5173
```
Restart uvicorn after editing `.env`. (Tools like Swagger UI, `curl`, and `Invoke-RestMethod`
are not browsers, so they work regardless of CORS.)

---

## 8. Notes & limitations

- **Synchronous `/run`.** The pipeline runs on a worker thread (so the server stays responsive)
  but the call blocks until the run finishes and returns the whole result in one response. A long
  run (big data, many algorithms, tuning on) can exceed a reverse-proxy/gateway timeout. A
  background-job path (submit → poll → fetch) is deferred to **v1.5**.
- **Outputs are overwritten each run.** Artifacts use fixed filenames and all runs share one
  `OUTPUT_DIR`, so each `/run` overwrites the previous run's files (same behaviour as the CLI —
  see `RUNBOOK.md`). Download what you need before the next run, or point `OUTPUT_DIR` at a fresh
  folder per run.
- **`/explain` is a stub** until model persistence lands (v2.0).
- **Tuning** (`tuning.enabled: true`) is OFF by default and can make a `/run` much slower; it has
  a hard per-model time cap (see `RUNBOOK.md` / `backend_short_desc.md`).

---

## 9. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `ModuleNotFoundError: api` / `classifyos` | Not running from `backend/`. `cd C:\Projects\classifyos\backend` first. |
| Startup log shows an unexpected `DATA_DIR`/`OUTPUT_DIR` | `.env` missing or a shell var is overriding it (exported vars win over `.env`). Check `backend/.env`. |
| `/run` → 422 | Invalid `RunConfig`: missing/empty `input_file`/`target`/`feature_cols`, a bad enum (e.g. `problem_type`), or `target` also in `feature_cols`. The 422 body names the field. |
| `/run` → 400 `{"status":"error",...}` | Run-time failure, usually `input_file` not found in `DATA_DIR`. Confirm the key (and that uploads use the `uploads/...` `server_path`). |
| Browser frontend gets a CORS error | Add its origin to `CORS_ORIGINS` in `.env` and restart uvicorn. |
| `/outputs` is empty | No run has completed yet in this `OUTPUT_DIR`, or `OUTPUT_DIR` differs from where `/run` wrote (check the startup log). |
| `/outputs/{name}` → 404 | File not produced (no run yet) or wrong name; list available files with `GET /outputs`. |
| A model row has `"status":"failed"` | That algorithm errored on this data (e.g. an unknown name); the `error` string explains it and the other models still ran. |
| `/run` hangs / times out behind a proxy | It's synchronous — see §8. Use fewer algorithms / smaller data, or raise the gateway timeout; background jobs are a v1.5 item. |

---

_See also: `RUNBOOK.md` (engine/CLI), `docs/api_contract.md` (locked schema),
`api_short_desc.md` (plain-language API overview), `CLAUDE.md` (hard rules)._
