"""Persistent job-state store for the Databricks orchestration layer (§6.6 Step 6, Part B).

FastAPI is stateless — a restart mid-poll would lose an in-flight ``job_id`` and the user could
not reconnect to their running Databricks Job. This module persists the mapping

    job_id (our handle) → { databricks_run_id, status, submitted_at, updated_at, config, … }

in a small ``classifyos_jobs`` table via **SQLAlchemy Core** (not the ORM — one table, plain
inserts/updates, no models to maintain). The store is the **existing MLflow Postgres** by default
(``MLFLOW_TRACKING_URI`` when it is a ``postgresql://`` URI), so a FastAPI restart re-reads any
``RUNNING`` job from the same DB. It can be overridden with ``CLASSIFYOS_JOBS_DSN`` (CI points this
at a temp sqlite file), and falls back to a local sqlite file when neither is configured.

Discipline: the engine is created lazily + cached (like :mod:`api.deps`'s storage), and
:func:`init_db` (called at startup) creates the table if absent and is a no-op if the DB is
unreachable — a missing/broken jobs DB must never block app startup or a local run.

[RISK] no PII / credentials are stored here — never the user's PAT. ``config_json`` is the run's
own (already client-supplied) RunConfig, useful for audit + reconnect.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

_metadata = MetaData()

#: The one table. TEXT ids/status keep it portable across sqlite (CI) and Postgres (prod).
jobs_table = Table(
    "classifyos_jobs",
    _metadata,
    Column("job_id", String(64), primary_key=True),
    Column("databricks_run_id", Text, nullable=True),
    Column("status", String(32), nullable=False),
    Column("submitted_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("config_json", Text, nullable=True),
    Column("message", Text, nullable=True),
    Column("error", Text, nullable=True),
)

_engine: Engine | None = None


def _dsn() -> str:
    """Resolve the jobs-store DSN.

    Precedence: explicit ``CLASSIFYOS_JOBS_DSN`` → the MLflow Postgres (``MLFLOW_TRACKING_URI`` when
    it is a ``postgresql`` URI, reusing the store we already run) → a local sqlite fallback.
    """
    explicit = (os.environ.get("CLASSIFYOS_JOBS_DSN") or "").strip()
    if explicit:
        return explicit
    mlflow_uri = (os.environ.get("MLFLOW_TRACKING_URI") or "").strip()
    if mlflow_uri.startswith("postgresql"):
        return mlflow_uri
    return "sqlite:///classifyos_jobs.db"


def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine (constructed once, lazily)."""
    global _engine
    if _engine is None:
        dsn = _dsn()
        # sqlite + FastAPI's threadpool (sync routes run off the event loop) need this flag.
        connect_args = {"check_same_thread": False} if dsn.startswith("sqlite") else {}
        _engine = create_engine(dsn, connect_args=connect_args, future=True)
        logger.info("ClassifyOS jobs store: %s", _engine.url.render_as_string(hide_password=True))
    return _engine


def reset_engine() -> None:
    """Drop the cached engine so the next call rebuilds it (used by tests to swap the DSN)."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def init_db() -> None:
    """Create ``classifyos_jobs`` if it does not exist. Safe to call at every startup.

    Never raises: a missing/unreachable DB only logs a warning so it can't block app startup or a
    local (non-Databricks) run that never touches the store.
    """
    try:
        _metadata.create_all(get_engine())
    except Exception as exc:  # noqa: BLE001 — startup must not fail on a jobs-DB hiccup
        logger.warning("ClassifyOS jobs store unavailable (create_all failed): %s", exc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_job(
    databricks_run_id: str | None,
    status: str = "PENDING",
    config_json: str | None = None,
) -> str:
    """Insert a new job row and return its generated ``job_id`` (a uuid4 hex handle)."""
    job_id = uuid.uuid4().hex
    now = _now()
    with get_engine().begin() as conn:
        conn.execute(
            insert(jobs_table).values(
                job_id=job_id,
                databricks_run_id=databricks_run_id,
                status=status,
                submitted_at=now,
                updated_at=now,
                config_json=config_json,
                message=None,
                error=None,
            )
        )
    return job_id


def update_status(
    job_id: str,
    status: str,
    message: str | None = None,
    error: str | None = None,
) -> None:
    """Update a job's ``status`` (and optional ``message``/``error``) + ``updated_at``."""
    values: dict[str, Any] = {"status": status, "updated_at": _now()}
    if message is not None:
        values["message"] = message
    if error is not None:
        values["error"] = error
    with get_engine().begin() as conn:
        conn.execute(update(jobs_table).where(jobs_table.c.job_id == job_id).values(**values))


def get_job(job_id: str) -> dict[str, Any] | None:
    """Return the job row as a dict, or ``None`` if unknown.

    Datetimes are returned as UTC ISO-8601 strings so the row is JSON-safe for the API.
    """
    with get_engine().connect() as conn:
        row = conn.execute(
            select(jobs_table).where(jobs_table.c.job_id == job_id)
        ).mappings().first()
    if row is None:
        return None
    data = dict(row)
    for key in ("submitted_at", "updated_at"):
        value = data.get(key)
        if isinstance(value, datetime):
            # sqlite may hand back a naive datetime; treat it as UTC for a stable ISO string.
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            data[key] = value.isoformat()
    return data
