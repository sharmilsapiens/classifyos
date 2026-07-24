# ClassifyOS — API Surface (Plain-Language Summary)

## About ClassifyOS

ClassifyOS is a GenAI-developed machine-learning framework for the insurance domain: it
predicts categorical outcomes (will a policy lapse? is a claim fraudulent? which risk tier?)
from ordinary tabular data. It is built in three layers — a **React** browser frontend talks
to a **FastAPI** backend, which drives a pure-Python **ML engine**. You set a run up in the
browser, it is sent to the API, the engine executes it, and the results stream back as JSON
to fill charts and tables. This file covers the **API surface** (the FastAPI layer). For the
engine itself see `backend_short_desc.md`.

---

## What the API is

The API is a thin translator: an HTTP request comes in, it calls the existing ML engine
(`ModelRunner` / `inspect_file`) exactly as the command-line tool does, and sends JSON back.
**It adds no machine-learning logic** — think of it as "the CLI, but the caller is a browser
instead of a terminal." It was built in Phase 8 and is the point at which the `/run` response
shape was **locked** (frozen) so the frontend can be built against a stable contract.

## The endpoints (all under `/api/v1/`)

- **`GET /health`** — the simplest check: "is the server up?" Returns a tiny fixed message.
  Monitors poll this.
- **`POST /upload`** — the browser uploads a data file (CSV/Excel/Parquet). The API saves it
  (through the storage gateway, into the input folder so a later run can read it) and
  immediately *inspects* it — returning the columns, types, missing-value counts, a small
  sample, and a guessed problem type — so the setup screen can populate its dropdowns. It
  hands back a `server_path` the browser passes to `/run`.
- **`POST /run`** — the main event. The browser sends the run configuration; the API runs the
  whole pipeline (train every requested model, score them, draw the charts, write all files)
  and returns one big, fixed-shape JSON result: run metadata, a per-model scoreboard, a
  sample of the predictions table, confusion matrices, per-class breakdowns, the ranked
  feature impact, the ROC/PR curve points for charts, and the list of downloadable files.
  **The request can also carry `user_features`** — a list of user-defined *structured* feature
  specs (e.g. "divide column A by column B", "the year of a date column"). These are picked from
  a fixed allowlist of operations on existing columns — never a free-text formula — and the API
  rejects an unknown operation (or a two-column op missing its second column) with a precise 422.
  The created columns flow into the engineered feature set and show up in the response's
  `active_features`; this is a **request-side addition only — the response shape is unchanged.**
- **`POST /explain`** — meant for "why did the model predict this for this one row?" (SHAP).
  **In v1.0 this is an honest placeholder**: the server keeps no trained model between
  requests and there's no model store yet, so it returns a clearly-structured "not available
  until v2.0" response shaped so the real feature can drop in later.
- **`GET /outputs`** — lists the result files a run produced (name, type, size).
- **`GET /outputs/{name}`** — downloads one result file (a CSV or a chart PNG) from the server's local
  output folder — where **local** runs write. The charts are fetched here on demand, never stuffed
  into the `/run` response.
- **`GET /outputs/{run_id}/{name}`** *(run-scoped; additive)* — the same, but for a run whose files
  live somewhere other than the server's local folder. In the **Databricks** mode a run's plots/CSVs
  are written on the cluster and logged to Databricks' MLflow, **not** the web server's disk — so this
  downloads the file from that run's MLflow record (by run id, using the service token) and streams it
  back. It's what makes a Databricks run's images and CSV links work in the dashboard (fresh *and*
  reloaded from the Runs page). In local mode it just serves from the output folder like `/outputs/{name}`.
- **`GET /runs`** *(1.10)* — lists past runs recorded in MLflow (most-recent first) as lightweight
  summary rows: when it ran, target, problem type, the algorithms, the best F1, status, and whether
  it can be reloaded. This is what the dashboard's **Runs** view shows.
- **`GET /runs/{run_id}`** *(1.10)* — reloads ONE past run: returns the exact same `/run` result it
  was rendered with, so the dashboard drops it straight into every result page. Unknown run (or one
  with no saved snapshot) → 404; an unreachable tracking store → 503.

## The locked `/run` result (the contract)

The `/run` response is **frozen** (see `docs/api_contract.md`), now at version `1.1`. Key points
the frontend relies on: models come back as a **list** (so a failed model is shown, not
hidden); the predictions table is **sampled** for display (the full table is a downloadable
CSV); the confusion matrices and curves are always computed on the **full** test set; charts
are referenced by filename only; and every number is JSON-safe (undefined values become
`null`, never broken JSON). Future changes must be additive and bump the version number.

**`1.1` (additive) — tuned hyperparameters.** The response gained one new **optional** block,
`result.tuning`, carrying the per-model tuned hyperparameters when Optuna tuning was on: the
tuning settings (`metric`/`cv`/`cv_folds`/`n_trials`/`timeout_seconds`), the list of
`tuned_models`, and `best_params` (`{model: {param: value}}`). It is `null`/absent when tuning
was OFF (or produced nothing), so a non-tuning run is byte-identical to `1.0` — every existing
field is untouched. The block is copied straight from the engine's `run_profile.json` `tuning`
block; the API adds no ML. This is the **first version bump of the locked contract**, done
additively (`schema_version` now reports `"1.1"`).

## Supporting pieces

- **The curve helper (`evaluation/curves.py`, `compute_curve_points`)** — one shared function
  that turns test predictions into ROC/PR chart coordinates. Both the saved chart image
  (`plot2`) and the interactive chart in the browser use it, so the two can never disagree. It
  only ever reads the held-out test predictions — it trains nothing.
- **Request validation** — the API checks the incoming configuration before doing any work and
  rejects bad requests with a precise "422" error (e.g. a missing target), reusing the engine's
  own validation so the rules can't drift between the two layers.
- **CORS & startup** — the API only allows browser origins from an approved list (never a
  blanket wildcard in production), and on startup it loads its environment settings and logs
  exactly which data/output folders it's using. **Phase 10 verified this with a real browser:** a
  cross-origin request from the frontend origin succeeds (it is in `CORS_ORIGINS`), and a
  non-simple request (a JSON `POST`) triggers a browser **preflight `OPTIONS`** which the API
  answers correctly — confirming the allowlist is genuinely enforced (curl/TestClient never
  exercise CORS because they aren't browsers). One operational note the test surfaced: because
  `main.py` calls `load_dotenv()` with the default `override=False`, environment variables already
  set in the process (e.g. by a test harness or a container) take precedence over `backend/.env`.
- **Multilabel over the same contract (Phase 11)** — the multilabel use case (Product
  Recommendation) now returns through the **unchanged, locked** `/run` envelope. Per-label metrics,
  per-label one-vs-rest ROC/PR curves, and a per-label class report populate normally; the fields
  that have no meaning for a multi-hot target (a single confusion matrix, MCC, log-loss) come back
  empty/`null` rather than wrong — so the contract did not need a new field. The 7-use-case sweep
  test drives all seven cases (binary, multiclass, multilabel) through this endpoint.
- **Data Profile blocks on `/upload` (2026-06-26, additive)** — `/upload` now returns, alongside
  the usual file inspection, a per-column profile for the dashboard's Data Profile view:
  distribution stats + a histogram for number columns, top value-frequencies for category columns,
  date ranges for date columns, and a correlation grid over the number columns. It is computed on
  the file the upload already loaded (no extra read), reads no target and fits nothing (no leakage),
  and any non-numbers (`NaN`/`Infinity`) are turned into `null` so the JSON is always valid. This is
  the upload/inspect payload, **not** the locked `/run` contract, so it is purely additive — **no
  version bump**. Documented in `docs/api_contract.md`.

- **Post-training feature importance on `/run` (2026-06-26, additive, `1.2 → 1.3`)** — the `/run`
  response gained an optional `result.feature_importance` block: each model's **native** importance
  (tree impurity/gain or coefficient magnitude), keyed by model name, as ranked
  `{feature, importance, rank}` rows. It's the post-training, model-derived counterpart to the
  existing pre-training `result.feature_impact` screen of raw features. Models with no native
  importance (RBF-SVM, GaussianNB) are omitted, and the whole block is `null` when none qualify —
  so a run with only those models is byte-identical to earlier schemas. Also written as
  `feature_importance_summary.csv`. Pure plumbing of values the engine already computed (the API
  adds no ML); documented in `docs/api_contract.md` (the contract's third additive bump).

- **Per-type missing-value strategy on `/run` (2026-06-27, additive, request-side)** — the `/run`
  request gained two optional fields, `missing_strategy_numeric` and `missing_strategy_categorical`
  (both default `null` → inherit the legacy global `missing_strategy`). They let a caller pick a
  different blank-filling strategy for number columns vs category columns — and unlock the new
  number-only options (k-nearest-neighbours, iterative/model-based, backward-fill). A bad value
  (e.g. a number-only strategy on the categorical field) is rejected with a precise 422 by the
  engine's `build_config`, same as every other enum. This is **request-side only** — the response
  envelope is unchanged, so there is **no `schema_version` bump**; the request example in
  `docs/api_contract.md` was updated.

- **Per-column missing-value overrides on `/run` (2026-07-01, additive, request-side)** — the
  `/run` request gained one more optional field, `missing_strategy_by_column`, a `{column:
  strategy}` map (default `{}`). It layers on top of the per-type fields above: a named column uses
  its own strategy, any column left out keeps its per-type default (so an empty map changes
  nothing). Values are validated by the engine's `build_config` against the full strategy set (a
  bad name → 422); a number-only strategy named on a category column is coerced back to that
  column's type default at fit time rather than erroring. **Request-side only** — the response
  envelope is unchanged, so **no `schema_version` bump**; the request example in
  `docs/api_contract.md` was updated.

## LLM reason-code narratives on the SHAP block (schema 1.6 → 1.7, additive) — 2026-07-03
- The `/run` request's optional `explainability` block gained one more flag, `llm_narratives`
  (default `false`), and each per-row SHAP explanation in the response gained an optional
  `narrative` string. When `llm_narratives` is on (it requires `explainability.enabled`) **and** the
  server has the five `AZURE_OPEN_AI_*` env vars configured, the engine attaches an LLM-authored
  plain-language reason-code paragraph to each explained row; otherwise `narrative` is `null` and
  the run is byte-identical to `1.6`. The `schema_version` was bumped **`1.6 → 1.7`** (additive —
  no earlier field renamed/retyped/removed) and `docs/api_contract.md` was updated (header note,
  request + response examples, notes bullet, footer). The `explanations_summary.csv` artifact gained
  a `narrative` column. Purely a presentation layer — the API still just plumbs values the engine
  computed; absent credentials or a failed call degrade gracefully to SHAP-only.

## Narrative context knobs (request-only, no version change) — 2026-07-03
- The `explainability` block gained three request-only fields that shape the LLM prompt (not the
  ML, not the response): `context_mode` (`given` | `derived` | `both`), `dataset_context`
  (free-text on the data/target), and `column_context` (`{column: note}`). They let the narrator
  cite ORIGINAL feature values and business meaning instead of scaled numbers. Validated by
  `build_config` (bad `context_mode` → 422). The response envelope and `schema_version` are
  **unchanged** (`narrative` is still a string), so this is purely additive on the request side;
  `docs/api_contract.md` request example + notes updated. [RISK] privacy — `derived`/`both` cause
  the server to send sample data values to Azure OpenAI (opt-in).

## MLflow run logging + model persistence on `/run` (schema 1.8 → 1.9, additive) — 2026-07-08
- The `/run` request gained an optional `mlflow` block (`{enabled, experiment, run_name}`, OFF by
  default), and the response gained an optional `result.mlflow` pointer (`{run_id, experiment_id,
  tracking_uri, models}`). When `mlflow.enabled` is on, the engine logs the run to MLflow **after**
  training — the config as params, each model's headline test metrics, the artifact files, and one
  saved model per algorithm — and the response reports where it landed (`models` maps each algorithm
  to a load URI). This is the first piece of the Databricks-integration roadmap (Phase A) and also
  fixes the "runs kept nothing / overwrote each other" gap. It is `null` when logging was OFF (the
  default) or failed, so a run without it is byte-identical to `1.8`; the `schema_version` was bumped
  **`1.8 → 1.9`** (additive — no earlier field renamed/retyped/removed). The API still just plumbs a
  pointer the engine recorded — no ML. A bad `mlflow` value (e.g. an empty `experiment`) is rejected
  by `build_config` with a precise 422. **Where it logs is a server-side concern**, not a request
  field: unset → MLflow's local default (a `mlflow.db` + `./mlruns` next to the process); set the
  `MLFLOW_TRACKING_URI` env var to point at a database/managed server later with no code change.
  `docs/api_contract.md` updated (header note, request + response examples, notes bullet).

## MLflow read-path — list & reload past runs (schema 1.9 → 1.10, additive) — 2026-07-08
- **The payoff of persistence.** Phase A made runs *log* to MLflow; Interim 2a (design
  `docs/databricks_integration.md` §6.5) moves MLflow's **backend store** to a local **Postgres**
  (`postgresql://…` via the `MLFLOW_TRACKING_URI` env var) while keeping artifacts a local folder —
  **configuration only, no engine code change**. This new read-path is what makes those runs
  *visible*: two new GET endpoints — **`GET /runs`** (list) and **`GET /runs/{run_id}`** (reload) —
  back the dashboard's new **Runs** view, so results now survive a browser refresh and a server
  restart (the state lives in Postgres, not the browser).
- **How reload is byte-identical.** When a run is logged to MLflow, `/run` now also persists its
  *rendered* result envelope as a run artifact (`api/run_response.json`) — report-only, so a failure
  there only makes that run non-reloadable, never affects the response. `GET /runs/{run_id}` returns
  that saved envelope verbatim, so a reloaded run matches the original exactly.
- **Additive, `/run` unchanged.** The `POST /run` request/response envelope is byte-identical to
  `1.9`; only new endpoints were added. The `schema_version` marker moved **`1.9 → 1.10`** to record
  the contract's advance (locked-contract rule). All reads go through a small `api/mlflow_read.py`
  helper that imports `mlflow` lazily, turns an unreachable store into a clean **503** and an unknown
  run into a **404** — never a 500. Verified live end-to-end against a real local Postgres.
  `docs/api_contract.md` updated (header note, endpoint table, a dedicated endpoints section, footer).
- **Per-user + Databricks-sourced (2026-07-23).** In the `databricks` execution backend the Runs view
  is scoped to the CALLER and read from Databricks-managed MLflow: `/runs` filters by a
  `classifyos.user_email` tag (the Job logs it; the caller's email is resolved on read from the
  `X-Databricks-Token` PAT via SCIM), and `/runs/{id}` 404s another user's run. The **service token**
  authenticates the MLflow read; the PAT only resolves identity — thread-safe, no per-request
  credential swap. A missing/expired PAT → **401** (the UI prompts). The **local** backend is
  unchanged (lists everything, no PAT). No `/run` contract change; runs are filtered by the STABLE
  email tag, so PAT rotation never loses history.

## Postgres input source — draw a run's data from a database (request-side; no version bump) — 2026-07-08
- **What it adds.** A run can now optionally pull its data from a SQL database instead of an
  uploaded file (Interim 2b of `docs/databricks_integration.md` §6.5). A new request block
  `input_source` picks the source: the default `{ "type": "file" }` reads `input_file` from
  storage exactly as before, and `{ "type": "postgres", "connection_env": "…", "table": "…" }`
  (or `"query": "…"`) runs the table/query and feeds the result into the pipeline.
- **How (materialize-to-file, Option B).** Before the run, the configured table/query is executed
  **once** and the result is written to `input_file` under DATA_DIR (a `.parquet`/`.csv` snapshot)
  through the StorageAdapter; the engine then loads that file **unchanged**. So there is **no new
  response field and no `schema_version` bump** — it stays `1.10` — and the snapshot is a durable,
  auditable copy of exactly the rows the run saw.
- **Credentials never travel in the request.** `connection_env` is the **name** of a server-side
  environment variable (in `backend/.env`, gitignored) holding the SQLAlchemy DSN — the request
  carries the env-var name, never a credential. `build_config` is the authoritative validator: an
  unknown `type`, both/neither of `table`/`query`, a missing `connection_env`, an unsafe table
  identifier, or a non-`.parquet`/`.csv` destination → **HTTP 422**. A source that cannot be read
  at run time (unset env var, unreachable DB, failed query, empty result) → the `status: "error"`
  envelope (**HTTP 400**), like a missing input file.
- **Reproducibility note.** A SQL table is a *set*: a bare `table`/`SELECT *` may return rows in a
  different order than a CSV, and the seeded train/test split is order-sensitive — add an `ORDER BY`
  to the `query` for a byte-for-byte reproducible snapshot (verified to match the CSV exactly).
  Driver: `SQLAlchemy` + `psycopg2` (pinned). `docs/api_contract.md` updated (request example +
  a dedicated request-side note). Dashboard UI to pick a table/query is a follow-up.

## Input-source read-path — list & select DB tables for the picker (additive; no version bump) — 2026-07-09
- **What it adds.** Two small endpoints that let the dashboard offer an **"Import from database"**
  picker over the existing Interim-2b Postgres input source — so a user runs on a DB table by
  clicking, not by hand-crafting a request. They ride the **upload/profile side** (like `/upload`),
  NOT the locked `/run` envelope, so they carry **no `schema_version`** and are purely additive.
  - **`GET /input-sources/tables`** — lists the tables in the input DB (via the `CLASSIFYOS_PG_DSN`
    DSN) as `{connection_env, tables[]}`. An unreachable/unconfigured DB is a clean **503** (the
    same "store unavailable" discipline the MLflow read-path uses), never a 500.
  - **`POST /input-sources/select`** — picks a table (or raw query): runs it through the **exact 2b
    engine path** (`materialize_source` writes a `.parquet` snapshot under DATA_DIR via the
    StorageAdapter), then profiles that snapshot with the **same `inspect_file` the `/upload` flow
    uses** — so the response is the **same `InspectProfile` shape** an upload returns, and the
    frontend treats a DB table exactly like an uploaded file. It additionally returns an
    `input_source` block; the frontend sets it on the run so the actual `/run` reads from Postgres
    (the 2b path), not merely the profiling snapshot. Bad request (both/neither table+query, unsafe
    identifier, bad target) → **422**; DB unavailable → **503**.
- **Reuse, no re-implementation.** No new ML and no new DB reading: the endpoints reuse the engine's
  `list_tables` / `materialize_source` and its authoritative `_validate_input_source`. [RISK]
  leakage — materialize runs strictly before any pipeline and only writes a snapshot; the run then
  loads → splits → fits-on-train as always. Verified live end-to-end against the local Postgres
  (list → select iris/arizona → a full `/run` on the DB `input_source`). Endpoint tests use a
  sqlite DSN so CI needs no live Postgres. `docs/api_contract.md` updated (endpoint table + a
  dedicated section).

## Databricks orchestration — run training as a Databricks Job (✅ Done, 2026-07-14)
**In one line:** The API can now hand a training run off to a **Databricks Job** instead of running
it inside the web server — you submit, poll, and fetch results — while a normal local install keeps
working exactly as before, because the whole thing is switched on by one setting.
- **Why:** on the real deployment (Azure-hosted API + Databricks compute), a big training run can
  take minutes and would time out a normal web request. The fix is the classic "submit a job, then
  poll for it" pattern. This is the last piece of the Databricks plan (`docs/databricks_integration.md`
  §6.6 Step 6), after the engine was made cluster-ready in Steps 1–5.
- **One switch, two behaviours.** A server setting (`CLASSIFYOS_EXECUTION_BACKEND`) chooses the mode.
  Left at its default (`local`), `POST /run` runs the pipeline in-process and returns the full result
  in one response — **byte-for-byte the same as before**, so local dev and the test suite are
  unaffected. Set to `databricks`, the *same* `POST /run` instead submits a Databricks Job and returns
  a small `{job_id, run_id}` straight away.
- **Submit → poll → fetch (the new endpoints).** `GET /run/{job_id}/status` reports the job as
  *pending / running / completed / failed* (translated from Databricks' own run state); once it's
  completed, `GET /run/{job_id}/results` returns the **exact same result envelope** the dashboard
  already knows — read back from the file the job wrote to the cluster's storage. So a Databricks run
  and a local run look identical to every result page.
- **Stateless — no database for jobs.** The web server keeps no job store: the Databricks `run_id`
  IS the `job_id`, so `/status` and `/results` poll Databricks directly with that id on every
  request. A server restart loses nothing (nothing was stored), and Databricks is the only external
  dependency — no managed database to run for deployment.
- **Your token, used carefully.** The user's Databricks personal access token is sent per-request in a
  header, forwarded to the job so it reads Unity Catalog data **as that user**, and is **never stored**.
  A separate service token is used only for the job-management calls.
- **Browse the data too.** Three read-only endpoints (`/databricks/catalogs`, `/schemas`, `/tables`)
  proxy Unity Catalog so the UI can offer a catalog → schema → table picker.
- **Additive + safe.** The API contract bumped `1.10 → 1.11` (additive only); the `/health` check now
  also reports which mode the server is in so the frontend knows what to expect. Every Databricks call
  is **mocked in the tests** — CI never touches a real cluster. Backend 461 tests green; the API's
  request model gained optional `catalog`/`schema`/`limit` so a run can read a Databricks **Delta**
  table. Hallucination-checked against the Azure Databricks REST docs. Running it on a real cluster is
  pending cluster access (the job's notebook is written and ready).

## Databricks table-profile — populate the column picker from a UC table's schema (additive; no version bump) — 2026-07-14
- **The gap it closes.** The Unity Catalog picker's list endpoints return table **names only** (no
  columns), so after selecting a table a user had to type the target and feature column names by hand.
- **What it adds.** One endpoint, **`GET /databricks/table-profile?catalog=&schema=&table=`**, fetches
  the chosen table's schema from Unity Catalog (the *get-a-table* REST call, authenticated with the
  user's PAT) and returns it in the **same `InspectProfile` shape a CSV `/upload` returns** — columns,
  types, and the numeric/categorical/binary/datetime groups — so the dashboard reuses its existing
  column picker (target dropdown + feature selector) with **no manual entry and no branching**. It also
  returns a `delta` `input_source` + a snapshot `server_path`, exactly like `/input-sources/select`
  does for Postgres, so the frontend's existing `applyUpload` plumbing sets the run up to read the Delta
  table. It rides the **upload/profile side** (not the locked `/run` envelope), so **no `schema_version`
  bump**.
- **Honest about what a schema can't tell you.** Row-level stats (`n_rows`, `n_missing`, `sample`, the
  class distribution) aren't available from schema-only metadata, so they come back zeroed/empty rather
  than fabricated; the real per-column stats are computed on the cluster when the run reads the table.
- **Gated + safe.** Only available in the `databricks` execution backend (else **503** — never a silent
  fall-through to manual entry); a `catalog`/`schema`/`table` that isn't a simple SQL identifier → **422**
  (they're interpolated into the UC REST path); missing PAT → **401**; unreachable workspace or a
  columnless table → **503**. Column-type → group mapping is **hallucination-checked** against the
  Databricks SDK `ColumnTypeName` enum. Every Databricks call is mocked in the tests. `docs/api_contract.md`
  updated (endpoint table + a dedicated section + footer note).

## Databricks table-profile now reads a real-data SAMPLE (additive; no version bump) — 2026-07-23
- **The gap it closes.** The 2026-07-14 table-profile above returned the table's **schema only** — so a
  Databricks source populated the column picker but left the **Data Profile page** and the
  **Configuration feature picker** empty (no histograms/stats/correlation, no per-feature density/chips),
  unlike a CSV upload or a Postgres source.
- **What it adds.** When a SQL warehouse is configured, `GET /databricks/table-profile` now reads a
  **bounded sample** of the table's *actual* rows via the **SQL Statement Execution API**
  (`POST /api/2.0/sql/statements`, `SELECT * … row_limit`, authenticated with the caller's **PAT** — the
  same identity as the UC browser) and runs the **SAME** profiling a CSV upload does (`inspect_file` was
  refactored to a reusable `inspect_dataframe` core). So the response carries the **full `InspectProfile`
  including the Data-Profile blocks** (`column_profiles` + `correlation`) and real per-column stats — the
  Databricks source is now as rich as file/Postgres, with **no frontend change**.
- **Cleanest option, and why.** The FastAPI runs *off-cluster* (no Spark), so the existing Delta
  materialize path can't read the sample there; a SQL warehouse is the natural HTTP-queryable endpoint.
  **Reuses the existing `httpx` client seam** (no new dependency; mocked in CI exactly like the other
  Databricks calls) rather than the `databricks-sql-connector` or the legacy Command Execution API.
- **Bounded, non-blocking, honest.** `row_limit` (`CLASSIFYOS_DBRICKS_PROFILE_SAMPLE_ROWS`, default
  10000) caps the read; `wait_timeout=30s` + `on_wait_timeout=CANCEL` = one call, no polling, a slow
  query is cancelled. **Any** failure (no warehouse — `DATABRICKS_SQL_WAREHOUSE_ID` or an `<id>` parsed
  from `DATABRICKS_HTTP_PATH` — unreachable, huge/unreadable, non-SUCCEEDED) **degrades to the previous
  schema-only profile**, so the picker is never blocked and no stats are fabricated. `n_rows` reflects
  the *sample* size. Display-only — the `/run` still reads the FULL table on the cluster (unchanged).
- **Safe + tested.** Reads only, in-memory (no snapshot written at selection time), no leakage. Statement
  Execution API shape **hallucination-checked** vs Microsoft Learn + the Databricks Python SDK (state enum,
  INLINE/JSON_ARRAY `data_array`-of-strings, `row_limit`, `on_wait_timeout`). New tests: the sample path
  (full blocks over mocked rows, PAT + `row_limit` asserted) + the graceful fallback (statement fails →
  schema-only, no 5xx); all Databricks HTTP mocked. File/Postgres flows byte-identical (full suite green).

## Databricks Runs read-path store + run-scoped artifact serving (2026-07-23, additive; no version bump)
Two fixes so the dashboard's **Runs** tab and a run's **artifact files** work end-to-end when the
server runs the `databricks` execution backend. **API + frontend only — no engine/notebook/wheel
change** (deploys with a FastAPI restart + a frontend rebuild; no cluster restart). The **local**
backend is byte-identical.
- **Runs read the right MLflow store (§6.1).** The Runs read-path (`api/mlflow_read.py`) used to read
  whatever `MLFLOW_TRACKING_URI` the *FastAPI process* had — in a Databricks deployment that's often a
  leftover local Postgres, so the Runs tab listed nothing and reported "Tracking store:
  postgresql://…localhost". Now, when the backend is `databricks`, the read-path targets the
  workspace's **managed MLflow** by passing `tracking_uri="databricks"` **per call** to
  `MlflowClient(...)` and `download_artifacts(...)` (mlflow 3.14 accepts both) — **no process-global
  `set_tracking_uri`, so it stays thread-safe** under the shared server — and reports the store as
  `"databricks"`. The **service token** authenticates the read; the PAT still only scopes *which* runs.
  It also **scopes the search to the ClassifyOS experiment** (`/Shared/classifyos`; override
  `CLASSIFYOS_MLFLOW_EXPERIMENT`) so a workspace with hundreds of experiments doesn't exceed Databricks'
  100-`experiment_ids` `search_runs` cap. Local backend unchanged (reads/reports its env store, searches all).
- **A Databricks run's artifacts display (§6.2).** A run's PNGs/CSVs live in its MLflow run (under
  `classifyos/`) + the UC volume — **not** the API's local output folder — so the flat `/outputs/{name}`
  404'd them (broken images, dead CSV links). New **run-scoped** `GET /outputs/{run_id}/{name}` downloads
  `classifyos/{name}` from the MLflow run (service token, `tracking_uri="databricks"`) and streams it;
  the frontend builds that URL from `result.mlflow.run_id` **only for Databricks-backed runs** (its
  `tracking_uri` starts with `"databricks"`), so local runs keep the flat URL. Works for a fresh run and
  a run reloaded from the Runs tab. **[RISK]** an `<img>`/`<a>` can't send the PAT, so isolation is the
  unguessable 32-hex run id + service token (app-level), not a per-user ACL. The response is marked
  **immutable** (run artifacts are write-once), so the browser caches it and the frontend prefetches a
  run's plot PNGs on load — instant, lag-free result tabs (the flat `/outputs/{name}` stays uncached).
- **Tested, CI-safe.** MLflow/Databricks fully mocked (a stubbed `load_artifact` / `MlflowClient` /
  `download_artifacts`, the backend flipped with `monkeypatch.setenv`) so CI never touches a live
  workspace; one end-to-end test does a real mlflow-logged `/run` and reads an artifact back from a real
  (temp `file:`) store to prove the `classifyos/{name}` path matches what the engine writes. Backend
  490+ tests green; frontend 175 vitest green. Hallucination-checked against mlflow 3.14.0. `docs/api_contract.md`,
  `docs/databricks_how_it_works.md`, `docs/databricks_wisdom.md` updated.

## LLM narratives on the Databricks backend — creds via a secret scope (2026-07-23, additive; no version bump)
The opt-in Azure OpenAI reason-code narratives (schema 1.7 — `result.explanations[].rows[].narrative`)
worked locally but were always `null` on the **databricks** backend: they're generated by the engine on
the **cluster**, which had no `AZURE_OPEN_AI_*` creds (the notebook set storage/MLflow/token env vars but
not these), so the narrator returned nothing and the run shipped SHAP only. **Fix — API + notebook only
(no engine/wheel change):** on a databricks submit that requested narratives AND has the creds, FastAPI
syncs them into a Databricks **secret scope** (Secrets REST API, service token: `scopes/create` +
`put` per key + `acls/put` granting the cluster's `AIML_RD` principal READ) and forwards **only the scope
name** to the Job — the key never appears in run parameters or logs; the notebook reads them via
`dbutils.secrets.get` into the env before the run. Opt-in + report-only (no creds / narratives off / any
sync failure → SHAP only, submit never blocked); the **local** backend is unchanged (in-process narrator
reads `.env`). New optional env knobs: `CLASSIFYOS_DBRICKS_SECRET_SCOPE` (default `classifyos-llm`) and
`CLASSIFYOS_DBRICKS_SECRET_READ_PRINCIPAL` (default `AIML_RD`). All Databricks/Secrets REST mocked in
tests (`test_api_jobs.py` +6). Narratives are baked into a run at run time, so re-run once after deploy to
see them on a reloaded past run. No `/run` contract change (narrative exists since 1.7). Docs:
`docs/databricks_how_it_works.md` §15, `docs/databricks_wisdom.md`, `backend/.env.example`.

## LLM narratives moved OFF the cluster to a FastAPI step (2026-07-24, additive; no version bump)
- **The gap it closes.** The secret-scope fix above correctly delivered the Azure creds to the cluster,
  but the cluster **still can't reach Azure OpenAI** — it is locked to a private endpoint, so every
  narrate call failed with `403 Public access is disabled` (confirmed in a live job log) and narratives
  were always `null` on the databricks backend. FastAPI *can* reach the endpoint (that is why local
  works), so narration was moved off the cluster to the API.
- **New endpoint `POST /api/v1/runs/{run_id}/narrate`.** It loads the run's persisted `/run` envelope +
  a new `api/narration_context.json` side artifact, rebuilds the **full** narrator context (the analyst
  dataset/column context + context_mode + data-derived schema/sample rows from the artifact;
  class base rates from `result.run.class_distribution`; per-model metrics from `result.models`; global
  features from `result.permutation_importance`/`feature_impact`; the SHAP rows from
  `result.explanations`), narrates every row via the **engine narrator** (`classifyos.analysis.llm_explain`
  — no new ML), attaches `narrative`, and **re-persists** the narrated envelope as the run's snapshot
  (routed to Databricks MLflow with `tracking_uri="databricks"`, mirroring the §6.1 read fix) so a
  reload shows narratives instantly. **Report-only**: absent creds / absent context / any failure returns
  the envelope unchanged — never a 500. `404` unknown run/no snapshot, `503` store unreachable, `401`
  missing PAT (databricks).
- **Engine side (wheel change; additive + flag-gated).** The run still computes SHAP; when narratives are
  requested it serializes the `narration_context.json` side artifact (via `mlflow_logging.log_run`,
  grouped with the envelope snapshot under `api/`). A new engine flag `CLASSIFYOS_NARRATE_IN_ENGINE`
  (default **true** → local byte-identical, engine narrates in-process as today) gates the in-engine call;
  the Databricks Job notebook sets it **false** so the cluster skips the unreachable Azure call. It is a
  SIDE artifact, not part of the locked `/run` envelope → **no `schema_version` bump** (`narrative` has
  existed since 1.7). This needs a **wheel rebuild + cluster restart + notebook re-import** (B-full).
- **Frontend.** The Explainability page auto-calls `/narrate` for a databricks-backed run whose SHAP rows
  lack a `narrative`, then swaps in the narrated envelope; a pre-narrated (persisted) past run reloads
  instantly. **The moot secret-scope handoff was removed** (notebook widget/loop, `sync_llm_secrets` +
  its helpers, the `azure_secret_scope` submit param). All Azure/MLflow/Databricks are mocked in tests
  (`test_api_narrate.py`, `test_narration_offload.py`); `test_api_jobs.py` now asserts the submit forwards
  no Azure material. Docs: `docs/databricks_how_it_works.md` §15, plan_tweak #52.

---

## How to read this project

- **CLAUDE.md** — the conventions and hard rules.
- **PROJECT_STATE.md** — the live status (done, decisions, issues, next steps).
- **plan_tweak.md** — the honest register of deviations from the signed plan.
- **docs/api_contract.md** — the **locked** `/run` request/response schema (the frozen contract).
- **backend_short_desc.md** — plain-language summary of the ML engine.
- **api_short_desc.md** (this file) — plain-language summary of the API surface.
- **frontend_short_desc.md** — plain-language summary of the React dashboard (Phase 9).
