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
