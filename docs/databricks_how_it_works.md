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
| `DATABRICKS_JOB_NOTEBOOK_PATH` | Path to the job runner notebook (no `.py` extension). **Must be a notebook inside a Git folder** (repo-backed) so the `api` reshaper is importable (§7, §11) — a plain imported Workspace notebook gives `No module named 'api'`. The Git folder may be under `/Workspace/Users/…` or `/Repos/…`. | `/Workspace/Users/sharmil.basa@sapiens.com/classifyos/notebooks/classifyos_job_runner` |
| `DATABRICKS_JOB_WHEEL_PATH` | UC volume path to the classifyos wheel | `/Volumes/aiml_rd/classifyos/libs/classifyos-1.0.0-py3-none-any.whl` |
| `CLASSIFYOS_STORAGE_BACKEND` | `databricks` = use `DatabricksVolumeStorage`; unset = local | `databricks` |
| `DBRICKS_INPUT_VOLUME` | UC volume path for input data snapshots | `/Volumes/aiml_rd/classifyos/input` |
| `DBRICKS_OUTPUT_VOLUME` | UC volume path for run artifacts and result envelope | `/Volumes/aiml_rd/classifyos/output` |
| `MLFLOW_TRACKING_URI` | Set to `databricks` on cluster to use managed MLflow | `databricks` |
| `MLFLOW_REGISTRY_URI` | Set to `databricks-uc` on cluster for UC model registry | `databricks-uc` |
| `CLASSIFYOS_UC_MODEL` | UC model name the best model registers under (notebook; optional) | `aiml_rd.classifyos.classifyos_model` |
| `CLASSIFYOS_JOBS_DSN` | Postgres DSN for persistent job state (defaults to MLflow Postgres) | `postgresql://...` |

---

## 3. Unity Catalog layout

Output is **namespaced per `job_id`** (the FastAPI job handle) so concurrent / successive runs
never overwrite each other. The result envelope lives under `api/{job_id}/` and every training
artifact under `artifacts/{job_id}/`.

```
aiml_rd  (catalog)
└── classifyos  (schema)
    ├── libs/     (volume) — wheel + notebook stored here
    │   ├── classifyos-1.0.0-py3-none-any.whl
    │   └── classifyos_job_runner.py  (reference copy — not used at runtime)
    ├── input/    (volume) — Delta table snapshots written here before training
    └── output/   (volume) — artifacts written here after training
        ├── api/
        │   └── {job_id}/
        │       └── run_response.json  ← locked /run envelope FastAPI fetches
        └── artifacts/
            └── {job_id}/
                ├── plot1.png ... plot6.png
                ├── classification_results.csv
                ├── metrics_comparison.csv (+ the other CSVs)
                └── run_profile.json
```

Trained models are **not** written to the volume as files — they are persisted to the managed
**MLflow** tracking server (per-model, flavor-native) and the best model is registered in the
Unity Catalog **Model Registry** as `aiml_rd.classifyos.classifyos_model` (see §7, §13).

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
| 2 | Reads `run_config` (JSON), `user_token`, and `job_id` from Databricks widgets (passed as `base_parameters`). `job_id` namespaces all output. |
| 3 | Sets env vars: `CLASSIFYOS_STORAGE_BACKEND=databricks`, UC volume paths, MLflow URIs. Sets `DATABRICKS_TOKEN` to user's PAT so UC reads run as the user. Adds `backend/` to `sys.path` if running from a Databricks Repo. |
| 4 | Builds per-job `DatabricksVolumeStorage` (`artifacts/{job_id}/`), resolves the MLflow experiment (permission fallback), enables the engine's MLflow logging, `build_config(...)` → `ModelRunner.run()`. |
| 4b | Registers the best model (`f1_weighted`) as a version of `aiml_rd.classifyos.classifyos_model` + sets the `champion` alias (report-only, permission fallbacks). |
| 5 | Writes the **full locked** `/run` envelope (`build_run_result` + `RunResponse`) to `api/{job_id}/run_response.json` on the output volume. |

**Important:** The wheel is installed as a **task library** by FastAPI before the notebook runs. The notebook does NOT need a `%pip install` magic command. Cell 1 only falls back to pip if the wheel wasn't installed (standalone run).

---

## 7. Result fetching flow (FastAPI side)

`GET /api/v1/run/{job_id}/results`:

1. Polls Databricks for current job state
2. If `COMPLETED`: calls `fetch_uc_file(DBRICKS_OUTPUT_VOLUME + "/api/{job_id}/run_response.json")`
   — the **per-job** key built by `routes/jobs.py::result_envelope_key(job_id)`, the single source
   of that path shape (the notebook builds the identical path from the same `job_id`, so the write
   and the fetch can never drift). The exact path fetched is logged (`logging.INFO`) and echoed in
   the 404 detail, so a mismatch is diagnosable.
3. `fetch_uc_file` hits `GET {DATABRICKS_HOST}/api/2.0/fs/files{volume_path}` with the service token,
   through the shared `_build_client` seam (so CI can mock it with `httpx.MockTransport`).
4. Returns the JSON envelope to the frontend

**Resolved (2026-07-14):** the notebook now writes the **full locked `/run` envelope**
(`{status, schema_version, result, error}`) via the canonical `api.result_builder.build_run_result`
+ `RunResponse` (Option A — Cell 5), so the dashboard renders it byte-identical to a local run.
Previously Cell 5 wrote a simplified envelope (`{status, mlflow_run, metrics, best_model,
artifacts_written}`) that the frontend's `parseRunResponse` rejected → "Could not fetch the run
results." (This is why Option A needs the `api` package on `sys.path` — run the notebook from a
Databricks Repo checkout, per §11; Cell 3 adds `backend/` to `sys.path`.)

> **Interactive charts vs PNGs.** The dashboard's charts (ROC/PR curves, confusion matrix, feature
> impact, …) are drawn from the JSON envelope's `result.*` blocks and render fully. The *downloadable
> PNG* artifacts are still fetched by name via `GET /outputs/{name}`, which reads the local
> `OUTPUT_DIR` — in Databricks mode the PNGs live on the UC volume under `artifacts/{job_id}/`, so
> the PNG thumbnails do not load yet. Streaming `/outputs` from the UC volume in Databricks mode is a
> documented follow-up (§12).

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
| `No module named 'api'` | Notebook is a plain imported Workspace copy, not inside a Git folder — the `api` reshaper isn't in the wheel | Run from a **Git folder** (repo-backed; may be under `/Workspace/Users/…` or `/Repos/…`) and point `DATABRICKS_JOB_NOTEBOOK_PATH` at the notebook inside it (see §11). Cell 3 then adds `backend/` to `sys.path`. |
| `Unable to access the notebook "…" … does not exist` | `DATABRICKS_JOB_NOTEBOOK_PATH` points at a path that doesn't exist (e.g. a `/Repos/…` guess when the Git folder is actually under `/Workspace/Users/…`) | Right-click the notebook in your Git folder → **Copy → Copy full path**, and use exactly that (§11). |
| `build_config() missing 2 required positional arguments` | Passing dict directly | Unpack: `build_config(input_file=..., target=..., feature_cols=..., **rest)` |
| `'input_source.type' must be one of ['file', 'postgres']` | Old wheel without delta support | Rebuild wheel and re-upload |
| `results envelope is not available yet (looked in …)` | Job did not write `api/{job_id}/run_response.json`, or a path mismatch | The 404 detail + the INFO log show the exact UC path fetched; confirm the notebook wrote the same `job_id`-namespaced path (Cell 5) |
| `Could not fetch the run results` (dashboard) | Notebook wrote a non-locked envelope | Fixed: Cell 5 writes the full `RunResponse` envelope via `build_run_result` (needs the `api` pkg on `sys.path` → run from a Databricks Repo) |
| `Databricks unreachable` | `DATABRICKS_HOST` missing `https://` or empty | Fix URL format in `.env` |
| `Permission denied` on volume | Cluster lacks READ on that volume | Grant `READ VOLUME` in Unity Catalog permissions |

---

## 11. Databricks Repos setup (REQUIRED for the full result envelope)

**Why this is required, not just "recommended".** Cell 5 builds the locked `/run` envelope with
`api.result_builder.build_run_result` (+ `api.models.RunResponse`, `api.serialize.safe_jsonify`).
That `api` package is **not in the `classifyos` wheel** — the wheel ships the engine only
(`pyproject.toml` → `include = ["classifyos*"]`, to keep it web-free). So `api` is importable on the
cluster ONLY when the notebook runs from a **Git folder** (a repo-backed checkout), where the repo's
`backend/` dir is on the cluster filesystem. Running a **plain imported Workspace notebook** (uploaded,
not backed by Git) gives `ModuleNotFoundError: No module named 'api'`, because it has no `backend/`
next to it.

> **The path prefix does NOT matter — being a Git folder does.** A Git folder can live under
> `/Workspace/Users/<user>/<repo>` (modern default) **or** `/Repos/<user>/<repo>` (legacy) — both work.
> What matters is that the notebook you point the Job at lives *inside a Git folder*, not that it starts
> with `/Repos`. (Setting the Job to a `/Repos/…` path that doesn't exist gives
> *"Unable to access the notebook … it does not exist"*.)

Steps:

1. Databricks UI → **Workspace → Create → Git folder** (older UIs: **Repos → Add repo**).
2. URL: `https://github.com/sharmilsapiens/classifyos`. Note where the folder is created — e.g.
   `/Workspace/Users/sharmil.basa@sapiens.com/classifyos`.
3. Point the Job at the notebook INSIDE that Git folder. Easiest: right-click the notebook →
   **Copy → Copy full path**, and set that in `backend/.env`:
   ```
   DATABRICKS_JOB_NOTEBOOK_PATH=/Workspace/Users/sharmil.basa@sapiens.com/classifyos/notebooks/classifyos_job_runner
   ```
4. After each code push to `main`: the Git folder → **Pull** (so the cluster has the latest `backend/`
   + notebook).

Cell 3's `_add_backend_to_path()` then puts `<repo>/backend` on `sys.path` — it looks on the existing
`sys.path`, walks up from the working directory, AND derives the repo root from the notebook's own
workspace path (so it works even when the Job's cwd isn't the notebook's folder, and regardless of
whether the Git folder is under `/Workspace/Users/…` or `/Repos/…`). If `api` still can't be found it
raises a clear error naming this section, rather than failing deep in Cell 5.

---

## 12. What is NOT done yet

Resolved in the 2026-07-14 orchestration fix pass (Problems 1–5):
- ✅ **Full result envelope from the Databricks path** — the notebook writes the locked `/run`
  envelope; interactive charts render (see §7).
- ✅ **Per-run output isolation** — output is namespaced per `job_id`, so runs no longer overwrite
  each other (§3, §7).
- ✅ **Models persisted on Databricks** — the engine's MLflow layer logs one saved model per
  algorithm to the managed tracking server (§13).
- ✅ **Model registry** — the best model is registered as a version of
  `aiml_rd.classifyos.classifyos_model` and given the `champion` alias, so it is loadable/servable by
  alias (§13). Registration + alias are report-only with permission fallbacks.

Still open:
- **PNG artifacts in Databricks mode** — `/outputs/{name}` reads local `OUTPUT_DIR`; the PNGs live on
  the UC volume under `artifacts/{job_id}/`, so PNG thumbnails don't load yet (interactive charts do
  — see the note in §7). Follow-up: stream `/outputs` from the UC volume when in the databricks backend.
- **Model *serving* endpoint** — the model is registered + aliased; standing up a Databricks Model
  Serving endpoint from the `champion` alias is the remaining Phase C step.
- **MLflow run history in the UI** — runs are logged to managed MLflow, but the dashboard's Runs
  view still reads the local/Postgres MLflow store, not the Databricks one (Phase D — deferred).
- **PAT secret-scope handoff** — the user PAT is still passed in the Databricks run parameters
  (visible in the run UI). Hardening to a secret scope is the follow-up (`api/databricks.py` [RISK]).

## 13. MLflow logging + Unity Catalog Model Registry (2026-07-14)

The Job entrypoint (`notebooks/classifyos_job_runner.py`) drives MLflow by **reusing the engine's
built-in logger** (`classifyos.mlflow_logging.log_run`, opt-in via `cfg["mlflow"]`) rather than
re-implementing MLflow calls in the notebook — the "API/orchestration wraps the engine, never
re-implements ML logic" rule. Cell 4:

1. Resolves the experiment path with a permission fallback (`/classifyos/runs` →
   `/classifyos-fallback` → disable logging) so an MLflow permission failure never aborts the run.
2. Sets `cfg["mlflow"] = {enabled, experiment, run_name: "classifyos-{job_id}"}` and runs the engine.
   The engine then logs the config (params), each model's held-out TEST metrics, the artifact files,
   and **one saved model per fitted algorithm** (flavor-native `mlflow.xgboost`/`lightgbm`/`sklearn`)
   to the managed tracking server (`MLFLOW_TRACKING_URI=databricks`, set in Cell 3).

Cell 4b then registers the **best** model (highest `f1_weighted`) as a new version of the three-part
UC name `aiml_rd.classifyos.classifyos_model` (override via `CLASSIFYOS_UC_MODEL`) and moves the
`champion` alias to it — Unity Catalog uses **aliases, not stages**. Registration and aliasing are
each wrapped report-only: without `CREATE MODEL` / registry permission the model stays logged as an
MLflow artifact and the run is unaffected. The MLflow `run_id` flows into the result envelope via
`result.mlflow`, so the dashboard can link to the MLflow UI.

Load the champion model anywhere with:
`mlflow.pyfunc.load_model("models:/aiml_rd.classifyos.classifyos_model@champion")`.
