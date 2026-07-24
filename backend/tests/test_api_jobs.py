"""Databricks orchestration tests — submit / poll / fetch (§6.6 Step 6, stateless).

Everything Databricks is MOCKED: the REST client's ``_build_client`` seam is swapped for an
``httpx.MockTransport`` so no real workspace is contacted. This exercises the whole
databricks-backend flow — the env-gated ``POST /run`` submission, status mapping, and results
fetch from the (temp) output volume — without any external dependency, exactly as CI requires.

The design is **stateless**: there is no local job store. The Databricks ``run_id`` returned by the
submit IS the ``job_id`` the client polls with, so ``/run/{job_id}/status`` and ``/results`` poll
Databricks directly on every request.

The default LOCAL backend (and its full synchronous ``/run`` envelope) is covered by
``test_api_run.py``; conftest pins ``CLASSIFYOS_EXECUTION_BACKEND=local`` for the base suite, and
these tests flip it to ``databricks`` per-test via monkeypatch.
"""

from __future__ import annotations

import json

import httpx
import pytest

import api.databricks as dbx

from .conftest import LAPSE_FEATURES, _run_payload

_MOCK_HOST = "https://mock.databricks.net"


@pytest.fixture
def dbx_env(monkeypatch: pytest.MonkeyPatch):
    """Configure the databricks execution backend for one test (stateless — no job store)."""
    monkeypatch.setenv("CLASSIFYOS_EXECUTION_BACKEND", "databricks")
    monkeypatch.setenv("DATABRICKS_HOST", _MOCK_HOST)
    monkeypatch.setenv("DATABRICKS_TOKEN", "svc-token")
    monkeypatch.setenv("DATABRICKS_JOB_NOTEBOOK_PATH", "/Repos/classifyos/notebooks/classifyos_job_runner")
    monkeypatch.setenv("DATABRICKS_JOB_CLUSTER_ID", "0716-000000-abcd")
    monkeypatch.setenv(
        "DATABRICKS_JOB_WHEEL_PATH", "/Volumes/main/classifyos/libs/classifyos-1.0.0-py3-none-any.whl"
    )


def _install_mock(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Swap the client factory for one backed by an ``httpx.MockTransport``.

    Preserves the real ``Authorization: Bearer <token>`` header so a test can assert the SERVICE
    token is used for the Jobs API and the USER PAT for Unity Catalog.
    """

    def _build(token: str) -> httpx.Client:
        return httpx.Client(
            base_url=_MOCK_HOST,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(dbx, "_build_client", _build)


def _payload() -> dict:
    return _run_payload(
        "policy_lapse.csv", "will_lapse", LAPSE_FEATURES, algorithms=["LogisticRegression"]
    )


# --------------------------------------------------------------------------- #
# POST /run (databricks backend) — submit + return the run_id as the job_id     #
# --------------------------------------------------------------------------- #


def test_submit_returns_job_and_forwards_pat(api_client, dbx_env, monkeypatch) -> None:
    """Databricks submit returns {job_id == run_id, status} and forwards the user PAT + config."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        # FastAPI resolves the user's email (SCIM, with their PAT) before submitting, to namespace
        # the Job's output. The SCIM call uses the USER PAT, never the service token.
        if request.url.path == "/api/2.0/preview/scim/v2/Me":
            assert request.headers["Authorization"] == "Bearer user-pat-xyz"
            return httpx.Response(200, json={"userName": "user@example.com"})
        assert request.url.path == "/api/2.1/jobs/runs/submit"
        # Jobs API is authenticated with the SERVICE token, never the user PAT.
        assert request.headers["Authorization"] == "Bearer svc-token"
        body = json.loads(request.content)
        params = body["tasks"][0]["notebook_task"]["base_parameters"]
        seen["user_token"] = params["user_token"]
        seen["user_email"] = params["user_email"]
        seen["run_config"] = json.loads(params["run_config"])
        assert body["tasks"][0]["libraries"] == [
            {"whl": "/Volumes/main/classifyos/libs/classifyos-1.0.0-py3-none-any.whl"}
        ]
        return httpx.Response(200, json={"run_id": 55501})

    _install_mock(monkeypatch, handler)
    resp = api_client.post(
        "/api/v1/run", json=_payload(), headers={"X-Databricks-Token": "user-pat-xyz"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Stateless: the job_id IS the Databricks run_id (both present for contract compatibility).
    assert body["job_id"] == "55501"
    assert body["run_id"] == "55501"
    assert body["status"] == "PENDING"
    assert body["schema_version"] == "1.11"

    # The user's PAT was forwarded to the Job (for UC data access), the config too.
    assert seen["user_token"] == "user-pat-xyz"
    assert seen["run_config"]["target"] == "will_lapse"
    # The PAT is never echoed back into the submitted run config.
    assert "user-pat-xyz" not in json.dumps(seen["run_config"])
    # The resolved user email is forwarded, sanitized for use as an output folder segment.
    assert seen["user_email"] == "user_example.com"


def test_submit_cluster_id_overrides_env(api_client, dbx_env, monkeypatch) -> None:
    """A request-supplied ``cluster_id`` targets that cluster; it is NOT leaked into base_parameters.

    The env var ``DATABRICKS_JOB_CLUSTER_ID`` (set by ``dbx_env``) is the fallback default; a
    non-empty ``cluster_id`` in the /run body overrides it as ``existing_cluster_id``. Because
    ``cluster_id`` is a submission knob (not a RunConfig the notebook rebuilds), it must be excluded
    from the notebook ``base_parameters`` so ``build_config`` on the cluster never sees it.
    """
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/2.0/preview/scim/v2/Me":
            return httpx.Response(200, json={"userName": "user@example.com"})
        body = json.loads(request.content)
        task = body["tasks"][0]
        seen["cluster"] = task["existing_cluster_id"]
        seen["run_config"] = json.loads(task["notebook_task"]["base_parameters"]["run_config"])
        return httpx.Response(200, json={"run_id": 77})

    _install_mock(monkeypatch, handler)
    payload = _payload()
    payload["cluster_id"] = "0716-picked-9999"
    resp = api_client.post(
        "/api/v1/run", json=payload, headers={"X-Databricks-Token": "user-pat"}
    )
    assert resp.status_code == 200, resp.text
    assert seen["cluster"] == "0716-picked-9999"  # request override, not the env default
    assert "cluster_id" not in seen["run_config"]  # never reaches the notebook's build_config


def test_submit_falls_back_to_env_cluster(api_client, dbx_env, monkeypatch) -> None:
    """With no ``cluster_id`` in the request, the ``DATABRICKS_JOB_CLUSTER_ID`` env var is used."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/2.0/preview/scim/v2/Me":
            return httpx.Response(200, json={"userName": "user@example.com"})
        body = json.loads(request.content)
        seen["cluster"] = body["tasks"][0]["existing_cluster_id"]
        return httpx.Response(200, json={"run_id": 78})

    _install_mock(monkeypatch, handler)
    resp = api_client.post(
        "/api/v1/run", json=_payload(), headers={"X-Databricks-Token": "user-pat"}
    )
    assert resp.status_code == 200, resp.text
    assert seen["cluster"] == "0716-000000-abcd"  # the dbx_env env-var default


def test_submit_missing_pat_is_401(api_client, dbx_env, monkeypatch) -> None:
    """A databricks-backend /run with no X-Databricks-Token is a clean 401 (never submits)."""
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover — must not be hit
        called["n"] += 1
        return httpx.Response(200, json={"run_id": 1})

    _install_mock(monkeypatch, handler)
    resp = api_client.post("/api/v1/run", json=_payload())
    assert resp.status_code == 401
    assert called["n"] == 0  # never reached the submit call


def test_submit_bad_config_is_422(api_client, dbx_env) -> None:
    """Config validation runs in BOTH backends: a bad config is 422 before any Databricks call."""
    bad = _payload()
    bad["target"] = "will_lapse"
    bad["feature_cols"] = ["will_lapse"]  # target must not be a feature → build_config raises
    resp = api_client.post("/api/v1/run", json=bad, headers={"X-Databricks-Token": "p"})
    assert resp.status_code == 422


def test_submit_workspace_unavailable_is_503(api_client, dbx_env, monkeypatch) -> None:
    """A workspace that can't be reached at submit time is a 503, not a 500."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    _install_mock(monkeypatch, handler)
    resp = api_client.post(
        "/api/v1/run", json=_payload(), headers={"X-Databricks-Token": "p"}
    )
    assert resp.status_code == 503


# --------------------------------------------------------------------------- #
# GET /run/{job_id}/status — poll + map RunState                               #
# --------------------------------------------------------------------------- #


def _submit(api_client, monkeypatch, states: list[dict]) -> str:
    """Submit a job whose subsequent runs/get polls walk through ``states``; return the job_id."""
    calls = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/2.0/preview/scim/v2/Me":
            return httpx.Response(200, json={"userName": "user@example.com"})
        if request.url.path.endswith("/jobs/runs/submit"):
            return httpx.Response(200, json={"run_id": 777})
        if request.url.path.endswith("/jobs/runs/get"):
            assert request.url.params["run_id"] == "777"
            state = states[min(calls["i"], len(states) - 1)]
            calls["i"] += 1
            return httpx.Response(200, json={"state": state})
        return httpx.Response(404)  # pragma: no cover

    _install_mock(monkeypatch, handler)
    resp = api_client.post(
        "/api/v1/run", json=_payload(), headers={"X-Databricks-Token": "user-pat"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["job_id"]


def test_status_progression_pending_running_completed(api_client, dbx_env, monkeypatch) -> None:
    """Status maps the RunState life-cycle: PENDING → RUNNING → COMPLETED."""
    job_id = _submit(
        api_client,
        monkeypatch,
        states=[
            {"life_cycle_state": "PENDING"},
            {"life_cycle_state": "RUNNING"},
            {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS", "state_message": "done"},
        ],
    )
    assert api_client.get(f"/api/v1/run/{job_id}/status").json()["status"] == "PENDING"
    assert api_client.get(f"/api/v1/run/{job_id}/status").json()["status"] == "RUNNING"
    final = api_client.get(f"/api/v1/run/{job_id}/status").json()
    assert final["status"] == "COMPLETED"
    # run_id echoes the job_id (they are the same value in the stateless design).
    assert final["run_id"] == "777"
    assert final["job_id"] == "777"


def test_status_failed_path(api_client, dbx_env, monkeypatch) -> None:
    """A TERMINATED run with a non-success result_state maps to FAILED with the message."""
    job_id = _submit(
        api_client,
        monkeypatch,
        states=[{"life_cycle_state": "TERMINATED", "result_state": "FAILED", "state_message": "OOM"}],
    )
    body = api_client.get(f"/api/v1/run/{job_id}/status").json()
    assert body["status"] == "FAILED"
    assert body["message"] == "OOM"


def test_status_unknown_job_polls_databricks(api_client, dbx_env, monkeypatch) -> None:
    """No local store: an unrecognised job_id is polled straight to Databricks. A run id the
    workspace rejects (HTTP 400 RESOURCE_DOES_NOT_EXIST) surfaces as a 503 — never a fabricated
    404 from a cache."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error_code": "RESOURCE_DOES_NOT_EXIST"})

    _install_mock(monkeypatch, handler)
    assert api_client.get("/api/v1/run/does-not-exist/status").status_code == 503


# --------------------------------------------------------------------------- #
# GET /run/{job_id}/results — fetch the envelope from the output volume         #
# --------------------------------------------------------------------------- #


def test_results_completed_returns_envelope(
    api_client, dbx_env, monkeypatch
) -> None:
    """Once COMPLETED, /results fetches the per-USER, per-job envelope from the UC output volume."""
    job_id = _submit(
        api_client,
        monkeypatch,
        states=[{"life_cycle_state": "TERMINATED", "result_state": "SUCCESS"}],
    )
    envelope = {
        "status": "ok",
        "schema_version": "1.11",
        "result": {"run": {"target": "will_lapse"}},
        "error": None,
    }
    # In Databricks mode the endpoint calls fetch_uc_file (a bare httpx.get that bypasses
    # _build_client). Patch it directly so no real network call is made, and capture the path so we
    # can assert it carries the {user_email}/{job_id} prefix the Job wrote under.
    monkeypatch.setenv("DBRICKS_OUTPUT_VOLUME", "/Volumes/aiml_rd/classifyos/output")
    seen: dict[str, str] = {}

    def _fake_fetch(path: str) -> bytes:
        seen["path"] = path
        return json.dumps(envelope).encode()

    monkeypatch.setattr("api.routes.jobs.fetch_uc_file", _fake_fetch)
    # The PAT lets /results resolve the same email (via the mocked SCIM in _submit's handler) the
    # Job namespaced its output under, so the fetch path matches what the notebook wrote.
    resp = api_client.get(
        f"/api/v1/run/{job_id}/results", headers={"X-Databricks-Token": "user-pat"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == envelope
    assert (
        seen["path"]
        == "/Volumes/aiml_rd/classifyos/output/user_example.com/777/api/run_response.json"
    )


def test_results_not_complete_is_409(api_client, dbx_env, monkeypatch) -> None:
    """Asking for results before the run finishes is a 409 with the current status."""
    job_id = _submit(api_client, monkeypatch, states=[{"life_cycle_state": "RUNNING"}])
    resp = api_client.get(f"/api/v1/run/{job_id}/results")
    assert resp.status_code == 409
    assert resp.json()["status"] == "RUNNING"


def test_results_unknown_job_polls_databricks(api_client, dbx_env, monkeypatch) -> None:
    """Same as /status: an unknown job_id → a Databricks poll → 503 (no store, no fabricated 404)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error_code": "RESOURCE_DOES_NOT_EXIST"})

    _install_mock(monkeypatch, handler)
    assert api_client.get("/api/v1/run/nope/results").status_code == 503


# --------------------------------------------------------------------------- #
# LLM narratives on Databricks — sync the Azure creds to a secret scope and     #
# forward ONLY the scope name (the key never rides in Job params). All mocked.  #
# --------------------------------------------------------------------------- #

_AZURE_ENV = {
    "AZURE_OPEN_AI_ENDPOINT": "https://x.openai.azure.com/",
    "AZURE_OPEN_AI_API_KEY": "secret-key-123",
    "AZURE_OPEN_AI_API_VERSION": "2024-08-01-preview",
    "AZURE_OPEN_AI_DEPLOYMENT_NAME": "gpt-5-mini",
    "AZURE_OPEN_AI_MODEL": "gpt-5-mini",
}


def _set_azure_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _AZURE_ENV.items():
        monkeypatch.setenv(key, value)


def _clear_azure_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _AZURE_ENV:
        monkeypatch.delenv(key, raising=False)


def test_sync_llm_secrets_pushes_creds_and_grants_read(dbx_env, monkeypatch) -> None:
    """sync_llm_secrets creates the scope (users-manage), puts each cred (key == env-var name), and
    grants the cluster principal READ — returning the scope name. The values go to the Secrets API."""
    _set_azure_env(monkeypatch)
    calls: dict = {"create": [], "put": [], "acl": []}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        if request.url.path == "/api/2.0/secrets/scopes/create":
            calls["create"].append(body)
        elif request.url.path == "/api/2.0/secrets/put":
            calls["put"].append(body)
        elif request.url.path == "/api/2.0/secrets/acls/put":
            calls["acl"].append(body)
        else:  # pragma: no cover
            return httpx.Response(404)
        return httpx.Response(200, json={})

    _install_mock(monkeypatch, handler)
    scope = dbx.sync_llm_secrets()

    assert scope == "classifyos-llm"
    assert calls["create"][0] == {"scope": "classifyos-llm", "initial_manage_principal": "users"}
    put = {c["key"]: c["string_value"] for c in calls["put"]}
    assert put["AZURE_OPEN_AI_API_KEY"] == "secret-key-123"
    assert put["AZURE_OPEN_AI_ENDPOINT"] == "https://x.openai.azure.com/"
    assert set(put) == set(_AZURE_ENV)  # all 5 (4 required + optional MODEL)
    assert calls["acl"][0] == {
        "scope": "classifyos-llm",
        "principal": "AIML_RD",
        "permission": "READ",
    }


def test_sync_llm_secrets_absent_creds_returns_none(dbx_env, monkeypatch) -> None:
    """No AZURE_OPEN_AI_* on this host → sync is a no-op returning None (zero REST calls)."""
    _clear_azure_env(monkeypatch)
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover — must not be hit
        called["n"] += 1
        return httpx.Response(200, json={})

    _install_mock(monkeypatch, handler)
    assert dbx.sync_llm_secrets() is None
    assert called["n"] == 0


def test_sync_llm_secrets_tolerates_existing_scope(dbx_env, monkeypatch) -> None:
    """A scope that already exists (create → 400 RESOURCE_ALREADY_EXISTS) is treated as success."""
    _set_azure_env(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/2.0/secrets/scopes/create":
            return httpx.Response(400, json={"error_code": "RESOURCE_ALREADY_EXISTS", "message": "x"})
        return httpx.Response(200, json={})

    _install_mock(monkeypatch, handler)
    assert dbx.sync_llm_secrets() == "classifyos-llm"


def test_submit_forwards_secret_scope_when_narratives_on(api_client, dbx_env, monkeypatch) -> None:
    """With narratives requested + creds present, the creds are synced and only the scope NAME rides
    in base_parameters — the Azure key never appears in the Job parameters."""
    _set_azure_env(monkeypatch)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/2.0/preview/scim/v2/Me":
            return httpx.Response(200, json={"userName": "user@example.com"})
        if request.url.path.startswith("/api/2.0/secrets/"):
            return httpx.Response(200, json={})
        if request.url.path == "/api/2.1/jobs/runs/submit":
            seen["params"] = json.loads(request.content)["tasks"][0]["notebook_task"]["base_parameters"]
            return httpx.Response(200, json={"run_id": 900})
        return httpx.Response(404)  # pragma: no cover

    _install_mock(monkeypatch, handler)
    payload = _run_payload(
        "policy_lapse.csv", "will_lapse", LAPSE_FEATURES, algorithms=["LogisticRegression"],
        explainability={"enabled": True, "llm_narratives": True, "sample_rows": 2, "background_size": 20},
    )
    resp = api_client.post("/api/v1/run", json=payload, headers={"X-Databricks-Token": "user-pat"})
    assert resp.status_code == 200, resp.text
    assert seen["params"]["azure_secret_scope"] == "classifyos-llm"
    assert "secret-key-123" not in json.dumps(seen["params"])  # the key is NOT in Job params


def test_submit_no_secret_scope_when_narratives_off(api_client, dbx_env, monkeypatch) -> None:
    """Narratives OFF → the scope param is empty and the Secrets API is never touched."""
    _set_azure_env(monkeypatch)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/2.0/preview/scim/v2/Me":
            return httpx.Response(200, json={"userName": "user@example.com"})
        if request.url.path == "/api/2.1/jobs/runs/submit":
            seen["params"] = json.loads(request.content)["tasks"][0]["notebook_task"]["base_parameters"]
            return httpx.Response(200, json={"run_id": 901})
        return httpx.Response(404)  # secrets endpoints must NOT be hit  # pragma: no cover

    _install_mock(monkeypatch, handler)
    resp = api_client.post(
        "/api/v1/run", json=_payload(), headers={"X-Databricks-Token": "user-pat"}
    )
    assert resp.status_code == 200, resp.text
    assert seen["params"]["azure_secret_scope"] == ""


def test_submit_no_secret_scope_when_creds_absent(api_client, dbx_env, monkeypatch) -> None:
    """Narratives ON but this host has no Azure creds → sync returns None → empty scope (SHAP only)."""
    _clear_azure_env(monkeypatch)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/2.0/preview/scim/v2/Me":
            return httpx.Response(200, json={"userName": "user@example.com"})
        if request.url.path == "/api/2.1/jobs/runs/submit":
            seen["params"] = json.loads(request.content)["tasks"][0]["notebook_task"]["base_parameters"]
            return httpx.Response(200, json={"run_id": 902})
        return httpx.Response(404)  # secrets endpoints must NOT be hit (no creds → no sync)  # pragma: no cover

    _install_mock(monkeypatch, handler)
    payload = _run_payload(
        "policy_lapse.csv", "will_lapse", LAPSE_FEATURES, algorithms=["LogisticRegression"],
        explainability={"enabled": True, "llm_narratives": True, "sample_rows": 2, "background_size": 20},
    )
    resp = api_client.post("/api/v1/run", json=payload, headers={"X-Databricks-Token": "user-pat"})
    assert resp.status_code == 200, resp.text
    assert seen["params"]["azure_secret_scope"] == ""
