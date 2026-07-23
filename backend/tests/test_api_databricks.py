"""Unity Catalog browser-proxy tests — ``GET /api/v1/databricks/{catalogs,schemas,tables}``.

All Databricks HTTP is MOCKED (the client's ``_build_client`` seam is swapped for an
``httpx.MockTransport``), so CI never contacts a real workspace. The proxies authenticate with the
caller's PAT (``X-Databricks-Token``), which is passed straight through and never stored — the
tests assert that header reaches Unity Catalog. A missing PAT is a 401; an unreachable workspace a
503.
"""

from __future__ import annotations

import json

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
# Authenticated with the SERVICE token (DATABRICKS_TOKEN), NOT the user's PAT: the service identity
# submits the Job and picks the cluster, so the picker reflects where jobs actually run. Only
# clusters a Job can actually be submitted to are surfaced — RUNNING (live) or TERMINATED
# (restartable) — sorted by cluster_name. No user PAT is required.

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


@pytest.fixture
def clusters_env(monkeypatch: pytest.MonkeyPatch):
    """Env for the clusters endpoint: the workspace host + the SERVICE token (not a user PAT)."""
    monkeypatch.setenv("DATABRICKS_HOST", _MOCK_HOST)
    monkeypatch.setenv("DATABRICKS_TOKEN", "svc-token")


def test_list_clusters_filters_and_sorts(api_client, clusters_env, monkeypatch) -> None:
    """Only RUNNING/TERMINATED clusters are returned, sorted case-insensitively by name."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/2.0/clusters/list"
        # The cluster picker authenticates with the SERVICE token, NOT a user PAT.
        assert request.headers["Authorization"] == "Bearer svc-token"
        return httpx.Response(200, json={"clusters": _CLUSTERS})

    _install_mock(monkeypatch, handler)
    # No X-Databricks-Token header needed — this is a service-token operation.
    resp = api_client.get("/api/v1/databricks/clusters")
    assert resp.status_code == 200, resp.text
    clusters = resp.json()["clusters"]

    # TERMINATING / ERROR / UNKNOWN / PENDING are dropped; the two usable ones remain, name-sorted.
    assert clusters == [
        {"cluster_id": "0716-term", "cluster_name": "Alpha-terminated", "state": "TERMINATED"},
        {"cluster_id": "0716-run", "cluster_name": "zeta-running", "state": "RUNNING"},
    ]


def test_list_clusters_empty_when_none_usable(api_client, clusters_env, monkeypatch) -> None:
    """A workspace with no usable clusters returns an empty list (a valid 200, not an error)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"clusters": [
            {"cluster_id": "x", "cluster_name": "x", "state": "TERMINATING"},
        ]})

    _install_mock(monkeypatch, handler)
    resp = api_client.get("/api/v1/databricks/clusters")
    assert resp.status_code == 200, resp.text
    assert resp.json()["clusters"] == []


def test_list_clusters_missing_service_token_is_500(api_client, uc_env, monkeypatch) -> None:
    """With the host set but no DATABRICKS_TOKEN, it's a server-config error (500), before any HTTP.

    ``uc_env`` sets only ``DATABRICKS_HOST``; conftest does not pin a service token, so
    ``_service_token()`` raises ``DatabricksConfigError`` → 500 without contacting the workspace.
    """
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover — must not be hit
        called["n"] += 1
        return httpx.Response(200, json={"clusters": _CLUSTERS})

    _install_mock(monkeypatch, handler)
    resp = api_client.get("/api/v1/databricks/clusters")
    assert resp.status_code == 500
    assert "databricks_token" in resp.json()["detail"].lower()
    assert called["n"] == 0


def test_list_clusters_unavailable_is_503(api_client, clusters_env, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    _install_mock(monkeypatch, handler)
    resp = api_client.get("/api/v1/databricks/clusters")
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
    the one test without rebuilding the shared app. The SQL-warehouse vars are cleared so the
    schema-only tests are deterministic regardless of the developer's real ``.env`` (a machine with
    ``DATABRICKS_HTTP_PATH`` set would otherwise trigger a sample read); the sampling tests re-set
    ``DATABRICKS_SQL_WAREHOUSE_ID`` explicitly.
    """
    monkeypatch.setenv("DATABRICKS_HOST", _MOCK_HOST)
    monkeypatch.setenv("CLASSIFYOS_EXECUTION_BACKEND", "databricks")
    monkeypatch.delenv("DATABRICKS_SQL_WAREHOUSE_ID", raising=False)
    monkeypatch.delenv("DATABRICKS_HTTP_PATH", raising=False)


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


# --------------------------------------------------------------------------- #
# GET /api/v1/databricks/table-profile — SAMPLE the real data (SQL warehouse)   #
# --------------------------------------------------------------------------- #
#
# When a SQL warehouse is configured, table-profile reads a BOUNDED SAMPLE of the table's real rows
# via the SQL Statement Execution API (as the caller's PAT) and runs the SAME profiling a CSV
# /upload does — so the response carries the full Data-Profile blocks. All HTTP is mocked. If the
# sample can't be read it degrades to the schema-only profile (never a 5xx, never a blocked picker).

#: A JSON_ARRAY result manifest matching ``_TABLE_COLUMNS`` (every cell is a STRING, as the API returns).
_SQL_MANIFEST_COLUMNS = [
    {"name": "age", "type_name": "INT", "type_text": "int", "position": 0},
    {"name": "annual_premium", "type_name": "DOUBLE", "type_text": "double", "position": 1},
    {"name": "balance", "type_name": "DECIMAL", "type_text": "decimal(10,2)", "position": 2},
    {"name": "region", "type_name": "STRING", "type_text": "string", "position": 3},
    {"name": "has_agent", "type_name": "BOOLEAN", "type_text": "boolean", "position": 4},
    {"name": "policy_start", "type_name": "TIMESTAMP", "type_text": "timestamp", "position": 5},
    {"name": "dob", "type_name": "DATE", "type_text": "date", "position": 6},
]


def _sql_sample_rows(n: int = 200) -> list[list[str]]:
    """``n`` sample rows as JSON_ARRAY string cells; values repeat so no column trips the id flag."""
    regions = ["north", "south", "east", "west"]
    return [
        [
            str(30 + (i % 25)),                 # age → 25 distinct
            f"{1000 + (i % 40) * 10}.50",       # annual_premium → 40 distinct (numeric)
            f"{200 + (i % 30) * 5}.00",         # balance → 30 distinct (DECIMAL numeric)
            regions[i % 4],                     # region → 4 categories
            "true" if i % 2 == 0 else "false",  # has_agent → 2 values (binary)
            "2019-10-14T00:00:00.000Z",         # policy_start (parses as datetime)
            f"19{60 + (i % 30):02d}-06-01",     # dob → 30 distinct dates
        ]
        for i in range(n)
    ]


def _sql_success_response() -> dict:
    return {
        "statement_id": "01ef-0000",
        "status": {"state": "SUCCEEDED"},
        "manifest": {
            "format": "JSON_ARRAY",
            "schema": {"column_count": 7, "columns": _SQL_MANIFEST_COLUMNS},
            "total_row_count": 200,
            "truncated": False,
        },
        "result": {"chunk_index": 0, "row_offset": 0, "row_count": 200, "data_array": _sql_sample_rows()},
    }


def test_table_profile_reads_sample_when_warehouse_configured(api_client, dbx_backend, monkeypatch) -> None:
    """With a SQL warehouse set, the profile is computed over the table's REAL data (full blocks)."""
    monkeypatch.setenv("DATABRICKS_SQL_WAREHOUSE_ID", "wh-123")
    seen = {"sql": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/2.0/sql/statements":
            seen["sql"] += 1
            assert request.method == "POST"
            # The SAMPLE read runs as the USER's PAT (like the UC browsers), NOT the service token.
            assert request.headers["Authorization"] == "Bearer user-pat"
            payload = json.loads(request.content)
            assert payload["warehouse_id"] == "wh-123"
            assert payload["row_limit"] >= 1  # bounded — a capped sample, never the whole table
            assert "main.insurance.policy_lapse" in payload["statement"]
            return httpx.Response(200, json=_sql_success_response())
        # Otherwise the get-a-table schema call (still made — the authoritative fallback source).
        assert request.url.path == "/api/2.1/unity-catalog/tables/main.insurance.policy_lapse"
        return httpx.Response(200, json={"columns": _TABLE_COLUMNS})

    _install_mock(monkeypatch, handler)
    resp = api_client.get(
        "/api/v1/databricks/table-profile",
        params={"catalog": "main", "schema": "insurance", "table": "policy_lapse"},
        headers={"X-Databricks-Token": "user-pat"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert seen["sql"] == 1  # the SQL sample WAS read
    # Full InspectProfile — the Data-Profile blocks a CSV /upload carries, now over real UC data.
    assert body["n_rows"] == 200
    assert "column_profiles" in body and len(body["column_profiles"]) == 7
    assert body["correlation"] is not None  # ≥2 non-identifier numeric columns
    assert len(body["sample"]) == 5
    # Data-driven column groups (from the sampled VALUES, exactly like /upload) — numeric columns
    # coerced from JSON_ARRAY strings via the manifest types; BOOLEAN reads as binary + categorical.
    assert set(body["numeric_cols"]) == {"age", "annual_premium", "balance"}
    assert body["binary_cols"] == ["has_agent"]
    assert set(body["datetime_cols"]) == {"policy_start", "dob"}
    # Still carries the delta input_source + snapshot server_path (the run reads the Delta table).
    assert body["server_path"] == "db_snapshots/main_insurance_policy_lapse.parquet"
    assert body["input_source"]["type"] == "delta"


def test_table_profile_falls_back_to_schema_when_sample_fails(api_client, dbx_backend, monkeypatch) -> None:
    """A warehouse is configured but the statement doesn't succeed → schema-only profile (no 5xx)."""
    monkeypatch.setenv("DATABRICKS_SQL_WAREHOUSE_ID", "wh-123")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/2.0/sql/statements":
            # Statement did not succeed (e.g. warehouse asleep / timed out → cancelled).
            return httpx.Response(200, json={"statement_id": "x", "status": {"state": "FAILED"}})
        return httpx.Response(200, json={"columns": _TABLE_COLUMNS})

    _install_mock(monkeypatch, handler)
    resp = api_client.get(
        "/api/v1/databricks/table-profile",
        params={"catalog": "main", "schema": "insurance", "table": "policy_lapse"},
        headers={"X-Databricks-Token": "user-pat"},
    )
    # Degraded gracefully to the schema-only shape — picker still works, no fabricated stats, no 5xx.
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "column_profiles" not in body
    assert body["n_rows"] == 0
    assert body["sample"] == []
    assert body["columns"] == [
        "age", "annual_premium", "balance", "region", "has_agent", "policy_start", "dob",
    ]
    assert body["server_path"] == "db_snapshots/main_insurance_policy_lapse.parquet"
    assert body["input_source"]["type"] == "delta"
