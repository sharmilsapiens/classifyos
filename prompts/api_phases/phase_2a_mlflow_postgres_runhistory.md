ClassifyOS is a GenAI-developed ML classification framework for the insurance domain: it predicts categorical outcomes (lapse, fraud, risk tier, etc.) from tabular data. Three layers — React frontend → FastAPI backend → pure-Python ML engine. The engine cleans, engineers features, balances classes, trains and compares multiple models (with optional Optuna tuning), and reports the best one; results surface in a dashboard.

Before doing anything, read PROJECT_STATE.md and the relevant short_desc file(s) for the surface you're touching (backend_short_desc.md / api_short_desc.md / frontend_short_desc.md), plus CLAUDE.md for the hard rules. Respect the project's constraints: no data leakage (fit on train only), additive changes (don't rewrite earlier sections), StorageAdapter for all I/O, and the locked API contract.

My task:

Implement Interim Phase 2a of docs/databricks_integration.md §6.5 — read that doc first (Phase A / MLflow logging is already merged: commit 876ba7b, schema 1.9). This is local-only; no Databricks, no push.

- Move MLflow's backend store from the local default to a local Postgres (postgresql://…), keeping the artifact store a local folder. This must be configuration only — the Phase-A logging code in classifyos/mlflow_logging.py must not change; the store is selected by env vars (MLFLOW_TRACKING_URI / backend-store URI + artifact root), which Phase A already made swappable. Add pinned psycopg2-binary to requirements.txt (MLflow's SQLAlchemy backend driver).
- Add a read path so the persistence is visible: FastAPI endpoint(s) to list past runs and reload a single run (querying MLflow), and a "Runs" view on the dashboard that lists past runs and reloads one into the existing result pages. This is the payoff — results now survive a browser refresh and a server restart.
- API changes are additive only: new endpoints, schema_version bump per the locked-contract rule, /run and all existing fields unchanged; update docs/api_contract.md.
- Document the Postgres + artifact-root env vars in backend/.env.example (commented; .env stays gitignored and machine-local, same convention as DATA_DIR/OUTPUT_DIR).
- If a local Postgres isn't running yet, help me stand one up first (Docker postgres is fine) and create the database before wiring anything.
- Hallucination check first: verify the MLflow backend-store URI form and the psycopg2 driver against the installed MLflow 3.14.0 before coding.
- Verify: run two pipelines with MLflow ON; confirm both appear as rows in Postgres with params/metrics and their artifacts on disk; confirm the dashboard "Runs" view lists them and reloads either one after a full page refresh.

Out of scope (later): Interim 2b Postgres input source, Phase B DatabricksVolumeStorage, Phase C Model Registry/Serving, and the /explain→persisted-model wiring.

When done: run the relevant tests and make sure they pass, then update PROJECT_STATE.md and the appropriate short_desc file(s) to reflect what changed. Update plan_tweak.md only if this genuinely deviated from the plan — don't invent an entry. Do a hallucination check on any library calls against the installed versions.
