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
# MAGIC `run_config` (JSON), `user_token`, and `job_id` arrive as notebook `base_parameters` from
# MAGIC the submit call. `job_id` is FastAPI's own handle for this run; the notebook uses it to
# MAGIC namespace all output (`api/{job_id}/…` + `artifacts/{job_id}/…`) so concurrent runs never
# MAGIC overwrite one another (§Problem 2) and `GET /run/{job_id}/results` reads the right file.

# COMMAND ----------

import json

dbutils.widgets.text("run_config", "", "RunConfig JSON")
dbutils.widgets.text("user_token", "", "User Databricks PAT")
dbutils.widgets.text("job_id", "", "FastAPI job handle (namespaces output)")

run_config = json.loads(dbutils.widgets.get("run_config"))
user_token = dbutils.widgets.get("user_token")
# Fall back to "local" for a standalone (non-FastAPI) run so the output paths are still well-formed.
job_id = dbutils.widgets.get("job_id").strip() or "local"

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

# Make the `api` package importable — it holds the `/run` reshaper (`result_builder`/`models`/
# `serialize`) that Cell 5 needs, and it is NOT in the classifyos WHEEL (the wheel ships the engine
# only). So this notebook must run from a **Databricks Repo / Git folder** where the repo's
# `backend/` dir is present; we add that dir to sys.path here. See docs/databricks_how_it_works.md §11.
def _add_backend_to_path() -> None:
    """Put the repo's `backend/` (the one containing `api/result_builder.py`) on sys.path.

    Searches, in order: (a) sys.path already resolves `api` → nothing to do; (b) walking up from the
    current working directory; (c) walking up from THIS notebook's own Git-folder path (reliable even
    when the job's cwd is not the notebook's directory). Raises a clear, actionable error if none hit,
    instead of a cryptic `ModuleNotFoundError: No module named 'api'` later in Cell 5.
    """
    def _has_api(d: Path) -> bool:
        return (d / "api" / "result_builder.py").exists()

    # (a) already importable via an existing sys.path entry
    if any(_has_api(Path(p)) for p in sys.path):
        return

    candidates: list[Path] = []
    # (b) walk up from the working directory
    here = Path.cwd()
    candidates += [c / "backend" for c in [here, *here.parents]]
    # (c) derive from the notebook's own workspace path, e.g.
    #     /Repos/<user>/<repo>/notebooks/classifyos_job_runner → /Workspace/Repos/<user>/<repo>/backend
    try:
        nb_path = (
            dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
        )
        ws_root = Path("/Workspace" + nb_path) if not nb_path.startswith("/Workspace") else Path(nb_path)
        candidates += [c / "backend" for c in ws_root.parents]
    except Exception:  # noqa: BLE001 — best-effort; the cwd walk above may already have found it
        pass

    for backend_dir in candidates:
        if _has_api(backend_dir):
            sys.path.insert(0, str(backend_dir))
            return

    raise RuntimeError(
        "The `api` package (needed to build the full /run result envelope in Cell 5) is not "
        "importable. Run this notebook from a Databricks Repo / Git folder so the repo's backend/ "
        "dir is on sys.path — set DATABRICKS_JOB_NOTEBOOK_PATH to the /Repos path (NOT a /Workspace/"
        "Users copy) and Pull after each push. See docs/databricks_how_it_works.md §11. (The "
        "classifyos wheel ships the engine only; the api reshaper lives in the repo source.)"
    )


_add_backend_to_path()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 4 — configure MLflow, build the engine config, run the pipeline
# MAGIC `build_config` applies the SAME validation + translation the synchronous `/run` route uses,
# MAGIC so a Databricks run is configured identically to a local one. A `delta` input source
# MAGIC materializes the Unity Catalog table to a Parquet snapshot on the input volume before
# MAGIC training (Step 4); leakage discipline unchanged. Two Databricks-specific wirings happen here:
# MAGIC
# MAGIC * **Per-job output** (§Problem 2) — the storage adapter's output root is
# MAGIC   `.../output/artifacts/{job_id}`, so every engine artifact (CSVs, plots, `run_profile.json`)
# MAGIC   lands under `artifacts/{job_id}/` and concurrent runs never overwrite each other.
# MAGIC * **MLflow logging** (§Problems 3 + 4) — we enable the engine's built-in, report-only MLflow
# MAGIC   layer (`classifyos.mlflow_logging`, opt-in via `cfg["mlflow"]`). Reusing the engine's tested
# MAGIC   logger — rather than re-implementing MLflow calls in the notebook — logs the config as
# MAGIC   params, each model's held-out TEST metrics, the artifact files, and **one saved model per
# MAGIC   fitted algorithm** (flavor-native: `mlflow.xgboost`/`lightgbm`/`sklearn`) to the managed
# MAGIC   tracking server (Cell 3 set `MLFLOW_TRACKING_URI=databricks`). This is what persists the
# MAGIC   trained models on Databricks (§Problem 3); the run id then flows into the result envelope
# MAGIC   via `result.mlflow` (§Problem 4d), so the dashboard can link to the MLflow UI.

# COMMAND ----------

import mlflow  # noqa: E402

from classifyos.config import build_config  # noqa: E402
from classifyos.io.storage import DatabricksVolumeStorage  # noqa: E402
from classifyos.runner import ModelRunner  # noqa: E402

# Per-job output root (§Problem 2). The Job entrypoint owns these path shapes; FastAPI's
# GET /run/{job_id}/results fetches api/{job_id}/run_response.json from the SAME OUTPUT_BASE.
OUTPUT_BASE = os.environ.get("DBRICKS_OUTPUT_VOLUME", "/Volumes/aiml_rd/classifyos/output").rstrip("/")
storage = DatabricksVolumeStorage(output_dir=f"{OUTPUT_BASE}/artifacts/{job_id}")


def _resolve_experiment(candidates):
    """First MLflow experiment path `set_experiment` accepts, or None if all fail (report-only).

    [FALLBACK] The extra candidate + the None return exist because the user may not yet have
    permission to create `/classifyos/runs`. An MLflow permission problem must NEVER abort the
    training run — remove this fallback list once the workspace experiment perms are granted.
    """
    for path in candidates:
        try:
            mlflow.set_experiment(path)
            print(f"MLflow experiment → {path!r}")
            return path
        except Exception as exc:  # noqa: BLE001 — a permission failure is report-only
            print(f"[warn] could not set MLflow experiment {path!r}: {exc}")
    return None


experiment_path = _resolve_experiment(["/classifyos/runs", "/classifyos-fallback"])

_cfg = dict(run_config)
engine_config = build_config(
    input_file=_cfg.pop("input_file"),
    target=_cfg.pop("target"),
    feature_cols=_cfg.pop("feature_cols"),
    **_cfg,
)
# Enable the engine's report-only MLflow logging (params + metrics + artifacts + per-model saved
# models). Disabled ONLY if no experiment path was accepted (the permission fallback above) — the
# run still completes and writes its envelope, just without an MLflow record.
engine_config["mlflow"] = {
    "enabled": experiment_path is not None,
    "experiment": experiment_path or "classifyos",
    "run_name": f"classifyos-{job_id}",
}

runner = ModelRunner(config=engine_config, storage=storage)
runner.run()
print("MLflow run:", getattr(runner, "mlflow_run_", None))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 4b — register the best model in the Unity Catalog Model Registry (§Problem 5)
# MAGIC The engine already logged one saved model per algorithm in Cell 4. Here we register the
# MAGIC **best** model (highest held-out `f1_weighted`) as a new VERSION of the three-part Unity
# MAGIC Catalog model `aiml_rd.classifyos.classifyos_model` and point the `champion` alias at it, so
# MAGIC it is loadable / servable by alias
# MAGIC (`models:/aiml_rd.classifyos.classifyos_model@champion`).
# MAGIC
# MAGIC Unity Catalog uses **aliases, not stages** — we never set a `"Staging"`/`"Production"` stage.
# MAGIC Every step is wrapped report-only: if the user lacks `CREATE MODEL` / registry permission the
# MAGIC model stays logged as an MLflow artifact (loadable by its run URI) and the training run is
# MAGIC unaffected. [FALLBACK] remove the try/except once UC registry perms are granted.

# COMMAND ----------

#: Three-part Unity Catalog model name (catalog.schema.model). Overridable via env for other WSs.
UC_MODEL_NAME = os.environ.get("CLASSIFYOS_UC_MODEL", "aiml_rd.classifyos.classifyos_model")


def _best_model_name(runner):
    """Name of the successful model with the highest held-out `f1_weighted` (or None)."""
    df = getattr(runner, "metrics_df_", None)
    if df is None or df.empty:
        return None
    ok = df[df["status"] == "ok"]
    if ok.empty:
        return None
    return str(ok.sort_values("f1_weighted", ascending=False).iloc[0]["model"])


registry_info = None
_mlflow_run = getattr(runner, "mlflow_run_", None) or {}
_model_uris = _mlflow_run.get("models") or {}
_best = _best_model_name(runner)

if _best and _best in _model_uris:
    try:
        _mv = mlflow.register_model(_model_uris[_best], UC_MODEL_NAME)
        registry_info = {"name": UC_MODEL_NAME, "version": str(_mv.version), "source_model": _best}
        print(f"Registered {_best!r} → {UC_MODEL_NAME} v{_mv.version}")
        try:
            mlflow.MlflowClient().set_registered_model_alias(UC_MODEL_NAME, "champion", _mv.version)
            registry_info["alias"] = "champion"
            print(f"Alias 'champion' → {UC_MODEL_NAME} v{_mv.version}")
        except Exception as exc:  # noqa: BLE001 — alias permission is report-only
            print(f"[warn] could not set 'champion' alias (permissions?): {exc}")
    except Exception as exc:  # noqa: BLE001 — registry permission is report-only
        print(f"[warn] could not register model to UC registry (permissions?): {exc}")
else:
    print("No MLflow-logged model to register (MLflow disabled, or no successful model).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cell 5 — write the locked `/run` envelope to the output volume (§Problem 1)
# MAGIC Reshape the finished runner with the canonical `build_run_result` (the SAME reshaper the
# MAGIC local `/run` route uses) and wrap it in the locked `RunResponse` envelope
# MAGIC (`{status, schema_version, result, error}`), so the dashboard renders it **byte-identical to
# MAGIC a local run** — fixing the previous blank/error dashboard, which was caused by writing a
# MAGIC simplified (non-locked) envelope the frontend's `parseRunResponse` rejected. Written to
# MAGIC `api/{job_id}/run_response.json` on the OUTPUT volume — exactly the key
# MAGIC `GET /api/v1/run/{job_id}/results` fetches. Requires the `api` package on `sys.path`
# MAGIC (Cell 3 bootstrap — this notebook runs from a Databricks Repo checkout).

# COMMAND ----------

from api.result_builder import build_run_result  # noqa: E402
from api.models import RunResponse  # noqa: E402
from api.serialize import safe_jsonify  # noqa: E402

# build_run_result reads the finished runner (metrics, curves, predictions preview, feature
# impact/importance, the artifact listing from `storage`, and result.mlflow from runner.mlflow_run_).
result = build_run_result(runner, storage)
# safe_jsonify: numpy → Python + NaN/Inf → None; RunResponse then stamps schema_version. by_alias
# keeps the on-disk envelope byte-identical to the wire response the local /run route emits.
envelope = RunResponse(status="ok", result=safe_jsonify(result)).model_dump(by_alias=True)

result_path = f"{OUTPUT_BASE}/api/{job_id}/run_response.json"
os.makedirs(os.path.dirname(result_path), exist_ok=True)
with open(result_path, "w", encoding="utf-8") as fh:
    json.dump(envelope, fh)

print("Wrote locked /run envelope to", result_path)
if getattr(runner, "metrics_df_", None) is not None and not runner.metrics_df_.empty:
    display(runner.metrics_df_.sort_values("f1_weighted", ascending=False))
if registry_info:
    print("Registered model:", registry_info)
