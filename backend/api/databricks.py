"""Databricks REST client + execution-backend gate for the orchestration layer (§6.6 Step 6).

The Azure-hosted FastAPI submits training as a **Databricks Job** and reads Unity Catalog metadata
through this thin ``httpx`` client. It talks to two API families:

* **Jobs 2.1** — ``POST /api/2.1/jobs/runs/submit`` (one-off run) and ``GET /api/2.1/jobs/runs/get``
  (poll status), authenticated with the **service token** (``DATABRICKS_TOKEN``). The user's PAT is
  forwarded as a *task parameter* so the job reads Unity Catalog data as the user — never the
  service identity.
* **Unity Catalog 2.1** — ``…/unity-catalog/{catalogs,schemas,tables}`` for the UI's data-source
  picker, authenticated with the **user's PAT** (passed per request, never stored).

Discipline (mirrors the project's other optional integrations):

* **Opt-in / gated.** :func:`execution_backend` reads ``CLASSIFYOS_EXECUTION_BACKEND`` *per call*
  (default ``"local"``). Nothing here runs, and no Databricks env is required, unless a deployment
  explicitly sets ``databricks`` — so local dev / CI are byte-identical to before.
* **Clean failure modes.** A missing PAT raises :class:`DatabricksAuthError` (→ HTTP 401); an
  unreachable / erroring workspace raises :class:`DatabricksUnavailable` (→ 503). Tokens are never
  logged or echoed in an error message.
* **Testable.** All HTTP goes through :func:`_build_client`; tests swap in an
  ``httpx.MockTransport`` so CI never contacts a real workspace.

[RISK] the user PAT is forwarded in the Job's ``base_parameters`` (per the Step 6 spec), which makes
it visible in the run's parameters in the Databricks UI. Hardening to a secret scope is a documented
follow-up; the token is still never persisted server-side.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

#: API paths (Jobs 2.1 + Unity Catalog 2.1 — verified against Microsoft Learn / Azure Databricks).
_SUBMIT_PATH = "/api/2.1/jobs/runs/submit"
_GET_RUN_PATH = "/api/2.1/jobs/runs/get"
_CATALOGS_PATH = "/api/2.1/unity-catalog/catalogs"
_SCHEMAS_PATH = "/api/2.1/unity-catalog/schemas"
_TABLES_PATH = "/api/2.1/unity-catalog/tables"

#: The four public job states the API surfaces (mapped from Databricks' RunState).
JOB_STATUSES = ("PENDING", "RUNNING", "COMPLETED", "FAILED")

#: HTTP timeout (seconds) for a single Databricks REST call (NOT the Job's own run timeout).
_HTTP_TIMEOUT = 30.0

#: Default Job wall-clock cap if ``DATABRICKS_JOB_TIMEOUT_SECONDS`` is unset (cost guardrail).
_DEFAULT_JOB_TIMEOUT_SECONDS = 3600


class DatabricksError(RuntimeError):
    """Base class for Databricks orchestration errors."""


class DatabricksUnavailable(DatabricksError):
    """The workspace could not be reached / returned an error (→ HTTP 503)."""


class DatabricksAuthError(DatabricksError):
    """A required PAT was missing, or the workspace rejected the credentials (→ HTTP 401)."""


class DatabricksConfigError(DatabricksError):
    """The server is set to the databricks backend but a required env var is missing (→ 500)."""


# --------------------------------------------------------------------------- #
# Environment / configuration (read per-call so tests can monkeypatch)         #
# --------------------------------------------------------------------------- #


def execution_backend() -> str:
    """Return the configured execution backend: ``"local"`` (default) or ``"databricks"``.

    Read from ``CLASSIFYOS_EXECUTION_BACKEND`` on every call (not cached) so a test can flip it
    with ``monkeypatch.setenv`` and reuse the shared app/client. Any value other than an exact,
    case-insensitive ``"databricks"`` is treated as local — the safe default.
    """
    return "databricks" if os.environ.get("CLASSIFYOS_EXECUTION_BACKEND", "").strip().lower() == "databricks" else "local"


def _host() -> str:
    """The workspace base URL (``DATABRICKS_HOST``), e.g. ``https://adb-....azuredatabricks.net``."""
    host = (os.environ.get("DATABRICKS_HOST") or "").strip().rstrip("/")
    if not host:
        raise DatabricksConfigError("DATABRICKS_HOST is not set")
    return host


def _service_token() -> str:
    """The service PAT used for the Jobs API calls (``DATABRICKS_TOKEN``)."""
    token = (os.environ.get("DATABRICKS_TOKEN") or "").strip()
    if not token:
        raise DatabricksConfigError("DATABRICKS_TOKEN is not set")
    return token


def _job_timeout_seconds() -> int:
    raw = (os.environ.get("DATABRICKS_JOB_TIMEOUT_SECONDS") or "").strip()
    if not raw:
        return _DEFAULT_JOB_TIMEOUT_SECONDS
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_JOB_TIMEOUT_SECONDS


# --------------------------------------------------------------------------- #
# HTTP client (single seam for tests)                                          #
# --------------------------------------------------------------------------- #


def _build_client(token: str) -> httpx.Client:
    """Build an ``httpx.Client`` bound to the workspace with ``token`` as the bearer credential.

    This is the ONE place HTTP is constructed; tests monkeypatch it to inject an
    ``httpx.MockTransport`` so no real workspace is contacted. The caller closes it (``with``).
    """
    return httpx.Client(
        base_url=_host(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=_HTTP_TIMEOUT,
    )


def _request(client: httpx.Client, method: str, path: str, **kwargs: Any) -> Any:
    """Issue one request through ``client`` and return parsed JSON, mapping failures to our errors.

    A network/transport failure or a non-2xx status becomes :class:`DatabricksUnavailable`, except
    401/403 which become :class:`DatabricksAuthError`. Response bodies are truncated and the auth
    header is never included, so a token can never leak into a log line or error message.
    """
    try:
        resp = client.request(method, path, **kwargs)
    except httpx.HTTPError as exc:  # transport-level: DNS, connect, timeout, TLS, …
        raise DatabricksUnavailable(f"could not reach Databricks: {exc}") from exc

    if resp.status_code in (401, 403):
        raise DatabricksAuthError("Databricks rejected the credentials (check the PAT/token)")
    if resp.status_code >= 400:
        raise DatabricksUnavailable(
            f"Databricks returned HTTP {resp.status_code}: {resp.text[:300]}"
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise DatabricksUnavailable("Databricks returned a non-JSON response") from exc


# --------------------------------------------------------------------------- #
# Jobs API — submit + poll                                                     #
# --------------------------------------------------------------------------- #


def _submit_payload(run_config: dict[str, Any], user_pat: str) -> dict[str, Any]:
    """Build the ``jobs/runs/submit`` body: install the wheel, run the entrypoint notebook.

    The task carries the RunConfig JSON and the user's PAT as ``base_parameters`` so the cluster
    job builds the engine config and reads Unity Catalog data as the requesting user. Requires
    ``DATABRICKS_JOB_NOTEBOOK_PATH`` (the entrypoint) and ``DATABRICKS_JOB_CLUSTER_ID`` (an existing
    cluster); the wheel path (``DATABRICKS_JOB_WHEEL_PATH``) is attached as a library when set.
    """
    notebook_path = (os.environ.get("DATABRICKS_JOB_NOTEBOOK_PATH") or "").strip()
    cluster_id = (os.environ.get("DATABRICKS_JOB_CLUSTER_ID") or "").strip()
    wheel_path = (os.environ.get("DATABRICKS_JOB_WHEEL_PATH") or "").strip()
    if not notebook_path:
        raise DatabricksConfigError("DATABRICKS_JOB_NOTEBOOK_PATH is not set")
    if not cluster_id:
        raise DatabricksConfigError("DATABRICKS_JOB_CLUSTER_ID is not set")

    task: dict[str, Any] = {
        "task_key": "classifyos_run",
        "existing_cluster_id": cluster_id,
        "notebook_task": {
            "notebook_path": notebook_path,
            # base_parameters reach the notebook as string widgets. [RISK] the PAT is visible in
            # the run's parameters in the Databricks UI — a secret-scope handoff is the follow-up.
            "base_parameters": {
                "run_config": json.dumps(run_config),
                "user_token": user_pat,
            },
        },
    }
    if wheel_path:
        task["libraries"] = [{"whl": wheel_path}]

    target = run_config.get("target") or "run"
    return {
        "run_name": f"classifyos · {target}",
        "tasks": [task],
        "timeout_seconds": _job_timeout_seconds(),
    }


def submit_run(run_config: dict[str, Any], user_pat: str) -> dict[str, Any]:
    """Submit a one-off Databricks Job for ``run_config``; return ``{"run_id": "<id>"}``.

    Authenticated with the service token; the user's PAT rides along as a task parameter. Raises
    :class:`DatabricksUnavailable` if the workspace can't be reached, :class:`DatabricksAuthError`
    on a rejected service token, or :class:`DatabricksConfigError` on missing config.
    """
    payload = _submit_payload(run_config, user_pat)
    with _build_client(_service_token()) as client:
        body = _request(client, "POST", _SUBMIT_PATH, json=payload)
    run_id = body.get("run_id")
    if run_id is None:
        raise DatabricksUnavailable("Databricks submit returned no run_id")
    return {"run_id": str(run_id)}


def _status_from_state(state: dict[str, Any]) -> tuple[str, str]:
    """Map a Databricks ``RunState`` to one of :data:`JOB_STATUSES` + a human message.

    Uses ``life_cycle_state`` for the coarse stage and ``result_state`` to resolve a TERMINATED run
    to COMPLETED vs FAILED. ``SUCCESS``/``SUCCEEDED`` both count as success (the Jobs API uses the
    former, system tables the latter). Unknown/absent life-cycle values default to RUNNING so an
    in-flight poll never spuriously reports a terminal state.
    """
    life = str(state.get("life_cycle_state") or "").upper()
    result = str(state.get("result_state") or "").upper()
    message = state.get("state_message") or result or life or "unknown"

    if life in ("PENDING", "QUEUED", "BLOCKED", "WAITING_FOR_RETRY"):
        return "PENDING", message
    if life in ("RUNNING", "TERMINATING"):
        return "RUNNING", message
    if life == "TERMINATED":
        if result in ("SUCCESS", "SUCCEEDED"):
            return "COMPLETED", message
        return "FAILED", message
    if life in ("INTERNAL_ERROR", "SKIPPED"):
        return "FAILED", message
    return "RUNNING", message


def get_run_status(databricks_run_id: str) -> dict[str, str]:
    """Poll ``jobs/runs/get`` for ``databricks_run_id``; return ``{"status", "message"}``.

    ``status`` is one of :data:`JOB_STATUSES`. Authenticated with the service token. Raises
    :class:`DatabricksUnavailable` / :class:`DatabricksAuthError` on transport/auth failure.
    """
    with _build_client(_service_token()) as client:
        body = _request(client, "GET", _GET_RUN_PATH, params={"run_id": databricks_run_id})
    # Jobs 2.1 nests the state under ``state``; tolerate a flat body or a 2.2-style ``status``.
    state = body.get("state") or body.get("status") or body
    status, message = _status_from_state(state if isinstance(state, dict) else {})
    return {"status": status, "message": message}


# --------------------------------------------------------------------------- #
# Unity Catalog — data-source browsing (authenticated with the USER's PAT)     #
# --------------------------------------------------------------------------- #


def _names(items: Any) -> list[str]:
    """Extract the ``name`` field from a UC list payload's items (skips entries without one)."""
    if not isinstance(items, list):
        return []
    return [str(it["name"]) for it in items if isinstance(it, dict) and it.get("name")]


def list_catalogs(user_pat: str) -> list[str]:
    """List Unity Catalog catalog names visible to ``user_pat`` (sorted)."""
    with _build_client(_require_pat(user_pat)) as client:
        body = _request(client, "GET", _CATALOGS_PATH)
    return sorted(_names(body.get("catalogs")))


def list_schemas(catalog: str, user_pat: str) -> list[str]:
    """List schema names in ``catalog`` visible to ``user_pat`` (sorted)."""
    with _build_client(_require_pat(user_pat)) as client:
        body = _request(client, "GET", _SCHEMAS_PATH, params={"catalog_name": catalog})
    return sorted(_names(body.get("schemas")))


def list_tables(catalog: str, schema: str, user_pat: str) -> list[str]:
    """List table names in ``catalog.schema`` visible to ``user_pat`` (sorted)."""
    with _build_client(_require_pat(user_pat)) as client:
        body = _request(
            client, "GET", _TABLES_PATH,
            params={"catalog_name": catalog, "schema_name": schema},
        )
    return sorted(_names(body.get("tables")))


def get_table_columns(catalog: str, schema: str, table: str, user_pat: str) -> list[dict[str, Any]]:
    """Return the column metadata for ``catalog.schema.table`` (authenticated with ``user_pat``).

    Calls Unity Catalog's *get-a-table* endpoint —
    ``GET /api/2.1/unity-catalog/tables/{full_name}`` where ``full_name`` is the dotted
    ``catalog.schema.table`` — and returns the table's ``columns`` array. Each entry is a
    ``ColumnInfo`` dict (verified against the Databricks SDK ``ColumnInfo`` / ``ColumnTypeName``:
    ``name``, ``type_name``, ``type_text``, ``nullable``, ``comment``, ``position``, …).

    Raises :class:`DatabricksAuthError` on a missing/rejected PAT (→ 401),
    :class:`DatabricksUnavailable` on an unreachable/erroring workspace **or** a response that
    carries no columns (→ 503) — so an empty/columnless table is a clear error, never a silent
    fall-through to manual column entry.
    """
    full_name = f"{catalog}.{schema}.{table}"
    with _build_client(_require_pat(user_pat)) as client:
        body = _request(client, "GET", f"{_TABLES_PATH}/{full_name}")
    columns = body.get("columns")
    if not isinstance(columns, list) or not columns:
        raise DatabricksUnavailable(f"Unity Catalog returned no columns for {full_name!r}")
    return [c for c in columns if isinstance(c, dict)]


def _require_pat(user_pat: str | None) -> str:
    """Return a non-empty PAT or raise :class:`DatabricksAuthError` (→ 401)."""
    if not user_pat or not user_pat.strip():
        raise DatabricksAuthError("a Databricks PAT is required (X-Databricks-Token header)")
    return user_pat.strip()
