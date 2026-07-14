# ClassifyOS — Databricks Integration: Design & Phased Roadmap

> **Status:** active — Phase B in progress. §6.6 Steps 1 (`DatabricksVolumeStorage`) and 2
> (wheel packaging) are DONE and verified locally (2026-07-14); Steps 3–6 pending cluster
> access. Updated 2026-07-14.
> **Purpose:** answer, in one place, *how the project would run on Databricks*, *what
> "deploy as a library" means*, *how input/output and model weights should be handled*,
> and *where the current React dashboard fits*. Databricks/MLflow specifics below were
> verified against Microsoft Learn (Azure Databricks docs), not written from memory.
>
> **Deployment target (2026-07-14):** Azure-hosted FastAPI as orchestration layer →
> Databricks Jobs for compute. Phase B (I/O adapter + wheel) is the prerequisite for that
> orchestration — FastAPI cannot submit a meaningful Databricks Job until the engine runs
> cleanly on the cluster with Unity Catalog I/O. See §6.6 for the active execution plan.

---

## Current status — what is done

| Phase | Item | Status |
|---|---|---|
| Phase A | MLflow logging in `ModelRunner` (opt-in, lazy, report-only) | ✅ Done |
| Interim 2a | MLflow backend store = Postgres (run history, persistent) | ✅ Done |
| Interim 2b | Postgres as input source (materialize-to-file) | ✅ Done |
| Phase B | `DatabricksVolumeStorage` + `get_default_storage()` update | ✅ Done (§6.6 Step 1, 2026-07-14) |
| Phase B | Delta table input source (`materialize_delta_source`) | ✅ Engine done + unit-tested (§6.6 Step 4, 2026-07-14); cluster end-to-end pending smoke test |
| Phase B | MLflow env-var wiring for managed tracking server | ✅ Done — zero code, verified (§6.6 Step 3, 2026-07-14) |
| Phase B | Wheel packaging (`pyproject.toml`) | ✅ Done (§6.6 Step 2, 2026-07-14) |
| Phase B | Cluster smoke-test notebook (`notebooks/classifyos_smoke_test.py`) | ✅ Written (§6.6 Step 5, 2026-07-14); run pending cluster access |
| Orchestration | Async API + Databricks Jobs REST integration (FastAPI layer) | 🔲 After Phase B |
| Phase C | Unity Catalog Model Registry + Model Serving endpoint | 🔲 Deferred |
| Phase D | Persistent dashboard / run history UI | 🔲 Deferred |

---

## 1. Context — why this note exists

Today ClassifyOS runs entirely locally and **keeps nothing between runs**:

- Trained models live only in memory inside `ModelRunner` during a run and are **discarded**
  when `run()` returns. There is no saved weight file anywhere. (This is exactly why
  `/api/v1/explain` is a stateless stub and SHAP is computed *during* the run.)
- Artifacts (`classification_results.csv`, `run_profile.json`, `plot1..6.png`, …) are written
  to `OUTPUT_DIR` with **fixed filenames**, so **each run overwrites the previous one**.
- The `/run` JSON result is held only in the browser's in-memory React store
  (`frontend/src/store/AppStore.tsx`, `result` field). A page refresh loses it — there is no
  `localStorage`, no database.

The goal is to run the training engine on Databricks and, from there, hand trained models to
serving — which also happens to fix the persistence gaps above. This note is the map for that.

---

## 2. Current data flow (the starting point)

```
React frontend  ──HTTP──▶  FastAPI backend  ──imports──▶  Python ML engine
(browser, Vite)            (backend/api/, thin wrapper)   (backend/classifyos/, pure Python)
```

1. **Upload** → `POST /api/v1/upload` writes the file into `DATA_DIR` via
   `StorageAdapter.save_input` and returns a logical key; the profile is stored in the browser.
2. **Configure** → the run config is built in the browser (`buildPayload`).
3. **Run** → `POST /api/v1/run` (`backend/api/routes/run.py`) translates the request into an
   engine config and calls `ModelRunner.run()` on a worker thread. The runner writes ~14
   artifacts to `OUTPUT_DIR` and the route **reshapes** the finished runner's in-memory state
   into the locked JSON envelope (`docs/api_contract.md`).
4. **Results** → the JSON populates the dashboard (held in memory); PNGs/CSVs are fetched on
   demand from `GET /api/v1/outputs/{name}` (`backend/api/routes/outputs.py`), which streams
   whatever files currently sit in `OUTPUT_DIR`.

**The one layer that matters for Databricks is the engine.** It has *no* web dependencies — it
is importable and already runs standalone via the CLI (`python -m classifyos.cli`). That is the
whole reason porting to Databricks is a "write an adapter + add a logging hook" job, not a
rewrite.

---

## 3. What "deploy on Databricks" actually means

Databricks is **compute, not a web host.** You do not move the React+FastAPI stack there. You
ship the **pure-Python engine** and drive it from a notebook or Job.

### 3.1 "Deploy as a library" — confirmed model

1. **Build a wheel** from `backend/` → `classifyos-<ver>-py3-none-any.whl`.
2. **Install it on the cluster** (pick one): upload the wheel to a Unity Catalog volume and
   `%pip install /Volumes/<catalog>/<schema>/<volume>/classifyos-*.whl` (notebook-scoped);
   attach it as a **cluster library**; or publish to a private index and `pip install`.
3. **Import, configure, run** in the notebook — the notebook plays the exact role `cli.py`
   plays locally:
   ```python
   from classifyos.runner import ModelRunner
   from classifyos.io.storage import DatabricksVolumeStorage   # new adapter (Phase B)

   config  = {"input_file": "policy_lapse.csv", "target": "will_lapse", "models": [...], ...}
   runner  = ModelRunner(config, DatabricksVolumeStorage(...)).run()
   ```

### 3.2 Input & output on Databricks — volumes, not a database

**Do not build a database for input/output.** Databricks already gives you the right stores;
MLflow is the "database" for run history. Mapping:

| Kind of thing | Home on Databricks |
|---|---|
| **Input data** | a file in a **Unity Catalog volume** (`/Volumes/…`) or a **Delta table** |
| **Output artifacts** (CSV/PNG/JSON) | **MLflow artifacts** + a volume |
| **Run metrics / params** | **MLflow tracking** (metrics, params, tags) |
| **Trained models / weights** | **MLflow Model Registry** (in Unity Catalog) |
| *(optional, later)* cross-run analytics in SQL | one **Delta table** of run summaries |

**Key finding (verified):** Unity Catalog volumes expose **POSIX-style paths**
(`/Volumes/<catalog>/<schema>/<volume>/<path>`) that work with plain Python `open()`, the `os`
module, and pandas — docs call them *"ideal for … OSS Python modules that require POSIX-style
access."* So `DatabricksVolumeStorage` is essentially `LocalFolderStorage` with its two roots
pointed at volume paths. The engine's file I/O does **not** change. (Volumes require Databricks
Runtime 13.3 LTS+.)

### 3.3 Is MLflow integration automatic on deployment?

**The infrastructure is; the logging calls are not.** A Databricks cluster runs a managed MLflow
tracking server + Registry (in Unity Catalog) out of the box — you configure no tracking URI and
stand nothing up. But MLflow only records what the code tells it to, and today `ModelRunner`
calls nothing. So integration = **add an opt-in logging hook to the engine** (Phase A). Because
MLflow also logs to a local `./mlruns` folder with identical code, this is built and tested
locally first and simply "lights up" on the cluster.

---

## 4. Where the React dashboard fits

Three roles, not mutually exclusive. The dashboard always talks HTTP to *some* endpoint; the
question is whose.

| Option | What it is | When to use |
|---|---|---|
| **A. Unchanged, backend re-homed** | Keep React+FastAPI as-is; point the FastAPI layer at MLflow/volumes (via the storage adapter + an MLflow read path) instead of local folders. Host FastAPI anywhere (VM/container) or on **Databricks Apps** (verified to host FastAPI). | Training-results dashboard — the current experience — reading persisted runs instead of "last run in the folder." |
| **B. Model-serving client** | Add a screen that calls a **Databricks Model Serving** REST endpoint to score *new* rows with a registered model (`serving_endpoints.query`). | Live/what-if scoring of a single policy/claim — the productionised use of the shared weights. |
| **C. Run history / launcher** | Dashboard lists past MLflow runs and can trigger a training run via the **Jobs REST API**, then poll + reload. | "Runs" list, re-open an old run, kick off training from the UI. |

**Recommended end-state:** the dashboard becomes a **read-through client over MLflow** (Option A
with a persistence-backed backend) for training results, plus **Option B** for live scoring. The
training compute lives in Databricks Jobs; the dashboard/API is a thin viewer hosted on
Databricks Apps or elsewhere. **Do not run heavy training inside a Databricks App** — Apps are
for lightweight web serving; training stays a Job.

---

## 5. Sharing trained models / weights

The direct answer to *"can the training details / weights be shared, and how?"* — **yes, via
MLflow.** Once the engine logs models (Phase A):

- `mlflow.sklearn.log_model(...)` / the `xgboost` / `lightgbm` flavors serialize each fitted
  model (weights + the sklearn/booster object) as an MLflow artifact.
- `mlflow.register_model(...)` registers it in the **Unity Catalog Model Registry** with
  versions and stage aliases (Champion/Challenger, Staging/Production), centralized access
  control, and lineage. A teammate loads it by URI (`models:/<catalog.schema.name>/<version>`);
  Model Serving reads the *same* registered version → REST endpoint. One source of truth.
- **Serving gotcha (verified):** Databricks Runtime ML ships `mlflow-skinny`; when logging a
  model destined for serving, pass `pip_requirements=["mlflow==<ver>", …]` so the served
  container gets full `mlflow`.

**Fallback that also works locally today:** a **portable model bundle** — joblib-serialize each
fitted model + the fitted `Preprocessor` + metadata, written through the `StorageAdapter` as a
versioned artifact, re-loadable anywhere without MLflow. Recommended stance: **MLflow flavor as
the primary path; the portable bundle as the offline/no-MLflow fallback** (both are just extra
artifacts the runner emits — no pipeline change).

---

## 6. Phased roadmap

Ordered by value. Phases A–B need **zero Databricks** — they're built and verified locally, and
they *also* fix today's persistence/overwrite problems immediately.

### Phase A — MLflow logging + model persistence in `ModelRunner` (highest value)
- Add an **opt-in, lazy-imported, report-only** MLflow layer (same discipline as
  `shap`/`optuna`/`openai`: off by default, `import mlflow` only when enabled, any failure
  degrades to "no logging" and never aborts a run).
- After training: `log_params` (the run config), `log_metrics` (the per-model headline metrics),
  `log_artifact` (the existing CSVs/PNGs/`run_profile.json`), and **`log_model` per fitted
  model** with the correct flavor. `mlflow.autolog()` may supplement but does not replace
  explicit artifact logging.
- **Leakage discipline preserved:** logging happens *after* fit and reads nothing back into the
  pipeline; `[RISK]` comments untouched. **No `/run` contract change** (or an additive
  `mlflow`/`model_uri` block, version-bumped per the locked-contract rule).
- New dependency: `mlflow` (add to `requirements.txt`, pin, hallucination-check the exact calls
  against the installed version before coding — governance requirement).
- **Outcome:** run history, persistent per-run artifacts, and shareable saved weights — locally
  (`./mlruns`) and, unchanged, on the cluster's managed tracking server.

### Phase B — Package the engine as a wheel + `DatabricksVolumeStorage` — **DEFERRED (needs Databricks)**
- Add `DatabricksVolumeStorage(StorageAdapter)` in `backend/classifyos/io/storage.py`
  (roots default to `/Volumes/<catalog>/<schema>/<volume>/…`; POSIX `open()` works directly — a
  thin subclass/config of the local adapter). Selected at startup via env, exactly like the
  local adapter today. **No pipeline code changes** (the CLAUDE.md storage-abstraction rule is
  what makes this a drop-in).
- Add the wheel build to the tooling. Smoke-test: import the wheel in a notebook, run on a small
  volume dataset.

### Phase C — Register the winning model → Model Serving — **DEFERRED (needs Databricks)**
- On (or after) a run, `register_model` the best model into the Unity Catalog registry; enable a
  Model Serving endpoint (UI or Databricks SDK). Now the saved weights are a live REST endpoint.

### Phase D — Persistent dashboard (optional polish)
- Cheapest first: persist the `result` (and form) to `localStorage` in `AppStore.tsx` so a
  refresh no longer wipes the dashboard.
- Then: run-id-namespaced outputs (`OUTPUT_DIR/<run_id>/…`) so runs stop overwriting, or go
  straight to an MLflow read path in FastAPI (list runs, reload one). Optionally host the
  FastAPI+React viewer on Databricks Apps; add Option B (serving client) and/or Option C (Jobs
  API launcher) screens.

---

## 6.5 Interim local phase (temporary — Postgres; Databricks deferred)

The near-term path after Phase A. Everything here runs on this machine; nothing needs
Databricks. It delivers real persistence and a database-backed input source now, and none of
it is wasted work — MLflow-on-Postgres and the file/DB input split all carry forward to the
Databricks phases unchanged.

**Design decisions (locked 2026-07-08):**
- **Output/history store → MLflow backed by Postgres.** Point MLflow's **backend store** at a
  local Postgres (`postgresql://…`); keep the **artifact store** a local folder (the PNGs, CSVs,
  `run_profile.json`, and `log_model` files stay files — never binary blobs in the DB). This is
  MLflow's native two-store split (see §2/§5), not a bespoke schema. Postgres then holds
  params/metrics/tags/run-history + the model registry, SQL-queryable.
- **Input source → materialize-to-file (Option B).** A Postgres table/query is exported once to
  a Parquet/CSV in `DATA_DIR` **through `StorageAdapter`**, then the pipeline runs unchanged on
  that file. Keeps *all* engine reads behind `StorageAdapter` (the CLAUDE.md rule stays intact),
  keeps the leakage discipline literally untouched (load → split → fit-on-train, as today), and
  snapshots exactly what data the run saw (good for the audit posture). Direct `pd.read_sql`
  (Option A) was considered and rejected for now because it bends the file abstraction.

### Interim 2a — MLflow backend store = Postgres (+ dashboard run history)
- Prereq: a local Postgres instance + an MLflow artifact folder. Because MLflow's backend is
  swappable by **env var**, the Phase-A logging code needs **no change** — only configuration
  (`MLFLOW_TRACKING_URI` / backend-store URI + artifact root) moves from `./mlruns` to Postgres.
- Add a read path so the value is visible: FastAPI endpoint(s) to **list past runs** and
  **reload one** (query MLflow), and a "Runs" view on the dashboard. This is what finally makes
  results survive a browser refresh and a server restart. Additive to the API contract
  (new endpoints / version bump per the locked-contract rule) — existing `/run` unchanged.
- Driver note: MLflow's SQLAlchemy backend needs a Postgres driver (`psycopg2-binary`);
  hallucination-check the backend-store URI form and driver against the installed MLflow.

### Interim 2b — Postgres as an input source (Option B, materialize-to-file)
- Add an opt-in **input source** to config: default `file` (today's behavior) vs new `postgres`
  carrying a connection reference (env/DSN, never a hardcoded credential) + a table name or SQL
  query. Validate it in `build_config` (bad value → 422), same discipline as other config.
- A small helper (API-side or a loader pre-step) runs the query **once**, writes the result to a
  Parquet/CSV under `DATA_DIR` via `StorageAdapter.save_input`/`open_write`, and hands the
  resulting key to the normal pipeline. `data_loader` and everything downstream are unchanged.
- Connection config lives in `.env` (gitignored, machine-local — same convention as `DATA_DIR`).
  Driver: SQLAlchemy engine + `psycopg`/`psycopg2` for `pd.read_sql`; pin it and hallucination-
  check the `create_engine` / `read_sql` calls.
- Surfacing in the dashboard (pick a table/query) is a follow-up; the engine + API come first.

### Scope guard
Cap the interim work at Phase A + 2a + 2b. Do **not** build the deferred Databricks pieces
(volume adapter, Model Serving) speculatively — they can't be exercised without Databricks.

---

## 7. Constraints honored

- **Additive only.** Every phase is opt-in and off by default; a run with the flags off is
  byte-for-byte identical to today. Any `/run` schema change is additive with a version bump
  (locked-contract rule).
- **No leakage.** All new work (logging, persistence, serving) happens *after* training and reads
  nothing back into fit/transform.
- **Storage abstraction.** All new I/O goes through `StorageAdapter`; `DatabricksVolumeStorage`
  is a new adapter, not new hardcoded paths.
- **Engine stays web-free.** MLflow is a normal Python dependency (like shap/optuna), not a web
  dependency — it does not couple the engine to FastAPI.

---

## 8. Open questions (resolved 2026-07-14)

1. **Environment:** Azure Databricks, Unity Catalog volumes confirmed. Managed MLflow confirmed.
   Cluster: Standard_E8ds_v5 (64 GB, 8 cores), Databricks Runtime 18.2 / Spark 4.1.0.
2. **Weight sharing:** MLflow Registry as primary. Portable joblib bundle deferred (Phase C).
3. **Model scope for serving:** best model per run only (Phase C, deferred).
4. **Dashboard target:** FastAPI re-homed to Azure (Option A) as orchestration layer.
   Databricks Apps not used — FastAPI submits Jobs, it does not run inside Databricks.

---

## 6.6 Active execution plan — Phase B (I/O + wheel) → Orchestration

This is the current work order. Each step is independently testable before the next.

### Step 1 — `DatabricksVolumeStorage` (testable locally today) — ✅ DONE (2026-07-14)

File: `backend/classifyos/io/storage.py`

Add `DatabricksVolumeStorage` as a thin subclass of `LocalFolderStorage` — roots pointed
at Unity Catalog volume paths from env vars. Update `get_default_storage()` to select it
when `CLASSIFYOS_STORAGE_BACKEND=databricks` or `DBRICKS_INPUT_VOLUME` is set.

**Local test:** set `DBRICKS_INPUT_VOLUME` to a local folder → engine must behave
identically to `LocalFolderStorage`. No cluster needed.

New env vars:
```
CLASSIFYOS_STORAGE_BACKEND=databricks
DBRICKS_INPUT_VOLUME=/Volumes/main/classifyos/data/input
DBRICKS_OUTPUT_VOLUME=/Volumes/main/classifyos/data/output
```

Detail: `ClassifyOS_Databricks_Enhancement_Guide.md` Enhancement 1 (~60 lines).
Implemented + unit-tested + verified end-to-end (local folders as volume roots) 2026-07-14.

---

### Step 2 — Wheel packaging (`pyproject.toml`) — ✅ DONE (2026-07-14)

File: `backend/pyproject.toml` (new)

Add build metadata so the engine can be packaged as a `.whl` and installed on the cluster.
No engine code changes — purely build tooling. Packages ONLY the `classifyos` engine (not the
web-free-breaking `api` layer). **Guide corrections applied + hallucination-checked:** the
build backend is `setuptools.build_meta` (the guide's `setuptools.backends.legacy:build` does
not exist), and the dependency list adds `openai` + `psycopg2-binary` so it matches the "ML
engine" section of `requirements.txt` exactly. Built cleanly →
`backend/dist/classifyos-1.0.0-py3-none-any.whl` (`dist/` gitignored).

```bash
cd backend/
pip install build
python -m build --wheel
# produces: dist/classifyos-1.0.0-py3-none-any.whl
```

Upload the wheel to a Unity Catalog volume so the cluster can install it:
```bash
databricks fs cp dist/classifyos-1.0.0-py3-none-any.whl \
    dbfs:/Volumes/main/classifyos/libs/classifyos-1.0.0-py3-none-any.whl
```

Detail: `ClassifyOS_Databricks_Enhancement_Guide.md` Enhancement 4.

---

### Step 3 — MLflow env-var wiring (zero code) — ✅ DONE (verified 2026-07-14)

Set on the cluster (Compute → Edit → Advanced → Environment Variables):
```
MLFLOW_TRACKING_URI=databricks
MLFLOW_REGISTRY_URI=databricks-uc
```

The existing `mlflow_logging.py` reads `MLFLOW_TRACKING_URI` and never sets it — it
automatically routes to the managed tracking server with no code change.

**Verified (2026-07-14):** re-read `backend/classifyos/mlflow_logging.py` — it only *reads*
`MLFLOW_TRACKING_URI` (in `_maybe_allow_file_store`, via `os.environ.get`), never calls
`mlflow.set_tracking_uri()`, and relies entirely on MLflow's own env-driven store resolution
(`log_run` reports back `mlflow.get_tracking_uri()`). `_maybe_allow_file_store` sets
`MLFLOW_ALLOW_FILE_STORE` only for a `file:`/schemeless store and is inert for a `databricks`
URI. So `MLFLOW_TRACKING_URI=databricks` + `MLFLOW_REGISTRY_URI=databricks-uc` route logging to
the managed server / Unity Catalog registry with **no code change**. These are documented (as
cluster-side env, commented) in `backend/.env.example`. A run still opts in via `mlflow.enabled`.

---

### Step 4 — Delta table input source — ✅ ENGINE DONE + unit-tested (2026-07-14)

Files: `backend/classifyos/io/sql_source.py`, `config.py`, `runner.py`

`materialize_delta_source(config, storage)` added — identical discipline to the existing Postgres
`materialize_source()` (opt-in, lazy import, materialize-to-file, no leakage). Reads a Unity
Catalog Delta table via the active SparkSession (`spark.table("<catalog>.<schema>.<table>")`) or a
raw `spark.sql(query)`, optionally `sdf.limit(n)`, converts to pandas (`toPandas()`), and writes a
Parquet/CSV snapshot to the input volume root via `StorageAdapter.save_input` (reusing
`_write_snapshot`); the normal file pipeline then runs unchanged. `runner._load()` calls it right
after `materialize_source` — both no-op for a `file` source.

Config (`DEFAULT_CONFIG["input_source"]` gained `catalog` / `schema` / `limit`; `"delta"` added to
`INPUT_SOURCE_TYPES`):
```python
"input_source": {
    "type":    "delta",
    "catalog": "main",
    "schema":  "insurance",
    "table":   "policy_lapse",   # provide table OR query
    "limit":   5000,             # optional positive-int row cap (dev/smoke runs)
}
```

Validation (`config._validate_delta_source`): requires `table` or `query`; **[RISK] SQL
injection** — `catalog`/`schema`/`table` are validated against `_SQL_IDENTIFIER_RE` at
config-build time (they are interpolated into the dotted table name and cannot be bound
parameters); a raw `query` is the analyst's own opt-in SQL. `limit` must be a positive int; the
snapshot destination (`input_file`) must be `.parquet`/`.csv`.

Lazy PySpark import — outside a cluster (no PySpark, or no active SparkSession) this raises a clear
`InputSourceError`, never crashes a local file run. Unit tests mock PySpark entirely
(`backend/tests/test_sql_source.py`, "Delta input source" section) — no test contacts a real
cluster. **Hallucination check ✅** (Microsoft Learn / Azure Databricks PySpark reference, Spark
4.1.0 / DBR 18.2): `SparkSession.getActiveSession()` → `SparkSession | None`,
`SparkSession.table(tableName)` / `.sql(query)` → `DataFrame`, `DataFrame.limit(num)` → `DataFrame`,
`DataFrame.toPandas()` → `pandas.DataFrame`.

Cluster end-to-end (a real Delta read) is exercised by the Step 5 smoke-test notebook.

Detail: `ClassifyOS_Databricks_Enhancement_Guide.md` Enhancement 2 (~80 lines).

---

### Step 5 — Smoke test on cluster (notebook) — ✅ WRITTEN (2026-07-14); run pending cluster

`notebooks/classifyos_smoke_test.py` (a Databricks notebook-source `.py`) installs the wheel, sets
the Step 1/3 env vars, and runs a small Delta table end-to-end. It verifies:
- `DatabricksVolumeStorage` reads/writes to the correct UC volume paths
- the Delta read → `materialize_delta_source` → Parquet snapshot chain (Step 4)
- the MLflow experiment appears in the Databricks Experiments UI (Step 3)
- artifacts (PNGs, CSVs, `run_profile.json`) land in the output volume
- no engine code changes were needed

Note: the notebook calls the real `build_config(input_file, target, feature_cols, **overrides)`
(the guide's `build_config(raw_config)` shorthand does not match the signature, and `feature_cols`
is required) — set `feature_cols`, the catalog/schema/table, and the MLflow experiment path to your
workspace before running.

---

### Step 6 — Orchestration layer (FastAPI on Azure → Databricks Jobs)

**After Steps 1–5 are verified on the cluster**, the engine runs cleanly as a Databricks
Job. The orchestration layer is then built in the FastAPI layer (`backend/api/`):

- `POST /api/v1/run` → submits a Databricks Job via `POST /api/2.1/jobs/runs/submit`,
  returns `{ job_id }` immediately (async — no blocking)
- `GET /api/v1/run/{job_id}/status` → polls `GET /api/2.1/jobs/runs/get`
- `GET /api/v1/run/{job_id}/results` → fetches artifacts from UC volume once complete
- Persistent job state in Postgres (reuse existing MLflow Postgres) so FastAPI restarts
  don't lose in-flight job_ids
- User's Databricks PAT passed in request, used for UC data access, never persisted

Full detail: `docs/enabling_parallelization.md` items 1–4.

---

### How Steps 1–6 connect end-to-end

```
Browser (React UI)
  │  run config + UC data path + PAT
  ▼
FastAPI (Azure — Step 6)
  │  POST /api/2.1/jobs/runs/submit  (user PAT for data auth)
  ▼
Databricks Job
  │  %pip install classifyos wheel  (Step 2)
  │  CLASSIFYOS_STORAGE_BACKEND=databricks  (Step 1)
  │  MLFLOW_TRACKING_URI=databricks  (Step 3)
  ├─ reads Delta table → materialize_delta_source → Parquet snapshot  (Step 4)
  ├─ runs ModelRunner on 8 cores (n_jobs=-1)
  └─ writes artifacts to UC volume + logs to MLflow
  ▼
FastAPI polls job status → fetches results from UC volume
  ▼
Browser dashboard populated
```

Steps 1–5 are the engine side — testable now, no orchestration needed.
Step 6 is the API/orchestration layer — built after Steps 1–5 are verified.
