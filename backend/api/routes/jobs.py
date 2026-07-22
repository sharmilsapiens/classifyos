"""Databricks async-run endpoints — poll a submitted Job and fetch its results (§6.6 Step 6).

Paired with ``POST /api/v1/run`` in the **databricks** execution backend (see ``routes/run.py``),
which submits the Job and returns ``{job_id, run_id}``:

* ``GET /api/v1/run/{job_id}/status``  — poll the Databricks run and report
  ``PENDING | RUNNING | COMPLETED | FAILED``.
* ``GET /api/v1/run/{job_id}/results`` — once ``COMPLETED``, return the SAME locked ``/run``
  envelope the Job wrote to the Unity Catalog **output** volume (``api/run_response.json``), so the
  dashboard drops it straight into the existing result pages — identical to a local run's response.

**Stateless (§6.6 Step 6).** ``job_id`` IS the Databricks ``run_id`` (returned by the submit in
``routes/run.py``), so every request polls Databricks directly — there is no local job store. A
FastAPI restart loses nothing because nothing was persisted, and Databricks stays the only external
dependency. Polling uses the **service token** (the Jobs API); no user PAT is needed here. No ML —
pure orchestration plumbing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from classifyos.io.storage import StorageAdapter

from ..databricks import (
    DatabricksAuthError,
    DatabricksConfigError,
    DatabricksError,
    DatabricksUnavailable,
    execution_backend,
    fetch_uc_file,
    get_run_status,
    get_task_run_id,
    get_user_email,
)
from ..deps import get_storage, get_user_pat
from ..models import JobStatusResponse

router = APIRouter(tags=["jobs"])

#: Where the Databricks Job writes the rendered ``/run`` envelope on the UC output volume — the
#: same relative key the MLflow snapshot uses (``api/run_response.json``), fetched by ``/results``.
RESULT_ENVELOPE_KEY = "api/run_response.json"


def _refresh_status(job_id: str) -> tuple[str, str | None]:
    """Poll Databricks for the run's state and return ``(status, message)``.

    ``job_id`` IS the Databricks ``run_id`` (the stateless design — see ``routes/run.py``), so this
    is a direct poll with no store to consult. Any Databricks failure (auth / misconfig /
    unreachable) propagates to the caller, which maps it to the right HTTP status. There is no
    cached fallback, and that is correct: a transient outage is an honest 503, never a fabricated
    last-known status.
    """
    state = get_run_status(job_id)
    return state["status"], state.get("message")


def _status_error_response(exc: DatabricksError) -> JSONResponse:
    """Map a Databricks poll failure to the matching HTTP response (shared by /status + /results).

    401 rejected credentials · 500 server not configured for the databricks backend · 503 an
    unreachable / erroring workspace (``DatabricksUnavailable`` and any other ``DatabricksError``).
    """
    if isinstance(exc, DatabricksAuthError):
        return JSONResponse(status_code=401, content={"detail": str(exc)})
    if isinstance(exc, DatabricksConfigError):
        return JSONResponse(status_code=500, content={"detail": str(exc)})
    return JSONResponse(status_code=503, content={"detail": f"Databricks unavailable: {exc}"})


@router.get("/run/{job_id}/status", response_model=JobStatusResponse)
def get_status_endpoint(job_id: str) -> Any:
    """Poll the Databricks run for ``job_id`` and report its coarse status + message.

    ``job_id`` is the Databricks run id, so the poll goes straight to the workspace: a rejected
    service token → 401, a server not configured for databricks → 500, an unreachable/erroring
    workspace → 503. There is no local store, so an unrecognised ``job_id`` is not a fabricated
    404 — Databricks itself decides it (a rejected id surfaces as 503, a finished-but-failed run
    as ``FAILED``).
    """
    try:
        status, message = _refresh_status(job_id)
    except DatabricksError as exc:
        return _status_error_response(exc)
    return JobStatusResponse(job_id=job_id, run_id=job_id, status=status, message=message)


@router.get("/run/{job_id}/results", response_model=None)
def get_results_endpoint(
    job_id: str,
    storage: StorageAdapter = Depends(get_storage),
    user_pat: str | None = Depends(get_user_pat),
) -> Any:
    """Return the locked ``/run`` envelope for a COMPLETED run (fetched from the UC output volume).

    Refreshes the status first (so a caller need not poll separately), then:

    * not yet terminal / still running → 409 with the current status;
    * ``FAILED`` → 409 with the failure message;
    * ``COMPLETED`` but no envelope on the volume yet → 404 (the Job finished but did not write it);
    * ``COMPLETED`` with the envelope present → the locked ``/run`` response, byte-identical to a
      local run.

    ``job_id`` is the Databricks run id (stateless — no local store); the status poll can raise the
    same 401 / 500 / 503 as ``/status``. In the databricks backend the caller's PAT
    (``X-Databricks-Token``) is used to resolve the same ``{user_email}`` prefix the Job wrote
    under, so the fetch path matches; a missing PAT falls back to ``"unknown_user"`` (the run's
    envelope will then only be found if it, too, landed under that fallback).
    """
    try:
        status, message = _refresh_status(job_id)
    except DatabricksError as exc:
        return _status_error_response(exc)

    if status != "COMPLETED":
        return JSONResponse(
            status_code=409,
            content={
                "detail": f"run {job_id!r} is not complete (status={status})",
                "status": status,
                "message": message,
            },
        )

    # Fetch the envelope the Job wrote to the OUTPUT volume.
    # Databricks mode: fetch from UC volume via Files API (the result is on the cluster, not local).
    # Local mode: read from the local OUTPUT_DIR via the storage adapter.
    if execution_backend() == "databricks":
        output_volume = os.environ.get("DBRICKS_OUTPUT_VOLUME", "").rstrip("/")
        if not output_volume:
            raise HTTPException(status_code=500, detail="DBRICKS_OUTPUT_VOLUME is not set")
        # The notebook namespaces output under {user_email}/{task_run_id}/ where task_run_id is what
        # currentRunId() returns inside the notebook — different from the outer run_id FastAPI uses
        # as job_id for a SUBMIT_RUN multi-task job. get_task_run_id bridges the gap with one extra
        # /runs/get call. get_user_email never raises — a missing/rejected PAT → "unknown_user".
        user_email = get_user_email((user_pat or "").strip())
        task_run_id = get_task_run_id(job_id)
        uc_path = f"{output_volume}/{user_email}/{task_run_id}/api/run_response.json"
        try:
            raw = fetch_uc_file(uc_path)
        except DatabricksUnavailable:
            raise HTTPException(
                status_code=404,
                detail=f"run {job_id!r} completed but its results envelope is not available yet",
            )
        except DatabricksAuthError as exc:
            return JSONResponse(status_code=401, content={"detail": str(exc)})
        envelope = json.loads(raw)
    else:
        try:
            resolved = Path(storage.path_for(RESULT_ENVELOPE_KEY, output=True))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid results key: {exc}") from exc
        if not resolved.is_file():
            raise HTTPException(
                status_code=404,
                detail=f"run {job_id!r} completed but its results envelope is not available yet",
            )
        with open(resolved, encoding="utf-8") as fh:
            envelope = json.load(fh)
    return JSONResponse(content=envelope)
