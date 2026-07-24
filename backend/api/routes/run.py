"""``POST /api/v1/run`` — execute a classification run and return the locked schema.

This is the heart of the API. The body is a :class:`RunConfig` (validated by FastAPI before this
function runs). ``build_config`` (via ``RunConfig.to_engine_config``) is the single authoritative
validator, so a bad config is always a 422 regardless of backend.

**Two execution backends (env-gated — §6.6 Step 6).** ``CLASSIFYOS_EXECUTION_BACKEND`` selects how
the run executes:

* ``"local"`` (default) — the run executes **in-process, synchronously**: the whole pipeline runs
  through :class:`~classifyos.runner.ModelRunner` on a worker thread and the finished runner's
  state is reshaped (via :func:`api.result_builder.build_run_result`) into the locked
  ``/api/v1/run`` envelope, returned in one response. This is byte-identical to prior schemas and
  is what local dev + CI (and every existing test) exercise.
* ``"databricks"`` — the run is submitted as a **Databricks Job** and this endpoint returns a
  :class:`RunSubmission` (``{job_id, run_id, status}``) **immediately** (no blocking). The client
  then polls ``GET /run/{job_id}/status`` and, once ``COMPLETED``, fetches the SAME locked envelope
  from ``GET /run/{job_id}/results``. The user's PAT (``X-Databricks-Token`` header) is forwarded
  to the Job for Unity Catalog data access; the service token is used only for the Jobs API call.

Design notes worth understanding as a reader:

* **Why a threadpool (local)?** ``ModelRunner.run()`` is ordinary synchronous, CPU-heavy Python. If
  we called it directly in this ``async def`` it would block FastAPI's event loop. ``run_in_threadpool``
  moves the blocking work onto a worker thread so the server stays responsive. The Databricks submit
  (a quick REST call) is threadpooled for the same reason.
* **The reshaping lives in one place** — :mod:`api.result_builder` — so the synchronous route and
  the Databricks Job entrypoint notebook produce a byte-identical envelope.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from classifyos.io.sql_source import InputSourceError
from classifyos.io.storage import StorageAdapter
from classifyos.runner import ModelRunner

from ..databricks import (
    DatabricksAuthError,
    DatabricksConfigError,
    DatabricksError,
    execution_backend,
    get_user_email,
    submit_run,
    sync_llm_secrets,
)
from ..deps import get_storage, get_user_pat
from ..models import RunConfig, RunResponse, RunSubmission
from ..result_builder import build_run_result
from ..serialize import safe_jsonify

router = APIRouter(tags=["run"])


@router.post("/run", response_model=None)
async def run_endpoint(
    cfg: RunConfig,
    storage: StorageAdapter = Depends(get_storage),
    user_pat: str | None = Depends(get_user_pat),
) -> Any:
    """Run the full pipeline for ``cfg`` (local backend) or submit a Databricks Job (databricks).

    On a bad config (missing target, unknown enum, target in features, …) the engine's
    ``build_config`` raises ``ValueError`` → HTTP 422 — in **both** backends, so validation happens
    before any execution. Then:

    * local → run synchronously and return the locked ``result`` envelope (or a ``status="error"``
      envelope on a known input failure);
    * databricks → submit the Job and return a :class:`RunSubmission` (``{job_id, run_id, status}``).
    """
    # 1. Translate the web request into a validated engine config. build_config is the single
    #    authoritative validator; a problem there is a client error (422), not a 500. Runs in
    #    BOTH backends so a bad config never reaches Databricks.
    try:
        cfg.to_engine_config()
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    if execution_backend() == "databricks":
        return await _submit_to_databricks(cfg, user_pat)

    return await _run_locally(cfg, storage)


async def _submit_to_databricks(cfg: RunConfig, user_pat: str | None) -> Any:
    """Databricks backend: submit a Job and return a :class:`RunSubmission` (stateless — no store).

    The user's PAT is required (``X-Databricks-Token`` header) — a missing PAT is a clean 401 so the
    UI can prompt for it. The PAT is forwarded to the Job for UC data access and is **never stored**.

    **Statelessness (§6.6 Step 6).** The Databricks ``run_id`` the submit returns IS the ``job_id``
    the client polls with — there is no local job store. ``GET /run/{job_id}/status`` and
    ``/results`` (``routes/jobs.py``) poll Databricks directly with that id on every request, so a
    FastAPI restart loses nothing (nothing was persisted) and the only external dependency stays
    Databricks itself.
    """
    if not user_pat or not user_pat.strip():
        return JSONResponse(
            status_code=401,
            content={"detail": "a Databricks PAT is required (X-Databricks-Token header)"},
        )
    # Forward the request-shaped RunConfig to the Job (the entrypoint rebuilds the engine config).
    # by_alias so a delta input_source carries the ``schema`` key (its wire name), not the internal
    # ``db_schema`` field name — the notebook's RunConfig(**run_config) round-trips it either way,
    # but this keeps the submitted params byte-identical to the original request. ``cluster_id`` is
    # excluded: it is a submission knob (→ existing_cluster_id below), NOT part of the RunConfig the
    # notebook rebuilds via build_config (which would reject the unknown key), so the base_parameters
    # stay byte-identical to before this field existed and the deployed notebook needs no change.
    run_config = cfg.model_dump(by_alias=True, exclude={"cluster_id"})
    # Resolve the requesting user's email (via SCIM, using their PAT) so the Job namespaces its
    # output under {output_volume}/{user_email}/{job_id}/. Never blocks a run: get_user_email
    # returns "unknown_user" on any failure. Threadpooled — it is a blocking REST call.
    user_email = await run_in_threadpool(get_user_email, user_pat.strip())
    # LLM reason-code narratives (Azure OpenAI) are generated on the CLUSTER, which has none of the
    # AZURE_OPEN_AI_* creds. If this run requested narratives AND this host has the creds, push them
    # into a Databricks secret scope (service token) and forward ONLY the scope name — the key never
    # rides in the Job's run parameters. Report-only: sync_llm_secrets returns None on absent creds /
    # any failure → no scope forwarded → the run simply ships SHAP only (never blocks the submit).
    # Threadpooled (blocking REST). The local backend never reaches here.
    azure_secret_scope = ""
    if cfg.explainability.llm_narratives:
        azure_secret_scope = (await run_in_threadpool(sync_llm_secrets)) or ""
    try:
        submitted = await run_in_threadpool(
            submit_run, run_config, user_pat.strip(), cfg.cluster_id, user_email, azure_secret_scope
        )
    except DatabricksAuthError as exc:
        return JSONResponse(status_code=401, content={"detail": str(exc)})
    except DatabricksConfigError as exc:
        # The server is misconfigured for the databricks backend (missing host/token/notebook).
        return JSONResponse(status_code=500, content={"detail": str(exc)})
    except DatabricksError as exc:  # DatabricksUnavailable + any other client failure
        return JSONResponse(status_code=503, content={"detail": f"Databricks unavailable: {exc}"})

    # The Databricks run_id IS the job_id (both fields carry the same value for contract
    # compatibility — the frontend uses job_id in the poll paths, run_id as the workspace handle).
    run_id = submitted["run_id"]
    return RunSubmission(job_id=run_id, run_id=run_id, status="PENDING")


async def _run_locally(cfg: RunConfig, storage: StorageAdapter) -> Any:
    """Local backend: run the pipeline synchronously and return the locked envelope (unchanged)."""
    engine_config = cfg.to_engine_config()

    # Run the synchronous pipeline off the event loop (see module docstring).
    runner = ModelRunner(engine_config, storage)
    try:
        await run_in_threadpool(runner.run)
    except (FileNotFoundError, ValueError, InputSourceError) as exc:
        # Known input problems surfaced at run time: a missing file, an unparseable column, or a
        # postgres/delta input source that could not be read/materialized. All are 400-style errors.
        body = RunResponse(status="error", result=None, error=f"{type(exc).__name__}: {exc}")
        return JSONResponse(status_code=400, content=body.model_dump())

    # Reshape the finished runner into the locked schema, then make it JSON-safe
    # (numpy → Python, NaN/Inf → None) so encoding can never 500.
    result = build_run_result(runner, storage)
    response = RunResponse(status="ok", result=safe_jsonify(result))

    # If this run was logged to MLflow (opt-in mlflow.enabled succeeded), persist the rendered
    # envelope as a run artifact so the dashboard's Runs view can reload it byte-identically
    # (Interim 2a). Report-only — a failure only means the run is not reloadable; the /run
    # response is unaffected. [RISK] leakage — this writes the already-rendered result; it reads
    # nothing back into fit/transform.
    mlflow_run = getattr(runner, "mlflow_run_", None)
    if mlflow_run and mlflow_run.get("run_id"):
        from ..mlflow_read import snapshot_result

        # by_alias so the snapshot is byte-identical to the wire response FastAPI sends
        # (e.g. ClassReportRow's ``class`` alias) — a reload then matches the live run exactly.
        snapshot_result(mlflow_run["run_id"], response.model_dump(by_alias=True))

    return response
