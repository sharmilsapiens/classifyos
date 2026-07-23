# ClassifyOS — Databricks Integration: Wisdom & Gotchas

> **Purpose:** the hard-won mental models, gotchas, and debugging playbook for the Databricks
> execution path — the stuff that isn't obvious from the code and cost real debugging time. Read this
> alongside `docs/databricks_how_it_works.md` (the mechanics/flow), `docs/databricks_integration.md`
> (the design/roadmap), and `docs/databricks_api_contract.md` (the FastAPI↔Databricks contract).
> **Last updated:** 2026-07-23.

---

## 0. TL;DR — the five things that trip you up

1. **There are TWO MLflow stores.** The cluster logs runs to *Databricks-managed* MLflow; the FastAPI
   process's own `MLFLOW_TRACKING_URI` is often a leftover local dev Postgres. That mismatch used to
   make the **Runs tab read the wrong store and show nothing** — **RESOLVED (2026-07-23, §6.1):** the
   read-path now auto-routes to Databricks-managed MLflow via a **per-call** `tracking_uri="databricks"`
   (independent of the FastAPI's env), so a stale `MLFLOW_TRACKING_URI` no longer matters.
2. **The FastAPI is a separate process from the cluster.** Pulling the notebook and re-uploading the
   wheel do **nothing** for the FastAPI — it needs its own `git pull` + `uvicorn` restart, and its own
   `.env`.
3. **A same-version wheel does NOT reinstall** on an existing all-purpose cluster. After re-uploading
   `classifyos-1.0.0-…whl`, you must **restart the cluster** (or bump the version) or the cluster keeps
   the old code.
4. **Two Databricks run ids + one MLflow run id.** The submit returns the *outer* run id (= the
   `job_id` the UI polls); the notebook namespaces output by its *task* run id (`currentRunId()`);
   `result.mlflow.run_id` is a *third*, separate id (the MLflow run). Don't conflate them.
5. **The user PAT must ride along on every user-scoped call**, not just submit — `/results`, `/runs`,
   `/runs/{id}`. Miss it and the server resolves `user_email` to `unknown_user` → wrong path / empty
   list.

---

## 1. The mental models

### 1.1 Two execution backends (`CLASSIFYOS_EXECUTION_BACKEND`)
- `local` (default): `POST /run` runs the engine in-process (threadpool) and returns the full envelope
  in one response. Local dev + CI. Byte-identical to pre-Databricks behavior.
- `databricks`: `POST /run` submits a **Databricks Job** (`jobs/runs/submit`) and returns
  `{job_id, run_id, status}` immediately; the UI polls `GET /run/{job_id}/status` then
  `GET /run/{job_id}/results`. Read per-call (`execution_backend()`), so tests flip it with
  `monkeypatch.setenv`.

### 1.2 Two identities — never confuse them
- **Service token** (`DATABRICKS_TOKEN` in the FastAPI env): the *service* identity. Used for the Jobs
  API (submit/poll), the cluster picker, `fetch_uc_file`, and **reading MLflow**. On this workspace the
  cluster itself runs as a **service principal** (`current_user()` → `"AIML_RD"`, which has **no
  `/Users/AIML_RD` home** — see §6.4).
- **User PAT** (`X-Databricks-Token` header, per request, **never persisted**): the requesting user's
  identity. Forwarded to the Job as a `base_parameter` so Unity Catalog data reads run *as the user*,
  and used with SCIM (`get_user_email`) to resolve the user's email for output namespacing + per-user
  Runs filtering.

### 1.3 THREE run ids
| id | where it comes from | used for |
|---|---|---|
| **outer** job run id | `jobs/runs/submit` return | the `job_id` FastAPI/UI poll with |
| **task** run id | notebook `currentRunId()` (digits only) | namespaces UC output `{user_email}/{task_run_id}/` |
| **MLflow** run id | `result.mlflow.run_id` (in the envelope) | the MLflow run (artifacts, tags, reload) |

`GET /results` bridges outer → task via `get_task_run_id(job_id)` (one extra `jobs/runs/get`, reads
`tasks[0].run_id`). The MLflow run id is independent — carried in the envelope, present on fresh AND
reloaded runs.

### 1.4 Two MLflow stores (the #1 source of "why no runs?")
- **Cluster (write):** the notebook sets `MLFLOW_TRACKING_URI=databricks` (Cell 3) → runs log to the
  workspace's managed MLflow. Experiment must be an **absolute** path (`/Shared/classifyos`).
- **FastAPI (read):** `api/mlflow_read.py` now routes by backend (RESOLVED §6.1): in the `databricks`
  backend it builds `MlflowClient(tracking_uri="databricks")` and passes `tracking_uri="databricks"` to
  `download_artifacts` **per call** — so it reads Databricks-managed MLflow regardless of the FastAPI
  process's own `MLFLOW_TRACKING_URI` (no process-global `set_tracking_uri` → thread-safe). In the
  `local` backend it binds to the env-configured store exactly as before. The **service token**
  (`DATABRICKS_TOKEN` + `DATABRICKS_HOST`) authenticates the read.

### 1.5 Three artifact locations
For a Databricks run, the same output files exist in up to three places:
- **UC output volume:** `{DBRICKS_OUTPUT_VOLUME}/{user_email}/{task_run_id}/` — the `/run` envelope
  (`api/run_response.json`) + the artifact files (`plot*.png`, `*.csv`, `run_profile.json`).
- **MLflow (when `mlflow.enabled`):** artifact files under `classifyos/`, the envelope snapshot under
  `api/run_response.json` (tag `classifyos.result_artifact`), the owner tag `classifyos.user_email`.
- **FastAPI local `OUTPUT_DIR`:** only **local** runs write here. `GET /outputs/{name}` serves *this*
  → a Databricks run's plots/CSVs are NOT here → the artifact-display gap (§6.2).

---

## 2. File map

| File | Role |
|---|---|
| `backend/api/databricks.py` | REST client: `submit_run`, `get_run_status`, `get_task_run_id`, UC browser, `fetch_uc_file`, `get_user_email` (SCIM), `list_clusters`; `execution_backend()` gate; error taxonomy (`DatabricksAuthError`→401, `DatabricksConfigError`→500, `DatabricksUnavailable`→503) |
| `backend/api/routes/run.py` | `POST /run` — branches local vs databricks; forwards the PAT + resolved `user_email` to the Job |
| `backend/api/routes/jobs.py` | `GET /run/{job_id}/status` + `/results` — **stateless** poll (job_id == outer run id); `/results` bridges to the task run id + re-resolves `user_email` |
| `backend/api/routes/databricks.py` | UC browser (`/catalogs,/schemas,/tables`) + `/table-profile` |
| `backend/api/routes/runs.py` | `GET /runs` + `/runs/{id}` — **per-user** in databricks mode (resolves the caller's email, 401 on missing/expired PAT) |
| `backend/api/mlflow_read.py` | The read-path: `list_runs` (server-side `user_email` tag filter), `load_run` (ownership 404 + downloads the snapshot), `snapshot_result` (delegates to the engine) |
| `backend/classifyos/mlflow_logging.py` | `log_run` (params/metrics/artifacts/models) + `snapshot_envelope(run_id, envelope, user_email)` (single source: logs the envelope artifact + `SNAPSHOT_TAG` + `USER_EMAIL_TAG`) + the shared constants |
| `backend/classifyos/envelope/` | The `/run` envelope reshaper (`build_run_result`, `build_run_envelope`) + the pydantic **response** models + `SCHEMA_VERSION` — **in the engine wheel** so the notebook builds the envelope without an `api`/repo checkout. `api.result_builder`/`serialize`/`artifacts`/`models` re-export these |
| `backend/classifyos/io/storage.py` | `DatabricksVolumeStorage` (UC volumes are POSIX paths; a thin subclass of the local adapter) |
| `backend/classifyos/io/sql_source.py` | `materialize_delta_source()` — Delta table → pandas snapshot (Spark, cluster-only) |
| `notebooks/classifyos_job_runner.py` | The Job entrypoint. Cell 1 wheel-install fallback · Cell 2 read params + task run id · Cell 3 env + MLflow experiment normalize · Cell 4 build_config + `ModelRunner.run()` · Cell 5 `build_run_envelope` → UC + `snapshot_envelope` (owner tag) |
| `docs/databricks_how_it_works.md` | Mechanics/flow (submit→poll→results, path matching, per-user Runs §13) |
| `docs/databricks_integration.md` | Design/roadmap (Phases A/B/C, Interim 2a/2b, §6.x) |
| `docs/databricks_api_contract.md` | The FastAPI↔Databricks Jobs REST contract |
| `docs/enabling_parallelization.md` | Scale / concurrency planning |

---

## 3. Env vars — which PROCESS needs which

**Cluster (set in the notebook / Compute → Env):** `CLASSIFYOS_STORAGE_BACKEND=databricks`,
`DBRICKS_INPUT_VOLUME`, `DBRICKS_OUTPUT_VOLUME`, `MLFLOW_TRACKING_URI=databricks`,
`MLFLOW_REGISTRY_URI=databricks-uc`, `DATABRICKS_TOKEN`=the user's PAT (Cell 3 sets it for UC reads).

**FastAPI host (`backend/.env`):** `CLASSIFYOS_EXECUTION_BACKEND=databricks`, `DATABRICKS_HOST`,
`DATABRICKS_TOKEN` (**service** token — Jobs API + MLflow read + UC fetch), `DATABRICKS_JOB_NOTEBOOK_PATH`,
`DATABRICKS_JOB_CLUSTER_ID`, `DATABRICKS_JOB_WHEEL_PATH`, `CORS_ORIGINS`.
**For the Runs tab to read Databricks MLflow**, the FastAPI *also* needs `MLFLOW_TRACKING_URI=databricks`
(today it's often a leftover local Postgres URI — §6.1). Job state is **stateless** — there is no jobs
DB (`CLASSIFYOS_JOBS_DSN` was removed).

---

## 4. Confirmed facts (verified live this session — don't re-derive)
- The **service token can read** the workspace's MLflow (185 experiments visible); `/Shared/classifyos`
  exists and holds the logged runs.
- The Databricks MLflow **server accepts** the per-user tag filter grammar
  `` tags.`classifyos.user_email` = '<email>' `` (verified against the live server, not just the local
  parser).
- `get_task_run_id(outer)` correctly returns the task run id; `fetch_uc_file` returns the envelope from
  `{output_volume}/{user_email}/{task_run_id}/api/run_response.json`.
- mlflow **3.14.0**: `MlflowClient(tracking_uri=…)` and `mlflow.artifacts.download_artifacts(…,
  tracking_uri=…)` both accept an explicit per-call `tracking_uri` (so the read-path can target
  Databricks without any process-global `set_tracking_uri` mutation — thread-safe).

---

## 5. Debugging playbook (symptom → cause → fix)

| Symptom | Cause | Fix |
|---|---|---|
| `No module named 'api'` (notebook) | Old design imported `api.*` from a repo checkout that wasn't present | Resolved: the envelope now ships in the wheel as `classifyos.envelope`; pull the notebook + re-upload the current wheel |
| `No module named 'classifyos.envelope'` | Cluster has an **old wheel** (same-version cache) | Rebuild + re-upload the wheel **and restart the cluster** |
| MLflow `invalid experiment name 'classifyos'` / `NOT_FOUND: /Users/<x>` | Managed MLflow needs an **absolute, existing** path; `/Users/<current_user>` fails when the cluster runs as a service principal | Notebook nests it under `/Shared/classifyos` |
| `results envelope is not available yet` | Path mismatch: `/results` looked under the wrong `{user_email}/{run_id}` | Ensure the caller sends `X-Databricks-Token` (else `unknown_user`); notebook + `/results` must resolve the SAME SCIM identity; run id bridged via `get_task_run_id` |
| Runs tab **empty** + "Tracking store: postgresql://…localhost" | (pre-2026-07-23) FastAPI's `MLFLOW_TRACKING_URI` pointed at the local dev store, not Databricks | **RESOLVED §6.1** — the read-path auto-routes to `tracking_uri="databricks"` per-call in the databricks backend; just `git pull` + restart uvicorn. If still seen, confirm the FastAPI is on the current code and `execution_backend()=="databricks"` |
| `Too many experiment_ids specified in SearchRuns request. Maximum … 100. Found <N>` (Runs tab) | `list_runs` passed every workspace experiment id to `search_runs`; Databricks caps it at 100 | **RESOLVED §6.1 follow-up** — the databricks read scopes to the ClassifyOS experiment only (`_is_classifyos_experiment`; override `CLASSIFYOS_MLFLOW_EXPERIMENT`). If the experiment was renamed, set that env var to match |
| Databricks run's **PNG plots / CSV downloads don't display** | (pre-2026-07-23) `/outputs/{name}` served only the FastAPI's local `OUTPUT_DIR` | **RESOLVED §6.2** — run-scoped `GET /outputs/{run_id}/{name}` streams `classifyos/{name}` from the MLflow run; the frontend uses it for Databricks-backed runs. If still broken, confirm `result.mlflow.run_id` is present (needs `mlflow.enabled`) and the frontend is rebuilt |
| Wheel change "didn't take" | Re-uploading the same version (`1.0.0`) doesn't reinstall on a persistent cluster | Restart the cluster / bump version / use a job cluster |
| Dashboard shows results but the *reload* button was disabled | The run has no envelope snapshot (`classifyos.result_artifact` tag) | Ensure `mlflow.enabled` + the current notebook (Cell 5 `snapshot_envelope`) |

---

## 6. Open issues & backlog

### 6.1 Runs tab reads the wrong MLflow store (✅ RESOLVED 2026-07-23)
**Was:** in the databricks backend the Runs read-path read the FastAPI process's `MLFLOW_TRACKING_URI`,
which in the deployment is the **local dev Postgres** — so `/runs` listed the local store (empty of
Databricks runs) and the dashboard showed "Tracking store: postgresql://…localhost". The per-user tag
filter was correct — it was just pointed at the wrong store.
**Fix (built, API-only — no engine/wheel change):** `api/mlflow_read.py` gained `_tracking_uri()`,
which returns `"databricks"` when `execution_backend()=="databricks"` (else `None`). `_client()` builds
`MlflowClient(tracking_uri="databricks")`, `list_runs` reports `"databricks"` and `load_run` passes
`tracking_uri="databricks"` to `download_artifacts` — all **per call**, no process-global
`set_tracking_uri` (thread-safe). The service token authenticates; the PAT still only scopes *which*
runs. Local backend byte-identical (`_tracking_uri()` → `None` → env store). Deploy = FastAPI `git pull`
+ uvicorn restart. Tests: `test_api_runs.py` (`_tracking_uri` routing, `_client` binds per-call,
`list_runs` reports `"databricks"`), MLflow mocked.
**Follow-up (same day) — scope the search to the ClassifyOS experiment.** Once the read correctly hit
Databricks-managed MLflow, `list_runs` failed live with `INVALID_PARAMETER_VALUE: Too many
experiment_ids … Maximum 100. Found 185`: it passed **every** workspace experiment id to `search_runs`,
and Databricks caps that at 100 (the workspace had 185). `list_runs` now, in the databricks backend,
narrows to the **ClassifyOS experiment only** (`_is_classifyos_experiment`, basename match against
`CLASSIFYOS_MLFLOW_EXPERIMENT`, default `classifyos` → matches the Job's `/Shared/classifyos`) before
`search_runs` — the only experiment that can hold a matching run anyway, and always ≤ a handful so the
cap is moot. Local backend still searches every experiment (few, no cap). Tests: 150 unrelated
experiments + one `/Shared/classifyos` → only the ClassifyOS id is searched; local searches all.

### 6.2 A Databricks run's artifacts (PNGs/CSVs) don't display (✅ RESOLVED 2026-07-23)
**Was:** `GET /outputs/{name}` served the FastAPI's local `OUTPUT_DIR`; a Databricks run's files live
in MLflow (under `classifyos/`) + on the UC volume, so plot images 404'd and CSV links failed — fresh
AND reloaded. (Interactive JSON-driven charts were unaffected — they're in the envelope.)
**Fix (built, API + frontend only — no engine/wheel change):** a **run-scoped**
`GET /outputs/{run_id}/{name}` (`routes/outputs.py`) that, in the databricks backend, downloads
`classifyos/{name}` from the MLflow run via `mlflow_read.load_artifact` →
`download_artifacts(run_id, artifact_path="classifyos/{name}", tracking_uri="databricks")` and streams
it (local backend serves `OUTPUT_DIR` by name, `run_id` ignored → byte-identical). Frontend:
`outputUrl(name, runId?)` + `runScopedArtifactId(mlflow)` (returns the run id only when
`mlflow.tracking_uri` starts with `"databricks"`); `PngArtifact` gained a `runId` prop; the CSV `<a>`
links + the Overview artifact list pass it. The id comes from `result.mlflow.run_id` (present fresh +
reloaded). **[RISK]** an `<img>`/`<a>` can't carry the PAT, so it's served by the unguessable 32-hex
MLflow run id via the service token — app-level isolation, not a per-user ACL. Tests: run-scoped
endpoint (databricks stream / 404 / 503 / traversal, local byte-identical) + a real-store round-trip
proving `classifyos/{name}` matches `log_run`; frontend `outputUrl`/`runScopedArtifactId`/`PngArtifact`.

### 6.3 Pre-deployment backlog (shared AKS URL)
- **App auth (SSO / API gateway)** — the API has no authn today; only CORS + the per-request PAT gate.
- ~~**`/outputs` for Databricks (6.2)** and **the Runs store routing (6.1)**.~~ ✅ Done 2026-07-23 (§6.1, §6.2).
- **Output isolation** — local `OUTPUT_DIR` uses fixed artifact filenames (concurrent local runs
  overwrite); prod = databricks-backend-only sidesteps this.
- **Secrets** — service token/PAT as k8s secrets; PAT secret-scope handoff (the open `[RISK]` — the PAT
  is visible in the Job's run parameters); `CORS_ORIGINS` = the real domain, never `*`.
- **k8s liveness/readiness probes** (`/api/v1/health`, which reports `execution_backend`).
- **Structured logging + request ids**; a rate/cost guardrail on job submits.
- **`deploy.md` + Dockerfiles** (the capstone that documents all the above for DevOps).

---

## 7. Design principles that apply to every Databricks change
- **Additive + env-gated.** The whole databricks path is off by default; local dev + CI are
  byte-identical. Every optional integration (mlflow/delta/postgres/storage/execution) is gated the same
  way.
- **Stateless.** No job store — the Databricks `run_id` *is* the `job_id`; poll Databricks directly.
- **Thread-safe reads.** Never mutate process-global state (`os.environ`, `mlflow.set_tracking_uri`)
  per request under a shared server. Pass credentials/URIs per-call (constructor/arg), or set the
  process default **once** at startup from static config.
- **Byte-identical envelope.** Local `/run` and the Databricks Job produce the SAME
  `RunResponse.model_dump(by_alias=True)` from the SAME `classifyos.envelope` code — never two shapers.
- **Anything the notebook imports must be in the wheel** (the engine), not the `api` layer.
- **CI never touches a live workspace.** Databricks REST + MLflow are mocked (`httpx.MockTransport`,
  fake `MlflowClient`, temp `file:` stores). Verify against the live workspace manually/ad-hoc only.
- **Hallucination-check** every Databricks/MLflow/Spark call against the installed version — the
  API-reference site is a JS SPA, so the REST client is written defensively.
