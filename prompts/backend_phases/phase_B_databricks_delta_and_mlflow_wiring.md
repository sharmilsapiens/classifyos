# Phase B (Steps 3, 4 & 5) — Delta input source + managed-MLflow wiring + cluster smoke-test notebook

> Archived generation prompt (governance requirement). Task given to Claude Code on 2026-07-14.
> Produced: `materialize_delta_source()` in `classifyos/io/sql_source.py`; `"delta"` added to
> `INPUT_SOURCE_TYPES` + `catalog`/`schema`/`limit` added to `DEFAULT_CONFIG["input_source"]` +
> `_validate_delta_source`/`_require_snapshot_destination` in `classifyos/config.py`; the
> `materialize_delta_source` call in `runner._load()`; the Databricks managed-MLflow + Delta notes
> in `backend/.env.example`; the new `notebooks/classifyos_smoke_test.py`; +20 delta tests in
> `tests/test_sql_source.py` (PySpark mocked entirely); and the doc updates
> (`docs/databricks_integration.md` §6.6 Steps 3–5 + status table, PROJECT_STATE.md,
> backend_short_desc.md). Additive/opt-in — a local run with no `delta` source is byte-identical to
> before; no engine section modified; no `/api/v1/run` contract change (`schema_version` stays
> 1.10). Reference spec: `ClassifyOS_Databricks_Enhancement_Guide.md` Enhancements 2, 3, 4b.
> Companion to Phase B Steps 1 & 2 (`phase_B_databricks_storage_and_wheel.md`), Phase A
> (`phase_A_mlflow_logging.md`) and Interim 2b (`phase_2b_postgres_input_source.md`).
>
> **Step 3 verified (zero code):** re-read `classifyos/mlflow_logging.py` — it only *reads*
> `MLFLOW_TRACKING_URI` (never `set_tracking_uri()`), so `MLFLOW_TRACKING_URI=databricks` +
> `MLFLOW_REGISTRY_URI=databricks-uc` route logging to the managed server with no code change.
>
> **Hallucination check ✅** against the Microsoft Learn / Azure Databricks PySpark reference
> (Spark 4.1.0 / DBR 18.2): `SparkSession.getActiveSession()` → `SparkSession | None`;
> `SparkSession.table(tableName)` / `.sql(query)` → `DataFrame`; `DataFrame.limit(num)` →
> `DataFrame`; `DataFrame.toPandas()` → `pandas.DataFrame`; 3-part `catalog.schema.table` names
> work with `.table()`. (PySpark is not installed locally, so this substitutes for a live import
> check; the tests mock PySpark entirely.)
>
> **One correction to the reference spec:** the guide's / task's smoke-test notebook uses
> `build_config(raw_config)` (a dict positional), but the real signature is
> `build_config(input_file, target, feature_cols, **overrides)` and `feature_cols` is required —
> the archived notebook calls the real signature.

---

Implement Steps 3, 4, and 5 of the Databricks I/O integration plan in `docs/databricks_integration.md`
§6.6. Steps 1 and 2 (`DatabricksVolumeStorage` and wheel packaging) are already done. Credentials are
in `backend/.env`: `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `DATABRICKS_HTTP_PATH`.

## Step 3 — MLflow env-var wiring (zero code)

No engine changes needed. Document the cluster env vars in `backend/.env.example` and in
`docs/databricks_integration.md` §6.6 Step 3:

    MLFLOW_TRACKING_URI=databricks
    MLFLOW_REGISTRY_URI=databricks-uc

When these are set on the cluster, `mlflow_logging.py` automatically routes to the Databricks
managed tracking server. Verify this is true by reading `mlflow_logging.py` — confirm it reads
`MLFLOW_TRACKING_URI` from the environment and never hardcodes it.

## Step 4 — Delta table input source

Files to edit: `backend/classifyos/io/sql_source.py`, `backend/classifyos/config.py`,
`backend/classifyos/runner.py`.

Add `materialize_delta_source(config, storage)` to `sql_source.py` following the identical
discipline as the existing `materialize_source()` (Postgres):
- Opt-in: only runs when `config["input_source"]["type"] == "delta"`, otherwise no-ops.
- Lazy import: `from pyspark.sql import SparkSession` inside the function only — never at module level.
- If PySpark is not available (local run), raise a clear `InputSourceError` — never crash a file-based run.
- Get the active SparkSession via `SparkSession.getActiveSession()` — raise `InputSourceError` if `None`.
- Read via `spark.table("catalog.schema.table")` or `spark.sql(query)` depending on config.
- Convert to pandas, write Parquet snapshot via `StorageAdapter.save_input()` reusing the existing
  `_write_snapshot()` helper.
- [RISK] comment on SQL injection: validate `catalog`, `schema`, `table` fields against
  `_SQL_IDENTIFIER_RE` at config-build time.

Config additions in `config.py`:
- Add `"delta"` to `INPUT_SOURCE_TYPES` (currently `("file", "postgres")`).
- Add `"catalog"`, `"schema"`, `"limit"` fields to `DEFAULT_CONFIG["input_source"]`.
- Add validation in `_validate_input_source()` for `type="delta"`: require either `table` or
  `query`, validate identifiers.

One-line addition in `runner.py` `_load()`:

    from .io.sql_source import materialize_source, materialize_delta_source
    materialize_delta_source(cfg, self.storage)   # delta: runs or no-ops

Full implementation spec is in `ClassifyOS_Databricks_Enhancement_Guide.md` Enhancement 2 — use as
reference, hallucination-check all PySpark API calls against Databricks Runtime 18.2 / Spark 4.1.0.

Write unit tests in `backend/tests/test_sql_source.py` (or equivalent):
- `type="delta"` with no PySpark available → `InputSourceError` with clear message (mock the import).
- `type="delta"` with neither table nor query → `InputSourceError` at config validation.
- `type="file"` → `materialize_delta_source` is a complete no-op (call it, nothing happens).
- Identifier validation rejects unsafe table names.

Do NOT write a test that calls a real Databricks cluster — mock PySpark entirely.

## Step 5 — Smoke test on cluster

Write a Databricks notebook at `notebooks/classifyos_smoke_test.py` (plain Python, not `.ipynb`)
that: installs the wheel (`%pip install /Volumes/main/classifyos/libs/classifyos-1.0.0-py3-none-any.whl`);
sets the storage + MLflow env vars (`CLASSIFYOS_STORAGE_BACKEND=databricks`, `DBRICKS_INPUT_VOLUME`,
`DBRICKS_OUTPUT_VOLUME`, `MLFLOW_TRACKING_URI=databricks`, `MLFLOW_REGISTRY_URI=databricks-uc`);
builds a config with a `delta` input source (`catalog=main`, `schema=insurance`, `table=policy_lapse`,
`limit=5000`) and MLflow enabled; runs `ModelRunner` via `get_default_storage()`; and displays the
sorted `metrics_df_` + the MLflow run pointer.

Add a `notebooks/` folder; the notebook itself is safe to commit. It is documentation/tooling, not a
test — it verifies the full chain on a real cluster: Delta read → materialize → train → artifacts to
UC volume → MLflow experiment visible in Databricks UI.

## Scope boundary

Do not touch the FastAPI layer, API routes, or frontend. Engine sections are untouched. Only
`sql_source.py`, `config.py`, `runner.py`, `.env.example`, and the new notebook are in scope.

## When done

- Run the relevant tests and make sure they pass (add tests for new behaviour; CI must not depend on
  live external services — mock/stub them).
- Verify end-to-end where it makes sense.
- Update PROJECT_STATE.md, the appropriate `*_short_desc.md`, and `docs/databricks_integration.md`.
- Update plan_tweak.md only if this genuinely deviated from the plan.
- Do a hallucination check on any library calls against the installed version.
- Archive this session's generation prompt under `prompts/` (right surface subfolder) in the same
  commit as the code.
- Do not commit or push unless asked; when asked, keep it to one coherent commit; don't stage `data/`.
