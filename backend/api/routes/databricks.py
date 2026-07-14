"""Unity Catalog browsing proxies — let the UI pick a Databricks data source (§6.6 Step 6, Part C).

Three thin, read-only proxies over Unity Catalog so the dashboard can populate a
catalog → schema → table picker:

* ``GET /api/v1/databricks/catalogs``
* ``GET /api/v1/databricks/schemas?catalog=main``
* ``GET /api/v1/databricks/tables?catalog=main&schema=insurance``

Each is authenticated with the **user's PAT** (``X-Databricks-Token`` header), which is passed
straight through to Unity Catalog and **never stored** — so browsing shows exactly what that user
is entitled to. A missing PAT is a clean 401; an unreachable / erroring workspace is a 503. Pure
proxies — no ML, no persistence.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ..databricks import (
    DatabricksAuthError,
    DatabricksConfigError,
    DatabricksError,
    list_catalogs,
    list_schemas,
    list_tables,
)
from ..deps import get_user_pat
from ..models import CatalogsResponse, SchemasResponse, TablesResponse

router = APIRouter(tags=["databricks"])


def _auth_or_unavailable(exc: DatabricksError) -> JSONResponse:
    """Map a Databricks client error to the right HTTP response (401 / 500 / 503)."""
    if isinstance(exc, DatabricksAuthError):
        return JSONResponse(status_code=401, content={"detail": str(exc)})
    if isinstance(exc, DatabricksConfigError):
        return JSONResponse(status_code=500, content={"detail": str(exc)})
    return JSONResponse(
        status_code=503, content={"detail": f"Databricks unavailable: {exc}"}
    )


@router.get("/databricks/catalogs", response_model=CatalogsResponse)
def catalogs_endpoint(user_pat: str | None = Depends(get_user_pat)) -> Any:
    """List Unity Catalog catalogs the caller's PAT can see."""
    try:
        names = list_catalogs(user_pat or "")
    except DatabricksError as exc:
        return _auth_or_unavailable(exc)
    return CatalogsResponse(catalogs=names)


@router.get("/databricks/schemas", response_model=SchemasResponse)
def schemas_endpoint(
    catalog: str = Query(..., min_length=1),
    user_pat: str | None = Depends(get_user_pat),
) -> Any:
    """List schemas in ``catalog`` the caller's PAT can see."""
    try:
        names = list_schemas(catalog, user_pat or "")
    except DatabricksError as exc:
        return _auth_or_unavailable(exc)
    return SchemasResponse(catalog=catalog, schemas=names)


@router.get("/databricks/tables", response_model=TablesResponse)
def tables_endpoint(
    catalog: str = Query(..., min_length=1),
    schema: str = Query(..., min_length=1),
    user_pat: str | None = Depends(get_user_pat),
) -> Any:
    """List tables in ``catalog.schema`` the caller's PAT can see."""
    try:
        names = list_tables(catalog, schema, user_pat or "")
    except DatabricksError as exc:
        return _auth_or_unavailable(exc)
    return TablesResponse(catalog=catalog, schema=schema, tables=names)
