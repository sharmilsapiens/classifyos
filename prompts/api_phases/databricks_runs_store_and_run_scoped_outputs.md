# Databricks Runs dashboard fix — read-path store routing + run-scoped artifact serving

> Archived generation prompt (governance requirement, CLAUDE.md). Surface: **API + frontend**
> (FastAPI read/serve path + React artifact URLs). Session date: 2026-07-23. Resolves
> `docs/databricks_wisdom.md` §6.1 and §6.2. No engine/notebook/wheel change.

---

ClassifyOS is a GenAI-developed ML classification framework for the insurance domain: it predicts
categorical outcomes (lapse, fraud, risk tier, etc.) from tabular data. Three layers — React frontend →
FastAPI backend → pure-Python ML engine. The engine cleans, engineers features, balances classes, trains
and compares multiple models (with optional Optuna tuning), and reports the best one; results surface in a
dashboard.

Before doing anything, read PROJECT_STATE.md and the relevant *_short_desc.md for the surface(s) you're
touching (backend_short_desc.md / api_short_desc.md / frontend_short_desc.md), plus CLAUDE.md for the hard
rules. Also check bugs.md and docs/databricks_integration.md if the task relates to known issues or the
Databricks/MLflow roadmap.

Respect the project's constraints: no data leakage (fit on train only); additive changes only (don't
rewrite earlier sections — new models via the registry, new capabilities behind flags); all file I/O
through StorageAdapter (no hardcoded paths); the /api/v1/run contract is LOCKED — additive-only with a
schema_version bump, and update docs/api_contract.md. New optional dependencies follow the opt-in /
lazy-import / report-only discipline of shap/optuna/mlflow (OFF by default, imported only when used, never
abort a run on failure).

My task:

Fix the Databricks "Runs" dashboard so it works end-to-end when the deployment uses the Databricks
execution backend (CLASSIFYOS_EXECUTION_BACKEND=databricks). FIRST read docs/databricks_wisdom.md — its
§6.1 and §6.2 describe these exact two issues with the diagnosis and a suggested direction — and
docs/databricks_how_it_works.md. Then investigate the read/serve path and come up with + implement a
solution.

Two problems, both only when running on Databricks:

1. The "Runs" tab shows "No past runs yet" and displays "Tracking store:
   postgresql://classifyos:classifyos@localhost:5432/mlflow" — i.e. it is reading the LOCAL Postgres
   MLflow store, not the Databricks-managed MLflow the cluster actually logs runs to. So a user never sees
   their Databricks runs. (Runs execute and log on Databricks; the FastAPI read-path reads the wrong store.)

2. Even when a run's results render, a Databricks run's ARTIFACT FILES — the matplotlib PNG plots and the
   downloadable CSVs — do not display: the plot images are broken and the CSV download links 404. The
   interactive/JSON-driven charts are fine; only the artifact files served via /outputs are broken.

Expected outcome: in the Databricks backend, the Runs tab lists and reloads the REQUESTING USER's own runs
from Databricks-managed MLflow, and a run's artifacts (PNGs/CSVs) display in the dashboard for both a fresh
run and a run reloaded from the Runs tab. The LOCAL backend must stay byte-identical to today. Keep it
thread-safe (no per-request global/env or mlflow.set_tracking_uri mutation under the shared server),
additive, and CI-mockable (no live workspace in tests). This should be API + frontend only — no
engine/notebook/wheel change (so no cluster restart to deploy; just a FastAPI restart + frontend rebuild).
Relevant files to investigate: api/mlflow_read.py, api/routes/runs.py, api/routes/outputs.py, and the
frontend PngArtifact component + outputUrl helper + the Runs page.

When done:
- Run the relevant tests and make sure they pass (add tests for new behavior; CI must not depend on live
  external services — mock/stub them).
- Verify end-to-end where it makes sense (a real run / the affected flow).
- Update PROJECT_STATE.md and the appropriate *_short_desc.md; update docs/api_contract.md if the contract
  changed.
- Update the appropriate docs/databricks_*.md files (databricks_how_it_works.md and docs/databricks_wisdom.md
  as relevant).
- Update plan_tweak.md only if this genuinely deviated from the plan — don't invent entries.
- Do a hallucination check on any library calls against the installed version.
- Archive this session's generation prompt under prompts/ (per CLAUDE.md, in the right surface subfolder)
  in the same commit as the code.

Two notes:
- docs/databricks_wisdom.md is currently uncommitted (untracked). Since you'll reference it from the new
  session on this same working copy, it'll be read fine as-is — but say the word and I'll commit it so it's
  durable/travels.
- The wisdom doc already records the recommended fix direction for both issues (per-call
  tracking_uri="databricks" for the read; run-scoped /outputs/{run_id}/{name} from MLflow) — I framed the
  prompt so the new session reads it, validates, and implements, rather than me pre-baking the solution.

---

## What was implemented (summary)

**§6.1 — read-path store routing (`backend/api/mlflow_read.py`).** Added `_tracking_uri()` → `"databricks"`
when `execution_backend()=="databricks"`, else `None`. `_client()` builds
`MlflowClient(tracking_uri="databricks")`; `list_runs` reports `"databricks"`; `load_run` passes
`tracking_uri=_tracking_uri()` to `download_artifacts` — all per-call, no process-global
`set_tracking_uri` (thread-safe). Local backend unchanged. **Follow-up (same session):** live Databricks then
hit `Too many experiment_ids … Maximum 100. Found 185`, so `list_runs` now scopes the databricks search to
the ClassifyOS experiment (`_is_classifyos_experiment`; override `CLASSIFYOS_MLFLOW_EXPERIMENT`, default
`classifyos` → `/Shared/classifyos`) before `search_runs`; local searches all experiments (unchanged).

**§6.2 — run-scoped artifact serving.** `mlflow_read.load_artifact(run_id, name)` downloads
`classifyos/{name}` from the MLflow run (`download_artifacts(run_id, artifact_path=…,
tracking_uri="databricks")`); new route `GET /api/v1/outputs/{run_id}/{name}` (`routes/outputs.py`):
databricks → stream from MLflow, local → serve `OUTPUT_DIR` by name (`run_id` ignored, byte-identical),
bare-filename traversal guard (400), 404/503 mapping. Frontend: `outputUrl(name, runId?)` +
`runScopedArtifactId(mlflow)` (run-scoped only when `mlflow.tracking_uri` starts with `"databricks"`);
`PngArtifact` gained a `runId` prop; threaded through Overview / Curves / FeatureImpact / Interactions /
Predictions. Run id from `result.mlflow.run_id` (present fresh + reloaded). **Demo follow-up (same
session):** the databricks run-scoped response is `Cache-Control: … immutable` (run artifacts are
write-once), and the store prefetches a run's plot PNGs on load (`new Image()`, in `pollOnce` COMPLETED +
`applyReloadedRun`) so result tabs render instantly with no per-tab download — the "cache/store on the
frontend" is the browser's own cache; local `/outputs/{name}` stays uncached.

**Constraint honored:** API + frontend only (no engine/notebook/wheel change); additive with no
`schema_version` bump (the `/outputs` family carries none); thread-safe (per-call `tracking_uri`); local
backend byte-identical; all MLflow/Databricks mocked in CI (plus one real-store round-trip). Hallucination
check: mlflow 3.14.0. No plan_tweak entry (followed the wisdom doc's recorded fix direction — no deviation).
