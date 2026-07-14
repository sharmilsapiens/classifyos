"""Interim 2b — Postgres input source, materialize-to-file (Option B).

Design of record: ``docs/databricks_integration.md`` §6.5 (Interim 2b). A run may optionally
draw its data from a SQL database instead of an uploaded file. Rather than teaching the pipeline
to read a database (which would bend the file abstraction and the leakage discipline), we
**materialize to a file**: run the table/query ONCE up front, write the result to ``input_file``
under ``DATA_DIR`` through the :class:`~classifyos.io.storage.StorageAdapter`, and then let the
normal file pipeline run on that snapshot **unchanged**. So:

* :func:`~classifyos.io.loader.data_loader` and everything downstream are literally untouched —
  the engine still reads a file, so the ``StorageAdapter`` rule and the
  ``load → split → fit-on-train`` leakage discipline stay exactly as they are.
* the snapshot is a durable, auditable record of *precisely* the rows the run saw (good for the
  reproducibility / governance posture — the query result is frozen to a file).

Row order note (verified live): a SQL table is a *set* — a bare ``table`` / ``SELECT *`` returns
rows in an **unspecified** order, which can differ from a source CSV's order. The materialized
snapshot holds the identical row *set* either way, but because the seeded train/test split depends
on row order, an unordered query may yield slightly different metrics than the original CSV. Add an
``ORDER BY`` to the ``query`` (e.g. by a stable id) for a byte-for-byte reproducible snapshot — with
it, results match the CSV exactly. Once written, the snapshot file itself is fully deterministic.

Discipline (mirrors the ``mlflow_logging`` / ``shap`` / ``optuna`` integrations):

* **Opt-in** — nothing here runs unless ``config["input_source"]["type"] == "postgres"``; the
  default ``file`` source makes :func:`materialize_source` a no-op, so a file run is byte-identical.
* **Lazy import** — ``sqlalchemy`` (and ``pandas`` for the DB read) are imported *inside* the
  postgres branch, so a file run — or an install without SQLAlchemy — never touches the dependency.
* **No hardcoded credentials** — the connection is referenced by ``connection_env``, the NAME of a
  server-side environment variable (in ``backend/.env``, gitignored/machine-local) holding the
  SQLAlchemy DSN. The DSN is never carried in the request/config.

Implementation note: the connection is a generic SQLAlchemy engine, so any SQLAlchemy-supported
database works; the supported/pinned driver is ``psycopg2`` (PostgreSQL), matching the ``postgres``
source label in the config.

[RISK] leakage — this runs strictly BEFORE the pipeline and only *writes* a snapshot file; it feeds
nothing back into fit/transform. [RISK] SQL injection — a ``table`` name is validated to a safe SQL
identifier at config-build time (``config._validate_input_source``) because an identifier cannot be
a bound parameter; a raw ``query`` is the analyst's own opt-in SQL (local, trusted tool).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .storage import StorageAdapter

logger = logging.getLogger(__name__)

#: Snapshot formats a materialized source may be written to (kept in sync with
#: ``config.INPUT_SNAPSHOT_FORMATS``; the ``input_file`` suffix selects the format).
_SNAPSHOT_SUFFIXES = ("parquet", "csv")


class InputSourceError(RuntimeError):
    """A database input source (Postgres or Delta) could not be read or materialized to a file.

    Raised for a missing/empty connection env var, an unreachable database, a failed query, an
    empty result, or an unsupported snapshot suffix (Postgres); or for a missing PySpark / no
    active SparkSession / failed table read (Delta — e.g. attempting a ``type="delta"`` run off a
    Databricks cluster). The API ``/run`` route maps it to the ``status="error"`` envelope (a
    400-style run error, like a missing input file) rather than an opaque 500.
    """


def _resolve_connection_url(connection_env: str | None) -> str:
    """Return the SQLAlchemy DSN held by the env var named ``connection_env``.

    Enforces the "never a hardcoded credential" rule: the connection string is read from the
    environment (``backend/.env``, machine-local), never from the run config/request.
    """
    if not connection_env or not str(connection_env).strip():
        raise InputSourceError(
            "input_source.connection_env must name an environment variable holding the database DSN"
        )
    url = os.environ.get(connection_env, "").strip()
    if not url:
        raise InputSourceError(
            f"input_source.connection_env {connection_env!r} is not set (or is empty) in the "
            "environment; set it in backend/.env to a SQLAlchemy Postgres DSN "
            "(e.g. postgresql://user:pass@host:port/db)"
        )
    return url


def _write_snapshot(df: Any, key: str, storage: StorageAdapter) -> None:
    """Write ``df`` to ``key`` under the INPUT root via :meth:`StorageAdapter.save_input`.

    The ``key`` suffix selects the format (``.parquet`` → typed Parquet, preferred; ``.csv`` →
    UTF-8 CSV). The frame is serialized to an in-memory buffer and handed to ``save_input`` so ALL
    I/O stays behind the storage abstraction and lands in ``DATA_DIR`` (where ``data_loader`` reads).
    """
    import io  # noqa: PLC0415 — local, cheap

    suffix = key.lower().rsplit(".", 1)[-1] if "." in key else ""
    if suffix in ("parquet", "pq"):
        buffer = io.BytesIO()
        df.to_parquet(buffer, index=False)  # pyarrow engine (pinned dependency)
        buffer.seek(0)
    elif suffix == "csv":
        buffer = io.BytesIO(df.to_csv(index=False).encode("utf-8"))
    else:
        raise InputSourceError(
            f"cannot materialize a postgres source to {key!r}: the snapshot destination must end "
            f"in one of {list(_SNAPSHOT_SUFFIXES)}"
        )
    storage.save_input(key, buffer)


def list_tables(connection_env: str, schema: str | None = None) -> list[str]:
    """Return the table names in the database named by ``connection_env``'s DSN (sorted).

    A small read-only introspection helper for the dashboard's "Import from database" picker,
    so the UI can offer the available tables without the operator hand-crafting a request. It
    reuses the same discipline as :func:`materialize_source`: the DSN is read from the env var
    named by ``connection_env`` (never a credential in the request), and ``sqlalchemy`` is
    imported lazily inside the function so importing this module never requires a live DB.

    Args:
        connection_env: NAME of the environment variable holding the SQLAlchemy DSN.
        schema: Optional database schema to list (default: the connection's default schema —
            ``public`` for Postgres, where :func:`pandas.DataFrame.to_sql` writes by default).

    Returns:
        The table names in that database/schema, sorted.

    Raises:
        InputSourceError: If the connection env var is unset/empty, or the database cannot be
            reached/introspected. (The API route maps this to a clean 503 — the same "store
            unavailable" discipline the MLflow read-path uses — never an opaque 500.)
    """
    url = _resolve_connection_url(connection_env)

    # Lazy, opt-in dependency import (mirrors materialize_source).
    from sqlalchemy import create_engine, inspect as sa_inspect  # noqa: PLC0415

    logger.info(
        "input_source: listing tables (connection env %s, schema %s)", connection_env, schema
    )
    try:
        engine = create_engine(url)
        try:
            inspector = sa_inspect(engine)
            names = inspector.get_table_names(schema=schema)
        finally:
            engine.dispose()  # do not leak a connection pool
    except InputSourceError:
        raise
    except Exception as exc:  # noqa: BLE001 — any driver/DB/introspection failure is a clean error
        raise InputSourceError(
            f"failed to list tables from the input database (env {connection_env!r}): "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    return sorted(names)


def materialize_source(config: dict[str, Any], storage: StorageAdapter) -> str:
    """Materialize the run's input source to a file, returning the key the pipeline will read.

    For the default ``file`` source this is a **no-op** — it returns ``config["input_file"]``
    unchanged and imports nothing. For a ``postgres`` source it runs the configured table/query
    ONCE against the database named by ``input_source.connection_env`` and writes the result to
    ``config["input_file"]`` under ``DATA_DIR`` (via :meth:`StorageAdapter.save_input`), so the
    normal file pipeline then runs on that snapshot.

    Args:
        config: A validated run config (see :func:`classifyos.config.build_config`). Reads
            ``input_source`` and ``input_file``; nothing is mutated.
        storage: Storage adapter — the snapshot is written through it into the INPUT root.

    Returns:
        The logical key the pipeline should read (always ``config["input_file"]``).

    Raises:
        InputSourceError: If the connection env var is unset, the database is unreachable, the
            query fails or returns no rows, or the snapshot suffix is unsupported.
    """
    src = config.get("input_source") or {}
    input_file = config["input_file"]
    if src.get("type", "file") != "postgres":
        return input_file  # file source — the normal pipeline reads input_file directly

    # Lazy, opt-in dependency imports (only reached for a DB source).
    import pandas as pd  # noqa: PLC0415
    from sqlalchemy import create_engine, text  # noqa: PLC0415

    connection_env = src.get("connection_env")
    table = src.get("table")
    query = src.get("query")
    url = _resolve_connection_url(connection_env)
    # config validation guarantees EXACTLY ONE of table/query, and a safe identifier for table.
    sql = query if (isinstance(query, str) and query.strip()) else f"SELECT * FROM {table}"

    logger.info(
        "input_source=postgres: materializing %s to %s (connection env %s)",
        "query" if (isinstance(query, str) and query.strip()) else f"table {table!r}",
        input_file,
        connection_env,
    )

    try:
        engine = create_engine(url)
        try:
            with engine.connect() as conn:
                df = pd.read_sql(text(sql), conn)
        finally:
            engine.dispose()  # do not leak a connection pool per run
    except InputSourceError:
        raise
    except Exception as exc:  # noqa: BLE001 — any driver/DB/query failure is a clean input error
        raise InputSourceError(
            f"failed to read the postgres input source (env {connection_env!r}): "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    if df is None or df.empty:
        raise InputSourceError(
            f"the postgres input source returned no rows (env {connection_env!r}); "
            "nothing to materialize"
        )

    _write_snapshot(df, input_file, storage)
    logger.info(
        "input_source=postgres: wrote %d row(s) x %d column(s) to %s",
        len(df),
        df.shape[1],
        input_file,
    )
    return input_file


def materialize_delta_source(config: dict[str, Any], storage: StorageAdapter) -> None:
    """Materialize a Unity Catalog Delta table to a Parquet/CSV snapshot (Databricks §6.6 Step 4).

    The Delta twin of :func:`materialize_source`, following the identical materialize-to-file
    discipline so the pipeline stays byte-for-byte unchanged downstream:

    * **Opt-in** — a **no-op** unless ``config["input_source"]["type"] == "delta"``. For a
      ``file`` / ``postgres`` source this returns immediately, importing nothing, so the runner
      can call it unconditionally next to :func:`materialize_source`.
    * **Lazy import** — ``pyspark`` is imported *inside* the function (never at module load), so a
      local file run — or an install without PySpark — never touches the dependency. PySpark is
      pre-installed on Databricks clusters; off a cluster the import (or the absent SparkSession)
      raises a clear :class:`InputSourceError`, it never crashes a file-based run.
    * **Materialize-to-file** — reads the Delta table ONCE via the active SparkSession
      (``spark.table("<catalog>.<schema>.<table>")`` or ``spark.sql(query)``), converts to pandas,
      and writes the snapshot to ``config["input_file"]`` via :meth:`StorageAdapter.save_input`
      (reusing :func:`_write_snapshot`). ``data_loader`` and everything downstream then run on that
      plain file, completely unchanged.

    ``config["input_source"]`` fields for ``type="delta"``:
        catalog : Unity Catalog name, e.g. ``"main"`` (optional; qualifies the table name)
        schema  : schema/database, e.g. ``"insurance"`` (optional)
        table   : table name, e.g. ``"policy_lapse"`` (provide table OR query)
        query   : optional raw SQL override — ``spark.sql(query)`` (takes precedence over table)
        limit   : optional positive-int row cap (handy for dev/smoke runs)

    [RISK] leakage — runs strictly BEFORE split/fit and only *writes* a snapshot file; it feeds
    nothing back into fit/transform (identical to :func:`materialize_source`).
    [RISK] SQL injection — ``catalog`` / ``schema`` / ``table`` are validated to safe SQL
    identifiers at config-build time (:func:`classifyos.config._validate_delta_source`) because
    they are interpolated into the dotted table name and cannot be bound parameters; a raw
    ``query`` is the analyst's own opt-in SQL on their own cluster.
    [RISK] Spark context — requires an active SparkSession (always present on a Databricks
    cluster); its absence raises :class:`InputSourceError`, never an opaque failure.

    Args:
        config: A validated run config (see :func:`classifyos.config.build_config`). Reads
            ``input_source`` and ``input_file``; nothing is mutated.
        storage: Storage adapter — the snapshot is written through it into the INPUT root.

    Raises:
        InputSourceError: If PySpark is unavailable, there is no active SparkSession, neither
            ``table`` nor ``query`` is set, the table/query read fails, or the result is empty.
    """
    src = config.get("input_source") or {}
    if src.get("type") != "delta":
        return  # no-op for file/postgres sources — keeps the runner call site unconditional

    try:
        from pyspark.sql import SparkSession  # noqa: PLC0415 — lazy, cluster-only import
    except ImportError as exc:
        raise InputSourceError(
            "input_source.type='delta' requires PySpark, which is pre-installed on Databricks "
            "clusters. Use input_source.type='file' for local runs."
        ) from exc

    spark = SparkSession.getActiveSession()
    if spark is None:
        raise InputSourceError(
            "input_source.type='delta' found no active SparkSession; it must run on a Databricks "
            "cluster (where a session is always present). Use input_source.type='file' locally."
        )

    catalog = src.get("catalog")
    schema = src.get("schema")
    table = src.get("table")
    query = src.get("query")
    limit = src.get("limit")
    input_file = config["input_file"]

    has_query = isinstance(query, str) and query.strip() != ""
    has_table = isinstance(table, str) and table.strip() != ""
    # config validation guarantees at least one of table/query; this is a defensive fallback for a
    # hand-built config that bypassed build_config.
    if not has_query and not has_table:
        raise InputSourceError(
            "input_source with type='delta' requires either 'table' or 'query'"
        )

    try:
        if has_query:
            # A raw query takes precedence over table when both are somehow present.
            logger.info("input_source=delta: running custom query")
            sdf = spark.sql(query)
        else:
            full_name = ".".join(part for part in (catalog, schema, table) if part)
            logger.info("input_source=delta: reading table %s", full_name)
            sdf = spark.table(full_name)
        if limit:
            sdf = sdf.limit(int(limit))
        logger.info("input_source=delta: converting to pandas")
        df = sdf.toPandas()
    except InputSourceError:
        raise
    except Exception as exc:  # noqa: BLE001 — any Spark/read failure is a clean input error
        raise InputSourceError(
            f"failed to read the delta input source: {type(exc).__name__}: {exc}"
        ) from exc

    if df is None or df.empty:
        raise InputSourceError(
            "the delta input source returned no rows; nothing to materialize "
            "(check your table/query)."
        )

    _write_snapshot(df, input_file, storage)
    logger.info(
        "input_source=delta: wrote %d row(s) x %d column(s) to %s",
        len(df),
        df.shape[1],
        input_file,
    )
