# Per-user Runs from Databricks MLflow (read-path)

**Surface:** API read-path (`/runs`) + engine MLflow tagging + frontend Runs page.
**Session:** 2026-07-23. Follows the Databricks orchestration (§6.6 Step 6) and the
envelope-in-the-wheel refactor (`classifyos.envelope`).

## Goal
The dashboard's **Runs** tab must list/reload the CALLER'S OWN runs from Databricks-managed MLflow
(not the local store), thread-safely, without leaking other users' runs.

## Approach (as executed)
Filter by a stable EMAIL tag; the SERVICE token authenticates the MLflow read (constant,
process-level); the user PAT only resolves identity per request (SCIM). No per-request env mutation
(that would be thread-unsafe under concurrent users — the whole point of the tag-filter design).

1. **Write side (engine + notebook).** Move the snapshot constants (`SNAPSHOT_*`) + a new
   `USER_EMAIL_TAG` into `classifyos.mlflow_logging`; add `snapshot_envelope(run_id, envelope,
   user_email=None)` (log the `/run` envelope artifact + set the reloadable tag + the owner tag) as
   the SINGLE source. `api.mlflow_read.snapshot_result` delegates to it. The Databricks Job notebook
   (Cell 5) calls it after the run so the run is attributable + reloadable from the wheel alone.
2. **Read side (API).** `mlflow_read.list_runs(user_email=None)` adds a backticked tag
   `filter_string` when scoped; `load_run(run_id, user_email=None)` treats another owner's run as
   `RunNotFound`. `routes/runs.py` resolves the caller's email from `X-Databricks-Token` via SCIM
   when `execution_backend()=="databricks"`; a missing/expired PAT → 401 (UI prompts). Local backend
   is byte-identical (no PAT, no filter).
3. **Frontend.** `listRuns(pat?)`/`loadRun(runId, pat?)` send the PAT; the Runs page prompts for the
   PAT when on Databricks without one (reuses the in-memory `databricksPat`, never stored).

## Constraints honored
- No `/run` contract or `schema_version` change (additive request header + server-side filter).
- Thread-safe (service-token read; per-request work is only a SCIM lookup + a filter string).
- CI mocks all MLflow/Databricks calls — no live workspace/store.
- Deploy: the FastAPI process needs `MLFLOW_TRACKING_URI=databricks` + `DATABRICKS_HOST`/
  `DATABRICKS_TOKEN` (service) for the Runs read; the service identity needs READ on the experiment.

## Routine
Tests for new behavior (external services mocked), hallucination-check the MLflow calls against the
installed version (mlflow 3.14.0 — `search_runs(filter_string=…)` + backticked dotted tag key
verified), update PROJECT_STATE / *_short_desc / the databricks docs / plan_tweak, and archive this
prompt in the same commit as the code.
