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
    """A Postgres input source could not be read or materialized to a file.

    Raised for a missing/empty connection env var, an unreachable database, a failed query, an
    empty result, or an unsupported snapshot suffix. The API ``/run`` route maps it to the
    ``status="error"`` envelope (a 400-style run error, like a missing input file) rather than an
    opaque 500.
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
