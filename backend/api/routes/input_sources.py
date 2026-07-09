"""Input-source read-path endpoints — list DB tables + select one to run on (Interim 2b UI).

The Interim-2b engine path already lets a ``/run`` draw its data from Postgres
(``input_source.type="postgres"`` → :func:`classifyos.io.sql_source.materialize_source`), but the
only way to use it was a hand-crafted request. These two ADDITIVE endpoints give the dashboard a
"Import from database" picker instead:

* ``GET  /api/v1/input-sources/tables`` — list the tables in the input DB (via the DSN named by
  ``CLASSIFYOS_PG_DSN``), so the UI can offer them. An unreachable / unconfigured DB is a clean
  **503** (mirroring the MLflow read-path discipline in :mod:`api.mlflow_read`), never a 500.
* ``POST /api/v1/input-sources/select`` — pick a table (or query): materialize it to a snapshot
  under DATA_DIR through the **exact 2b engine path**, profile that snapshot with the same
  ``inspect_file`` the ``/upload`` flow uses, and return the same ``InspectProfile`` shape plus the
  ``input_source`` block the frontend sets on the run — so the actual ``/run`` reads from Postgres
  (the 2b path), not just the profiling snapshot.

These ride the **upload/profile side** of the API, NOT the locked ``/run`` envelope, so they are
purely additive and carry **no ``schema_version``** (see ``docs/api_contract.md``). This module
adds no ML and re-implements no DB reading — it reuses :func:`materialize_source` /
:func:`list_tables` and the engine's authoritative ``input_source`` validator.

[RISK] leakage — materialize runs strictly BEFORE any pipeline and only writes a snapshot file;
the run then loads → splits → fits-on-train exactly as always. Nothing here fits or reads a model.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

# Reuse the engine's AUTHORITATIVE input_source validator (the same one build_config calls) so the
# picker enforces exactly the 2b rules — safe identifier, exactly-one of table/query, etc. — rather
# than re-deriving them here. (Precedent: api.mlflow_read imports the engine's _maybe_allow_file_store.)
from classifyos.config import _validate_input_source
from classifyos.io.inspect import inspect_file
from classifyos.io.sql_source import InputSourceError, list_tables, materialize_source
from classifyos.io.storage import StorageAdapter

from ..deps import get_storage
from ..models import InputSourceSelectRequest, InputTablesResponse
from ..serialize import safe_jsonify

router = APIRouter(tags=["input-sources"])

#: Materialized DB snapshots land under this input-root subfolder so they never clobber uploaded
#: files or the committed sample CSVs. Typed Parquet is the preferred snapshot format.
DB_SNAPSHOT_PREFIX = "db_snapshots"
#: Everything outside this set is collapsed to ``_`` when turning a table name into a snapshot key.
_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9_]+")


def _snapshot_key(table: str | None, query: str | None) -> str:
    """Build the snapshot storage key (under DATA_DIR) for a table or query selection.

    A ``table`` becomes ``db_snapshots/<sanitized>.parquet`` (a schema-qualified ``a.b`` → ``a_b``
    so the key has a single suffix); a ``query`` becomes ``db_snapshots/query_<hash>.parquet`` so
    distinct queries don't collide. The key is only the *destination* of the snapshot — the run's
    ``input_source.table``/``query`` keeps the original value and drives the real SQL at run time.
    """
    if isinstance(table, str) and table.strip():
        safe = _UNSAFE_KEY_CHARS.sub("_", table.strip()).strip("_") or "table"
        return f"{DB_SNAPSHOT_PREFIX}/{safe}.parquet"
    digest = hashlib.sha1((query or "").encode("utf-8")).hexdigest()[:10]
    return f"{DB_SNAPSHOT_PREFIX}/query_{digest}.parquet"


def _materialize_and_profile(
    src: dict[str, Any], input_file: str, target: str | None, storage: StorageAdapter
) -> dict[str, Any]:
    """Run the 2b materialize path, then profile the snapshot (the blocking part; runs off-loop).

    ``materialize_source`` raises :class:`InputSourceError` (DB unavailable / unset env / failed
    query / empty result); ``inspect_file`` raises ``ValueError`` for a bad target. Both propagate
    to the route, which maps them to 503 / 422 respectively.
    """
    materialize_source({"input_source": src, "input_file": input_file}, storage)
    return inspect_file(input_file, storage, target=target, profile=True)


@router.get("/input-sources/tables", response_model=InputTablesResponse)
async def list_input_tables(connection_env: str = "CLASSIFYOS_PG_DSN") -> Any:
    """List the tables in the input DB so the dashboard can offer them in a picker.

    ``connection_env`` names the server-side env var holding the SQLAlchemy DSN (default
    ``CLASSIFYOS_PG_DSN``). If that DB is unreachable or unconfigured (env unset), returns a clean
    **503** with a readable message — the same "store unavailable" discipline the MLflow read-path
    uses — so the UI can show that state instead of the page failing.
    """
    try:
        tables = await run_in_threadpool(list_tables, connection_env)
    except InputSourceError as exc:
        return JSONResponse(
            status_code=503,
            content={"detail": f"input database unavailable: {exc}"},
        )
    return InputTablesResponse(connection_env=connection_env, tables=tables)


@router.post("/input-sources/select", response_model=None)
async def select_input_source(
    req: InputSourceSelectRequest,
    storage: StorageAdapter = Depends(get_storage),
) -> Any:
    """Select a DB table/query: materialize + profile it, returning the ``/upload`` profile shape.

    Runs the chosen table/query through the exact Interim-2b engine path
    (:func:`materialize_source`, writing a ``.parquet`` snapshot under DATA_DIR via the
    StorageAdapter), then profiles that snapshot with ``inspect_file`` — so the response is the
    same ``InspectProfile`` the ``/upload`` flow returns (``columns``/``dtypes``/column groups/
    ``n_missing``/``sample``, the Data-Profile blocks, ``server_path``, and — when ``target`` is
    given — ``class_distribution``/``suggested_problem_type``). It additionally carries an
    ``input_source`` block for the frontend to set on the run config, so the real ``/run`` reads
    from Postgres (the 2b path), not merely this profiling snapshot.

    Errors: a bad request shape (unknown/unsafe table, both/neither of table/query, empty
    ``connection_env``, or a bad ``target``) → **422**; a DB that cannot be read (unset env var,
    unreachable, failed query, empty result) → **503**.
    """
    src = {
        "type": "postgres",
        "connection_env": req.connection_env,
        "table": req.table,
        "query": req.query,
    }
    input_file = _snapshot_key(req.table, req.query)

    # 1. Authoritative shape validation (reuse the engine's 2b validator) → 422 on a bad request.
    try:
        _validate_input_source(src, input_file)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # 2-3. Materialize (the 2b path) then profile the snapshot — off the event loop, since a table
    #      read + file write is blocking. A DB failure → 503; a bad target → 422.
    try:
        result = await run_in_threadpool(
            _materialize_and_profile, src, input_file, req.target, storage
        )
    except InputSourceError as exc:
        return JSONResponse(
            status_code=503,
            content={"detail": f"input database unavailable: {exc}"},
        )
    except ValueError as exc:  # inspect_file: target not in the materialized table
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # server_path is the key the frontend echoes back to /run as input_file (the snapshot the run
    # re-materializes); input_source is the block that makes the run read Postgres (the 2b path).
    result["server_path"] = input_file
    result["input_source"] = src
    # NaN/Inf → null so the body is strict-JSON-valid for the browser parser (as /upload does).
    return safe_jsonify(result)
