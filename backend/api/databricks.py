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
import re
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:  # pandas is imported lazily inside fetch_table_sample; only the annotation needs it
    import pandas as pd

logger = logging.getLogger(__name__)

#: API paths (Jobs 2.1 + Unity Catalog 2.1 — verified against Microsoft Learn / Azure Databricks).
_SUBMIT_PATH = "/api/2.1/jobs/runs/submit"
_GET_RUN_PATH = "/api/2.1/jobs/runs/get"
_CATALOGS_PATH = "/api/2.1/unity-catalog/catalogs"
_SCHEMAS_PATH = "/api/2.1/unity-catalog/schemas"
_TABLES_PATH = "/api/2.1/unity-catalog/tables"
#: Compute 2.0 — list the workspace's clusters for the run-config cluster picker (user's PAT).
_CLUSTERS_PATH = "/api/2.0/clusters/list"
#: SCIM 2.0 — "who am I" for the requesting user's PAT; ``userName`` is their account email.
_SCIM_ME_PATH = "/api/2.0/preview/scim/v2/Me"
#: SQL Statement Execution 2.0 — run a SELECT on a SQL warehouse and read rows back over REST. Used
#: to profile a Unity Catalog table's ACTUAL data at selection time (a bounded sample); the training
#: run still reads the FULL table on the cluster via Spark. Verified against Microsoft Learn / the
#: Databricks SDK (INLINE + JSON_ARRAY → ``result.data_array`` of string cells; see fetch_table_sample).
_SQL_STATEMENTS_PATH = "/api/2.0/sql/statements"

#: Unity Catalog ``ColumnTypeName`` → the ``inspect_file`` column-group buckets (verified against the
#: Databricks SDK ``ColumnTypeName`` enum / Microsoft Learn). Shared by the schema-only mapper
#: (``routes/databricks._profile_from_columns``) and the SQL-sample numeric coercion
#: (:func:`fetch_table_sample`), so the two never diverge. Any type outside these sets falls through
#: to "categorical" (STRING, CHAR, BINARY, ARRAY/STRUCT/MAP, VARIANT, …) — the CSV inspector's default.
UC_NUMERIC_TYPES = frozenset({"BYTE", "SHORT", "INT", "LONG", "FLOAT", "DOUBLE", "DECIMAL"})
UC_DATETIME_TYPES = frozenset({"DATE", "TIMESTAMP", "TIMESTAMP_NTZ"})

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


def _submit_payload(
    run_config: dict[str, Any],
    user_pat: str,
    cluster_id: str | None = None,
    user_email: str | None = None,
) -> dict[str, Any]:
    """Build the ``jobs/runs/submit`` body: install the wheel, run the entrypoint notebook.

    The task carries the RunConfig JSON and the user's PAT as ``base_parameters`` so the cluster
    job builds the engine config and reads Unity Catalog data as the requesting user. Requires
    ``DATABRICKS_JOB_NOTEBOOK_PATH`` (the entrypoint) and a cluster to run on; the wheel path
    (``DATABRICKS_JOB_WHEEL_PATH``) is attached as a library when set.

    Cluster selection (schema 1.11, additive): a non-empty ``cluster_id`` (from the UI picker)
    overrides the ``DATABRICKS_JOB_CLUSTER_ID`` env var. When ``cluster_id`` is absent/empty the env
    var is used, exactly as before (so server-only deployments are unchanged). If neither is set a
    :class:`DatabricksConfigError` is raised, preserving the existing behaviour.

    Output isolation (additive): ``user_email`` (already resolved + sanitized by
    :func:`get_user_email`) rides along as a ``base_parameter`` so the notebook namespaces its
    output under ``{DBRICKS_OUTPUT_VOLUME}/{user_email}/{job_id}/`` — the same prefix
    ``GET /run/{job_id}/results`` rebuilds when fetching the envelope. Falls back to
    ``"unknown_user"`` so a run is never blocked on email resolution.
    """
    notebook_path = (os.environ.get("DATABRICKS_JOB_NOTEBOOK_PATH") or "").strip()
    # A request-supplied cluster overrides the env default; fall back to the env var otherwise.
    resolved_cluster_id = (cluster_id or "").strip() or (
        os.environ.get("DATABRICKS_JOB_CLUSTER_ID") or ""
    ).strip()
    wheel_path = (os.environ.get("DATABRICKS_JOB_WHEEL_PATH") or "").strip()
    if not notebook_path:
        raise DatabricksConfigError("DATABRICKS_JOB_NOTEBOOK_PATH is not set")
    if not resolved_cluster_id:
        raise DatabricksConfigError("DATABRICKS_JOB_CLUSTER_ID is not set")

    task: dict[str, Any] = {
        "task_key": "classifyos_run",
        "existing_cluster_id": resolved_cluster_id,
        "notebook_task": {
            "notebook_path": notebook_path,
            # base_parameters reach the notebook as string widgets. [RISK] the PAT is visible in
            # the run's parameters in the Databricks UI — a secret-scope handoff is the follow-up.
            "base_parameters": {
                "run_config": json.dumps(run_config),
                "user_token": user_pat,
                "wheel_path": wheel_path,
                "user_email": (user_email or "").strip() or "unknown_user",
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


def submit_run(
    run_config: dict[str, Any],
    user_pat: str,
    cluster_id: str | None = None,
    user_email: str | None = None,
) -> dict[str, Any]:
    """Submit a one-off Databricks Job for ``run_config``; return ``{"run_id": "<id>"}``.

    Authenticated with the service token; the user's PAT rides along as a task parameter. When
    ``cluster_id`` is a non-empty id (from the UI cluster picker) the Job runs on that cluster,
    otherwise the ``DATABRICKS_JOB_CLUSTER_ID`` env var is used (see :func:`_submit_payload`).
    ``user_email`` (from :func:`get_user_email`) is forwarded so the notebook namespaces its output
    per user. Raises :class:`DatabricksUnavailable` if the workspace can't be reached,
    :class:`DatabricksAuthError` on a rejected service token, or :class:`DatabricksConfigError` on
    missing config.
    """
    payload = _submit_payload(run_config, user_pat, cluster_id, user_email)
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


def get_task_run_id(outer_run_id: str) -> str:
    """Return the first task's run_id for a SUBMIT_RUN job.

    For ``SUBMIT_RUN`` jobs the outer ``run_id`` (what FastAPI receives from the submit and uses as
    ``job_id``) differs from the task-level ``run_id`` that ``dbutils.notebook.entry_point...
    currentRunId()`` returns inside the notebook. The notebook namespaces its output under the task
    run_id; this function bridges the gap so ``GET /run/{job_id}/results`` can build the correct UC
    path. Authenticated with the service token. Falls back to ``outer_run_id`` if the response
    carries no tasks (e.g. a flat single-task run or an unexpected payload shape).
    """
    with _build_client(_service_token()) as client:
        body = _request(client, "GET", _GET_RUN_PATH, params={"run_id": outer_run_id})
    tasks = body.get("tasks") or []
    if tasks and isinstance(tasks[0], dict) and tasks[0].get("run_id"):
        return str(tasks[0]["run_id"])
    return outer_run_id


# --------------------------------------------------------------------------- #
# Clusters — compute picker (authenticated with the SERVICE token)             #
# --------------------------------------------------------------------------- #

#: Cluster states a training Job can actually be submitted to: ``RUNNING`` is live and
#: ``TERMINATED`` can be auto-started by the Jobs API. Every other state — ``TERMINATING``,
#: ``ERROR``, ``UNKNOWN``, ``PENDING``, ``RESTARTING``, ``RESIZING`` — is excluded because a submit
#: against one would fail or hang. (Verified against the Clusters 2.0 ``ClusterState`` enum.)
_USABLE_CLUSTER_STATES = frozenset({"RUNNING", "TERMINATED"})


def list_clusters() -> list[dict[str, str]]:
    """List the Databricks clusters a run can be submitted to (usable state, sorted by name).

    Authenticated with the **service token** (``DATABRICKS_TOKEN``), NOT a user PAT — a training run
    is submitted to a cluster by the *service* identity (see :func:`submit_run` →
    ``existing_cluster_id``), so the picker must reflect the clusters that identity can actually run
    on, not the browsing user's view. This mirrors the other Jobs-API calls (submit/poll), which are
    also service-token authenticated; only the Unity Catalog *data* browsers use the user's PAT,
    because those expose user-scoped data.

    Calls ``GET /api/2.0/clusters/list`` and keeps only clusters a run can actually target: state in
    :data:`_USABLE_CLUSTER_STATES` (``RUNNING``/``TERMINATED``) and either a live ``spark_context_id``
    or one of those restartable states. Each surviving entry is reduced to the three fields the UI's
    cluster picker needs — ``cluster_id``, ``cluster_name`` (falls back to the id when unnamed), and
    ``state`` — and the list is sorted case-insensitively by ``cluster_name``.

    Returns:
        A list of ``{"cluster_id", "cluster_name", "state"}`` dicts, sorted by ``cluster_name``.

    Raises:
        DatabricksConfigError: ``DATABRICKS_HOST``/``DATABRICKS_TOKEN`` is not configured (→ 500).
        DatabricksAuthError: The workspace rejected the service token (→ 401).
        DatabricksUnavailable: The workspace could not be reached / returned an error (→ 503).
    """
    with _build_client(_service_token()) as client:
        body = _request(client, "GET", _CLUSTERS_PATH)
    raw = body.get("clusters")
    if not isinstance(raw, list):
        return []

    usable: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        cluster_id = item.get("cluster_id")
        state = str(item.get("state") or "").upper()
        if not cluster_id or state not in _USABLE_CLUSTER_STATES:
            continue
        # A submittable cluster is live (a spark_context_id is present) or in a restartable state —
        # both hold for the usable states above, so this is a belt-and-braces guard, not a 2nd filter.
        if not (item.get("spark_context_id") or state in ("RUNNING", "TERMINATED")):
            continue
        usable.append(
            {
                "cluster_id": str(cluster_id),
                "cluster_name": str(item.get("cluster_name") or cluster_id),
                "state": state,
            }
        )
    usable.sort(key=lambda c: c["cluster_name"].lower())
    return usable


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


#: Default row cap for the table-profile SAMPLE read (display-only). Kept well under the SQL
#: Statement Execution API's 25 MiB inline limit and the profiler's 50k internal-sampling threshold,
#: so a table-profile query stays a fast, bounded read. Override: CLASSIFYOS_DBRICKS_PROFILE_SAMPLE_ROWS.
_DEFAULT_PROFILE_SAMPLE_ROWS = 10_000


def _sql_warehouse_id() -> str:
    """Return the SQL warehouse id used to read a table sample for profiling.

    Prefers ``DATABRICKS_SQL_WAREHOUSE_ID``; falls back to the last path segment of
    ``DATABRICKS_HTTP_PATH`` (``/sql/1.0/warehouses/<id>``), which the deployment already sets for
    the SQL connector — so profiling works with no new env on a workspace that already has one.
    Raises :class:`DatabricksConfigError` when neither is set; the table-profile route catches that
    and degrades to the schema-only profile (never blocks the picker).
    """
    warehouse_id = (os.environ.get("DATABRICKS_SQL_WAREHOUSE_ID") or "").strip()
    if warehouse_id:
        return warehouse_id
    http_path = (os.environ.get("DATABRICKS_HTTP_PATH") or "").strip().rstrip("/")
    if http_path:
        segment = http_path.rsplit("/", 1)[-1]
        if segment:
            return segment
    raise DatabricksConfigError(
        "no SQL warehouse configured for table profiling; set DATABRICKS_SQL_WAREHOUSE_ID "
        "(or DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/<id>)"
    )


def _profile_sample_rows() -> int:
    """Row cap for the table-profile sample read (env override, positive int, else the default)."""
    raw = (os.environ.get("CLASSIFYOS_DBRICKS_PROFILE_SAMPLE_ROWS") or "").strip()
    if not raw:
        return _DEFAULT_PROFILE_SAMPLE_ROWS
    try:
        rows = int(raw)
    except ValueError:
        return _DEFAULT_PROFILE_SAMPLE_ROWS
    return rows if rows > 0 else _DEFAULT_PROFILE_SAMPLE_ROWS


def fetch_table_sample(
    catalog: str, schema: str, table: str, user_pat: str, *, limit: int | None = None
) -> "pd.DataFrame":
    """Read up to ``limit`` rows of ``catalog.schema.table`` for DISPLAY-ONLY profiling.

    Runs ``SELECT * FROM <catalog>.<schema>.<table>`` on the configured SQL warehouse via the
    Databricks **SQL Statement Execution API** (``POST /api/2.0/sql/statements``, INLINE +
    JSON_ARRAY), authenticated with the caller's ``user_pat`` — the same identity the Unity Catalog
    browsers use, so the sample reflects exactly what that user is entitled to read. The read is
    bounded by ``row_limit`` (default :data:`_DEFAULT_PROFILE_SAMPLE_ROWS`) so a huge table can never
    dump more than a capped sample into the API process, and the request carries ``wait_timeout=30s``
    + ``on_wait_timeout=CANCEL`` — one call, no polling, and a slow statement is cancelled rather than
    left running.

    Returns a pandas DataFrame with columns in the result's schema order; columns the manifest marks
    numeric are coerced with ``pd.to_numeric`` (JSON_ARRAY returns every cell as a string), so the
    engine's downstream type detection matches a CSV upload. Reads only — feeds nothing back into
    training; the run still reads the FULL table on the cluster (``materialize_delta_source``).

    Raises :class:`DatabricksConfigError` (no warehouse configured), :class:`DatabricksAuthError`
    (missing/rejected PAT), or :class:`DatabricksUnavailable` (unreachable workspace, a non-SUCCEEDED
    statement, or an empty result). The table-profile route catches ALL of these and falls back to
    the schema-only profile, so a failure here never blocks the column picker.
    """
    import pandas as pd  # noqa: PLC0415 — local: keep pandas out of this module's import path

    warehouse_id = _sql_warehouse_id()
    row_limit = int(limit) if (limit and int(limit) > 0) else _profile_sample_rows()
    full_name = f"{catalog}.{schema}.{table}"
    # row_limit (a request field) bounds the read WITHOUT interpolating a LIMIT clause; the dotted
    # identifier is validated to a simple SQL identifier by the route before this is ever called.
    payload = {
        "warehouse_id": warehouse_id,
        "statement": f"SELECT * FROM {full_name}",
        "row_limit": row_limit,
        "wait_timeout": "30s",
        "on_wait_timeout": "CANCEL",
        "disposition": "INLINE",
        "format": "JSON_ARRAY",
    }
    with _build_client(_require_pat(user_pat)) as client:
        body = _request(client, "POST", _SQL_STATEMENTS_PATH, json=payload)

    status = body.get("status") if isinstance(body, dict) else None
    state = str(status.get("state") if isinstance(status, dict) else "").upper()
    if state != "SUCCEEDED":
        # PENDING/RUNNING (timed out → cancelled), FAILED, CANCELED, CLOSED — no inline result.
        raise DatabricksUnavailable(
            f"table sample query did not succeed for {full_name!r} (state={state or 'unknown'})"
        )

    manifest = body.get("manifest") or {}
    columns_meta = (manifest.get("schema") or {}).get("columns") or []
    names = [str(c["name"]) for c in columns_meta if isinstance(c, dict) and c.get("name")]
    data_array = (body.get("result") or {}).get("data_array") or []
    if not names or not data_array:
        raise DatabricksUnavailable(f"table sample for {full_name!r} returned no rows")

    df = pd.DataFrame(data_array, columns=names)
    # JSON_ARRAY returns every cell as a string (or null). Coerce the columns the manifest marks
    # numeric so downstream type detection matches a CSV upload (a numeric column of string values
    # would otherwise read as categorical). Datetime/boolean/string are left for inspect's own
    # detection (dates parse from their separators; a two-value column reads as binary).
    for col in columns_meta:
        name = col.get("name") if isinstance(col, dict) else None
        if name in df.columns and str(col.get("type_name") or "").upper() in UC_NUMERIC_TYPES:
            df[name] = pd.to_numeric(df[name], errors="coerce")
    return df


def fetch_uc_file(volume_path: str) -> bytes:
    """Download a file from a Unity Catalog volume path using the Databricks Files API.

    ``volume_path`` must be an absolute UC volume path, e.g.
    ``/Volumes/aiml_rd/classifyos/output/api/{job_id}/run_response.json``.
    Authenticated with the service token. Raises :class:`DatabricksUnavailable` if the
    file does not exist or cannot be fetched.
    """
    host = _host()
    token = _service_token()
    url = f"{host}/api/2.0/fs/files{volume_path}"
    try:
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=_HTTP_TIMEOUT,
        )
    except httpx.TransportError as exc:
        raise DatabricksUnavailable(f"could not fetch UC file: {exc}") from exc
    if resp.status_code == 404:
        raise DatabricksUnavailable(f"UC file not found: {volume_path!r}")
    if resp.status_code == 401:
        raise DatabricksAuthError("service token rejected when fetching UC file")
    if not resp.is_success:
        raise DatabricksUnavailable(f"UC file fetch failed ({resp.status_code}): {volume_path!r}")
    return resp.content


def _require_pat(user_pat: str | None) -> str:
    """Return a non-empty PAT or raise :class:`DatabricksAuthError` (→ 401)."""
    if not user_pat or not user_pat.strip():
        raise DatabricksAuthError("a Databricks PAT is required (X-Databricks-Token header)")
    return user_pat.strip()


# --------------------------------------------------------------------------- #
# User identity — resolve the requesting user's email for output namespacing   #
# --------------------------------------------------------------------------- #

#: Characters allowed verbatim in a single output-folder segment; anything else (notably ``@`` and
#: any path separators / whitespace) collapses to ``_`` so an email is safe as a UC-volume folder.
_EMAIL_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_email_for_path(email: str) -> str:
    """Make ``email`` safe as a single UC-volume folder segment.

    Replaces every run of characters outside ``[A-Za-z0-9._-]`` (notably ``@`` and any path
    separators) with a single ``_`` and trims leading/trailing separators. Deterministic, so the
    value FastAPI passes to the notebook at submit and the value it re-resolves when fetching
    results always agree (both build the same ``{user_email}/{job_id}`` prefix).
    """
    cleaned = _EMAIL_UNSAFE_RE.sub("_", (email or "").strip()).strip("._-")
    return cleaned or "unknown_user"


def get_user_email(user_pat: str) -> str:
    """Resolve the Databricks user's email from their PAT via SCIM, for output namespacing.

    Calls ``GET {DATABRICKS_HOST}/api/2.0/preview/scim/v2/Me`` with the user's PAT and reads
    ``userName`` (the account email in Databricks), returning it sanitized for use as a folder
    name (see :func:`_sanitize_email_for_path`).

    On **any** failure — a missing/empty PAT, a rejected credential, an unreachable workspace, a
    missing ``userName`` field, or a misconfigured host — returns ``"unknown_user"`` rather than
    raising. Output namespacing must never block a run, so the fallback keeps the pipeline going
    (the run simply lands under the shared ``unknown_user`` folder).
    """
    try:
        pat = (user_pat or "").strip()
        if not pat:
            return "unknown_user"
        with _build_client(pat) as client:
            body = _request(client, "GET", _SCIM_ME_PATH)
        user_name = body.get("userName") if isinstance(body, dict) else None
        return _sanitize_email_for_path(str(user_name)) if user_name else "unknown_user"
    except Exception:  # noqa: BLE001 — email resolution must never block a run
        logger.warning("could not resolve user email from PAT; using 'unknown_user'")
        return "unknown_user"
