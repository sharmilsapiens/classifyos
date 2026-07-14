# Databricks notebook source
# MAGIC %md
# MAGIC # ClassifyOS — Databricks Job entrypoint (orchestration §6.6 Step 6)
# MAGIC
# MAGIC The notebook the **FastAPI orchestration layer** submits as a one-off Databricks Job
# MAGIC (`POST /api/2.1/jobs/runs/submit`). It is the cluster-side half of the async `/run` flow:
# MAGIC FastAPI submits this notebook → this notebook runs the engine and writes the locked `/run`
# MAGIC envelope to the Unity Catalog **output** volume → FastAPI's `GET /run/{job_id}/results`
# MAGIC fetches that envelope and returns it to the dashboard, byte-identical to a local run.
# MAGIC
# MAGIC It is **tooling / documentation — not an automated test** (like the Step 5 smoke test): it is
# MAGIC written against the real APIs and hallucination-checked, but running it needs a live cluster,
# MAGIC which is pending. The FastAPI side (submit / poll / fetch) is fully unit-tested with the
# MAGIC Databricks REST calls mocked.
# MAGIC
# MAGIC **How FastAPI invokes it.** The submit payload passes two `base_parameters`:
# MAGIC * `run_config` — the RunConfig as a JSON string (the exact `POST /run` request body), and
# MAGIC * `user_token` — the requesting user's PAT, so Unity Catalog reads run **as the user**, never
# MAGIC   as the service identity.
# MAGIC
# MAGIC **Why it can reshape the envelope.** The single canonical reshaper is
# MAGIC `api.result_builder.build_run_result` (the same one the synchronous `/run` route uses). The
# MAGIC engine wheel does not include the `api` package, so this notebook is expected to run from a
# MAGIC **Databricks Repo** (Git-backed) checkout of this repository — the bootstrap in Cell 3 adds
# MAGIC the repo's `backend/` to `sys.path` so `api.*` is importable. (`DATABRICKS_JOB_NOTEBOOK_PATH`
# MAGIC in `backend/.env.example` points at `/Repos/classifyos/notebooks/classifyos_job_runner`.)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 1 — install the engine wheel (notebook-scoped)
# MAGIC When submitted by FastAPI the wheel is already installed as a task library before this
# MAGIC notebook runs — no pip call needed. For standalone runs, set DATABRICKS_JOB_WHEEL_PATH
# MAGIC or pass wheel_path as a widget and this cell installs it.

# COMMAND ----------

import importlib, os, subprocess

dbutils.widgets.text("wheel_path", "", "Wheel path (leave blank if installed via task library)")
_wheel = dbutils.widgets.get("wheel_path").strip() or os.environ.get("DATABRICKS_JOB_WHEEL_PATH", "").strip()

try:
    importlib.import_module("classifyos")
except ModuleNotFoundError:
    if not _wheel:
        raise RuntimeError(
            "classifyos is not installed and no wheel_path was provided. "
            "Set DATABRICKS_JOB_WHEEL_PATH or pass wheel_path as a widget."
        )
    subprocess.run(["pip", "install", _wheel], check=True)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 2 — read the Job parameters
# MAGIC `run_config` (JSON) + `user_token` arrive as notebook `base_parameters` from the submit call.

# COMMAND ----------

import json

dbutils.widgets.text("run_config", "", "RunConfig JSON")
dbutils.widgets.text("user_token", "", "User Databricks PAT")

run_config = json.loads(dbutils.widgets.get("run_config"))
user_token = dbutils.widgets.get("user_token")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 3 — environment + import bootstrap
# MAGIC Select `DatabricksVolumeStorage` (Step 1) and the managed MLflow tracking server (Step 3);
# MAGIC forward the user's PAT so any token-based Unity Catalog access runs as the user. Then make
# MAGIC the `api` package importable (this notebook runs from a Databricks Repo checkout).

# COMMAND ----------

import os
import sys
from pathlib import Path

os.environ["CLASSIFYOS_STORAGE_BACKEND"] = "databricks"
os.environ.setdefault("DBRICKS_INPUT_VOLUME", "/Volumes/aiml_rd/classifyos/input")
os.environ.setdefault("DBRICKS_OUTPUT_VOLUME", "/Volumes/aiml_rd/classifyos/output")
os.environ["MLFLOW_TRACKING_URI"] = "databricks"
os.environ["MLFLOW_REGISTRY_URI"] = "databricks-uc"
# Unity Catalog reads run AS THE USER (their PAT), never the service token.
if user_token:
    os.environ["DATABRICKS_TOKEN"] = user_token

# Make the `api` package importable. In a Databricks Repo the repo files sit next to this
# notebook; walk up from the working directory to find the repo's backend/ dir.
if not any((Path(p) / "api" / "result_builder.py").exists() for p in sys.path):
    here = Path.cwd()
    for candidate in [here, *here.parents]:
        backend_dir = candidate / "backend"
        if (backend_dir / "api" / "result_builder.py").exists():
            sys.path.insert(0, str(backend_dir))
            break

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 4 — build the engine config and run the pipeline
# MAGIC `RunConfig(**run_config).to_engine_config()` is the SAME validation + translation the
# MAGIC synchronous `/run` route applies, so a Databricks run is configured identically to a local
# MAGIC one. A `delta` input source materializes the Unity Catalog table to a Parquet snapshot on the
# MAGIC input volume before training (Step 4); leakage discipline unchanged.

# COMMAND ----------

from classifyos.config import build_config  # noqa: E402
from classifyos.io.storage import get_default_storage  # noqa: E402
from classifyos.runner import ModelRunner  # noqa: E402

_cfg = dict(run_config)
engine_config = build_config(
    input_file=_cfg.pop("input_file"),
    target=_cfg.pop("target"),
    feature_cols=_cfg.pop("feature_cols"),
    **_cfg,
)
storage = get_default_storage()  # → DatabricksVolumeStorage (CLASSIFYOS_STORAGE_BACKEND=databricks)
runner = ModelRunner(config=engine_config, storage=storage)
runner.run()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 5 — write the locked `/run` envelope to the output volume
# MAGIC Reshape with the canonical `build_run_result` (identical to the local `/run` route) and write
# MAGIC it to `api/run_response.json` on the OUTPUT volume — exactly the key
# MAGIC `GET /api/v1/run/{job_id}/results` fetches through the StorageAdapter.

# COMMAND ----------

import json, numpy as np, pandas as pd  # noqa: E402

RESULT_ENVELOPE_KEY = "api/run_response.json"

def _serializable(obj):
    if isinstance(obj, (np.integer,)): return int(obj)
    if isinstance(obj, (np.floating,)): return float(obj)
    if isinstance(obj, np.ndarray): return obj.tolist()
    if isinstance(obj, pd.DataFrame): return obj.to_dict(orient="records")
    return str(obj)

# Write raw runner state — FastAPI's GET /run/{job_id}/results reshapes this
envelope = {
    "status": "ok",
    "mlflow_run": getattr(runner, "mlflow_run_", None),
    "metrics": _serializable(getattr(runner, "metrics_df_", pd.DataFrame())),
    "best_model": getattr(runner, "best_model_name_", None),
    "artifacts_written": True,
}

out_path = storage.path_for(RESULT_ENVELOPE_KEY, output=True)
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(envelope, fh, default=_serializable)

print("Wrote result envelope to", out_path)
if hasattr(runner, "metrics_df_"):
    display(runner.metrics_df_.sort_values("f1_weighted", ascending=False))
print("MLflow run:", getattr(runner, "mlflow_run_", None))
