# Databricks UC table-profile — populate the Data Profile + feature picker from a real-data SAMPLE (API)

> Archived generation prompt (governance requirement). Surface: API (one additive change to an
> existing upload/profile-side endpoint + a behaviour-preserving engine refactor), so filed under
> `api_phases/` following the Interim-2b / table-profile-column-picker precedent
> (`databricks_table_profile_column_picker.md`, which added the same endpoint). Kept verbatim as the
> historical record.

---

When a run's data is loaded from Databricks (a Unity Catalog / Delta table, in the databricks
execution backend), the pre-run DATA-EXPLORATION UI is empty — it should show the same Data Profile
and per-feature metrics that a file upload and a Postgres table already show. FIRST investigate what
happens today and WHY, then implement (the profiling logic already exists — it just isn't fed real
data on the Databricks path).

Expected outcome: in the databricks backend, selecting a Unity Catalog table reads a bounded slice
of the table's ACTUAL data at selection time and runs the SAME profiling over it, so the response
carries the full InspectProfile (Data-Profile blocks included) exactly like a file upload / Postgres
selection — and both the Data Profile page and the Configuration feature-picker metrics populate with
NO frontend branching. Figure the cleanest option to weigh — e.g. the Databricks SQL warehouse
connector / Statement Execution API vs the existing Delta materialize path — you decide, keeping it
opt-in / lazy-imported and CI-mockable. Cap the profiling sample (don't read everything); degrade
gracefully if the table is huge/unreadable (never block the picker or fabricate stats); profiling is
display-only (no leakage — reads only). The `/run` still reads the full table on the cluster as it
does today. File-upload and Postgres flows must stay byte-identical, and CI must never hit a live
external service (mock/stub the data read).

Also make sure the per-feature metrics we get when running locally (graph, min/max, …) — the ones
also shown when picking features for training in Configuration — appear for Databricks runs too, not
just local ones.

Relevant files: `backend/api/routes/databricks.py` (the table-profile route),
`backend/api/databricks.py` (`get_table_columns` / the Databricks HTTP client),
`backend/api/routes/upload.py`, `backend/api/routes/input_sources.py`,
`backend/classifyos/io/inspect.py`, `backend/classifyos/analysis/profile.py`,
`backend/classifyos/io/sql_source.py`; and on the frontend the Upload page / `DatabricksSourcePanel`
+ `getTableProfile` + the `applyUpload` store plumbing, the Data Profile page, and the Configuration
feature picker. (Context: this follows the recently completed Databricks Runs-store + run-scoped
artifacts + results flow, which already works; this is about the pre-run data-exploration UI.)

When done:
- Run the relevant tests and make sure they pass (add tests for new behaviour; CI must not depend on
  live external services — mock/stub them).
- Verify end-to-end where it makes sense (a real run / the affected flow).
- Update PROJECT_STATE.md and the appropriate *_short_desc.md; update docs/api_contract.md if the
  contract changed.
- Update plan_tweak.md only if this genuinely deviated from the plan — don't invent entries.
- Do a hallucination check on any library calls against the installed version.
- Archive this session's generation prompt under prompts/ (per CLAUDE.md, in the right surface
  subfolder) in the same commit as the code.

---

## Implementation notes (what was built)

- **Root cause.** `GET /databricks/table-profile` fetched Unity Catalog **schema only**
  (`get_table_columns` → `_profile_from_columns`) and read no rows, so the response had `n_rows=0`,
  `sample=[]`, and **no `column_profiles`/`correlation`**. `DataProfile.tsx` bails to the empty state
  when `column_profiles` is absent, and the Configure feature picker's per-feature block reads the
  same `column_profiles` — hence both were empty for a Databricks source, while file/Postgres (which
  call `inspect_file(..., profile=True)` on real data) were rich.

- **Decision — SQL Statement Execution API over the existing `httpx` seam.** The FastAPI runs
  off-cluster (no Spark), so `materialize_delta_source` (SparkSession-only) can't read a sample there.
  The **SQL Statement Execution API** (`POST /api/2.0/sql/statements`) is the natural HTTP-queryable
  read, authenticated with the caller's PAT (same identity as the UC browser), and it **reuses
  `_build_client`** — so no new dependency and CI mocks it with the same `httpx.MockTransport` as the
  other Databricks calls. Rejected: the `databricks-sql-connector` (new heavy dep, harder to mock) and
  the training cluster (driven by Job submits, not ad-hoc queries; cold-start latency).

- **Engine refactor (behaviour-preserving).** `classifyos/io/inspect.py`: extracted
  `inspect_dataframe(df, *, target, profile, source)` — everything after the file read — from
  `inspect_file`, which now reads then delegates. The file/Postgres output is byte-identical (a new
  `test_inspect.py` case asserts `inspect_dataframe(frame) == inspect_file(path)`).

- **New client fn.** `api/databricks.py::fetch_table_sample(catalog, schema, table, user_pat, *,
  limit)` — `SELECT * FROM cat.sch.tbl` with `row_limit`, `wait_timeout=30s`,
  `on_wait_timeout=CANCEL`, `disposition=INLINE`, `format=JSON_ARRAY`. Reads `status.state ==
  SUCCEEDED`, `manifest.schema.columns`, `result.data_array` (all cells strings), builds a pandas
  frame, coerces manifest-numeric columns with `pd.to_numeric`. Warehouse id from
  `DATABRICKS_SQL_WAREHOUSE_ID` or parsed from `DATABRICKS_HTTP_PATH` (`_sql_warehouse_id`); row cap
  `CLASSIFYOS_DBRICKS_PROFILE_SAMPLE_ROWS` (default 10000, `_profile_sample_rows`). `UC_NUMERIC_TYPES`
  / `UC_DATETIME_TYPES` moved here (shared with the route's schema-only mapper — one source).

- **Route wiring.** `api/routes/databricks.py::_sample_profile` calls `fetch_table_sample` →
  `inspect_dataframe(df, profile=True, source=full_name)`; the endpoint prefers it and falls back to
  the existing `_profile_from_columns(columns)` on **any** exception (best-effort — never blocks the
  picker). `server_path` + `delta` `input_source` attached unchanged, so `/run` still reads the full
  table on the cluster.

- **Frontend.** **No change** — `applyUpload`, `DataProfile.tsx`, and the Configure feature picker
  were already source-agnostic; once the blocks are present they render. 177 vitest still green.

- **Hallucination check.** Statement Execution API verified vs Microsoft Learn (the SQL-execution
  tutorial) + the Databricks Python SDK: `StatementState` ∈ {PENDING, RUNNING, SUCCEEDED, FAILED,
  CANCELED, CLOSED}; `on_wait_timeout` ∈ {CONTINUE, CANCEL}; `disposition` ∈ {INLINE, EXTERNAL_LINKS};
  `format` ∈ {JSON_ARRAY, ARROW_STREAM, CSV}; INLINE+JSON_ARRAY → `result.data_array` (array of arrays
  of string cells), manifest `schema.columns[].{name, type_name, type_text, position}`. `pd.to_numeric`
  / `pd.DataFrame` are standard.

- **Contract / additive.** Rides the upload/profile side (not the locked `/run` envelope) → **no
  `schema_version` bump** (stays 1.11). Display-only, reads only, no leakage. **No plan_tweak entry**
  — completes the documented "richer UC profiling" follow-up (plan_tweak #48), not a deviation.

- **Tests.** `test_api_databricks.py` +2 (sample path returns the full Data-Profile blocks over mocked
  rows, PAT + `row_limit` asserted; a non-SUCCEEDED statement → schema-only fallback, no 5xx);
  `test_inspect.py` +3. All Databricks HTTP mocked. Full backend suite 499 passed. NOT run on a live
  cluster/warehouse (manually verifiable once a warehouse is reachable).
