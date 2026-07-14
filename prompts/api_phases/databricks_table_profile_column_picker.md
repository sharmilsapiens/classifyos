# Databricks UC table-profile — populate the column picker from a table's schema (API + frontend)

> Archived generation prompt (governance requirement). Surface: API + frontend (one additive
> upload/profile-side endpoint + the Upload page wiring), so filed under `api_phases/` following the
> Interim-2b precedent (`interim_2b_ui_input_source_picker.md`, which likewise added an
> upload/profile-side endpoint + a dashboard picker). Kept verbatim as the historical record.

---

The Databricks Unity Catalog table picker (Step 6, now live) asks users to manually enter target and
feature columns after selecting a table — because table selection only returns the table name, not
its schema. The fix is to fetch the table schema from Unity Catalog after selection and render the
same column profile UI that CSV upload shows after inspect_file runs.

This is a small focused task: one new backend endpoint + frontend wires it up post-table-selection.

---
Part A — New FastAPI endpoint

File: backend/api/routes/databricks.py (already exists from Step 6)

Add:
GET /api/v1/databricks/table-profile
Query params: catalog, schema, table
Header: X-Databricks-Token (user PAT — same pattern as existing UC browser endpoints)

Call the Databricks Unity Catalog REST API:
GET {DATABRICKS_HOST}/api/2.1/unity-catalog/tables/{catalog}.{schema}.{table}

This returns the full table metadata including columns — an array of { name, type_name, nullable,
comment }. Extract and return a profile in the same shape as inspect_file returns for CSV files, so
the frontend can reuse existing column-picker logic without branching. Hallucination-check the Unity
Catalog Tables API response shape against Microsoft Learn / Azure Databricks docs before coding.

If the table has no columns or the call fails, return a clear error — never silently fall back to
manual entry without telling the user why.

Add CLASSIFYOS_EXECUTION_BACKEND guard: if not in Databricks mode return 503 with a clear message
(same pattern as other Databricks endpoints).

---
Part B — Frontend

Read the existing CSV upload flow carefully first — find where inspect_file results are received and
used to populate the target column dropdown and feature selector. The Databricks path must reuse that
exact same UI state/components, not build a parallel one.

After the user selects a table in the UC picker:
1. Call GET /api/v1/databricks/table-profile?catalog=...&schema=...&table=... with their PAT
2. Show a loading state while fetching ("Loading table schema...")
3. On success: populate the column profile UI identically to after CSV upload — target dropdown,
   feature selector, data types shown
4. On failure: show the error message clearly, let the user re-select or switch to CSV upload

The user should not need to manually type column names at any point.

---
Testing:

- Mock the Databricks Unity Catalog Tables API call — no live cluster in tests
- Test the endpoint returns the correct profile shape from a mocked response
- Test 503 when CLASSIFYOS_EXECUTION_BACKEND is not databricks
- Test the frontend: after table selection, loading state appears, then column picker populates;
  test the error state
- Existing CSV upload flow must be untouched — run the full test suite to confirm

Update docs/api_contract.md with the new endpoint (additive). Update PROJECT_STATE.md and
api_short_desc.md / frontend_short_desc.md.

---
When done:
- Run the relevant tests and make sure they pass (add tests for new behavior; CI must not depend on
  live external services — mock/stub them).
- Verify end-to-end where it makes sense (a real run / the affected flow).
- Update PROJECT_STATE.md and the appropriate *_short_desc.md.
- Update plan_tweak.md only if this genuinely deviated from the plan — don't invent entries.
- Do a hallucination check on any library calls against the installed version.
- Archive this session's generation prompt under prompts/ (per CLAUDE.md, in the right surface
  subfolder) in the same commit as the code.
- Do not commit or push unless I ask; when I do, keep it to one coherent commit; don't stage data/.

---

## Implementation notes (what was built)

- **Backend.** `api/databricks.py` gained `get_table_columns(catalog, schema, table, user_pat)` —
  the *get-a-table* call (`GET /api/2.1/unity-catalog/tables/{full_name}`, user PAT), returning the
  `columns` array (raising `DatabricksUnavailable` on a columnless table → 503).
  `routes/databricks.py` gained `GET /databricks/table-profile`: a databricks-backend guard (503),
  a simple-SQL-identifier check on catalog/schema/table (422, since they're interpolated into the UC
  REST path), then `_profile_from_columns()` maps each `ColumnInfo.type_name` into the
  `inspect_file` column groups and returns the `InspectProfile` shape + a `delta` `input_source` +
  a `db_snapshots/<catalog>_<schema>_<table>.parquet` `server_path` (mirroring
  `/input-sources/select`). Row-level stats (`n_rows`/`n_missing`/`sample`/class distribution) are
  zeroed/omitted — unavailable from schema-only metadata.
- **Hallucination check.** The `ColumnInfo` fields (`name`, `type_name`, `type_text`, `nullable`,
  `comment`, `position`, …) and the `ColumnTypeName` enum (`BOOLEAN`/`BYTE`/`SHORT`/`INT`/`LONG`/
  `FLOAT`/`DOUBLE`/`DECIMAL`/`DATE`/`TIMESTAMP`/`TIMESTAMP_NTZ`/`STRING`/… ) were verified against
  Microsoft Learn (the `databricks tables get FULL_NAME` reference) and the Databricks SDK
  `catalog.py` (`databricks-sdk-py`). The numeric/datetime/boolean → group mapping is derived from
  that enum.
- **Frontend.** `api/client.ts` gained `getTableProfile({catalog,schema,table}, pat)`. `Upload.tsx`
  now fetches the profile on table selection and flows it through the SAME `applyUpload` plumbing a
  CSV upload / DB-select uses (shared column table, target dropdown; the Configure page's feature
  selector) — the manual target/feature text boxes + "Run on Databricks" button were removed, so the
  Databricks source goes Upload → Configure → Run identically to a file. A "Loading table schema…"
  spinner covers the fetch; an error is shown with a retry.
- **Not a plan deviation.** The Step-6 archive + plan_tweak already recorded UC column profiling as a
  documented follow-up; this delivers it. No new plan_tweak entry.
