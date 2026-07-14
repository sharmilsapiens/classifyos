# Step 6 — Databricks orchestration layer (FastAPI → Databricks Jobs)

> Archived generation prompt (governance requirement). Task given to Claude Code on 2026-07-14.
> Implements `docs/databricks_integration.md` §6.6 **Step 6** (`docs/enabling_parallelization.md`
> items 1–4). **Additive + env-gated** (`CLASSIFYOS_EXECUTION_BACKEND`, default `local`): a `local`
> deployment is byte-identical to before; `databricks` switches `POST /run` to the async
> submit→poll→fetch flow. API contract bumped **`1.10 → 1.11`**. Engine sections
> (`backend/classifyos/`) UNTOUCHED.
>
> **Produced:**
> - `backend/api/databricks.py` — httpx REST client: `execution_backend()` gate, `submit_run`,
>   `get_run_status` (+ `RunState`→`PENDING|RUNNING|COMPLETED|FAILED` mapping), UC `list_catalogs`/
>   `list_schemas`/`list_tables`; `DatabricksUnavailable`/`DatabricksAuthError`/`DatabricksConfigError`.
> - `backend/api/jobs_store.py` — `classifyos_jobs` table via SQLAlchemy **Core** + `init_db`/
>   `create_job`/`update_status`/`get_job`; DSN = `CLASSIFYOS_JOBS_DSN` → MLflow Postgres → sqlite.
> - `backend/api/result_builder.py` — the `/run` reshaper (`build_run_result`) extracted verbatim
>   from `routes/run.py` (behavior-preserving) so the route AND the Job notebook share ONE reshaper.
> - `backend/api/routes/jobs.py` (`/run/{job_id}/status` + `/results`), `backend/api/routes/databricks.py`
>   (UC proxies); `routes/run.py` gated on the backend; `routes/health.py` reports `execution_backend`.
> - `backend/api/models.py` — `RunSubmission`/`JobStatusResponse`/`CatalogsResponse`/`SchemasResponse`/
>   `TablesResponse`; `SCHEMA_VERSION` → `1.11`; `InputSourceConfig` gained `catalog`/`schema`(alias)/
>   `limit` for Delta (dumped by-alias in `to_engine_config`). `deps.get_user_pat` (X-Databricks-Token).
> - `backend/api/main.py` — mount the new routers + `init_db()` at startup (databricks backend only).
> - Frontend: `api/types.ts` + `api/client.ts` (submit/status/results + UC calls; `execution_backend`
>   on health), `store/AppStore.tsx` (backend from `/health`; `runPipeline` local-sync vs
>   databricks-submit-then-poll; `POLL_INTERVAL_MS`), `pages/Overview.tsx` (polling spinner),
>   `pages/Upload.tsx` + `components/upload/DatabricksSourcePanel.tsx` (Databricks UC data-source tab).
> - `notebooks/classifyos_job_runner.py` — the Job entrypoint (tooling; runs the engine on the
>   cluster and writes the locked envelope to `api/run_response.json` on the UC output volume).
> - Tests (all mocked): `tests/test_api_jobs.py`, `tests/test_api_databricks.py`;
>   `AppStore.test.tsx` (polling state machine) + `upload.test.tsx` (data-source toggle). Version-bump
>   fixups in `test_api_run`/`test_api_runs`/`test_use_case_sweep`/`test_api_health` + conftest pins
>   the local backend. `requirements.txt` (`httpx` → runtime), `.env.example`, docs.
>
> **Verified:** backend **461** pytest green; frontend **159** vitest green; `tsc -b` + `vite build`
> clean; databricks-mode app boot + `init_db` table creation verified live. **NOT run on a real
> cluster** (Job notebook written, cluster run pending — like the Step 5 smoke test).
>
> **Hallucination check ✅** (Microsoft Learn / Azure Databricks): `POST /api/2.1/jobs/runs/submit`
> (→ `run_id`); `GET /api/2.1/jobs/runs/get` (`state.life_cycle_state`/`result_state`/`state_message`);
> `tasks[].{task_key, existing_cluster_id, notebook_task{notebook_path, base_parameters},
> libraries[{whl}]}`; `GET /api/2.1/unity-catalog/{catalogs, schemas?catalog_name=,
> tables?catalog_name=&schema_name=}`. The docs.databricks.com API reference is a JS SPA (WebFetch
> could not read raw JSON), so the client is written defensively (tolerates `SUCCESS`/`SUCCEEDED`,
> missing fields); the endpoint paths + UC param names + result-state semantics were corroborated
> against Microsoft Learn pages + the Databricks SDK code sample.
>
> **plan_tweak:** #47 (env-gated dual-mode `/run`, superseding #28's "background path deferred to
> v1.5"; owner-confirmed the env-gated interpretation over a literal "replace") and #48 (UC-table
> profiling follow-up — the browser proxies return names only).
>
> **Note on this archive:** the delivered task text below had a transmission truncation in the middle
> (Part B's table + Part C's intro were garbled — `"…submitted_at TIfrontend can populate…"`). The
> intent was unambiguous from the surrounding text and `docs/enabling_parallelization.md`, and is
> reconstructed inline in *[reconstructed]* markers; implementation followed that intent.

---

Implement Step 6 of the Databricks integration plan in `docs/databricks_integration.md` §6.6 — the
orchestration layer. Steps 1–5 are done: `DatabricksVolumeStorage`, wheel packaging, MLflow env
wiring, Delta input source, and smoke test notebook are all complete. This step wires the FastAPI
layer to Databricks Jobs and updates the UI to support Databricks as a data source.

Credentials are in `backend/.env`: `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `DATABRICKS_HTTP_PATH`.
Read `docs/api_contract.md` carefully before touching any routes — the contract is LOCKED,
additive-only with a `schema_version` bump. Check whether `httpx` is already in
`backend/requirements.txt` — add and pin it if not (hallucination-check the version).

## Part A — Async API refactor (FastAPI layer)

Files: `backend/api/routes/run.py`, new `backend/api/routes/jobs.py`

Current `POST /api/v1/run` blocks until the run completes. Replace with an async pattern —
additive, `schema_version` bump:

- `POST /api/v1/run` → submits a Databricks Job via `POST {DATABRICKS_HOST}/api/2.1/jobs/runs/submit`
  using httpx, returns `{ job_id, run_id }` immediately. Does NOT wait for completion.
- `GET /api/v1/run/{job_id}/status` → polls `GET {DATABRICKS_HOST}/api/2.1/jobs/runs/get?run_id={job_id}`,
  returns `{ status: PENDING | RUNNING | COMPLETED | FAILED, message }`.
- `GET /api/v1/run/{job_id}/results` → once status is COMPLETED, fetches result artifacts [from the UC
  volume]. *[text continues below]*

Use `DATABRICKS_HOST` and `DATABRICKS_TOKEN` from env for API calls. The user's PAT (passed in
request header `X-Databricks-Token`) is forwarded as a task parameter so the job uses it for UC data
access — never use the service token for data access. The job submission payload installs the
classifyos wheel from the UC volume and passes RunConfig as JSON task parameters.

## Part B — Persistent job state

FastAPI is stateless — a restart loses in-flight job_ids. Store state in the existing Postgres
(already used for MLflow backend store).

Create a `classifyos_jobs` table via SQLAlchemy core (not ORM) on FastAPI startup if it doesn't
exist:

```
job_id            TEXT PRIMARY KEY
databricks_run_id TEXT
status            TEXT
submitted_at      TI[MESTAMP]   -- [reconstructed: the delivered text truncated here]
-- [reconstructed] + updated_at, config_json, etc. as needed for reconnect/audit.
```

## Part C — UC browser endpoints *[reconstructed heading]*

*[reconstructed intro]* Add proxy endpoints so the frontend can populate a catalog/schema/table
picker using the user's PAT:

- `GET /api/v1/databricks/catalogs` — proxies `GET {DATABRICKS_HOST}/api/2.1/unity-catalog/catalogs`
  with the user's `X-Databricks-Token` header, returns list of catalog names.
- `GET /api/v1/databricks/schemas?catalog=main` — lists schemas in a catalog.
- `GET /api/v1/databricks/tables?catalog=main&schema=insurance` — lists tables in a schema.

PAT is passed per-request as `X-Databricks-Token`, never stored. These are pure proxy endpoints.

## Part D — Frontend updates (React)

Read the existing pages and store structure before touching anything. Read
`frontend/src/store/AppStore.tsx` and the Configure Run page carefully first.

Update the run submission flow:
- `POST /api/v1/run` now returns `{ job_id }` — store it in AppStore.
- Frontend polls `GET /api/v1/run/{job_id}/status` every 5 seconds.
- Show a "Training in progress..." spinner while polling.
- On COMPLETED: fetch `GET /api/v1/run/{job_id}/results` → populate dashboard as before.
- On FAILED: show the error message from the status response.

## Testing

- Mock all httpx Databricks REST calls — CI must not require live Databricks access.
- Test job submission, status polling, result fetching with mocked responses.
- Test UC browser endpoints with mocked Databricks responses.
- Test job state persistence: simulate FastAPI restart by creating a new app instance against the
  same DB — RUNNING jobs must still be retrievable.
- Frontend: test the data source toggle shows/hides correct inputs; test the polling state machine
  transitions (PENDING → RUNNING → COMPLETED, and FAILED path).

Update `docs/api_contract.md` with new endpoints and bump `schema_version`. Update
`docs/databricks_integration.md` §6.6 Step 6 status to done when complete.

## Scope boundary

Engine code (`backend/classifyos/`) is untouched. Only `backend/api/` and `frontend/src/` are in
scope.

## When done

- Run the relevant tests and make sure they pass (add tests for new behavior; CI must not depend on
  live external services — mock/stub them).
- Verify end-to-end where it makes sense (a real run / the affected flow).
- Update PROJECT_STATE.md and the appropriate `*_short_desc.md`.
- Update plan_tweak.md only if this genuinely deviated from the plan — don't invent entries.
- Do a hallucination check on any library calls against the installed version.
- Archive this session's generation prompt under `prompts/` (per CLAUDE.md, in the right surface
  subfolder) in the same commit as the code.
- Do not commit or push unless I ask; when I do, keep it to one coherent commit; don't stage `data/`.
