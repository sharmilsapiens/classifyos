# Phase Interim 2b — opt-in Postgres INPUT source (materialize-to-file, Option B)

> Archived generation prompt (governance requirement). Verbatim task given to Claude Code on
> 2026-07-08. Produced: `classifyos/io/sql_source.py`, the `input_source` config block +
> `_validate_input_source` in `config.py`, the `ModelRunner._load` pre-step, the API
> `InputSourceConfig` + `RunConfig.input_source` + `/run` `InputSourceError` handling,
> `tests/test_sql_source.py`, API tests, deps (`SQLAlchemy`), `.env.example`/`.env`, and the
> `docs/api_contract.md` request-side note. Additive, request-side only — no `schema_version`
> change (stays 1.10). Companion to Interim 2a (`api_phases/phase_2a_mlflow_postgres_runhistory.md`).

---

Implement Interim Phase 2b of docs/databricks_integration.md §6.5 using Option B (materialize-to-file) — read that doc first. Phases A and 2a are merged (MLflow logging + Postgres backend store + run-history; latest commit 4fdc72f, schema 1.10). Local-only; no Databricks, no push. PostgreSQL 17 is already running as a Windows service.

- Add an opt-in input source to config: default file (today's behavior) vs new postgres, carrying a connection reference (env/DSN — never a hardcoded credential) plus a table name or a SQL query. Validate it in build_config (the authoritative validator → bad value = 422), same discipline as the other config validators (e.g. how mlflow/explainability are validated).
- Use Option B, materialize-to-file: a small helper (API-side or a data_loader pre-step) runs the query once, writes the result to a Parquet/CSV under DATA_DIR via StorageAdapter (save_input/open_write), and hands the resulting key to the normal pipeline. data_loader and everything downstream must be unchanged — the engine still reads a file, so the StorageAdapter rule and the leakage discipline (load → split → fit-on-train) stay literally intact. Snapshotting the query result to a file is intended (reproducibility/audit).
- Add the driver dependency pinned to requirements.txt + requirements.lock (SQLAlchemy + psycopg/psycopg2); connection config lives in backend/.env (documented in .env.example, gitignored/machine-local).
- API: additive only — a request-side input-source block; bump schema_version only if the response shape changes (a pure request-side dial doesn't); update docs/api_contract.md. Existing fields unchanged.
- Dashboard UI to pick a table/query can be a follow-up — engine + API first. If you add any UI, keep it additive.
- Hallucination check first: verify sqlalchemy.create_engine + pandas.read_sql (and the chosen psycopg driver) against the installed versions before writing code.
- Verify: load a sample CSV (e.g. policy_lapse.csv) into a Postgres table, run the pipeline with source=postgres pointing at that table, and confirm it produces the same result as running on the original CSV file directly.

Out of scope (later/deferred): Phase B DatabricksVolumeStorage, Phase C Model Registry/Serving, the /explain→persisted-model wiring, and Phase D dashboard polish (e.g. localStorage last-view restore). Don't build the deferred Databricks pieces speculatively.

When done: run the relevant tests and make sure they pass, then update PROJECT_STATE.md and the appropriate short_desc file(s) to reflect what changed. Update plan_tweak.md only if this genuinely deviated from the plan — don't invent an entry. Do a hallucination check on any library calls against the installed versions. And archive this session's generation prompt under prompts/ (per CLAUDE.md) in the same commit as the code.
