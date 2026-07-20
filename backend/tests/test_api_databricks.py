"""Unity Catalog browser-proxy tests — ``GET /api/v1/databricks/{catalogs,schemas,tables}``.

All Databricks HTTP is MOCKED (the client's ``_build_client`` seam is swapped for an
``httpx.MockTransport``), so CI never contacts a real workspace. The proxies authenticate with the
caller's PAT (``X-Databricks-Token``), which is passed straight through and never stored — the
tests assert that header reaches Unity Catalog. A missing PAT is a 401; an unreachable workspace a
503.
"""

from __future__ import annotations

import httpx
import pytest

import api.databricks as dbx

_MOCK_HOST = "https://mock.databricks.net"


@pytest.fixture
def uc_env(monkeypatch: pytest.MonkeyPatch):
    """Minimal env for the UC proxies (they don't need the databricks execution backend)."""
    monkeypatch.setenv("DATABRICKS_HOST", _MOCK_HOST)


def _install_mock(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    def _build(token: str) -> httpx.Client:
        return httpx.Client(
            base_url=_MOCK_HOST,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(dbx, "_build_client", _build)


def test_list_catalogs(api_client, uc_env, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/2.1/unity-catalog/catalogs"
        # UC is authenticated with the USER's PAT (not the service token).
        assert request.headers["Authorization"] == "Bearer user-pat"
        return httpx.Response(200, json={"catalogs": [{"name": "samples"}, {"name": "main"}]})

    _install_mock(monkeypatch, handler)
    resp = api_client.get("/api/v1/databricks/catalogs", headers={"X-Databricks-Token": "user-pat"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["catalogs"] == ["main", "samples"]  # sorted


def test_list_schemas_passes_catalog_name(api_client, uc_env, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/2.1/unity-catalog/schemas"
        assert request.url.params["catalog_name"] == "main"
        return httpx.Response(200, json={"schemas": [{"name": "insurance"}, {"name": "default"}]})

    _install_mock(monkeypatch, handler)
    resp = api_client.get(
        "/api/v1/databricks/schemas",
        params={"catalog": "main"},
        headers={"X-Databricks-Token": "user-pat"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["catalog"] == "main"
    assert body["schemas"] == ["default", "insurance"]


def test_list_tables_passes_catalog_and_schema(api_client, uc_env, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/2.1/unity-catalog/tables"
        assert request.url.params["catalog_name"] == "main"
        assert request.url.params["schema_name"] == "insurance"
        return httpx.Response(200, json={"tables": [{"name": "policy_lapse"}, {"name": "claims"}]})

    _install_mock(monkeypatch, handler)
    resp = api_client.get(
        "/api/v1/databricks/tables",
        params={"catalog": "main", "schema": "insurance"},
        headers={"X-Databricks-Token": "user-pat"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["catalog"] == "main"
    assert body["schema"] == "insurance"
    assert body["tables"] == ["claims", "policy_lapse"]


# --------------------------------------------------------------------------- #
# GET /api/v1/databricks/clusters — the run-config cluster picker               #
# --------------------------------------------------------------------------- #
#
# Same auth pattern as the UC list proxies (user PAT via X-Databricks-Token; 401 no PAT, 503
# unreachable). Only clusters a Job can actually be submitted to are surfaced — RUNNING (live) or
# TERMINATED (restartable) — sorted by cluster_name.

#: A clusters/list response spanning every state so the filter + shape can be asserted at once.
_CLUSTERS = [
    {"cluster_id": "0716-run", "cluster_name": "zeta-running", "state": "RUNNING",
     "spark_context_id": 123},
    {"cluster_id": "0716-term", "cluster_name": "Alpha-terminated", "state": "TERMINATED"},
    {"cluster_id": "0716-terming", "cluster_name": "beta-terminating", "state": "TERMINATING"},
    {"cluster_id": "0716-err", "cluster_name": "err-cluster", "state": "ERROR"},
    {"cluster_id": "0716-unk", "cluster_name": "unknown-cluster", "state": "UNKNOWN"},
    {"cluster_id": "0716-pend", "cluster_name": "pending-cluster", "state": "PENDING"},
]


def test_list_clusters_filters_and_sorts(api_client, uc_env, monkeypatch) -> None:
    """Only RUNNING/TERMINATED clusters are returned, sorted case-insensitively by name."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/2.0/clusters/list"
        # The cluster picker authenticates with the USER's PAT, like the UC proxies.
        assert request.headers["Authorization"] == "Bearer user-pat"
        return httpx.Response(200, json={"clusters": _CLUSTERS})

    _install_mock(monkeypatch, handler)
    resp = api_client.get("/api/v1/databricks/clusters", headers={"X-Databricks-Token": "user-pat"})
    assert resp.status_code == 200, resp.text
    clusters = resp.json()["clusters"]

    # TERMINATING / ERROR / UNKNOWN / PENDING are dropped; the two usable ones remain, name-sorted.
    assert clusters == [
        {"cluster_id": "0716-term", "cluster_name": "Alpha-terminated", "state": "TERMINATED"},
        {"cluster_id": "0716-run", "cluster_name": "zeta-running", "state": "RUNNING"},
    ]


def test_list_clusters_empty_when_none_usable(api_client, uc_env, monkeypatch) -> None:
    """A workspace with no usable clusters returns an empty list (a valid 200, not an error)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"clusters": [
            {"cluster_id": "x", "cluster_name": "x", "state": "TERMINATING"},
        ]})

    _install_mock(monkeypatch, handler)
    resp = api_client.get("/api/v1/databricks/clusters", headers={"X-Databricks-Token": "user-pat"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["clusters"] == []


def test_list_clusters_missing_pat_is_401(api_client, uc_env, monkeypatch) -> None:
    """No X-Databricks-Token → 401 before any HTTP call to Databricks."""
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover — must not be hit
        called["n"] += 1
        return httpx.Response(200, json={"clusters": _CLUSTERS})

    _install_mock(monkeypatch, handler)
    resp = api_client.get("/api/v1/databricks/clusters")
    assert resp.status_code == 401
    assert called["n"] == 0


def test_list_clusters_unavailable_is_503(api_client, uc_env, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    _install_mock(monkeypatch, handler)
    resp = api_client.get("/api/v1/databricks/clusters", headers={"X-Databricks-Token": "user-pat"})
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()


def test_missing_pat_is_401(api_client, uc_env, monkeypatch) -> None:
    """No X-Databricks-Token → 401 (before any HTTP call to Databricks)."""
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover — must not be hit
        called["n"] += 1
        return httpx.Response(200, json={"catalogs": []})

    _install_mock(monkeypatch, handler)
    resp = api_client.get("/api/v1/databricks/catalogs")
    assert resp.status_code == 401
    assert called["n"] == 0


def test_workspace_unavailable_is_503(api_client, uc_env, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    _install_mock(monkeypatch, handler)
    resp = api_client.get("/api/v1/databricks/catalogs", headers={"X-Databricks-Token": "user-pat"})
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()


def test_rejected_credentials_is_401(api_client, uc_env, monkeypatch) -> None:
    """A workspace 403 (bad/expired PAT) surfaces as a clean 401."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "forbidden"})

    _install_mock(monkeypatch, handler)
    resp = api_client.get("/api/v1/databricks/catalogs", headers={"X-Databricks-Token": "bad"})
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# GET /api/v1/databricks/table-profile — fetch a UC table's schema as a profile #
# --------------------------------------------------------------------------- #
#
# The picker fetches the chosen table's Unity Catalog schema and returns it in the SAME
# InspectProfile shape a CSV /upload produces, so the frontend reuses its column picker without
# branching. All HTTP is mocked; the endpoint is gated on the databricks execution backend.


@pytest.fixture
def dbx_backend(monkeypatch: pytest.MonkeyPatch):
    """Env for the table-profile endpoint: the UC host + the DATABRICKS execution backend.

    ``execution_backend`` reads ``CLASSIFYOS_EXECUTION_BACKEND`` per call, so flipping it here (and
    letting monkeypatch restore conftest's pinned ``local`` afterwards) enables the endpoint for
    the one test without rebuilding the shared app.
    """
    monkeypatch.setenv("DATABRICKS_HOST", _MOCK_HOST)
    monkeypatch.setenv("CLASSIFYOS_EXECUTION_BACKEND", "databricks")


#: A representative Unity Catalog ``columns`` array covering every group the mapper buckets:
#: numeric (INT/DOUBLE/DECIMAL), categorical (STRING), boolean (→ binary + categorical), and
#: datetime (TIMESTAMP/DATE). Shapes match the Databricks SDK ``ColumnInfo``.
_TABLE_COLUMNS = [
    {"name": "age", "type_name": "INT", "type_text": "int", "nullable": True, "position": 0},
    {"name": "annual_premium", "type_name": "DOUBLE", "type_text": "double", "nullable": True, "position": 1},
    {"name": "balance", "type_name": "DECIMAL", "type_text": "decimal(10,2)", "nullable": True, "position": 2},
    {"name": "region", "type_name": "STRING", "type_text": "string", "nullable": True, "position": 3},
    {"name": "has_agent", "type_name": "BOOLEAN", "type_text": "boolean", "nullable": True, "position": 4},
    {"name": "policy_start", "type_name": "TIMESTAMP", "type_text": "timestamp", "nullable": True, "position": 5},
    {"name": "dob", "type_name": "DATE", "type_text": "date", "nullable": True, "position": 6},
]


def test_table_profile_maps_columns_to_inspect_shape(api_client, dbx_backend, monkeypatch) -> None:
    """A mocked get-a-table response is reshaped into the /upload InspectProfile shape."""

    def handler(request: httpx.Request) -> httpx.Response:
        # get-a-table: the dotted full_name is the last path segment; PAT passed straight through.
        assert request.url.path == "/api/2.1/unity-catalog/tables/main.insurance.policy_lapse"
        assert request.headers["Authorization"] == "Bearer user-pat"
        return httpx.Response(200, json={"columns": _TABLE_COLUMNS})

    _install_mock(monkeypatch, handler)
    resp = api_client.get(
        "/api/v1/databricks/table-profile",
        params={"catalog": "main", "schema": "insurance", "table": "policy_lapse"},
        headers={"X-Databricks-Token": "user-pat"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Column groups derived from the UC type_name (verified against the ColumnTypeName enum).
    assert body["columns"] == [
        "age", "annual_premium", "balance", "region", "has_agent", "policy_start", "dob",
    ]
    assert body["numeric_cols"] == ["age", "annual_premium", "balance"]
    assert body["categorical_cols"] == ["region", "has_agent"]  # BOOLEAN groups categorical too
    assert body["binary_cols"] == ["has_agent"]  # BOOLEAN is the one schema-known 2-valued type
    assert body["datetime_cols"] == ["policy_start", "dob"]
    assert body["dtypes"]["balance"] == "decimal(10,2)"  # SQL type_text preferred for display

    # Row-level stats are unavailable from schema-only metadata → zeroed/empty (not fabricated).
    assert body["n_rows"] == 0
    assert body["n_missing"]["age"] == 0
    assert body["sample"] == []

    # server_path + delta input_source, exactly like /input-sources/select does for Postgres, so
    # the frontend's existing applyUpload plumbing sets the run up to read the Delta table.
    assert body["server_path"] == "db_snapshots/main_insurance_policy_lapse.parquet"
    assert body["input_source"] == {
        "type": "delta",
        "connection_env": "CLASSIFYOS_PG_DSN",
        "catalog": "main",
        "schema": "insurance",
        "table": "policy_lapse",
        "query": None,
    }


def test_table_profile_no_columns_is_503(api_client, dbx_backend, monkeypatch) -> None:
    """A table whose metadata carries no columns is a clear 503 — never a silent empty profile."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"columns": []})

    _install_mock(monkeypatch, handler)
    resp = api_client.get(
        "/api/v1/databricks/table-profile",
        params={"catalog": "main", "schema": "insurance", "table": "empty_table"},
        headers={"X-Databricks-Token": "user-pat"},
    )
    assert resp.status_code == 503
    assert "no columns" in resp.json()["detail"].lower()


def test_table_profile_requires_databricks_backend(api_client, uc_env, monkeypatch) -> None:
    """In the LOCAL backend (conftest default) the picker is unavailable → 503, before any HTTP."""
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover — must not be hit
        called["n"] += 1
        return httpx.Response(200, json={"columns": _TABLE_COLUMNS})

    _install_mock(monkeypatch, handler)
    resp = api_client.get(
        "/api/v1/databricks/table-profile",
        params={"catalog": "main", "schema": "insurance", "table": "policy_lapse"},
        headers={"X-Databricks-Token": "user-pat"},
    )
    assert resp.status_code == 503
    assert "databricks execution backend" in resp.json()["detail"].lower()
    assert called["n"] == 0


def test_table_profile_missing_pat_is_401(api_client, dbx_backend, monkeypatch) -> None:
    """No X-Databricks-Token → 401 before any HTTP call to Databricks."""
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover — must not be hit
        called["n"] += 1
        return httpx.Response(200, json={"columns": _TABLE_COLUMNS})

    _install_mock(monkeypatch, handler)
    resp = api_client.get(
        "/api/v1/databricks/table-profile",
        params={"catalog": "main", "schema": "insurance", "table": "policy_lapse"},
    )
    assert resp.status_code == 401
    assert called["n"] == 0


def test_table_profile_bad_identifier_is_422(api_client, dbx_backend, monkeypatch) -> None:
    """A table name that is not a simple SQL identifier is rejected (422) before any HTTP call."""
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover — must not be hit
        called["n"] += 1
        return httpx.Response(200, json={"columns": _TABLE_COLUMNS})

    _install_mock(monkeypatch, handler)
    resp = api_client.get(
        "/api/v1/databricks/table-profile",
        params={"catalog": "main", "schema": "insurance", "table": "bad;name"},
        headers={"X-Databricks-Token": "user-pat"},
    )
    assert resp.status_code == 422
    assert "identifier" in resp.json()["detail"].lower()
    assert called["n"] == 0


def test_table_profile_workspace_error_is_503(api_client, dbx_backend, monkeypatch) -> None:
    """A workspace 404 (table not found) surfaces as a 503, never a 500."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "table not found"})

    _install_mock(monkeypatch, handler)
    resp = api_client.get(
        "/api/v1/databricks/table-profile",
        params={"catalog": "main", "schema": "insurance", "table": "missing"},
        headers={"X-Databricks-Token": "user-pat"},
    )
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()
