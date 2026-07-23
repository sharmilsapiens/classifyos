# ClassifyOS — Databricks Integration: How It Works

> **Purpose:** practical reference for any Claude session working on the Databricks
> execution path. Read this alongside `docs/databricks_integration.md` (the design/roadmap
> doc) and `docs/enabling_parallelization.md` (scale/perf planning).
> **Last updated:** 2026-07-23

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

> **Job state is stateless** — there is no database for job tracking. The Databricks `run_id`
> returned by the submit IS the `job_id` the UI polls with, so status/results poll Databricks
> directly. Databricks is the only external dependency (no Postgres, no `CLASSIFYOS_JOBS_DSN`).

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
        └── {user_email}/          ← per-user namespace (sanitized email, e.g. sharmil.basa_sapiens.com)
            └── {job_id}/          ← per-run namespace (Databricks run id)
                ├── api/
                │   └── run_response.json   ← result envelope FastAPI fetches
                └── (plots, CSVs, run_profile.json — the run's artifacts)
```

**Output is namespaced by `{user_email}/{job_id}`** so runs are isolated per user AND per run (no
overwriting between concurrent runs), and each user's runs sit under their own folder for later
per-user Unity Catalog permissions. Both halves are set on the cluster in the notebook (Cell 4
prepends the prefix to `DBRICKS_OUTPUT_VOLUME` before the storage adapter is built):

- `{user_email}` — FastAPI resolves the requesting user's email from their PAT via SCIM
  (`get_user_email`, §5) and passes it to the notebook as the `user_email` base_parameter;
  `unknown_user` is the fallback if resolution fails (never blocks a run).
- `{job_id}` — the notebook's OWN Databricks **task** run id, read from its run context
  (`currentRunId()`, NOT a widget). Note this is the *task* run id, which for a `SUBMIT_RUN` job
  differs from the *outer* run id FastAPI receives from the submit and polls with. So
  `GET /run/{job_id}/results` does NOT fetch under the raw `job_id`: it first bridges outer → task
  via `get_task_run_id(job_id)` (one extra `jobs/runs/get`, reading `tasks[0].run_id`) and fetches
  under that task run id — the same value the notebook namespaced with. This is what makes the fetch
  land on the exact path the Job wrote.

---

## 4. Key source files

| File | What it does |
|---|---|
| `backend/api/databricks.py` | All Databricks REST calls: submit job, poll status, UC browser, `fetch_uc_file()` |
| `backend/api/routes/run.py` | `POST /api/v1/run` — branches on `CLASSIFYOS_EXECUTION_BACKEND` |
| `backend/api/routes/jobs.py` | `GET /run/{job_id}/status` + `/results` — polls Databricks directly (stateless; `job_id` == `run_id`) |
| `backend/api/routes/databricks.py` | UC browser endpoints (`/catalogs`, `/schemas`, `/tables`, `/table-profile`) |
| `backend/classifyos/io/storage.py` | `DatabricksVolumeStorage` — POSIX paths to UC volumes |
| `backend/classifyos/io/sql_source.py` | `materialize_delta_source()` — Delta table → pandas snapshot |
| `backend/classifyos/envelope/` | The `/run` envelope reshaper (`build_run_result` + `build_run_envelope`) and its pydantic response models — shipped **in the engine wheel** so the notebook builds a byte-identical envelope without a repo checkout. `api.result_builder`/`serialize`/`artifacts`/`models` re-export these |
| `notebooks/classifyos_job_runner.py` | The notebook Databricks executes as a Job (imports the envelope from `classifyos.envelope` — wheel only, no `backend/` needed) |

---

## 5. Job submission flow (FastAPI side)

`POST /api/v1/run` when `CLASSIFYOS_EXECUTION_BACKEND=databricks`:

1. Resolves the requesting user's email for output namespacing: `get_user_email(user_pat)` calls
   `GET {DATABRICKS_HOST}/api/2.0/preview/scim/v2/Me` with the **user's PAT** and reads `userName`,
   sanitized for use as a folder segment (`@` → `_`). On any failure it returns `unknown_user` —
   email resolution never blocks a run.
2. Calls `POST {DATABRICKS_HOST}/api/2.1/jobs/runs/submit` with:
   - `existing_cluster_id` = the picked `cluster_id` (UI) or `DATABRICKS_JOB_CLUSTER_ID` (env)
   - `notebook_path` = `DATABRICKS_JOB_NOTEBOOK_PATH`
   - `libraries` = `[{"whl": DATABRICKS_JOB_WHEEL_PATH}]`
   - `base_parameters` = `{ run_config (JSON), user_token (PAT), wheel_path, user_email }`
     (`user_email` lets the notebook namespace its output — see §3)
3. Databricks returns `run_id` immediately
4. That `run_id` **IS** the `job_id` — there is no separate handle and no store. FastAPI returns
   `{ job_id: <run_id>, run_id: <run_id>, status: PENDING }` to the UI (both fields carry the same
   value for contract compatibility). The UI then polls `GET /run/{job_id}/status` and, once
   `COMPLETED`, fetches `GET /run/{job_id}/results` — both poll Databricks directly with that id.

---

## 6. Notebook execution flow (cluster side)

`notebooks/classifyos_job_runner.py` cells in order:

| Cell | What it does |
|---|---|
| 1 | Checks if `classifyos` is importable (wheel installed via task library). Only runs `pip install` if not importable — reads path from `wheel_path` widget, never hardcoded. |
| 2 | Reads `run_config` (JSON), `user_token`, and `user_email` from `base_parameters` widgets. Reads `job_id` from the notebook's OWN run context (`dbutils…currentRunId()`, the **task** run id), falling back to the `job_id` widget then `"local"`. FastAPI's `/results` bridges its outer run id to this task run id via `get_task_run_id` (§3), so the two namespaces agree. |
| 3 | Sets env vars: `CLASSIFYOS_STORAGE_BACKEND=databricks`, UC volume paths, MLflow URIs. Sets `DATABRICKS_TOKEN` to user's PAT so UC reads run as the user. Normalizes the MLflow experiment to an absolute workspace path (Databricks rejects a bare name — §10). **No import bootstrap** — the envelope reshaper ships in the wheel (`classifyos.envelope`), so no repo `backend/` on `sys.path` is needed. |
| 4 | Prepends `{user_email}/{job_id}` to `DBRICKS_OUTPUT_VOLUME` (so ALL artifacts land in the per-user, per-run namespace), then `build_config(input_file, target, feature_cols, **rest)` → `ModelRunner.run()`. |
| 5 | Builds the locked `/run` envelope via `classifyos.envelope.build_run_envelope(runner, storage)` (the SAME reshaper + `RunResponse` the local route uses, from the wheel) and writes it to `api/run_response.json` relative to the namespaced output root — i.e. `{output_volume}/{user_email}/{job_id}/api/run_response.json`, exactly what `GET /run/{job_id}/results` fetches. |

**Important:** The wheel is installed as a **task library** by FastAPI before the notebook runs. The notebook does NOT need a `%pip install` magic command. Cell 1 only falls back to pip if the wheel wasn't installed (standalone run).

**The notebook needs only the wheel — no repo checkout.** Cell 5 builds the locked envelope with `classifyos.envelope.build_run_envelope` — the SAME `build_run_result` + `RunResponse` the local `/run` route uses, now shipped INSIDE the engine wheel (`classifyos.envelope`, since 2026-07-23). The FastAPI layer's `api.result_builder` / `api.serialize` / `api.artifacts` / `api.models` re-export those names, so there is still exactly ONE implementation and the local + Databricks envelopes stay byte-identical. This is why the notebook can run from a **plain Workspace notebook import** and no longer needs a Git-folder checkout of `backend/` (earlier cuts imported `api.*` from a checkout — that dependency is gone). Rebuild + re-upload the wheel whenever the envelope changes (§9).

---

## 7. Result fetching flow (FastAPI side)

`GET /api/v1/run/{job_id}/results`:

1. Polls Databricks for current job state (`job_id` == the outer Databricks `run_id`, so this is a
   direct `jobs/runs/get` call — there is **no intermediate store**; the same poll backs `/status`)
2. Resolves the caller's email from the `X-Databricks-Token` PAT (`get_user_email`, same as at
   submit) to rebuild the `{user_email}` prefix; a missing PAT → `unknown_user`
3. Bridges the outer `job_id` to the **task** run id the notebook namespaced with:
   `get_task_run_id(job_id)` (one extra `jobs/runs/get`, reading `tasks[0].run_id`; falls back to
   `job_id` if the payload carries no tasks)
4. If `COMPLETED`: calls
   `fetch_uc_file(DBRICKS_OUTPUT_VOLUME + "/{user_email}/{task_run_id}/api/run_response.json")`
5. `fetch_uc_file` hits `GET {DATABRICKS_HOST}/api/2.0/fs/files{volume_path}` with the service token
6. Returns the JSON envelope to the frontend

Because there is no cached job state, a transient Databricks outage on either endpoint is an honest
`503` (never a fabricated last-known status), and an unrecognised `job_id` is decided by Databricks
itself (a rejected id → `503`, a finished-but-failed run → `FAILED`) rather than a local `404`.

> **The path must match on both sides**, and it hinges on two values agreeing:
> * `{user_email}` — the notebook writes under the `user_email` base_parameter FastAPI resolved
>   (from the user's PAT via SCIM) at submit; `/results` re-resolves it from the caller's PAT. Both
>   use the deterministic `get_user_email`, so as long as the same identity/PAT is used at submit and
>   fetch, they agree (a failure at either end → `unknown_user`, which only matches if BOTH ended up
>   there).
> * the run id — the notebook writes under its own **task** run id (`currentRunId()`); `/results`
>   derives the same task run id from the outer `job_id` via `get_task_run_id`. This assumes
>   `currentRunId()` inside the notebook equals `tasks[0].run_id` from `jobs/runs/get` — true for the
>   single-task `SUBMIT_RUN` job used here — so the two paths line up.
>
> (This resolves the earlier "results never reach the dashboard" mismatch, where the notebook
> namespaced by an empty `job_id` widget → `"local"` while FastAPI fetched by `run_id`.)

---

## 8. Cluster setup (one-time)

1. **Cluster**: Standard_E8ds_v5 (64 GB / 8 cores), Databricks Runtime 18.2 / Spark 4.1.0
2. **No manually installed libraries** — wheel is installed per-job via task library
3. **Volumes**: `aiml_rd.classifyos.{libs, input, output}` must exist in Unity Catalog
4. **Wheel**: `classifyos-1.0.0-py3-none-any.whl` uploaded to `aiml_rd/classifyos/libs/`
5. **Notebook**: imported into the Databricks Workspace at `DATABRICKS_JOB_NOTEBOOK_PATH` — a
   **plain notebook import is enough** (the envelope ships in the wheel, so a Git-folder checkout of
   `backend/` is no longer required; a Repos checkout still works if you prefer to pull via Git)

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
| `No module named 'api'` (Cell 5) | An **old** notebook that still imports `api.*` from a repo checkout (pre-2026-07-23 design), run without `backend/` on `sys.path` | **Resolved by design** — the current notebook imports the envelope from `classifyos.envelope` in the wheel, not `api.*`. Pull the current notebook and re-upload the current wheel |
| `No module named 'classifyos.envelope'` (Cell 5) | The cluster has an **old wheel** that predates the envelope move | Rebuild + re-upload the wheel (§9) — `classifyos.envelope` ships in `classifyos-1.0.0-py3-none-any.whl` since 2026-07-23 |
| `INVALID_PARAMETER_VALUE: Got an invalid experiment name 'classifyos'` (Cell 4) | Databricks managed MLflow needs an **absolute** experiment path (`/Users/<email>/…`), not a bare name | **Non-fatal** — logging is best-effort, so the run still completes (you'll see `MLflow logging failed; the training run is unaffected`). Fixed by pulling the current notebook: Cell 3 rewrites the experiment to `/Users/<current_user>/classifyos` when logging is enabled |
| `build_config() missing 2 required positional arguments` | Passing dict directly | Unpack: `build_config(input_file=..., target=..., feature_cols=..., **rest)` |
| `'input_source.type' must be one of ['file', 'postgres']` | Old wheel without delta support | Rebuild wheel and re-upload |
| `results envelope is not available yet` | Notebook wrote under a different `{user_email}/{job_id}` prefix than `/results` fetched | Ensure the deployed notebook is current (reads `job_id` from its run context + the `user_email` base_parameter — §6), the caller sends `X-Databricks-Token`, and both resolve the SAME SCIM identity (see §7) |
| `Databricks unreachable` | `DATABRICKS_HOST` missing `https://` or empty | Fix URL format in `.env` |
| `Permission denied` on volume | Cluster lacks READ on that volume | Grant `READ VOLUME` in Unity Catalog permissions |

---

## 11. Databricks Repos setup (optional)

**No longer required for the `/run` envelope** — that now ships in the wheel (§6). A Repos/Git-folder
checkout is still handy if you prefer to pull notebook updates via Git rather than re-importing:

1. Databricks UI → **Repos** → **Add repo**
2. URL: `https://github.com/sharmilsapiens/classifyos`
3. Set in `backend/.env`:
   ```
   DATABRICKS_JOB_NOTEBOOK_PATH=/Workspace/Users/sharmil.basa@sapiens.com/classifyos/notebooks/classifyos_job_runner
   ```
4. After each code push: Repos → `classifyos` → **Pull**

---

## 12. What is NOT done yet

> **Done since an earlier draft:** (1) Cell 5 writes the FULL envelope (same reshaper as the local
> `/run` route), so a Databricks run renders in the dashboard identically to a local run; (2) that
> reshaper + its pydantic response models were moved INTO the engine wheel (`classifyos.envelope`,
> 2026-07-23), so the notebook builds the envelope from the wheel alone — **no repo checkout of
> `backend/` is required** and the `No module named 'api'` failure mode is gone (§6, §11).

- MLflow run history visible in UI (Phase D — deferred)
- Model registry / serving (Phase C — deferred)
- Per-user Unity Catalog permissions on the `{user_email}/` output folders (the folder-level
  namespacing is now in place — see §3 — but no per-user grants are applied yet)
- Broader concurrent-user job isolation beyond output paths (enabling_parallelization.md item 11)
- PAT secret-scope handoff (PAT currently visible in Databricks run parameters)
