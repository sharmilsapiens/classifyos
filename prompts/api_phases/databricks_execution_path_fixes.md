@..\docs\databricks_how_it_works.md 

You are working on ClassifyOS — a GenAI-developed ML classification framework (insurance domain).
Read docs/databricks_how_it_works.md before doing anything else. That file explains the full
Databricks integration as it stands: architecture, env vars, UC volume layout, notebook flow,
result-fetch flow, and known issues. Also read docs/databricks_integration.md for broader context
and PROJECT_STATE.md for overall progress.

This session fixes four interconnected problems with the Databricks execution path. All changes
are in the backend — no frontend changes needed. We are on branch main.

---

## Background: how the current flow works

POST /api/v1/run → FastAPI submits a Databricks Job (notebooks/classifyos_job_runner.py) →
notebook runs on cluster, writes output to /Volumes/aiml_rd/classifyos/output/api/run_response.json
→ GET /api/v1/run/{job_id}/results → FastAPI fetches that file via Databricks Files API →
dashboard renders it.

The notebook is at:
  /Workspace/Users/sharmil.basa@sapiens.com/classifyos/notebooks/classifyos_job_runner
  (or /Repos/... if Databricks Repos has been set up — prefer Repos)

---

## Problem 1 — Results not shown in dashboard ("Could not fetch the run results")

The job completes successfully on the cluster and writes api/run_response.json to the UC output
volume. FastAPI (backend/api/routes/jobs.py, get_results_endpoint) fetches this file via
fetch_uc_file() (backend/api/databricks.py). Despite this, the frontend shows "Could not fetch
the run results."

Diagnose and fix. Likely causes to check:
a) The UC path being built: DBRICKS_OUTPUT_VOLUME + "/" + RESULT_ENVELOPE_KEY may not match
   where the notebook actually wrote the file. Log/print the exact path being fetched.
b) The notebook's Cell 5 uses storage.path_for(RESULT_ENVELOPE_KEY, output=True) which returns
   the local POSIX path (/Volumes/aiml_rd/classifyos/output/api/run_response.json). The Files API
   URL must be /api/2.0/fs/files + that same POSIX path. Verify they match exactly.
c) The simplified envelope Cell 5 writes ({status, mlflow_run, metrics, best_model,
   artifacts_written}) is not the locked /run schema the frontend expects. The frontend will
   either render blank or throw. Fix by either:
   - Option A (preferred if Databricks Repos is set up): in Cell 5, import
     api.result_builder.build_run_result and write the full locked envelope. The notebook's
     Cell 3 already adds backend/ to sys.path when running from a Repo.
   - Option B (fallback): in get_results_endpoint, reshape the simplified envelope into the
     locked schema before returning it to the frontend. The locked schema lives in
     docs/api_contract.md.
   Choose whichever is practical given the current setup and document the choice.

---

## Problem 2 — Each new run overwrites the previous run's results

Currently every job writes to the same fixed path:
  /Volumes/aiml_rd/classifyos/output/api/run_response.json

So when a second run starts, the first run's results are gone. Fix by namespacing output paths
per job_id or Databricks run_id.

Design:
- FastAPI passes the job_id (UUID) as a base_parameter to the notebook.
- The notebook writes to:  api/{job_id}/run_response.json  and all other artifacts
  (plots, CSVs, run_profile.json) under  artifacts/{job_id}/
- RESULT_ENVELOPE_KEY in both jobs.py and the notebook must use the same per-job path.
- get_results_endpoint already has job_id — use it to build the correct UC path.
- DatabricksVolumeStorage.path_for() may need a run_id prefix concept, or the notebook
  can just construct paths directly using os.path.join(OUTPUT_BASE, job_id, ...).
- The local (non-Databricks) path also uses OUTPUT_DIR from storage — keep it unchanged
  for local runs (they are single-tenant and job isolation is not needed there yet).

---

## Problem 3 — Models are not saved in Databricks mode

In local mode, ModelRunner saves the trained model artifacts (pickled models, feature importance
files, etc.) to OUTPUT_DIR via the StorageAdapter. In Databricks mode the StorageAdapter is
DatabricksVolumeStorage (pointing at the UC output volume), so models should already be written
there. Investigate:
a) Confirm that classifyos.runner.ModelRunner actually calls storage.save_artifact() (or
   equivalent) for the best model, and that DatabricksVolumeStorage implements that method.
b) If the method exists but the path is wrong, fix the path (use the per-job namespace from
   Problem 2).
c) If the method is missing from DatabricksVolumeStorage, implement it — it should write
   the bytes/file to /Volumes/aiml_rd/classifyos/output/artifacts/{job_id}/{filename}.
d) Ensure the saved model file (pickle or joblib) is accessible so MLflow can log it (Problem 4).

---

## Problem 4 — MLflow integration: metrics, models, artifacts must be logged to Databricks MLflow

The cluster already has MLFLOW_TRACKING_URI=databricks and MLFLOW_REGISTRY_URI=databricks-uc
(set in notebook Cell 3). However the runner may not be starting an MLflow run, or may be
logging to the wrong tracking URI.

Fix and integrate:
a) In notebooks/classifyos_job_runner.py Cell 4 (before runner.run()), start an explicit
   MLflow run:
     import mlflow
     mlflow.set_experiment("/classifyos/runs")  # Databricks workspace experiment path
     with mlflow.start_run(run_name=f"classifyos-{job_id}") as mlflow_run:
         runner.run()
         # log metrics, params, model below
b) After runner.run(), log to MLflow:
   - mlflow.log_metrics(runner.metrics_dict_)  — all evaluation metrics
   - mlflow.log_params({"model": runner.best_model_name_, "target": engine_config.target, ...})
   - mlflow.sklearn.log_model(runner.best_estimator_, "model",
       registered_model_name="classifyos.classifyos_model")  — logs to UC model registry
   - mlflow.log_artifacts(str(storage.output_dir), artifact_path="artifacts")  — plots + CSVs
c) Check what attributes ModelRunner exposes post-run (metrics_df_, best_model_name_,
   best_estimator_, etc.) — read backend/classifyos/runner.py to confirm exact attribute names.
d) Include the mlflow_run_id in the result envelope so the dashboard can link to the MLflow UI.

Permission fallback design (important — user may not have all UC/registry permissions yet):
- Wrap the mlflow.sklearn.log_model + registered_model_name call in try/except. If it fails
  with a PermissionError or MlflowException, fall back to mlflow.sklearn.log_model without
  registered_model_name (still logs the model artifact, just not to the registry). Log a warning.
- Wrap mlflow.set_experiment in try/except — if the experiment path cannot be created (no
  permission), fall back to mlflow.set_experiment("/classifyos-fallback") or use the default
  experiment. Never let an MLflow permission failure abort the training run.
- Document these fallbacks with comments so the user can remove them once permissions are granted.

---

## Problem 5 — Model Registry: models must be deployable from Databricks Model Registry

Design the model logging so models can be served from Databricks Model Registry (Unity Catalog).

Requirements:
- Models are logged with mlflow.sklearn.log_model(..., registered_model_name=
  "aiml_rd.classifyos.classifyos_model") — the three-part UC name (catalog.schema.model).
- Each run logs as a new version. The "best model" is the one with the highest f1_weighted.
- Add a model alias "champion" or "production" after a successful run (via
  mlflow.MlflowClient().set_registered_model_alias(...)) so it can be loaded by alias.
- Wrap this in try/except with a fallback to just logging the model without aliasing (in case
  permissions are not granted yet).
- Do not hardcode a stage ("Staging"/"Production") — Unity Catalog model registry uses aliases,
  not stages.
- After completing this, add a comment in docs/databricks_how_it_works.md § "What is NOT done
  yet" removing the model-registry item and noting what was done.

---

## Constraints

- No data leakage: encoder/scaler/SMOTE are still fitted on training split only. These fixes are
  orchestration-layer changes — never touch the ML pipeline internals.
- API contract is locked (schema_version 1.0, docs/api_contract.md). Additive fields only.
- All file I/O through StorageAdapter — never call open() directly in pipeline code, except in
  the notebook (which is tooling, not pipeline code).
- Read PROJECT_STATE.md and CLAUDE.md before writing any code.
- After completing all fixes, update PROJECT_STATE.md and docs/databricks_how_it_works.md to
  reflect what was fixed, what remains, and any new known issues.

Tackle the problems in order: 1 → 2 → 3 → 4 → 5. Test each fix by tracing the code path
before moving to the next. Do not create new files unless necessary — edit existing ones.
