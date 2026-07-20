"""Unity Catalog browsing proxies — let the UI pick a Databricks data source (§6.6 Step 6, Part C).

Read-only proxies over Unity Catalog so the dashboard can populate a catalog → schema → table
picker and then profile the chosen table:

* ``GET /api/v1/databricks/catalogs``
* ``GET /api/v1/databricks/schemas?catalog=main``
* ``GET /api/v1/databricks/tables?catalog=main&schema=insurance``
* ``GET /api/v1/databricks/table-profile?catalog=&schema=&table=`` — fetch the chosen table's
  Unity Catalog schema and return it in the **same ``InspectProfile`` shape a CSV ``/upload``
  produces**, so the frontend reuses its existing column-picker (target dropdown + feature
  selector) with no manual column entry and no branching.

Each is authenticated with the **user's PAT** (``X-Databricks-Token`` header), which is passed
straight through to Unity Catalog and **never stored** — so browsing shows exactly what that user
is entitled to. A missing PAT is a clean 401; an unreachable / erroring workspace is a 503. Pure
proxies — no ML, no persistence.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

# Reuse the engine's authoritative SQL-identifier regex so the identifiers we interpolate into the
# Unity Catalog REST path (``catalog.schema.table``) are validated exactly as the delta input-source
# validates them — never a divergent, hand-rolled check. (Precedent: routes/input_sources imports
# the engine's private ``_validate_input_source``.)
from classifyos.config import _SQL_IDENTIFIER_RE

from ..databricks import (
    DatabricksAuthError,
    DatabricksConfigError,
    DatabricksError,
    execution_backend,
    get_table_columns,
    list_catalogs,
    list_clusters,
    list_schemas,
    list_tables,
)
from ..deps import get_user_pat
from ..models import CatalogsResponse, ClustersResponse, SchemasResponse, TablesResponse
from ..serialize import safe_jsonify

router = APIRouter(tags=["databricks"])

#: Unity Catalog ``ColumnTypeName`` → the ``inspect_file`` column-group buckets. Verified against the
#: Databricks SDK ``ColumnTypeName`` enum (databricks-sdk-py ``catalog.py`` / Microsoft Learn). Any
#: type outside the numeric/datetime/boolean sets falls through to "categorical" (STRING, CHAR,
#: BINARY, ARRAY/STRUCT/MAP, VARIANT, …) — the same conservative default the CSV inspector uses.
_UC_NUMERIC_TYPES = frozenset({"BYTE", "SHORT", "INT", "LONG", "FLOAT", "DOUBLE", "DECIMAL"})
_UC_DATETIME_TYPES = frozenset({"DATE", "TIMESTAMP", "TIMESTAMP_NTZ"})

#: Delta snapshots the run materializes land under this input-root subfolder (mirrors
#: input_sources.DB_SNAPSHOT_PREFIX) so they never clobber uploads or the committed sample CSVs.
DB_SNAPSHOT_PREFIX = "db_snapshots"


def _auth_or_unavailable(exc: DatabricksError) -> JSONResponse:
    """Map a Databricks client error to the right HTTP response (401 / 500 / 503)."""
    if isinstance(exc, DatabricksAuthError):
        return JSONResponse(status_code=401, content={"detail": str(exc)})
    if isinstance(exc, DatabricksConfigError):
        return JSONResponse(status_code=500, content={"detail": str(exc)})
    return JSONResponse(
        status_code=503, content={"detail": f"Databricks unavailable: {exc}"}
    )


def _require_databricks_backend() -> JSONResponse | None:
    """Return a 503 ``JSONResponse`` unless the server runs the **databricks** execution backend.

    The UC picker (and this schema fetch) only make sense in the databricks backend — it is where
    the frontend even offers them — so a call in the default local mode is a clear 503, never a
    silent no-op that would leave the user typing column names by hand. ``None`` means "proceed".
    """
    if execution_backend() != "databricks":
        return JSONResponse(
            status_code=503,
            content={
                "detail": "the Databricks table picker requires the databricks execution backend"
            },
        )
    return None


def _profile_from_columns(columns: list[dict[str, Any]]) -> dict[str, Any]:
    """Reshape a Unity Catalog ``columns`` array into the ``inspect_file`` profile shape.

    Maps each ``ColumnInfo`` to the ``columns``/``dtypes``/column-group keys the CSV ``/upload``
    profile carries, deriving the numeric/categorical/binary/datetime buckets from ``type_name``
    (see :data:`_UC_NUMERIC_TYPES` / :data:`_UC_DATETIME_TYPES`). ``BOOLEAN`` is the only type known
    to be two-valued from the schema alone, so it is marked ``binary`` (and grouped categorical).

    Row-level statistics (``n_rows``, ``n_missing``, ``sample``, ``class_distribution``) are NOT
    available from schema-only metadata — no data is read here — so ``n_rows`` is ``0``,
    ``n_missing`` is ``0`` per column, and ``sample`` is empty. That is enough for the column
    picker (which only needs the columns, their types, and the groups); the real per-column stats
    are computed on the cluster when the run reads the Delta table.
    """
    names: list[str] = []
    dtypes: dict[str, str] = {}
    numeric_cols: list[str] = []
    categorical_cols: list[str] = []
    binary_cols: list[str] = []
    datetime_cols: list[str] = []
    n_missing: dict[str, int] = {}

    for col in columns:
        raw_name = col.get("name")
        if not raw_name:
            continue  # a ColumnInfo without a name is unusable; skip it
        name = str(raw_name)
        type_name = str(col.get("type_name") or "").upper()
        # Human-readable dtype for the UI's "Type" column: prefer the SQL text ("decimal(10,2)",
        # "string"), fall back to the enum lowercased, then a clear "unknown".
        dtypes[name] = str(col.get("type_text") or type_name.lower() or "unknown")
        names.append(name)
        n_missing[name] = 0  # unknown from schema-only metadata (see docstring)

        if type_name in _UC_DATETIME_TYPES:
            datetime_cols.append(name)
        elif type_name in _UC_NUMERIC_TYPES:
            numeric_cols.append(name)
        elif type_name == "BOOLEAN":
            binary_cols.append(name)
            categorical_cols.append(name)
        else:
            categorical_cols.append(name)

    return {
        "columns": names,
        "dtypes": dtypes,
        "numeric_cols": numeric_cols,
        "categorical_cols": categorical_cols,
        "binary_cols": binary_cols,
        "datetime_cols": datetime_cols,
        "n_rows": 0,
        "n_missing": n_missing,
        "sample": [],
    }


def _snapshot_key(catalog: str, schema: str, table: str) -> str:
    """Snapshot storage key (under DATA_DIR) the Delta run materializes the table to.

    A ``.parquet`` key qualified by ``catalog_schema_table`` so two same-named tables in different
    schemas never collide. This is only the snapshot *destination*; the actual Delta read uses the
    ``input_source.catalog``/``schema``/``table`` identifiers at run time.
    """
    return f"{DB_SNAPSHOT_PREFIX}/{catalog}_{schema}_{table}.parquet"


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


@router.get("/databricks/clusters", response_model=ClustersResponse)
def clusters_endpoint(user_pat: str | None = Depends(get_user_pat)) -> Any:
    """List the Databricks clusters the caller's PAT can submit a run to (usable state, sorted).

    Powers the run-config cluster picker: the returned ``cluster_id`` is echoed back on ``/run`` as
    the optional ``cluster_id`` field to override the server's ``DATABRICKS_JOB_CLUSTER_ID`` default.
    Same PAT/auth + error mapping as the ``/catalogs``/``/schemas``/``/tables`` proxies (401 no PAT,
    503 unreachable) — only usable clusters are returned (see :func:`api.databricks.list_clusters`).
    """
    try:
        clusters = list_clusters(user_pat or "")
    except DatabricksError as exc:
        return _auth_or_unavailable(exc)
    return ClustersResponse(clusters=clusters)


@router.get("/databricks/table-profile", response_model=None)
def table_profile_endpoint(
    catalog: str = Query(..., min_length=1),
    schema: str = Query(..., min_length=1),
    table: str = Query(..., min_length=1),
    user_pat: str | None = Depends(get_user_pat),
) -> Any:
    """Profile a Unity Catalog table's schema → the same ``InspectProfile`` shape as ``/upload``.

    After the UC picker selects ``catalog.schema.table``, this fetches that table's column
    metadata from Unity Catalog (``get-a-table``, authenticated with the caller's PAT) and reshapes
    it into the CSV-``/upload`` profile shape — ``columns``, ``dtypes``, the
    numeric/categorical/binary/datetime column groups — so the frontend reuses its existing
    column-picker (target dropdown + feature selector) verbatim, with **no manual column entry**.

    The response also carries ``server_path`` (a ``.parquet`` snapshot key) and a ``delta``
    ``input_source`` block, exactly like ``/input-sources/select`` does for Postgres, so the
    frontend's existing ``applyUpload`` plumbing sets the run up to read the Delta table on the
    cluster. Row-level stats (``n_rows``/``n_missing``/``sample``/``class_distribution``) are not
    available from schema-only metadata and are omitted/zeroed (see :func:`_profile_from_columns`).

    Gating & errors:

    * not the **databricks** execution backend → **503** (the picker is only offered there);
    * a ``catalog``/``schema``/``table`` that is not a simple SQL identifier → **422** (they are
      interpolated into the UC REST path, so this guards it — never a silent, reshaped URL);
    * missing/rejected PAT → **401**; unreachable workspace, or a table with no columns → **503**
      (never a silent fall-through to manual entry).
    """
    guard = _require_databricks_backend()
    if guard is not None:
        return guard

    for label, value in (("catalog", catalog), ("schema", schema), ("table", table)):
        if not _SQL_IDENTIFIER_RE.match(value.strip()):
            return JSONResponse(
                status_code=422,
                content={"detail": f"{label} must be a simple SQL identifier, got {value!r}"},
            )

    try:
        columns = get_table_columns(catalog, schema, table, user_pat or "")
    except DatabricksError as exc:
        return _auth_or_unavailable(exc)

    profile = _profile_from_columns(columns)
    # server_path is echoed back to /run as input_file (the snapshot destination); input_source is
    # the delta block that makes the run read the Unity Catalog table on the cluster (§6.6 Step 4).
    profile["server_path"] = _snapshot_key(catalog, schema, table)
    profile["input_source"] = {
        "type": "delta",
        "connection_env": "CLASSIFYOS_PG_DSN",  # unused for delta; kept for InputSourceConfig shape
        "catalog": catalog,
        "schema": schema,
        "table": table,
        "query": None,
    }
    # safe_jsonify for parity with /upload + /input-sources/select (harmless here — no NaN/Inf).
    return safe_jsonify(profile)
