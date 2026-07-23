"""MLflow read-path endpoints — list past runs and reload one (Interim 2a; per-user on Databricks).

* ``GET /api/v1/runs`` — list past runs recorded in MLflow (most-recent first), as lightweight
  summary rows the dashboard's "Runs" view renders.
* ``GET /api/v1/runs/{run_id}`` — reload ONE past run: returns the exact ``/run`` envelope the
  API persisted for it, so the dashboard drops it straight into the existing result pages.

**Per-user scope (Databricks backend).** In the ``databricks`` execution backend these are scoped to
the CALLER: the list is filtered — and a reload is authorized — by the ``classifyos.user_email`` tag
the Job logs, with the caller's identity resolved from the ``X-Databricks-Token`` PAT via SCIM. The
filter is by the stable EMAIL, not the PAT, so token rotation never loses history; a missing/expired
PAT is a clean 401 so the UI can prompt. In the default LOCAL backend nothing changes — every run is
listed and no PAT is required.

These are ADDITIVE to the locked contract (new endpoints; the ``/run`` envelope is unchanged — see
``docs/api_contract.md``, schema 1.10/1.11). All MLflow reads go through :mod:`api.mlflow_read`,
which imports ``mlflow`` lazily and turns an unreachable store into a clean 503 and an unknown run id
into a 404 — never a 500. No ML here — the API WRAPS the engine, reading back what a run logged.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from ..databricks import execution_backend, get_user_email
from ..deps import get_user_pat
from ..mlflow_read import MlflowUnavailable, RunNotFound, list_runs, load_run
from ..models import RunsListResponse

router = APIRouter(tags=["runs"])


def _resolve_user_email(user_pat: str | None) -> str | None:
    """Return the per-user scope for the Runs view (``None`` = list everything).

    * **Local backend** → ``None``: list/reload every run, exactly as before (no PAT needed).
    * **Databricks backend** → the caller's email, resolved from their PAT via SCIM, so the read
      path can filter to their own runs. A missing PAT, or one that no longer resolves (e.g.
      expired → ``get_user_email`` returns ``"unknown_user"``), is a **401** so the UI prompts for a
      fresh token rather than showing a misleading empty list. Scoping is by the stable EMAIL, not
      the PAT, so rotating the token never loses a user's history.
    """
    if execution_backend() != "databricks":
        return None
    pat = (user_pat or "").strip()
    if not pat:
        raise HTTPException(
            status_code=401,
            detail="a Databricks PAT is required (X-Databricks-Token header)",
        )
    email = get_user_email(pat)
    if email == "unknown_user":
        raise HTTPException(
            status_code=401,
            detail=(
                "could not resolve your Databricks identity from the token "
                "(it may be expired) — reconnect with a valid PAT"
            ),
        )
    return email


@router.get("/runs", response_model=RunsListResponse)
def list_runs_endpoint(user_pat: str | None = Depends(get_user_pat)) -> Any:
    """List past MLflow runs (most-recent first) for the dashboard's Runs view.

    Local backend lists every run; the Databricks backend lists ONLY the caller's runs (filtered by
    the ``classifyos.user_email`` tag). If the tracking store cannot be reached, returns HTTP 503
    rather than failing the page; a missing/expired PAT (Databricks) is a 401.
    """
    try:
        user_email = _resolve_user_email(user_pat)
        data = list_runs(user_email=user_email)
    except MlflowUnavailable as exc:
        return JSONResponse(
            status_code=503,
            content={"detail": f"MLflow tracking store unavailable: {exc}"},
        )
    return RunsListResponse(tracking_uri=data["tracking_uri"], runs=data["runs"])


@router.get("/runs/{run_id}", response_model=None)
def get_run_endpoint(run_id: str, user_pat: str | None = Depends(get_user_pat)) -> Any:
    """Reload one past run — the persisted ``/run`` envelope, byte-identical.

    Returns the same locked ``/run`` response shape (``{status, schema_version, result, error}``)
    the run was originally rendered with, so the dashboard can populate every result page from it.
    In the Databricks backend a run owned by a DIFFERENT user is a 404 (no cross-user reload). A run
    with no persisted snapshot is a 404; an unknown run id is a 404; an unreachable store is a 503;
    a missing/expired PAT (Databricks) is a 401.
    """
    try:
        user_email = _resolve_user_email(user_pat)
        envelope = load_run(run_id, user_email=user_email)
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
