"""Unity Catalog browsing proxies — let the UI pick a Databricks data source (§6.6 Step 6, Part C).

Read-only proxies over Unity Catalog so the dashboard can populate a catalog → schema → table
picker and then profile the chosen table:

* ``GET /api/v1/databricks/catalogs``
* ``GET /api/v1/databricks/schemas?catalog=main``
* ``GET /api/v1/databricks/tables?catalog=main&schema=insurance``
* ``GET /api/v1/databricks/table-profile?catalog=&schema=&table=`` — profile the chosen table and
  return the **same ``InspectProfile`` shape a CSV ``/upload`` produces**. When a SQL warehouse is
  reachable it reads a bounded sample of the table's REAL data and runs the SAME profiling (so the
  Data-Profile blocks + per-feature stats populate); otherwise it degrades to the Unity Catalog
  schema alone. Either way the frontend reuses its column-picker / Data Profile / Configure views
  with no manual column entry and no branching.

Each is authenticated with the **user's PAT** (``X-Databricks-Token`` header), which is passed
straight through to Unity Catalog and **never stored** — so browsing shows exactly what that user
is entitled to. A missing PAT is a clean 401; an unreachable / erroring workspace is a 503. Pure
proxies — no ML, no persistence.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

# Reuse the engine's authoritative SQL-identifier regex so the identifiers we interpolate into the
# Unity Catalog REST path (``catalog.schema.table``) are validated exactly as the delta input-source
# validates them — never a divergent, hand-rolled check. (Precedent: routes/input_sources imports
# the engine's private ``_validate_input_source``.)
from classifyos.config import _SQL_IDENTIFIER_RE
# The SAME profiling core the CSV /upload + Postgres /input-sources/select flows use — so a Unity
# Catalog table sample produces a byte-identical InspectProfile with the Data-Profile blocks.
from classifyos.io.inspect import inspect_dataframe

from ..databricks import (
    UC_DATETIME_TYPES,
    UC_NUMERIC_TYPES,
    DatabricksAuthError,
    DatabricksConfigError,
    DatabricksError,
    execution_backend,
    fetch_table_sample,
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

logger = logging.getLogger(__name__)

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

    The **schema-only fallback** used when the SQL-warehouse sample can't be read
    (see :func:`_sample_profile`). Maps each ``ColumnInfo`` to the ``columns``/``dtypes``/column-group
    keys the CSV ``/upload`` profile carries, deriving the numeric/categorical/binary/datetime buckets
    from ``type_name`` (see :data:`api.databricks.UC_NUMERIC_TYPES` / ``UC_DATETIME_TYPES``).
    ``BOOLEAN`` is the only type known to be two-valued from the schema alone, so it is marked
    ``binary`` (and grouped categorical).

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

        if type_name in UC_DATETIME_TYPES:
            datetime_cols.append(name)
        elif type_name in UC_NUMERIC_TYPES:
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


def _sample_profile(
    catalog: str, schema: str, table: str, user_pat: str
) -> dict[str, Any] | None:
    """Profile a bounded sample of the table's REAL data, or ``None`` if it can't be read.

    Reads up to a capped number of rows via the SQL Statement Execution API
    (:func:`api.databricks.fetch_table_sample`) and runs the SAME ``inspect_dataframe`` profiling the
    CSV ``/upload`` and Postgres ``/input-sources/select`` flows use — so the result carries the full
    Data-Profile blocks (``column_profiles`` + ``correlation``) and real per-column stats, exactly
    like a file upload.

    Best-effort: ANY failure — no SQL warehouse configured, an unreachable workspace, a
    non-SUCCEEDED / empty statement, or a profiling error — returns ``None`` so the caller falls back
    to the schema-only profile. The column picker is therefore never blocked on the SQL read.
    Read-only and display-only: it feeds nothing back into training (the run still reads the FULL
    table on the cluster via ``materialize_delta_source``) — no leakage surface.
    """
    full_name = f"{catalog}.{schema}.{table}"
    try:
        df = fetch_table_sample(catalog, schema, table, user_pat)
        return inspect_dataframe(df, profile=True, source=full_name)
    except Exception as exc:  # noqa: BLE001 — profiling is best-effort; never block the picker
        logger.info(
            "table-profile: sampling %s unavailable (%s); using the schema-only profile",
            full_name,
            exc,
        )
        return None


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
def clusters_endpoint() -> Any:
    """List the Databricks clusters a run can be submitted to (usable state, sorted).

    Powers the run-config cluster picker: the returned ``cluster_id`` is echoed back on ``/run`` as
    the optional ``cluster_id`` field to override the server's ``DATABRICKS_JOB_CLUSTER_ID`` default.
    Unlike the ``/catalogs``/``/schemas``/``/tables`` data browsers (which run as the user's PAT),
    this uses the **service token** — the service identity is what submits the Job and picks the
    cluster, so the picker reflects where jobs actually run. No user PAT is required. Errors: an
    unconfigured server (missing host/service token) → 500, unreachable/rejected workspace →
    503/401 (see :func:`api.databricks.list_clusters`).
    """
    try:
        clusters = list_clusters()
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
    """Profile a Unity Catalog table → the same ``InspectProfile`` shape as ``/upload``.

    After the UC picker selects ``catalog.schema.table``, this returns the same ``InspectProfile``
    the CSV ``/upload`` and Postgres ``/input-sources/select`` flows do, so the frontend reuses its
    existing column-picker (target dropdown + feature selector) AND its Data Profile / Configure
    per-feature views verbatim — with **no manual column entry and no frontend branching**.

    Two data paths, one shape:

    * **Sampled (preferred).** When a SQL warehouse is configured
      (``DATABRICKS_SQL_WAREHOUSE_ID`` / ``DATABRICKS_HTTP_PATH``) and reachable, it reads a BOUNDED
      SAMPLE of the table's real rows (:func:`_sample_profile` → the SQL Statement Execution API,
      authenticated with the caller's PAT) and runs the SAME profiling a file upload does — so the
      response carries the full ``InspectProfile`` INCLUDING the Data-Profile blocks
      (``column_profiles`` + ``correlation``) and real per-column stats.
    * **Schema-only (fallback).** If the sample can't be read (no warehouse, unreachable, a
      huge/unreadable table), it degrades to the Unity Catalog schema alone (``get-a-table``):
      ``columns``/``dtypes`` + type-derived groups, ``n_rows`` ``0``, ``sample`` ``[]``, no
      Data-Profile blocks (see :func:`_profile_from_columns`). The picker is never blocked and no
      stats are fabricated.

    The sample is display-only — reads nothing back into training; the run still reads the FULL
    table on the cluster (``materialize_delta_source``).

    The response also carries ``server_path`` (a ``.parquet`` snapshot key) and a ``delta``
    ``input_source`` block, exactly like ``/input-sources/select`` does for Postgres, so the
    frontend's existing ``applyUpload`` plumbing sets the run up to read the Delta table on the
    cluster.

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

    # Prefer a profile over the table's ACTUAL data (a bounded sample read via the SQL warehouse) so
    # the response carries the FULL InspectProfile — the Data-Profile blocks + real per-column stats,
    # exactly like a CSV /upload or a Postgres /input-sources/select. When the sample can't be read
    # it degrades to the schema-only profile — the picker is never blocked and no stats are fabricated.
    profile = _sample_profile(catalog, schema, table, user_pat or "")
    if profile is None:
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
