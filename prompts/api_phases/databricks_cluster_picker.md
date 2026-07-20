You are working on ClassifyOS — a GenAI-developed ML classification framework.
Read CLAUDE.md, PROJECT_STATE.md, and docs/databricks_how_it_works.md before writing any code.
Also read docs/api_contract.md — the /run schema is LOCKED (schema_version 1.0, additive only).

## Task: cluster picker — select a Databricks cluster from the UI at run time

Currently DATABRICKS_JOB_CLUSTER_ID in backend/.env is the only way to set which cluster
a training job runs on. Add the ability to pick a cluster from a dropdown in the UI.
The env var must remain as the fallback — nothing breaks if the new field is absent.

## What to build (three parts, in order)

### Part 1 — API endpoint: list available clusters

In backend/api/routes/databricks.py, add:
  GET /api/v1/databricks/clusters

Authenticated with the user's PAT (X-Databricks-Token header, same pattern as the
existing /catalogs, /schemas, /tables endpoints in that file).
Calls GET {DATABRICKS_HOST}/api/2.0/clusters/list on Databricks.
Returns only clusters that are in a usable state: RUNNING or TERMINATED (can be restarted),
NOT TERMINATING, ERROR, or UNKNOWN.
Response shape:
  { "clusters": [ { "cluster_id": "...", "cluster_name": "...", "state": "RUNNING" }, ... ] }
Filter to clusters the user can actually submit jobs to — check spark_context_id is present
or state in ("RUNNING", "TERMINATED"). Sort by cluster_name.

Add the matching function in backend/api/databricks.py:
  def list_clusters(user_pat: str) -> list[dict]
Same pattern as list_catalogs / list_schemas / list_tables — uses _build_client + _request,
raises DatabricksAuthError / DatabricksUnavailable on failure.

### Part 2 — pass cluster_id through the run config

In backend/api/models.py (RunConfig Pydantic model), add:
  cluster_id: str | None = None

In backend/api/routes/run.py (the Databricks branch of POST /api/v1/run), when calling
submit_run(), extract cluster_id from the validated RunConfig and pass it through.

In backend/api/databricks.py, update _submit_payload() to accept an optional cluster_id
parameter. If provided and non-empty, it overrides the env var. If absent/empty, fall back
to os.environ.get("DATABRICKS_JOB_CLUSTER_ID") as today. Raise DatabricksConfigError if
neither is set (existing behaviour).

This is an ADDITIVE change to the locked /run schema (new optional field, ignored locally).
Note it as additive in any doc update.

### Part 3 — UI dropdown in the run config form

The run config form lives in the frontend. Find the Databricks-specific section of the
run config form (where the user picks the data source table etc.).
Add a "Cluster" dropdown that:
- Do NOT change any existing endpoint signatures or response shapes (api_contract.md is locked).
- cluster_id: null in the run payload must be handled gracefully — falls back to env var.
- The env var fallback must still work with no UI changes (server-only deployments).
- The local (non-Databricks) execution path must be completely unaffected.
- Follow existing code patterns exactly: same error types, same PAT header name, same route
  registration style as the other /databricks/* endpoints.
- Type hints + docstrings on every new public function.
- After completing, update PROJECT_STATE.md with what was added.
- Do NOT update docs/databricks_how_it_works.md — that file is maintained separately.

## Key files to read before coding
- backend/api/databricks.py — list_catalogs/schemas/tables pattern to follow exactly
- backend/api/routes/databricks.py — how routes are wired, PAT extraction
- backend/api/models.py — RunConfig shape
- backend/api/routes/run.py — how Databricks branch handles the run payload
- docs/api_contract.md — locked schema (additive only)
- frontend/ — find the run config form component before writing any UI code
