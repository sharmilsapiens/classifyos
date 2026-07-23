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
# MAGIC `run_config` (JSON) + `user_token` + `user_email` arrive as notebook `base_parameters` from
# MAGIC the submit call. The output namespace `job_id` is read from the notebook's own Databricks run
# MAGIC context (NOT a widget) so it always equals the id FastAPI polls with — the fix for the
# MAGIC "results never reach the dashboard" path mismatch.

# COMMAND ----------

import json

dbutils.widgets.text("run_config", "", "RunConfig JSON")
dbutils.widgets.text("user_token", "", "User Databricks PAT")
dbutils.widgets.text("job_id", "", "Databricks run id (fallback; namespaces output)")
dbutils.widgets.text("user_email", "", "User email (namespaces output)")

run_config = json.loads(dbutils.widgets.get("run_config"))
user_token = dbutils.widgets.get("user_token")

# Namespace output by the notebook's OWN Databricks task run id so FastAPI can locate the envelope.
# currentRunId() returns the TASK-level run_id (not the outer submit run_id), potentially wrapped
# as "RunId(858655363815036)" — strip non-digits to get just the number. FastAPI resolves the task
# run_id from the outer run_id via GET /runs/get (get_task_run_id in routes/jobs.py) so the paths
# always match regardless of which level of run_id each side sees.
import re as _re
try:
    _raw_run_id = str(
        dbutils.notebook.entry_point
        .getDbutils().notebook().getContext()
        .currentRunId().get()
    )
    _ctx_run_id = _re.sub(r'[^0-9]', '', _raw_run_id)  # strips "RunId(...)" wrapper → just digits
except Exception:
    _ctx_run_id = ""

job_id = _ctx_run_id or dbutils.widgets.get("job_id").strip() or "local"
# FastAPI resolves the user's email (SCIM, using their PAT) and forwards it here so each user's runs
# live under their own folder; "unknown_user" is the fallback for standalone runs.
user_email = dbutils.widgets.get("user_email").strip() or "unknown_user"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 3 — environment + import bootstrap
# MAGIC Select `DatabricksVolumeStorage` (Step 1) and the managed MLflow tracking server (Step 3);
# MAGIC forward the user's PAT so any token-based Unity Catalog access runs as the user. Normalize
# MAGIC the MLflow experiment to an absolute workspace path (Databricks rejects a bare name). Then
# MAGIC make the `api` package importable (it is NOT in the wheel — it lives in the repo's
# MAGIC `backend/`). The bootstrap adds the repo's `backend/` to `sys.path`, resolving it from the
# MAGIC notebook's own Workspace path with the **`/Workspace`** driver-mount prefix prepended (which
# MAGIC `notebookPath()` omits), and **fails loud with diagnostics** if `backend/` can't be found —
# MAGIC so a bad Repo/Git-folder setup surfaces here, not as a cryptic `ModuleNotFoundError` in Cell 5.

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

# Databricks managed MLflow requires the experiment to be an ABSOLUTE workspace path
# (e.g. /Users/<email>/classifyos); a bare name like "classifyos" makes set_experiment() fail with
# INVALID_PARAMETER_VALUE. If MLflow logging is enabled and the configured experiment is not
# already absolute, nest it under the caller's workspace home (resolved via Spark), falling back to
# /Shared. The engine already treats MLflow logging as best-effort (report-only) — this just lets it
# actually succeed on the cluster instead of being swallowed as "MLflow logging failed".
_mlflow_cfg = run_config.get("mlflow")
if isinstance(_mlflow_cfg, dict) and _mlflow_cfg.get("enabled"):
    _exp = str(_mlflow_cfg.get("experiment") or "classifyos").strip()
    if not _exp.startswith("/"):
        try:
            _me = spark.sql("SELECT current_user()").first()[0]
            _mlflow_cfg["experiment"] = f"/Users/{_me}/{_exp}"
        except Exception:
            _mlflow_cfg["experiment"] = f"/Shared/{_exp}"
    print("MLflow experiment:", _mlflow_cfg["experiment"])

# Make the `api` package importable. It is NOT in the engine wheel — it lives in the repo's
# backend/ dir — so this notebook must run from a Workspace/Git-folder checkout of the repo.
# GOTCHA: Databricks mounts workspace files on the driver under /Workspace/<path>, but
# notebookPath() returns the LOGICAL path WITHOUT that prefix, so we must add /Workspace to reach
# the files on disk. Try (in order) paths already on sys.path, the cwd, the mounted notebook dir,
# then the raw notebook dir — walking each upward looking for backend/api/result_builder.py.
def _ensure_api_importable():
    if any((Path(p) / "api" / "result_builder.py").exists() for p in sys.path):
        return "already on sys.path"
    try:
        _nb = (
            dbutils.notebook.entry_point.getDbutils().notebook()
            .getContext().notebookPath().get() or ""
        ).rstrip("/")
    except Exception:
        _nb = ""
    roots = [Path.cwd()]
    if _nb:
        _mounted = _nb if _nb.startswith("/Workspace/") else "/Workspace" + _nb
        roots += [Path(_mounted).parent, Path(_nb).parent]
    for _root in roots:
        for _candidate in [_root, *_root.parents]:
            if (_candidate / "backend" / "api" / "result_builder.py").exists():
                sys.path.insert(0, str(_candidate / "backend"))
                return str(_candidate / "backend")
    # Fail loud HERE with diagnostics — far clearer than a ModuleNotFoundError three cells later.
    raise RuntimeError(
        "Could not locate the repo's backend/ dir, so the `api` package is not importable. "
        "This notebook must run from a Workspace Git-folder checkout of the repo, so that "
        "backend/api/result_builder.py exists alongside it. Diagnostics: "
        f"cwd={Path.cwd()}, notebookPath={_nb!r}, roots_tried={[str(r) for r in roots]}."
    )

print("api package importable from:", _ensure_api_importable())

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

# Namespace ALL of this run's output under {output_volume}/{user_email}/{job_id}/ so runs are
# isolated per user AND per run (concurrent runs never overwrite each other), and so the envelope
# lands exactly where GET /run/{job_id}/results fetches it. Set BEFORE get_default_storage(), which
# reads DBRICKS_OUTPUT_VOLUME at construction time.
OUTPUT_BASE = f"{os.environ.get('DBRICKS_OUTPUT_VOLUME', '').rstrip('/')}/{user_email}/{job_id}"
os.environ["DBRICKS_OUTPUT_VOLUME"] = OUTPUT_BASE

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
# MAGIC Builds the envelope via `api.result_builder.build_run_result` (the SAME reshaper the
# MAGIC synchronous `/run` route uses) and writes it to `api/run_response.json` **relative to the
# MAGIC namespaced output root** set in Cell 4, i.e.
# MAGIC `{output_volume}/{user_email}/{job_id}/api/run_response.json` — exactly the path
# MAGIC `GET /api/v1/run/{job_id}/results` rebuilds and fetches. The envelope shape is byte-identical
# MAGIC to a local `/run` response (`{status, schema_version, result, error}`) so the dashboard drops
# MAGIC it straight into the existing result pages without any reshaping on the FastAPI side.

# COMMAND ----------

import json  # noqa: E402

from api.result_builder import build_run_result
from api.models import RunResponse
from api.serialize import safe_jsonify

RESULT_ENVELOPE_KEY = "api/run_response.json"

result = build_run_result(runner, storage)
response = RunResponse(status="ok", result=safe_jsonify(result))
envelope = response.model_dump(by_alias=True)

out_path = storage.path_for(RESULT_ENVELOPE_KEY, output=True)
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(envelope, fh)

print("Wrote result envelope to", out_path)
print("schema_version:", envelope.get("schema_version"))
if hasattr(runner, "metrics_df_") and runner.metrics_df_ is not None:
    display(runner.metrics_df_.sort_values("f1_weighted", ascending=False))
print("MLflow run:", getattr(runner, "mlflow_run_", None))
