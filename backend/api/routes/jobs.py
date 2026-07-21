"""Databricks async-run endpoints — poll a submitted Job and fetch its results (§6.6 Step 6).

Paired with ``POST /api/v1/run`` in the **databricks** execution backend (see ``routes/run.py``),
which submits the Job and returns ``{job_id, run_id}``:

* ``GET /api/v1/run/{job_id}/status``  — poll the Databricks run and report
  ``PENDING | RUNNING | COMPLETED | FAILED``.
* ``GET /api/v1/run/{job_id}/results`` — once ``COMPLETED``, return the SAME locked ``/run``
  envelope the Job wrote to the Unity Catalog **output** volume (``api/run_response.json``), so the
  dashboard drops it straight into the existing result pages — identical to a local run's response.

State lives in the persistent :mod:`api.jobs_store` (the MLflow Postgres), so a FastAPI restart
mid-poll does not lose an in-flight ``job_id``. Polling uses the **service token** (the Jobs API);
no user PAT is needed here. No ML — pure orchestration plumbing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from classifyos.io.storage import StorageAdapter

import os

from ..databricks import DatabricksAuthError, DatabricksError, DatabricksUnavailable, execution_backend, fetch_uc_file, get_run_status
from ..deps import get_storage
from ..jobs_store import get_job, update_status
from ..models import JobStatusResponse

router = APIRouter(tags=["jobs"])

#: Where the Databricks Job writes the rendered ``/run`` envelope on the UC output volume — the
#: same relative key the MLflow snapshot uses (``api/run_response.json``), fetched by ``/results``.
RESULT_ENVELOPE_KEY = "api/run_response.json"


def _refresh_status(job_id: str, databricks_run_id: str | None) -> tuple[str, str | None]:
    """Poll Databricks for the run's state, persist it, and return ``(status, message)``.

    On a transient Databricks outage the last-known stored status is returned (so a polling client
    does not see the run "reset"); a missing ``databricks_run_id`` also falls back to the store.
    """
    row = get_job(job_id)
    stored_status = (row or {}).get("status", "PENDING")
    stored_message = (row or {}).get("message")
    if not databricks_run_id:
        return stored_status, stored_message
    try:
        state = get_run_status(databricks_run_id)
    except DatabricksAuthError:
        raise
    except DatabricksError:
        # Transient/unreachable: keep the last-known status rather than failing the poll.
        return stored_status, stored_message
    status, message = state["status"], state.get("message")
    update_status(
        job_id,
        status,
        message=message,
        error=message if status == "FAILED" else None,
    )
    return status, message


@router.get("/run/{job_id}/status", response_model=JobStatusResponse)
def get_status_endpoint(job_id: str) -> Any:
    """Poll the Databricks run for ``job_id`` and report its coarse status + message.

    Unknown ``job_id`` → 404; a rejected service token → 401. A transient Databricks blip returns
    the last-known status (never a 500) so the client's polling loop stays alive.
    """
    row = get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id!r}")
    try:
        status, message = _refresh_status(job_id, row.get("databricks_run_id"))
    except DatabricksAuthError as exc:
        return JSONResponse(status_code=401, content={"detail": str(exc)})
    return JobStatusResponse(
        job_id=job_id, run_id=row.get("databricks_run_id"), status=status, message=message
    )


@router.get("/run/{job_id}/results", response_model=None)
def get_results_endpoint(
    job_id: str,
    storage: StorageAdapter = Depends(get_storage),
) -> Any:
    """Return the locked ``/run`` envelope for a COMPLETED run (fetched from the UC output volume).

    Refreshes the status first (so a caller need not poll separately), then:

    * not yet terminal / still running → 409 with the current status;
    * ``FAILED`` → 409 with the failure message;
    * ``COMPLETED`` but no envelope on the volume yet → 404 (the Job finished but did not write it);
    * ``COMPLETED`` with the envelope present → the locked ``/run`` response, byte-identical to a
      local run.
    """
    row = get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id!r}")

    try:
        status, message = _refresh_status(job_id, row.get("databricks_run_id"))
    except DatabricksAuthError as exc:
        return JSONResponse(status_code=401, content={"detail": str(exc)})

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
        uc_path = f"{output_volume}/api/{job_id}/run_response.json"
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
