# ClassifyOS — Databricks Integration: How It Works

> **Purpose:** practical reference for any Claude session working on the Databricks
> execution path. Read this alongside `docs/databricks_integration.md` (the design/roadmap
> doc) and `docs/enabling_parallelization.md` (scale/perf planning).
> **Last updated:** 2026-07-14

---

## 1. Architecture overview

```
Browser (React UI)
  │  run config + UC table path + user PAT
  ▼
FastAPI (local / Azure — backend/api/)
  │  POST /api/2.1/jobs/runs/submit   (Databricks Jobs REST API)
  │  service token auth (DATABRICKS_TOKEN)
  ▼
Databricks Cluster (Standard_E8ds_v5, 64 GB / 8 cores)
  │  installs classifyos wheel (task library)
  │  runs notebooks/classifyos_job_runner.py
  │  reads Delta table → trains → writes artifacts
  ▼
Unity Catalog output volume (/Volumes/aiml_rd/classifyos/output/)
  │  api/run_response.json  ← result envelope
  │  *.png, *.csv, run_profile.json ← artifacts
  ▼
FastAPI polls job status → fetches result via Databricks Files API
  ▼
Browser dashboard populated
```

---

## 2. Env vars — full reference

All set in `backend/.env` (gitignored). Template in `backend/.env.example`.

| Variable | Purpose | Example |
|---|---|---|
| `CLASSIFYOS_EXECUTION_BACKEND` | `databricks` = submit Jobs; `local` = run in-process (default) | `databricks` |
| `DATABRICKS_HOST` | Workspace URL — must include `https://` | `https://adb-8377180828718542.2.azuredatabricks.net` |
| `DATABRICKS_TOKEN` | Service PAT — used by FastAPI to submit jobs and poll status. **Regenerate if exposed.** | `dapi...` |
| `DATABRICKS_HTTP_PATH` | SQL warehouse path — used for Delta table queries | `/sql/1.0/warehouses/a533bb87aa12d132` |
| `DATABRICKS_JOB_CLUSTER_ID` | Existing cluster the job runs on | `0421-071516-3h9grzl1` |
| `DATABRICKS_JOB_NOTEBOOK_PATH` | Workspace path to the job runner notebook (no `.py` extension) | `/Workspace/Users/sharmil.basa@sapiens.com/classifyos/notebooks/classifyos_job_runner` |
| `DATABRICKS_JOB_WHEEL_PATH` | UC volume path to the classifyos wheel | `/Volumes/aiml_rd/classifyos/libs/classifyos-1.0.0-py3-none-any.whl` |
| `CLASSIFYOS_STORAGE_BACKEND` | `databricks` = use `DatabricksVolumeStorage`; unset = local | `databricks` |
| `DBRICKS_INPUT_VOLUME` | UC volume path for input data snapshots | `/Volumes/aiml_rd/classifyos/input` |
| `DBRICKS_OUTPUT_VOLUME` | UC volume path for run artifacts and result envelope | `/Volumes/aiml_rd/classifyos/output` |
| `MLFLOW_TRACKING_URI` | Set to `databricks` on cluster to use managed MLflow | `databricks` |
| `MLFLOW_REGISTRY_URI` | Set to `databricks-uc` on cluster for UC model registry | `databricks-uc` |
| `CLASSIFYOS_JOBS_DSN` | Postgres DSN for persistent job state (defaults to MLflow Postgres) | `postgresql://...` |

---

## 3. Unity Catalog layout

```
aiml_rd  (catalog)
└── classifyos  (schema)
    ├── libs/     (volume) — wheel + notebook stored here
    │   ├── classifyos-1.0.0-py3-none-any.whl
    │   └── classifyos_job_runner.py  (reference copy — not used at runtime)
    ├── input/    (volume) — Delta table snapshots written here before training
    └── output/   (volume) — artifacts written here after training
        ├── api/
        │   └── run_response.json  ← result envelope FastAPI fetches
        ├── plot1.png ... plot6.png
        ├── classification_results.csv
        └── run_profile.json
```

---

## 4. Key source files

| File | What it does |
|---|---|
| `backend/api/databricks.py` | All Databricks REST calls: submit job, poll status, UC browser, `fetch_uc_file()` |
| `backend/api/routes/run.py` | `POST /api/v1/run` — branches on `CLASSIFYOS_EXECUTION_BACKEND` |
| `backend/api/routes/jobs.py` | `GET /run/{job_id}/status` + `/results` — polling + result fetch |
| `backend/api/jobs_store.py` | Persistent job state in Postgres (`classifyos_jobs` table) |
| `backend/api/routes/databricks.py` | UC browser endpoints (`/catalogs`, `/schemas`, `/tables`, `/table-profile`) |
| `backend/classifyos/io/storage.py` | `DatabricksVolumeStorage` — POSIX paths to UC volumes |
| `backend/classifyos/io/sql_source.py` | `materialize_delta_source()` — Delta table → pandas snapshot |
| `notebooks/classifyos_job_runner.py` | The notebook Databricks executes as a Job |

---

## 5. Job submission flow (FastAPI side)

`POST /api/v1/run` when `CLASSIFYOS_EXECUTION_BACKEND=databricks`:

1. Calls `POST {DATABRICKS_HOST}/api/2.1/jobs/runs/submit` with:
   - `existing_cluster_id` = `DATABRICKS_JOB_CLUSTER_ID`
   - `notebook_path` = `DATABRICKS_JOB_NOTEBOOK_PATH`
   - `libraries` = `[{"whl": DATABRICKS_JOB_WHEEL_PATH}]`
   - `base_parameters` = `{ run_config (JSON), user_token (PAT), wheel_path }`
2. Databricks returns `run_id` immediately
3. FastAPI generates a `job_id` (UUID), stores `{ job_id, run_id, status=PENDING }` in Postgres
4. Returns `{ job_id, run_id, status }` to UI

---

## 6. Notebook execution flow (cluster side)

`notebooks/classifyos_job_runner.py` cells in order:

| Cell | What it does |
|---|---|
| 1 | Checks if `classifyos` is importable (wheel installed via task library). Only runs `pip install` if not importable — reads path from `wheel_path` widget, never hardcoded. |
| 2 | Reads `run_config` (JSON) and `user_token` from Databricks widgets (passed as `base_parameters`) |
| 3 | Sets env vars: `CLASSIFYOS_STORAGE_BACKEND=databricks`, UC volume paths, MLflow URIs. Sets `DATABRICKS_TOKEN` to user's PAT so UC reads run as the user. Adds `backend/` to `sys.path` if running from a Databricks Repo. |
| 4 | `build_config(input_file, target, feature_cols, **rest)` → `ModelRunner.run()` |
| 5 | Writes simplified result envelope to `api/run_response.json` on output volume |

**Important:** The wheel is installed as a **task library** by FastAPI before the notebook runs. The notebook does NOT need a `%pip install` magic command. Cell 1 only falls back to pip if the wheel wasn't installed (standalone run).

---

## 7. Result fetching flow (FastAPI side)

`GET /api/v1/run/{job_id}/results`:

1. Polls Databricks for current job state
2. If `COMPLETED`: calls `fetch_uc_file(DBRICKS_OUTPUT_VOLUME + "/api/run_response.json")`
3. `fetch_uc_file` hits `GET {DATABRICKS_HOST}/api/2.0/fs/files{volume_path}` with service token
4. Returns the JSON envelope to the frontend

**Known issue (in progress):** The notebook currently writes a simplified envelope
`{ status, mlflow_run, metrics, best_model, artifacts_written }` — not the full locked
`/run` envelope the frontend expects. This means the dashboard shows limited results
(metrics table only, no charts). Fix options:
- Option A (correct): Set up Databricks Repos so `backend/` is on `sys.path` in the
  notebook, then use `api.result_builder.build_run_result` to write the full envelope.
- Option B (quick): Have `GET /run/{job_id}/results` in FastAPI reshape the simplified
  envelope by reading the artifacts from the UC volume directly.

---

## 8. Cluster setup (one-time)

1. **Cluster**: Standard_E8ds_v5 (64 GB / 8 cores), Databricks Runtime 18.2 / Spark 4.1.0
2. **No manually installed libraries** — wheel is installed per-job via task library
3. **Volumes**: `aiml_rd.classifyos.{libs, input, output}` must exist in Unity Catalog
4. **Wheel**: `classifyos-1.0.0-py3-none-any.whl` uploaded to `aiml_rd/classifyos/libs/`
5. **Notebook**: imported into Databricks Workspace at `DATABRICKS_JOB_NOTEBOOK_PATH`
   OR cloned via Databricks Repos from `https://github.com/sharmilsapiens/classifyos`

---

## 9. Rebuilding and uploading the wheel

Whenever engine code changes, rebuild and re-upload:

```powershell
cd C:\Projects\classifyos\backend
.venv\Scripts\python -m build --wheel
# produces: dist/classifyos-1.0.0-py3-none-any.whl
```

Upload via Databricks UI:
**Catalog → aiml_rd → classifyos → libs → Upload to this volume** → overwrite existing.

No cluster restart needed — wheel installs fresh per job.

---

## 10. Common errors and fixes

| Error | Cause | Fix |
|---|---|---|
| `DATABRICKS_JOB_NOTEBOOK_PATH is not set` | Missing env var | Add to `backend/.env` |
| `DATABRICKS_JOB_CLUSTER_ID is not set` | Missing env var | Add cluster ID from Databricks Compute UI |
| `%pip install /Volumes/main/...` | Stale Workspace notebook | Delete + re-import notebook from repo |
| `No module named 'api'` | Notebook not running from Databricks Repo | Set up Repos OR use self-contained notebook (Option B) |
| `build_config() missing 2 required positional arguments` | Passing dict directly | Unpack: `build_config(input_file=..., target=..., feature_cols=..., **rest)` |
| `'input_source.type' must be one of ['file', 'postgres']` | Old wheel without delta support | Rebuild wheel and re-upload |
| `results envelope is not available yet` | FastAPI reading local storage instead of UC volume | `fetch_uc_file` in `jobs.py` must use Databricks Files API |
| `Databricks unreachable` | `DATABRICKS_HOST` missing `https://` or empty | Fix URL format in `.env` |
| `Permission denied` on volume | Cluster lacks READ on that volume | Grant `READ VOLUME` in Unity Catalog permissions |

---

## 11. Databricks Repos setup (recommended)

Allows the notebook to import `api.*` from `backend/`, giving the full result envelope.

1. Databricks UI → **Repos** → **Add repo**
2. URL: `https://github.com/sharmilsapiens/classifyos`
3. Set in `backend/.env`:
   ```
   DATABRICKS_JOB_NOTEBOOK_PATH=/Workspace/Users/sharmil.basa@sapiens.com/classifyos/notebooks/classifyos_job_runner
   ```
4. After each code push: Repos → `classifyos` → **Pull**

---

## 12. What is NOT done yet

- Full result envelope from Databricks path (charts don't render — see §7 known issue)
- MLflow run history visible in UI (Phase D — deferred)
- Model registry / serving (Phase C — deferred)
- Concurrent user job isolation (enabling_parallelization.md item 11)
- PAT secret-scope handoff (PAT currently visible in Databricks run parameters)
