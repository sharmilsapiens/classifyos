# ClassifyOS — Technical Overview

*Engineering orientation for anyone inheriting or extending the project.*

> **Purpose.** This is a **high-level map**, not a line-by-line manual. It explains how
> ClassifyOS is put together, the rules that must not be broken, where the detailed docs live,
> and how the project can be taken forward. The code itself is thoroughly documented, and an
> AI coding assistant (e.g. Claude Code) can walk it with you — so this document deliberately
> stays at the level of *"what exists, why, and where to read more."*
>
> For the non-technical view, see [`business_overview.md`](business_overview.md).

---

## 1. Architecture at a glance

ClassifyOS is three layers. The golden rule is that **each layer wraps the one below and adds
no logic that belongs lower down.**

```
   Browser (React SPA)          You configure a run in the browser…
        │  HTTP  /api/v1/…
        ▼
   FastAPI backend              …it is POSTed to the API, which validates it and…
        │  in-process call  (or hands off to a Databricks Job)
        ▼
   Python ML engine             …the pure-Python engine executes the pipeline and
   ("classifyos")               returns JSON results that populate the charts/tables.
```

- **React frontend** — a single-page app; a pure HTTP client of the API. Contains **no ML
  logic**.
- **FastAPI backend** — a thin translator: HTTP in, calls the engine, JSON out. **Adds no ML**
  — "the CLI, but the caller is a browser." It is **stateless** (no model or session is held
  between requests).
- **Python ML engine (`classifyos`)** — the real work. It has **no web dependencies**: it is
  importable and runnable standalone via a CLI, and packaged as an installable wheel so it can
  run on a Databricks cluster unchanged.

The `/api/v1/run` request/response schema is a **locked contract** (`docs/api_contract.md`);
the frontend's typed client mirrors it exactly.

---

## 2. Repository layout

```
frontend/            React (Vite + TypeScript) dashboard — ~13 pages, shadcn/ui, Recharts, typed API client
backend/
  classifyos/        The ML engine — the "16 sections" + tuning + explainability, split into modules
  api/               FastAPI layer — routes, request/response models, serializers
  tests/             pytest — a test file per section + API tests
prompts/             Archived generation prompts (governance record), by surface
docs/                All documentation (this file lives in docs/documentation/)
```

The **logical-section → physical-module map** (which file implements each pipeline stage) is
maintained in [`../../CLAUDE.md`](../../CLAUDE.md) — the canonical reference for where things
live. Start there before hunting through the tree.

---

## 3. Non-negotiable design rules

These are the constraints that keep ClassifyOS correct and trustworthy. They are enforced by
design and by tests; **do not violate them** (full statements in
[`../../CLAUDE.md`](../../CLAUDE.md)):

1. **No data leakage.** Every statistic (encoder, scaler, imputer, balancing, feature
   engineering, tuning) is learned from the **training split only** and merely applied to the
   test split. The test set is never modified. This is the single most important invariant.
2. **Sections are additive.** A later stage never edits an earlier one. New models are added
   **only** via the model registry, never by editing existing wrappers.
3. **All I/O goes through the storage abstraction.** No hardcoded paths, no direct `open()` in
   pipeline code — this is what lets the same engine read/write local folders *or* Databricks
   Unity Catalog volumes with no code change.
4. **The API contract is locked.** Changes to `/api/v1/run` must be **additive** and bump the
   schema version. The frontend is generated against it.
5. **The API is stateless and wraps the engine.** It never re-implements ML; it never assumes
   a previous request's state survives.
6. **One source of truth for curve points.** ROC/PR curve coordinates are computed once
   (`evaluation/curves.py`) and shared by the saved chart and the interactive chart, so the
   PNG and the JSON can never disagree.
7. **`[RISK]` comments** mark known risk points (leakage, imbalance, calibration, threshold
   sensitivity, …) in the code and must not be removed without documented rationale.

---

## 4. What's built — capability map

A compact inventory. For the full, plain-language, feature-by-feature story of each surface,
read the **short-description** docs (they are the best next stop after this one).

### ML engine — `backend/classifyos/`
→ detail: [`../reference/backend_short_desc.md`](../reference/backend_short_desc.md)

- **Full pipeline:** inspect → load → rank feature impact → split → preprocess (impute /
  outliers / encode / scale) → engineer features → balance (train-only) → train → evaluate →
  predict → plot, orchestrated by `ModelRunner`, runnable via a **CLI**.
- **Six model algorithms** behind one interface: Logistic Regression, Random Forest, XGBoost,
  LightGBM, SVM, Naive Bayes.
- **Three problem types:** binary, multiclass, multilabel.
- **Imbalance handling:** SMOTE / undersample / class-weight / none (train-only).
- **Optional hyperparameter tuning** (Optuna) — off by default, leakage-safe (CV inside the
  training split), with a hard per-model time cap.
- **Honest evaluation:** F1-weighted is primary; MCC and PR-AUC alongside accuracy on
  imbalanced problems; train-vs-test gap reported to expose overfitting.
- **Calibration & decision-threshold policy** (default / fixed / auto-tuned).
- **Explainability:** per-row **SHAP** waterfalls for all six models, plus optional
  **Azure OpenAI reason-code narratives** in plain language. Both opt-in.
- **Feature importance** two ways: model-native and model-agnostic (permutation).
- **User-defined structured features** built from a **fixed allowlist of operations** (never
  an evaluated formula string — a deliberate safety boundary).
- **Run recording (MLflow):** optional logging of config, metrics, artifacts, and saved
  models; runs can be reloaded later.

### API — `backend/api/`
→ detail: [`../reference/api_short_desc.md`](../reference/api_short_desc.md) ·
contract: [`../api_contract.md`](../api_contract.md)

- Endpoints under `/api/v1/`: `health`, `upload`, `run`, `outputs` (incl. run-scoped),
  `runs` (list/reload from MLflow), and the Databricks/input-source pickers.
- **Two execution modes** (see §5), chosen by one environment variable.
- Reuses the engine's own validation, so rules can't drift between layers; bad requests get a
  precise `422`.

### Frontend — `frontend/`
→ detail: [`../reference/frontend_short_desc.md`](../reference/frontend_short_desc.md)

- ~13 pages: Upload, Data Profile, Configuration, Overview, Feature Impact, Confusion Matrix,
  Class Report, ROC/PR Curves, Predictions, Tuning Results, Explainability, and reference
  pages (Setup Guide, Risk Register).
- shadcn/ui + Tailwind design system (one token block re-skins the app); Recharts for charts.
- A **typed API client** that mirrors the locked contract exactly.

---

## 5. Execution modes and data sources

**Execution mode** is the single biggest operational choice, set by
`CLASSIFYOS_EXECUTION_BACKEND`:

| Mode | What happens | When to use |
|---|---|---|
| **`local`** (default) | The full pipeline runs **in-process** in the backend. A `/run` can take minutes. | Dev, demos, small data. |
| **`databricks`** | `/run` submits a **Databricks Job** and returns a `job_id`; the UI polls for status/results. Compute + storage live on Databricks. | Production, large/bursty data. |

**Data sources** for a run: an uploaded file (CSV/Excel/Parquet), a **Postgres** table/query,
or a **Databricks Unity Catalog** table. All three arrive at the pipeline through the same
path, so the engine treats them identically.

Deep dives:
[`../databricks_how_it_works.md`](../databricks_how_it_works.md) (end-to-end),
[`../databricks_integration.md`](../databricks_integration.md) (design & phased roadmap),
[`../databricks_wisdom.md`](../databricks_wisdom.md) (gotchas).

---

## 6. Running and operating

Point-and-follow guides already exist — use these rather than reconstructing setup:

- **First time on a new machine:** [`../getting-started/FIRST_RUN.md`](../getting-started/FIRST_RUN.md)
- **Run the full stack (web + API) locally:** [`../getting-started/RUN_FULL_SYSTEM.md`](../getting-started/RUN_FULL_SYSTEM.md)
- **Engine via the CLI (no web server):** [`../runbooks/RUNBOOK.md`](../runbooks/RUNBOOK.md)
- **Operate the API layer:** [`../runbooks/API_RUNBOOK.md`](../runbooks/API_RUNBOOK.md)
- **Deploy on AKS (DevOps handoff):** [`../deployment/deploy.md`](../deployment/deploy.md)

Environment is configured via `backend/.env` (`DATA_DIR`, `OUTPUT_DIR`, `CORS_ORIGINS`, the
Databricks/MLflow vars); `backend/.env.example` is the annotated template.

---

## 7. Testing & governance

- **Tests:** `pytest` (backend, ~500 tests — one file per section + API), `vitest` (frontend
  render/unit), and **Playwright** browser E2E (real browser → live API → engine → rendered
  charts). Databricks/MLflow calls are mocked, so CI never touches a live workspace.
- **Governance record:** every generated section's exact prompt is archived under `prompts/`;
  library calls are **hallucination-checked** against installed versions before use; the v1.0
  sign-off dossier is [`../governance_signoff_v1.0.md`](../governance_signoff_v1.0.md).
- **Live status:** [`../../PROJECT_STATE.md`](../../PROJECT_STATE.md) is the running log of
  what's done, decisions, known issues, and next steps; [`../../plan_tweak.md`](../../plan_tweak.md)
  is the honest register of deviations from the original plan.

---

## 8. How the project could be taken forward

The two forward-looking design docs are the authoritative source — read them before starting
any of this work:

- [`../enabling_parallelization.md`](../enabling_parallelization.md) — parallelism & large-data
  plan (priority-ordered, with a dependency graph and *"what is / isn't needed for this
  cluster"*).
- [`../databricks_integration.md`](../databricks_integration.md) — the phased Databricks
  roadmap.

The highest-value opportunities, grouped:

### 8a. Run faster / models in parallel
- **Train the requested algorithms concurrently.** Each *tree* model already uses all CPU
  cores within itself (`n_jobs=-1` on RandomForest/XGBoost/LightGBM), but the requested
  algorithms are currently trained **one after another** in `ModelRunner`. They are
  independent, so training them in parallel (a process/thread pool) is a direct wall-clock
  win with no change to results.
- **Parallel hyperparameter tuning.** Optuna trials run sequentially today; its ask/tell
  interface with a shared study lets several trials run at once (4–8 is the sweet spot). See
  `enabling_parallelization.md` §7.
- **Cross-node parallelism** (`joblibspark`, `SparkTrials`) — only worthwhile once the cluster
  grows beyond a couple of workers; documented as *deferred* for the current cluster size.

### 8b. Handle large datasets
- **Balancing at scale.** SMOTE is O(n²) on the training set and will not scale to millions of
  rows — switch to random oversampling / borderline-SMOTE-on-a-sample / `class_weight` above a
  row threshold (`enabling_parallelization.md` §5).
- **Profiling at scale.** Sample rather than full-scan for the data profile on very large
  tables (partially in place for the Databricks sampled profile; generalise it).
- **Data larger than a single machine's memory** — adopt Spark-backed dataframes
  (`pyspark.pandas`) only if data outgrows the driver; not needed at current scale.
- **Artifact lifecycle** — large models/plots accumulate; add a retention/TTL policy and lean
  on the model registry for versioned storage.
- **Cost & safety guardrails** — job timeouts, a cancel endpoint, and DBU-usage reporting for
  runaway runs (`enabling_parallelization.md` §10–12).

### 8c. Product & model depth
- **Deploy on AKS** — the immediate next milestone (guide already written; see
  [`../deployment/deploy.md`](../deployment/deploy.md)).
- **Real-data revalidation** — all metrics to date are on synthetic data; re-validate on real
  business data before live use.
- **Real-time `/explain` on stored models (v2.0)** — explanations are computed *during* a run
  today; a stateless per-request explanation endpoint needs a model store/registry.
- **Per-label thresholds & imbalance weighting for multilabel** — a documented v1.x refinement.

---

## 9. Known limitations / open items

Kept honest and current in [`../../PROJECT_STATE.md`](../../PROJECT_STATE.md) (Known issues /
Next steps). At the time of writing:

- **Synthetic data only** so far — real-data revalidation pending.
- **Human sign-off pending** — engineering is v1.0-complete; formal review/demo/sign-off and
  the `v1.0` tag remain.
- **Local-mode `/run` is synchronous** — long runs can approach a gateway timeout; the
  **Databricks (submit→poll)** mode is the answer for heavy workloads.
- A sample dataset showed **suspected target leakage** (perfect scores) — flagged for a data
  review, not a code bug.

---

## 10. Key references (start here, then go deep)

| Document | What it's for |
|---|---|
| [`../../CLAUDE.md`](../../CLAUDE.md) | Conventions, hard rules, the section→module map, the environment record. |
| [`../../PROJECT_STATE.md`](../../PROJECT_STATE.md) | Live status: done, decisions, known issues, next steps. |
| [`../README.md`](../README.md) | The full documentation index (everything, categorised). |
| [`../api_contract.md`](../api_contract.md) | The **locked** `/api/v1/run` schema. |
| `../reference/*_short_desc.md` | Plain-language, feature-by-feature summaries (engine / API / frontend). |
| [`../enabling_parallelization.md`](../enabling_parallelization.md) | The parallelism & large-data roadmap. |
