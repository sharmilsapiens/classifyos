# ClassifyOS — Databricks Storage & Compute Enhancement Guide

> **Based on full source analysis of:** `storage.py`, `sql_source.py`, `runner.py`,
> `config.py`, `mlflow_logging.py`, `requirements.txt`, `.env`,
> `docs/databricks_integration.md`
>
> **Principle:** Every enhancement is **additive and opt-in**. A run with no new
> env vars set is byte-identical to your current local behaviour.

---

## What the codebase already has (your head-start)

Before listing what to build, it is worth being explicit about what is already in
place — because the architecture was consciously designed for this migration:

| Component | Status | Notes |
|---|---|---|
| `StorageAdapter` ABC | ✅ Done | `open_read`, `open_write`, `save_input`, `exists`, `list`, `path_for` all abstract |
| `LocalFolderStorage` | ✅ Done | Reads `DATA_DIR`, writes `OUTPUT_DIR` |
| `get_default_storage()` | ✅ Done | Returns `LocalFolderStorage` today; just needs a branch for Databricks |
| MLflow logging layer (`mlflow_logging.py`) | ✅ Done | Opt-in, lazy-import, report-only; logs params/metrics/artifacts/models |
| Postgres materialize-to-file (`sql_source.py`) | ✅ Done | The exact pattern to replicate for Delta tables |
| `input_source.type` config key | ✅ Done | `"file"` or `"postgres"` today; `"delta"` is the addition |
| `mlflow.enabled` config flag | ✅ Done | Flip it + set `MLFLOW_TRACKING_URI=databricks` → managed server |
| Engine is web-free | ✅ Done | `ModelRunner` has no FastAPI imports — importable from a notebook |
| `requirements.txt` | ✅ Done | `mlflow`, `SQLAlchemy`, `pyarrow` already pinned |

The roadmap document (`docs/databricks_integration.md`) names these as **Phase B**
(volume adapter + wheel) and **Phase C** (model registry). Both were explicitly deferred
until Databricks access was available. That is where you are now.

---

## The four enhancements required

```
Enhancement 1 — DatabricksVolumeStorage      ~60 lines   io/storage.py
Enhancement 2 — Delta table input source     ~80 lines   io/sql_source.py + config.py + runner.py
Enhancement 3 — Databricks MLflow wiring     0 lines     env config only
Enhancement 4 — Wheel + Databricks notebook  ~40 lines   pyproject.toml + notebook
```

All four are independent. You can ship them in order across sprints.

---

## Enhancement 1 — `DatabricksVolumeStorage`

### Why it is almost free

Unity Catalog volumes expose POSIX paths (`/Volumes/<catalog>/<schema>/<vol>/...`)
that work with plain Python `open()`, `os`, and `pandas` — Databricks docs describe
them as "ideal for OSS Python modules that require POSIX-style access" (DBR 13.3 LTS+).
`DatabricksVolumeStorage` is therefore `LocalFolderStorage` with its two root paths
pointed at volume paths instead of local Windows folders. The engine changes nothing.

### File to edit

`backend/classifyos/io/storage.py` — add the class after `LocalFolderStorage`, then
update `get_default_storage()`.

### Code

```python
# ── add after LocalFolderStorage in storage.py ─────────────────────────────

class DatabricksVolumeStorage(LocalFolderStorage):
    """Unity Catalog volume adapter (Databricks Runtime 13.3 LTS+).

    Unity Catalog volumes expose POSIX paths (/Volumes/<catalog>/<schema>/<vol>/...)
    that are directly usable with Python open() / pandas / matplotlib — identical to a
    local folder from the engine's perspective. This adapter is therefore a thin subclass
    of LocalFolderStorage whose roots default to volume paths from the environment.

    Required environment variables (set on the cluster or in a notebook cell):
        DBRICKS_INPUT_VOLUME  — full volume path for input data
                                e.g. /Volumes/main/classifyos/data/input
        DBRICKS_OUTPUT_VOLUME — full volume path for artifacts
                                e.g. /Volumes/main/classifyos/data/output

    Paths can also be passed directly to the constructor (useful in notebooks where
    the catalog/schema/volume are known at runtime).

    All StorageAdapter guarantees (path-traversal protection, parent-directory creation,
    the save_input/open_read/open_write input-vs-output root split) are inherited
    unchanged from LocalFolderStorage.
    """

    def __init__(
        self,
        data_dir: str | None = None,
        output_dir: str | None = None,
    ) -> None:
        resolved_data = (
            data_dir
            or os.environ.get("DBRICKS_INPUT_VOLUME")
            or os.environ.get("DATA_DIR", "data")
        )
        resolved_output = (
            output_dir
            or os.environ.get("DBRICKS_OUTPUT_VOLUME")
            or os.environ.get("OUTPUT_DIR", "classification_output")
        )
        super().__init__(data_dir=resolved_data, output_dir=resolved_output)


# ── replace get_default_storage() ──────────────────────────────────────────

def get_default_storage() -> StorageAdapter:
    """Return the configured storage adapter.

    Selection order:
      1. CLASSIFYOS_STORAGE_BACKEND=databricks  → DatabricksVolumeStorage
      2. DBRICKS_INPUT_VOLUME present            → DatabricksVolumeStorage
      3. default                                 → LocalFolderStorage (unchanged)

    Local runs need no env change — they continue to get LocalFolderStorage as before.
    """
    backend = os.environ.get("CLASSIFYOS_STORAGE_BACKEND", "").lower()
    if backend == "databricks" or (
        not backend and os.environ.get("DBRICKS_INPUT_VOLUME")
    ):
        return DatabricksVolumeStorage()
    return LocalFolderStorage()
```

### Cluster environment variables to set

```bash
# Databricks: Compute → Edit cluster → Advanced → Environment Variables
CLASSIFYOS_STORAGE_BACKEND=databricks
DBRICKS_INPUT_VOLUME=/Volumes/main/classifyos/data/input
DBRICKS_OUTPUT_VOLUME=/Volumes/main/classifyos/data/output
```

### What changes in the engine

**Nothing.** Every call in `ModelRunner`, `data_loader`, `Preprocessor`, the plot
writers — all go through `storage.open_read()` / `storage.open_write()` /
`storage.path_for()`. They do not know or care whether those resolve to
`C:/Projects/...` or `/Volumes/main/...`.

---

## Enhancement 2 — Delta table input source

### Two sub-options

**Option A — Volume file (zero new code)**
If your data already lives in a Unity Catalog volume as a CSV or Parquet file, just
set `DBRICKS_INPUT_VOLUME` and put the filename in `input_file`. The existing
`data_loader` reads it through `DatabricksVolumeStorage.open_read()`. No code change.

**Option B — Delta table (the right long-term path)**
Add `input_source.type = "delta"` that reads a Delta table via `spark.table()`,
converts to pandas, and writes a Parquet snapshot to the volume's input root via
`StorageAdapter.save_input()`. The pattern is identical to the Postgres
`materialize_source()` already in `sql_source.py`.

### Files to edit for Option B

- `backend/classifyos/io/sql_source.py` — add `materialize_delta_source()`
- `backend/classifyos/config.py` — add `"delta"` to `INPUT_SOURCE_TYPES`, add fields
- `backend/classifyos/runner.py` — add one call in `_load()`

### Code for `sql_source.py`

```python
# ── add after materialize_source() in sql_source.py ────────────────────────

def materialize_delta_source(config: dict, storage: StorageAdapter) -> None:
    """Materialize a Unity Catalog Delta table to a Parquet/CSV snapshot (Option B).

    Follows the identical discipline to materialize_source (Postgres):
    - Opt-in: only runs when config["input_source"]["type"] == "delta"
    - Lazy import: pyspark imported inside the function; never touched by file runs
    - Materialize-to-file: reads the Delta table ONCE, writes the snapshot to
      DATA_DIR via StorageAdapter.save_input(), then the normal file pipeline runs
      unchanged — data_loader, Preprocessor, ModelRunner are all untouched
    - No leakage: runs strictly BEFORE split/fit; writes only a snapshot file

    config["input_source"] fields for type="delta":
        catalog  : Unity Catalog name, e.g. "main"
        schema   : schema/database, e.g. "insurance"
        table    : table name, e.g. "policy_lapse"
        query    : optional SQL override (provide table OR query, not both)
        limit    : optional int row cap (useful for dev/smoke runs)

    [RISK] SQL injection — catalog/schema/table validated to safe identifiers at
    config-build time. A raw query is the analyst's own SQL on their own cluster.
    [RISK] Spark context — requires an active SparkSession; always present on a
    Databricks cluster, raises ImportError outside one.
    """
    source = config.get("input_source", {})
    if source.get("type") != "delta":
        return  # no-op for file/postgres sources — keeps call sites unconditional

    try:
        from pyspark.sql import SparkSession  # noqa: PLC0415 — lazy, cluster-only
    except ImportError as exc:
        raise InputSourceError(
            "input_source.type='delta' requires PySpark, which is pre-installed on "
            "Databricks clusters. Use input_source.type='file' for local runs."
        ) from exc

    spark = SparkSession.getActiveSession()
    if spark is None:
        raise InputSourceError(
            "No active SparkSession found. materialize_delta_source() must run on a "
            "Databricks cluster where a session is always present."
        )

    catalog = source.get("catalog", "")
    schema  = source.get("schema", "")
    table   = source.get("table")
    query   = source.get("query")
    limit   = source.get("limit")

    if query:
        logger.info("Delta source: running custom query")
        sdf = spark.sql(query)
    elif table:
        full_name = ".".join(filter(None, [catalog, schema, table]))
        logger.info("Delta source: reading table %s", full_name)
        sdf = spark.table(full_name)
    else:
        raise InputSourceError(
            "input_source with type='delta' requires either 'table' or 'query'"
        )

    if limit:
        sdf = sdf.limit(int(limit))

    logger.info("Delta source: converting to pandas")
    df = sdf.toPandas()

    if df.empty:
        raise InputSourceError(
            "Delta source returned an empty dataframe — check your table/query."
        )

    snapshot_key = config["input_file"]
    _write_snapshot(df, snapshot_key, storage)   # reuses existing helper unchanged
    logger.info(
        "Delta source: materialized %d rows to snapshot '%s'", len(df), snapshot_key
    )
```

### Config additions (`config.py`)

```python
# 1. Extend INPUT_SOURCE_TYPES (currently ("file", "postgres"))
INPUT_SOURCE_TYPES = ("file", "postgres", "delta")

# 2. Add fields to DEFAULT_CONFIG["input_source"]
"input_source": {
    "type":           "file",
    "connection_env": "CLASSIFYOS_PG_DSN",   # postgres only
    "table":          None,
    "query":          None,
    # new Delta fields:
    "catalog":        None,   # e.g. "main"
    "schema":         None,   # e.g. "insurance"
    "limit":          None,   # optional int row cap for dev runs
},
```

### One-line addition to `runner.py` `_load()`

```python
def _load(self, cfg):
    from .io.loader    import data_loader
    from .io.sql_source import materialize_source, materialize_delta_source

    materialize_source(cfg, self.storage)         # postgres: runs or no-ops
    materialize_delta_source(cfg, self.storage)   # delta:    runs or no-ops  ← add
    return data_loader(cfg, self.storage)
```

### Config validation — add to `_validate_input_source()`

```python
elif src_type == "delta":
    table = src.get("table")
    query = src.get("query")
    if not table and not query:
        raise ValueError(
            "input_source with type='delta' requires 'table' or 'query'"
        )
    if table and not _SQL_IDENTIFIER_RE.match(str(table)):
        raise ValueError(
            f"input_source.table {table!r} is not a safe SQL identifier"
        )
```

---

## Enhancement 3 — Databricks MLflow wiring

### Zero code required

`mlflow_logging.py` already reads `MLFLOW_TRACKING_URI` from the environment and never
sets it itself. When you set that variable to `"databricks"` on the cluster, MLflow
automatically routes to the cluster's managed tracking server and Unity Catalog registry.
Nothing in the codebase changes.

### Cluster environment variables

```bash
MLFLOW_TRACKING_URI=databricks       # routes to managed tracking server
MLFLOW_REGISTRY_URI=databricks-uc   # routes model registry to Unity Catalog
```

### Run config to enable logging

```python
"mlflow": {
    "enabled":    True,
    "experiment": "/Users/your.name@company.com/classifyos",
    "run_name":   "policy-lapse-2024-q4",
}
```

### What gets logged automatically (existing `mlflow_logging.py`)

| What | MLflow call | Where it appears |
|---|---|---|
| All run config keys | `log_params` | Experiments UI → Parameters |
| Per-model accuracy, F1, ROC-AUC, MCC, PR-AUC | `log_metrics` | Experiments UI → Metrics |
| All CSVs, PNGs, `run_profile.json` | `log_artifact` | Artifacts tab |
| Fitted models (sklearn/XGBoost/LightGBM flavor) | `log_model` | Artifacts → `models/<name>` |

### Phase C — Unity Catalog Model Registry (~10 lines, add to `mlflow_logging.py`)

```python
def _register_best_model(
    run_id: str,
    artifact_path: str,
    registered_model_name: str,   # 3-part UC name: catalog.schema.model_name
    mlflow_module,
) -> None:
    """Register the best model into Unity Catalog Model Registry. Report-only."""
    try:
        model_uri = f"runs:/{run_id}/{artifact_path}"
        mlflow_module.register_model(model_uri=model_uri, name=registered_model_name)
        logger.info("Registered '%s' from run %s", registered_model_name, run_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Model registration failed (non-fatal): %s", exc)
```

---

## Enhancement 4 — Wheel packaging + Databricks notebook

### 4a — `pyproject.toml` (add to `backend/`)

The engine is already a proper Python package. It just needs build metadata:

```toml
# backend/pyproject.toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "classifyos"
version = "1.0.0"
requires-python = ">=3.11"
dependencies = [
    "numpy>=1.26,<3", "pandas>=2.1,<3", "scikit-learn>=1.4,<2",
    "imbalanced-learn>=0.12,<1", "xgboost>=2.0,<4", "lightgbm>=4.0,<5",
    "matplotlib>=3.8,<4", "optuna>=3.6,<5", "shap>=0.46,<1",
    "mlflow>=3.1,<4", "SQLAlchemy>=2.0,<3", "pyarrow>=15.0",
    "joblib>=1.3", "openpyxl>=3.1",
]

[tool.setuptools.packages.find]
where = ["."]
include = ["classifyos*"]
```

Build and upload:

```bash
cd backend/
pip install build
python -m build --wheel
databricks fs cp dist/classifyos-1.0.0-py3-none-any.whl \
    dbfs:/Volumes/main/classifyos/libs/classifyos-1.0.0-py3-none-any.whl
```

### 4b — Databricks notebook (complete end-to-end entrypoint)

```python
# COMMAND ----------
%pip install /Volumes/main/classifyos/libs/classifyos-1.0.0-py3-none-any.whl

# COMMAND ----------
import os
os.environ["CLASSIFYOS_STORAGE_BACKEND"] = "databricks"
os.environ["DBRICKS_INPUT_VOLUME"]       = "/Volumes/main/classifyos/data/input"
os.environ["DBRICKS_OUTPUT_VOLUME"]      = "/Volumes/main/classifyos/data/output"
os.environ["MLFLOW_TRACKING_URI"]        = "databricks"
os.environ["MLFLOW_REGISTRY_URI"]        = "databricks-uc"

# COMMAND ----------
from classifyos.runner     import ModelRunner
from classifyos.config     import build_config
from classifyos.io.storage import get_default_storage

raw_config = {
    "input_file":   "snapshots/policy_lapse_2024q4.parquet",
    "target":       "will_lapse",
    "feature_cols": ["age", "premium", "tenure_days", "claim_count", "channel", "region"],
    "problem_type": "binary",
    "algorithms":   ["LogisticRegression", "RandomForest", "XGBoost", "LightGBM"],
    "class_balance": "smote",
    "test_size": 0.2,
    "stratify":  True,
    "input_source": {
        "type":    "delta",
        "catalog": "main",
        "schema":  "insurance",
        "table":   "policy_lapse",
        # Or a query: "query": "SELECT * FROM main.insurance.policy_lapse WHERE year=2024 ORDER BY id"
    },
    "mlflow": {
        "enabled":    True,
        "experiment": "/Users/your.name@company.com/classifyos",
        "run_name":   "policy-lapse-2024q4",
    },
}

config  = build_config(raw_config)
storage = get_default_storage()      # → DatabricksVolumeStorage via env var

# COMMAND ----------
runner = ModelRunner(config=config, storage=storage)
runner.run()

display(runner.metrics_df_.sort_values("f1_weighted", ascending=False))
print("MLflow run:", runner.mlflow_run_)
```

---

## Summary table

| Enhancement | Files changed | New lines | Backwards-compatible |
|---|---|---|---|
| 1. `DatabricksVolumeStorage` | `io/storage.py` | ~60 | ✅ env-var opt-in |
| 2. Delta table input source | `io/sql_source.py`, `config.py`, `runner.py` | ~80 | ✅ new source type |
| 3. Databricks MLflow wiring | cluster env only | 0 | ✅ env-var only |
| 4. Wheel + notebook | `pyproject.toml` (new), notebook (new) | ~40 | ✅ additive |

---

## New environment variables reference

| Variable | Purpose |
|---|---|
| `CLASSIFYOS_STORAGE_BACKEND=databricks` | Selects `DatabricksVolumeStorage` |
| `DBRICKS_INPUT_VOLUME` | Volume path for input data (read root) |
| `DBRICKS_OUTPUT_VOLUME` | Volume path for run artifacts (write root) |
| `MLFLOW_TRACKING_URI=databricks` | Routes MLflow to managed tracking server |
| `MLFLOW_REGISTRY_URI=databricks-uc` | Routes model registry to Unity Catalog |

---

## Recommended implementation order

**Week 1 — foundation (zero risk, can be tested locally today)**
Add `DatabricksVolumeStorage` and update `get_default_storage()`. Test locally by
setting `DBRICKS_INPUT_VOLUME` to a local folder — the engine should work identically.
Wire up `MLFLOW_TRACKING_URI=databricks` on the cluster; test locally first with
`MLFLOW_TRACKING_URI=sqlite:///mlflow.db`.

**Week 2 — Delta input source (needs cluster access for end-to-end test)**
Add `materialize_delta_source()`, extend config validation, add the extra call in
`runner._load()`. Test on the cluster with a small Delta table.

**Week 3 — packaging and notebook**
Add `pyproject.toml`, build the wheel, upload to the volume, run the notebook.
Verify the MLflow experiment appears in the Databricks UI.

**Week 4 — model registry (Phase C)**
Add `_register_best_model()` to `mlflow_logging.py`. Test Unity Catalog
champion/challenger registration.

---

## Architecture after all four enhancements

```
┌────────────────────────────────────────────────────────────────────┐
│                     Databricks Cluster                             │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  classifyos wheel                                            │  │
│  │                                                              │  │
│  │  Delta table ──► materialize_delta_source()                  │  │
│  │  (Unity Cat.)     spark.table → pandas → Parquet snapshot    │  │
│  │                          │                                   │  │
│  │  DatabricksVolumeStorage │ /Volumes/main/classifyos/data/    │  │
│  │    input/  ◄─────────────┘   (read root for data_loader)    │  │
│  │    output/ ◄─────────────── ModelRunner artifacts            │  │
│  │                                                              │  │
│  │  ModelRunner (unchanged) ──► mlflow_logging.log_run()        │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                     │
│  ┌───────────────────────────▼────────────────────────────────┐    │
│  │  Managed MLflow · Experiments UI · Unity Catalog Registry  │    │
│  └────────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────┘

React + FastAPI dashboard (unchanged — or re-homed to Databricks Apps)
```

---

## Design principles preserved throughout

**All file I/O through StorageAdapter** — `DatabricksVolumeStorage` is a new adapter
behind the same interface. No `open()` calls are added outside the adapter.

**Materialize-to-file for all database sources** — Delta follows the identical pattern
to Postgres: one snapshot write before the pipeline, then `data_loader` and everything
downstream run on a plain file, completely unchanged.

**MLflow is opt-in and report-only** — a logging failure never aborts a run; the worst
outcome is a missing MLflow record.

**Additive only, never breaking** — `"file"` remains the default source type and
`LocalFolderStorage` remains the default adapter. No existing local run needs any
env-var or config change to continue working exactly as before.

**Engine stays web-free** — `ModelRunner` and all engine modules continue to have zero
FastAPI imports. The notebook drives them the same way `cli.py` does today.
