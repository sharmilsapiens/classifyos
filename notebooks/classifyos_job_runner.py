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
dbutils.widgets.text("azure_secret_scope", "", "Azure OpenAI secret scope (LLM narratives; empty = off)")

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
# Secret scope holding the Azure OpenAI creds for LLM reason-code narratives (empty = narratives off).
# FastAPI syncs the creds into this scope and passes only its NAME here — the key never rides in the
# Job's run parameters. Read the creds from it into the env in Cell 3.
azure_secret_scope = dbutils.widgets.get("azure_secret_scope").strip()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 3 — environment setup
# MAGIC Select `DatabricksVolumeStorage` (Step 1) and the managed MLflow tracking server (Step 3);
# MAGIC forward the user's PAT so any token-based Unity Catalog access runs as the user. Normalize
# MAGIC the MLflow experiment to an absolute workspace path (Databricks rejects a bare name).
# MAGIC
# MAGIC **No import bootstrap needed.** The envelope reshaper now ships INSIDE the engine wheel
# MAGIC (`classifyos.envelope`), so Cell 5 imports it from the installed package — this notebook no
# MAGIC longer needs the repo's `backend/` on `sys.path`, and can run from a plain notebook import
# MAGIC (a Git-folder checkout is no longer required for the `/run` envelope).

# COMMAND ----------

import os

os.environ["CLASSIFYOS_STORAGE_BACKEND"] = "databricks"
os.environ.setdefault("DBRICKS_INPUT_VOLUME", "/Volumes/aiml_rd/classifyos/input")
os.environ.setdefault("DBRICKS_OUTPUT_VOLUME", "/Volumes/aiml_rd/classifyos/output")
os.environ["MLFLOW_TRACKING_URI"] = "databricks"
os.environ["MLFLOW_REGISTRY_URI"] = "databricks-uc"
# Unity Catalog reads run AS THE USER (their PAT), never the service token.
if user_token:
    os.environ["DATABRICKS_TOKEN"] = user_token

# LLM reason-code narratives (Azure OpenAI): FastAPI synced the creds into a Databricks secret scope
# and passed only its NAME (the key never rides in the Job's run parameters). Pull them into the env
# so the engine's classifyos.analysis.llm_explain.narrator_from_env() finds them. Report-only: a
# missing scope/key (e.g. the optional MODEL, or narratives not requested) just leaves narratives off
# and SHAP still ships. dbutils.secrets.get redacts the values in any notebook output.
if azure_secret_scope:
    for _secret_key in (
        "AZURE_OPEN_AI_ENDPOINT",
        "AZURE_OPEN_AI_API_KEY",
        "AZURE_OPEN_AI_API_VERSION",
        "AZURE_OPEN_AI_DEPLOYMENT_NAME",
        "AZURE_OPEN_AI_MODEL",
    ):
        try:
            os.environ[_secret_key] = dbutils.secrets.get(scope=azure_secret_scope, key=_secret_key)
        except Exception:  # noqa: BLE001 — missing key/scope → skip; narratives just stay off
            pass

# Databricks managed MLflow requires the experiment to be an ABSOLUTE workspace path; a bare name
# like "classifyos" fails set_experiment() with INVALID_PARAMETER_VALUE. If logging is enabled and
# the configured experiment isn't already absolute, nest it under /Shared — which always exists and
# is writable by the cluster identity. We deliberately do NOT use /Users/<current_user>: this
# cluster runs as a service principal, so current_user() is e.g. "AIML_RD" and /Users/AIML_RD does
# not exist (the earlier NOT_FOUND). /Shared avoids guessing an identity's home dir. Report-only:
# a bad path only means "no MLflow record", never a failed run.
_mlflow_cfg = run_config.get("mlflow")
if isinstance(_mlflow_cfg, dict) and _mlflow_cfg.get("enabled"):
    _exp = str(_mlflow_cfg.get("experiment") or "classifyos").strip()
    if not _exp.startswith("/"):
        _mlflow_cfg["experiment"] = f"/Shared/{_exp}"
    print("MLflow experiment:", _mlflow_cfg["experiment"])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 4 — build the engine config and run the pipeline
# MAGIC `build_config(...)` runs the SAME validation the synchronous `/run` route applies (the route
# MAGIC reaches it via `RunConfig.to_engine_config`; the submit already dumped the request `by_alias`,
# MAGIC so a `delta` input source's `schema` key arrives in the shape `build_config` expects). The
# MAGIC request model `RunConfig` stays in the web layer — the notebook needs only the engine wheel.
# MAGIC A `delta` input source materializes the Unity Catalog table to a Parquet snapshot on the
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
# MAGIC Builds the envelope via `classifyos.envelope.build_run_envelope` (the SAME reshaper +
# MAGIC `RunResponse` the synchronous `/run` route uses, now shipped INSIDE the engine wheel) and
# MAGIC writes it to `api/run_response.json` **relative to the namespaced output root** set in Cell 4,
# MAGIC i.e. `{output_volume}/{user_email}/{job_id}/api/run_response.json` — exactly the path
# MAGIC `GET /api/v1/run/{job_id}/results` rebuilds and fetches. The envelope is byte-identical
# MAGIC to a local `/run` response (`{status, schema_version, result, error}`) so the dashboard drops
# MAGIC it straight into the existing result pages without any reshaping on the FastAPI side.

# COMMAND ----------

import json  # noqa: E402

from classifyos.envelope import build_run_envelope  # noqa: E402

RESULT_ENVELOPE_KEY = "api/run_response.json"

# Single call → the full {status, schema_version, result, error} envelope, byte-identical to a
# local /run response (build_run_result + RunResponse.model_dump(by_alias=True), all in the wheel).
envelope = build_run_envelope(runner, storage)

out_path = storage.path_for(RESULT_ENVELOPE_KEY, output=True)
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(envelope, fh)

print("Wrote result envelope to", out_path)
print("schema_version:", envelope.get("schema_version"))
if hasattr(runner, "metrics_df_") and runner.metrics_df_ is not None:
    display(runner.metrics_df_.sort_values("f1_weighted", ascending=False))
print("MLflow run:", getattr(runner, "mlflow_run_", None))

# Register this run in the per-user Runs view: attach the SAME envelope as an MLflow artifact and
# tag it with the owner (user_email) + the reloadable marker, via the engine's single-source helper
# (classifyos.mlflow_logging.snapshot_envelope). Report-only: if MLflow logging was off/failed,
# runner.mlflow_run_ is None and we skip. The tag value is the SAME sanitized email FastAPI resolves
# on GET /runs, so the dashboard filters this run to its owner and can reload it byte-identically.
_mlflow_run = getattr(runner, "mlflow_run_", None)
if _mlflow_run and _mlflow_run.get("run_id"):
    from classifyos.mlflow_logging import snapshot_envelope  # noqa: E402

    snapshot_envelope(_mlflow_run["run_id"], envelope, user_email=user_email)
    print("Registered MLflow run for per-user Runs:", _mlflow_run["run_id"], "owner:", user_email)
