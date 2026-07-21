"""Databricks orchestration tests — submit / poll / fetch + persistent job state (§6.6 Step 6).

Everything Databricks is MOCKED: the REST client's ``_build_client`` seam is swapped for an
``httpx.MockTransport`` so no real workspace is contacted, and the job-state store is pointed at a
per-test **sqlite** file (a swap of the Postgres DSN — the SQLAlchemy Core path is identical). This
exercises the whole databricks-backend flow — the env-gated ``POST /run`` submission, status
mapping, results fetch from the (temp) output volume, and restart-survival of an in-flight job —
without any external dependency, exactly as CI requires.

The default LOCAL backend (and its full synchronous ``/run`` envelope) is covered by
``test_api_run.py``; conftest pins ``CLASSIFYOS_EXECUTION_BACKEND=local`` for the base suite, and
these tests flip it to ``databricks`` per-test via monkeypatch.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

import api.databricks as dbx
import api.jobs_store as jobs_store

from .conftest import LAPSE_FEATURES, _run_payload

_MOCK_HOST = "https://mock.databricks.net"


@pytest.fixture
def dbx_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Configure the databricks backend + a temp sqlite jobs store for one test."""
    monkeypatch.setenv("CLASSIFYOS_EXECUTION_BACKEND", "databricks")
    monkeypatch.setenv("DATABRICKS_HOST", _MOCK_HOST)
    monkeypatch.setenv("DATABRICKS_TOKEN", "svc-token")
    monkeypatch.setenv("DATABRICKS_JOB_NOTEBOOK_PATH", "/Repos/classifyos/notebooks/classifyos_job_runner")
    monkeypatch.setenv("DATABRICKS_JOB_CLUSTER_ID", "0716-000000-abcd")
    monkeypatch.setenv(
        "DATABRICKS_JOB_WHEEL_PATH", "/Volumes/main/classifyos/libs/classifyos-1.0.0-py3-none-any.whl"
    )
    dsn = f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}"
    monkeypatch.setenv("CLASSIFYOS_JOBS_DSN", dsn)
    jobs_store.reset_engine()
    jobs_store.init_db()
    yield dsn
    jobs_store.reset_engine()


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
# POST /run (databricks backend) — submit + persist                            #
# --------------------------------------------------------------------------- #


def test_submit_returns_job_and_persists(api_client, dbx_env, monkeypatch) -> None:
    """Databricks submit returns {job_id, run_id}, forwards the user PAT, and persists the job."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/2.1/jobs/runs/submit"
        # Jobs API is authenticated with the SERVICE token, never the user PAT.
        assert request.headers["Authorization"] == "Bearer svc-token"
        body = json.loads(request.content)
        params = body["tasks"][0]["notebook_task"]["base_parameters"]
        seen["user_token"] = params["user_token"]
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
    assert body["run_id"] == "55501"
    assert body["status"] == "PENDING"
    assert body["schema_version"] == "1.11"

    # The user's PAT was forwarded to the Job (for UC data access), the config too.
    assert seen["user_token"] == "user-pat-xyz"
    assert seen["run_config"]["target"] == "will_lapse"

    # Persisted for reconnect/audit — but NOT the PAT.
    row = jobs_store.get_job(body["job_id"])
    assert row is not None
    assert row["databricks_run_id"] == "55501"
    assert row["status"] == "PENDING"
    assert "user-pat-xyz" not in (row["config_json"] or "")


def test_submit_cluster_id_overrides_env(api_client, dbx_env, monkeypatch) -> None:
    """A request-supplied ``cluster_id`` targets that cluster; it is NOT leaked into base_parameters.

    The env var ``DATABRICKS_JOB_CLUSTER_ID`` (set by ``dbx_env``) is the fallback default; a
    non-empty ``cluster_id`` in the /run body overrides it as ``existing_cluster_id``. Because
    ``cluster_id`` is a submission knob (not a RunConfig the notebook rebuilds), it must be excluded
    from the notebook ``base_parameters`` so ``build_config`` on the cluster never sees it.
    """
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
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
    assert final["run_id"] == "777"
    # The terminal status is persisted.
    assert jobs_store.get_job(job_id)["status"] == "COMPLETED"


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
    assert jobs_store.get_job(job_id)["error"] == "OOM"


def test_status_unknown_job_is_404(api_client, dbx_env) -> None:
    assert api_client.get("/api/v1/run/does-not-exist/status").status_code == 404


# --------------------------------------------------------------------------- #
# GET /run/{job_id}/results — fetch the envelope from the output volume         #
# --------------------------------------------------------------------------- #


def test_results_completed_returns_envelope(
    api_client, dbx_env, monkeypatch
) -> None:
    """Once COMPLETED, /results fetches the per-job envelope from the UC output volume."""
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
    # _build_client). Patch it directly so no real network call is made.
    monkeypatch.setenv("DBRICKS_OUTPUT_VOLUME", "/Volumes/aiml_rd/classifyos/output")
    monkeypatch.setattr(
        "api.routes.jobs.fetch_uc_file",
        lambda path: json.dumps(envelope).encode(),
    )
    resp = api_client.get(f"/api/v1/run/{job_id}/results")
    assert resp.status_code == 200, resp.text
    assert resp.json() == envelope


def test_results_not_complete_is_409(api_client, dbx_env, monkeypatch) -> None:
    """Asking for results before the run finishes is a 409 with the current status."""
    job_id = _submit(api_client, monkeypatch, states=[{"life_cycle_state": "RUNNING"}])
    resp = api_client.get(f"/api/v1/run/{job_id}/results")
    assert resp.status_code == 409
    assert resp.json()["status"] == "RUNNING"


def test_results_unknown_job_is_404(api_client, dbx_env) -> None:
    assert api_client.get("/api/v1/run/nope/results").status_code == 404


# --------------------------------------------------------------------------- #
# Persistent job state — survives a FastAPI restart                            #
# --------------------------------------------------------------------------- #


def test_job_state_survives_restart(dbx_env) -> None:
    """A RUNNING job persisted by one engine is still retrievable after the engine is rebuilt.

    ``reset_engine`` drops the cached SQLAlchemy engine; the next ``get_job`` rebuilds it against
    the SAME sqlite DSN — i.e. a new FastAPI process reading the same DB. An in-flight job must
    still be there (the whole point of Part B).
    """
    job_id = jobs_store.create_job(databricks_run_id="999", status="RUNNING", config_json="{}")
    jobs_store.reset_engine()  # simulate a FastAPI restart (fresh engine, same DB)
    row = jobs_store.get_job(job_id)
    assert row is not None
    assert row["status"] == "RUNNING"
    assert row["databricks_run_id"] == "999"
