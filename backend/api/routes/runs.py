"""MLflow read-path endpoints — list past runs and reload one (Interim 2a).

* ``GET /api/v1/runs`` — list past runs recorded in MLflow (most-recent first), as lightweight
  summary rows the dashboard's "Runs" view renders.
* ``GET /api/v1/runs/{run_id}`` — reload ONE past run: returns the exact ``/run`` envelope the
  API persisted for it, so the dashboard drops it straight into the existing result pages.

These are ADDITIVE to the locked contract (new endpoints; the ``/run`` envelope is unchanged —
see ``docs/api_contract.md``, schema 1.10). All MLflow reads go through :mod:`api.mlflow_read`,
which imports ``mlflow`` lazily and turns an unreachable store into a clean 503 and an unknown
run id into a 404 — never a 500. No ML here — the API WRAPS the engine, and this only reads back
what a completed run already logged.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ..mlflow_read import MlflowUnavailable, RunNotFound, list_runs, load_run
from ..models import RunsListResponse

router = APIRouter(tags=["runs"])


@router.get("/runs", response_model=RunsListResponse)
def list_runs_endpoint() -> Any:
    """List past MLflow runs (most-recent first) for the dashboard's Runs view.

    Returns the :class:`~api.models.RunsListResponse` envelope. If the tracking store cannot be
    reached (e.g. Postgres is down, or MLflow logging was never used so no store exists), returns
    HTTP 503 with a readable message rather than failing the page.
    """
    try:
        data = list_runs()
    except MlflowUnavailable as exc:
        return JSONResponse(
            status_code=503,
            content={"detail": f"MLflow tracking store unavailable: {exc}"},
        )
    return RunsListResponse(tracking_uri=data["tracking_uri"], runs=data["runs"])


@router.get("/runs/{run_id}", response_model=None)
def get_run_endpoint(run_id: str) -> Any:
    """Reload one past run — the persisted ``/run`` envelope, byte-identical.

    Returns the same locked ``/run`` response shape (``{status, schema_version, result, error}``)
    the run was originally rendered with, so the dashboard can populate every result page from it.
    A run with no persisted snapshot (e.g. one logged by the engine CLI, not via ``/run``) is a
    404 with a clear message; an unknown run id is a 404; an unreachable store is a 503.
    """
    try:
        envelope = load_run(run_id)
    except RunNotFound:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id!r}") from None
    except MlflowUnavailable as exc:
        return JSONResponse(
            status_code=503,
            content={"detail": f"MLflow tracking store unavailable: {exc}"},
        )
    if envelope is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"run {run_id!r} has no reloadable snapshot "
                "(it was not produced via POST /api/v1/run)"
            ),
        )
    # Return the persisted envelope verbatim so a reload matches the original run exactly.
    return JSONResponse(content=envelope)
