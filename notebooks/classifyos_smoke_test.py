# Databricks notebook source
# MAGIC %md
# MAGIC # ClassifyOS — Databricks cluster smoke test (Phase B, §6.6 Step 5)
# MAGIC
# MAGIC Documentation / tooling — **not** an automated test. It verifies the full chain end to
# MAGIC end on a real cluster once Steps 1–4 are in place:
# MAGIC
# MAGIC 1. **Wheel install** — the `classifyos` engine installs from a Unity Catalog volume (Step 2).
# MAGIC 2. **`DatabricksVolumeStorage`** — reads/writes the `/Volumes/...` input & output roots (Step 1).
# MAGIC 3. **Delta input source** — `materialize_delta_source` reads a Unity Catalog Delta table via
# MAGIC    Spark → pandas → a Parquet snapshot in the input volume (Step 4).
# MAGIC 4. **MLflow managed tracking** — with `MLFLOW_TRACKING_URI=databricks` the run appears in the
# MAGIC    Databricks Experiments UI, no code change (Step 3).
# MAGIC 5. **Artifacts** — the CSVs / PNGs / `run_profile.json` land in the output volume.
# MAGIC
# MAGIC No engine code changes are needed — the notebook plays the role `cli.py` plays locally.
# MAGIC Adjust the catalog/schema/table, the feature columns, and the MLflow experiment path to
# MAGIC your workspace before running.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 1 — install the wheel (notebook-scoped)
# MAGIC Build + upload the wheel first (see `docs/databricks_integration.md` §6.6 Step 2):
# MAGIC `databricks fs cp dist/classifyos-1.0.0-py3-none-any.whl dbfs:/Volumes/main/classifyos/libs/...`

# COMMAND ----------

# MAGIC %pip install /Volumes/main/classifyos/libs/classifyos-1.0.0-py3-none-any.whl

# COMMAND ----------

# MAGIC %md
# MAGIC A `%pip install` restarts the Python interpreter on recent Databricks runtimes. If yours
# MAGIC does not, uncomment the line below so the freshly-installed `classifyos` is importable.

# COMMAND ----------

# dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 2 — environment variables
# MAGIC These are normally set on the cluster (Compute → Edit → Advanced → Environment Variables);
# MAGIC setting them here keeps the smoke test self-contained. They select
# MAGIC `DatabricksVolumeStorage` (Step 1) and route MLflow to the managed tracking server (Step 3).

# COMMAND ----------

import os

os.environ["CLASSIFYOS_STORAGE_BACKEND"] = "databricks"
os.environ["DBRICKS_INPUT_VOLUME"] = "/Volumes/main/classifyos/data/input"
os.environ["DBRICKS_OUTPUT_VOLUME"] = "/Volumes/main/classifyos/data/output"
os.environ["MLFLOW_TRACKING_URI"] = "databricks"
os.environ["MLFLOW_REGISTRY_URI"] = "databricks-uc"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 3 — build the config and run with a Delta input source
# MAGIC `build_config(input_file, target, feature_cols, **overrides)` is the authoritative validator
# MAGIC (a bad value raises `ValueError`). `feature_cols` is **required** — set it to the feature
# MAGIC columns of your Delta table (the example below matches the `policy_lapse` sample). The Delta
# MAGIC table is materialized to `input_file` (a Parquet snapshot under the input volume) BEFORE the
# MAGIC pipeline runs, so training reads a plain file — leakage discipline unchanged.

# COMMAND ----------

from classifyos.config import build_config
from classifyos.io.storage import get_default_storage
from classifyos.runner import ModelRunner

config = build_config(
    input_file="snapshots/smoke_test.parquet",  # Parquet snapshot the Delta read materializes to
    target="will_lapse",
    feature_cols=[  # ← set to your Delta table's feature columns
        "age",
        "annual_premium",
        "policy_tenure_years",
        "num_late_payments",
        "claims_count",
    ],
    problem_type="binary",
    algorithms=["LogisticRegression", "RandomForest"],
    input_source={
        "type": "delta",
        "catalog": "main",
        "schema": "insurance",
        "table": "policy_lapse",
        "limit": 5000,  # small cap for a smoke test; drop for a full run
        # Or a raw query instead of catalog/schema/table:
        # "query": "SELECT * FROM main.insurance.policy_lapse WHERE year = 2024 ORDER BY id",
    },
    mlflow={
        "enabled": True,
        "experiment": "/Users/sharmil.basa@sapiens.com/classifyos-smoke",  # ← your workspace path
        "run_name": "smoke-test",
    },
)

storage = get_default_storage()  # → DatabricksVolumeStorage (CLASSIFYOS_STORAGE_BACKEND=databricks)
runner = ModelRunner(config=config, storage=storage)
runner.run()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 4 — inspect the results
# MAGIC The model scoreboard, plus the MLflow run pointer (its `run_id` / tracking URI and a load
# MAGIC URI per saved model). Open the Databricks **Experiments** UI to confirm the run, its params,
# MAGIC metrics, artifacts, and logged models are visible.

# COMMAND ----------

display(runner.metrics_df_.sort_values("f1_weighted", ascending=False))
print("MLflow run:", runner.mlflow_run_)
