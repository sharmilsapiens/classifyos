# ClassifyOS — Databricks Integration: Design & Phased Roadmap

> **Status:** design note (no code changed yet). Written 2026-07-08.
> **Purpose:** answer, in one place, *how the project would run on Databricks*, *what
> "deploy as a library" means*, *how input/output and model weights should be handled*,
> and *where the current React dashboard fits*. Databricks/MLflow specifics below were
> verified against Microsoft Learn (Azure Databricks docs), not written from memory.
>
> **⚠ Reprioritization (2026-07-08):** Databricks integration is **temporarily deferred**.
> After Phase A (MLflow logging), the near-term work is an **interim local phase** that stands
> up a **local Postgres** as (2a) MLflow's backend store and (2b) an optional input source —
> "everything we can do on this machine before Databricks." Phases B/C (volume adapter, Model
> Serving) are parked until Databricks is back on the table. See §6.5. This is a genuine,
> reversible deviation from the roadmap below → log a `plan_tweak.md` entry when built.

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

## 8. Open questions (to confirm before Phase A code)

1. **Environment:** Azure Databricks with **Unity Catalog volumes** (assumed) vs. legacy DBFS?
   Managed MLflow assumed.
2. **Weight sharing:** MLflow Registry as primary (recommended). Also build the portable joblib
   bundle as an offline fallback — yes/no?
3. **Model scope for serving:** serve only the best model per run, or every model?
4. **Dashboard target:** re-home the existing FastAPI backend (Option A) as the near-term step,
   with serving (B) / history (C) later — confirm this ordering.
