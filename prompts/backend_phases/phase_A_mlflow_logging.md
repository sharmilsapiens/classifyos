ClassifyOS is a GenAI-developed ML classification framework for the insurance domain: it predicts categorical outcomes (lapse, fraud, risk tier, etc.) from tabular data. Three layers — React frontend → FastAPI backend → pure-Python ML engine. The engine cleans, engineers features, balances classes, trains and compares multiple models (with optional Optuna tuning), and reports the best one; results surface in a dashboard.

Before doing anything, read PROJECT_STATE.md and the relevant short_desc file(s) for the surface you're touching (backend_short_desc.md / api_short_desc.md / frontend_short_desc.md), plus CLAUDE.md for the hard rules. Respect the project's constraints: no data leakage (fit on train only), additive changes (don't rewrite earlier sections), StorageAdapter for all I/O, and the locked API contract.

My task:

Implement Phase A of docs/databricks_integration.md §6 — read that doc first; it is the design of record for this work. Add an opt-in MLflow logging + model-persistence layer to the ML engine, logging to a local ./mlruns folder this session (no Databricks, no Postgres yet).

- Add the MLflow layer to ModelRunner following the exact discipline already used for shap/optuna/openai: OFF by default, import mlflow lazily only when enabled, every failure path report-only so it never aborts a run.
- Gate it behind a new default-False config flag (mirror how explainability.enabled is validated in config.py), forwarded through the API via build_config (the authoritative validator → bad value = 422).
- After training (no leakage surface — logging reads nothing back into fit/transform), log per run: log_params (the run config), log_metrics (each model's headline test metrics the runner already computes), log_artifact for the existing artifacts (the CSVs, six PNGs, run_profile.json), and log_model per fitted model with the correct flavor (mlflow.sklearn for LogisticRegression/RF/SVM/NaiveBayes, mlflow.xgboost, mlflow.lightgbm) — unwrap to the base estimator the same way feature_importance() already does for the calibration/threshold wrappers.
- All artifact reads/writes stay behind StorageAdapter; no hardcoded paths.
- API: additive only. If you surface anything in /run (e.g. an mlflow_run_id/model_uri block), bump schema_version per the locked-contract rule and update docs/api_contract.md; otherwise keep it request-side only. Do not change existing fields.
- Add pinned mlflow to backend/requirements.txt, and do the mandatory hallucination check first: verify mlflow.start_run, log_params/log_metrics/log_artifact, and the sklearn/xgboost/lightgbm log_model signatures against the installed version before writing engine code.
- Verify: run a real pipeline (e.g. policy_lapse.csv) with the flag ON, confirm an MLflow run appears under ./mlruns with params, metrics, the artifact files, and a loadable model per algorithm; confirm a flag-OFF run is byte-for-byte unchanged from before.

Out of scope (later phases — do not build): the Postgres backend store and run-history dashboard (Interim 2a), the Postgres input source (Interim 2b), the DatabricksVolumeStorage adapter (Phase B), and Model Registry / Model Serving (Phase C).

When done: run the relevant tests and make sure they pass, then update PROJECT_STATE.md and the appropriate short_desc file(s) to reflect what changed. Update plan_tweak.md only if this genuinely deviated from the plan — don't invent an entry. Do a hallucination check on any library calls against the installed versions.
