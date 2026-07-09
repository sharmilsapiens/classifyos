# Interim 2b UI — "Import from database" input-source picker (API + frontend)

> Archived generation prompt (governance requirement). Surface: API + frontend (the additive
> read endpoints + the dashboard picker), so filed under `api_phases/` following the Interim-2a
> precedent (`phase_2a_mlflow_postgres_runhistory.md`, which likewise added read endpoints + a
> dashboard view). Kept verbatim as the historical record.

---

Add a "Import from database" option to the dashboard so a user can run on data drawn from the
Postgres input source, by picking a table from a list — no hand-crafted API request. Context: the
Postgres input source (Interim 2b, docs/databricks_integration.md §6.5) exists at the engine + API
layer (input_source.type="postgres" → materialize_source in classifyos/io/sql_source.py), but there
is no UI for it. This adds that UI plus the small read endpoints it needs. Reuse the existing 2b
engine path — do not reimplement DB reading.

Seed data first (so the picker has something to show): load two example datasets into the input DB
(classifyos_data, DSN in env CLASSIFYOS_PG_DSN) as separate tables — iris (multiclass) and arizona
(from the existing arizona_buyingpropensity sample; binary converted target). One table per dataset.
A tiny seeding script (pandas to_sql) is fine; put it under backend/scripts/ and note it in the
RUNBOOK — it's a dev convenience, not pipeline code.

Backend (additive endpoints):
- GET /api/v1/input-sources/tables — list the table names in the input DB (via CLASSIFYOS_PG_DSN),
  so the UI can offer them. Unreachable/unconfigured DB → clean 503 (mirror the mlflow_read error
  discipline), never a 500.
- An endpoint to select a table that materializes + profiles it so the normal Configure flow works:
  reuse materialize_source (writes a .parquet/.csv snapshot to DATA_DIR via StorageAdapter) and the
  existing inspect/profile path, returning the same InspectProfile shape the /upload flow returns
  (so the frontend treats a DB table exactly like an uploaded file). It should also give the
  frontend what it needs to set the run's input_source block so the actual /run reads from Postgres
  (the 2b path), not just the profiling snapshot.
- These ride the upload/profile side, not the locked /run envelope — additive endpoints; bump
  schema_version only if a /run field actually changes (it shouldn't). Update docs/api_contract.md.

Frontend:
- On the Upload page, add a source choice: "Upload a file" (today's flow) vs "Import from database."
  The DB option fetches the table list and shows it as a selectable list (a query box is
  optional/secondary — the picker is the primary ask); selecting iris or arizona profiles it and
  drops the user into the existing Configure flow unchanged, with the form's input_source set so the
  run uses Postgres. Graceful states: DB unreachable / empty table list / no tables.
- Reuse the existing store applyUpload/profile plumbing and existing components; keep it additive so
  the file-upload path is untouched.

Scope guard: no new ML, no leakage surface (materialize runs before the pipeline and only writes a
snapshot; the run then loads→splits→fits-on-train as always). Do NOT touch the deferred Databricks
phases (B/C) or model serving.

When done: run the relevant backend + frontend tests and make sure they pass (endpoint tests for
list-tables + select/profile incl. the 503 path; a buildPayload/Configure test that a DB selection
sets input_source; a Upload-page render test for the source switch), then update PROJECT_STATE.md and
the appropriate short_desc file(s), and docs/api_contract.md. Update plan_tweak.md only if this
genuinely deviated — this is the additive UI 2b explicitly deferred, so most likely no entry (log it
as a decisions-log row in PROJECT_STATE instead). Do a hallucination check on any library calls
(SQLAlchemy table introspection, pandas to_sql) against the installed versions. Archive this
session's generation prompt under prompts/ (per CLAUDE.md — the surface is API+frontend; pick per
prompts/README.md) in the same commit as the code.
