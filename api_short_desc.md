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
- **`GET /outputs/{name}`** — downloads one result file (a CSV or a chart PNG). The charts are
  fetched here on demand, never stuffed into the `/run` response.
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

---

## How to read this project

- **CLAUDE.md** — the conventions and hard rules.
- **PROJECT_STATE.md** — the live status (done, decisions, issues, next steps).
- **plan_tweak.md** — the honest register of deviations from the signed plan.
- **docs/api_contract.md** — the **locked** `/run` request/response schema (the frozen contract).
- **backend_short_desc.md** — plain-language summary of the ML engine.
- **api_short_desc.md** (this file) — plain-language summary of the API surface.
- **frontend_short_desc.md** — plain-language summary of the React dashboard (Phase 9).
