"""Tests for the MLflow read-path endpoints — ``GET /runs`` + ``GET /runs/{run_id}`` (schema 1.10).

These exercise the Interim-2a persistence read-path end-to-end WITHOUT a database: the MLflow
tracking store is pointed at a per-test temp ``file:`` store (the same trick the schema-1.9 MLflow
test uses), a real ``/run`` is executed with ``mlflow.enabled`` so it logs + snapshots itself, and
then the list/reload endpoints are asserted against it. The Postgres backend store is a
configuration swap of exactly this ``MLFLOW_TRACKING_URI`` (verified live), so the same code path
is covered here without standing up a DB in CI.
"""

from __future__ import annotations

import pytest

from .conftest import LAPSE_FEATURES, _run_payload


@pytest.fixture
def mlflow_store(tmp_path, monkeypatch):
    """Point MLflow at a per-test temp ``file:`` store and return its tracking URI."""
    uri = "file:" + (tmp_path / "mlruns").as_posix()
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    monkeypatch.delenv("MLFLOW_ALLOW_FILE_STORE", raising=False)  # the engine sets this itself
    return uri


def _run_with_mlflow(api_client, experiment: str = "classifyos_runs_test") -> dict:
    """Execute a small binary /run with MLflow logging ON; return the response body."""
    payload = _run_payload(
        "policy_lapse.csv", "will_lapse", LAPSE_FEATURES,
        problem_type="binary", algorithms=["LogisticRegression"],
        mlflow={"enabled": True, "experiment": experiment},
    )
    resp = api_client.post("/api/v1/run", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_list_runs_surfaces_a_logged_run(api_client, mlflow_store) -> None:
    """After an mlflow-logged /run, GET /runs lists it with derived summary fields."""
    body = _run_with_mlflow(api_client)
    run_id = body["result"]["mlflow"]["run_id"]

    listed = api_client.get("/api/v1/runs")
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["schema_version"] == "1.11"
    assert payload["tracking_uri"] == mlflow_store
    rows = {r["run_id"]: r for r in payload["runs"]}
    assert run_id in rows

    row = rows[run_id]
    assert row["target"] == "will_lapse"
    assert row["problem_type"] == "binary"
    assert row["input_file"] == "policy_lapse.csv"
    assert row["algorithms"] == ["LogisticRegression"]
    assert row["models_logged"] == 1
    assert row["best_metric"] == "f1_weighted"
    assert row["best_model"] == "LogisticRegression"
    assert isinstance(row["best_value"], float)
    assert row["status"] == "FINISHED"
    assert row["start_time"]  # ISO string
    # A run produced via /run carries the persisted envelope snapshot → reloadable.
    assert row["reloadable"] is True


def test_reload_run_returns_byte_identical_envelope(api_client, mlflow_store) -> None:
    """GET /runs/{id} returns the exact /run envelope the run was rendered with."""
    original = _run_with_mlflow(api_client)
    run_id = original["result"]["mlflow"]["run_id"]

    reloaded = api_client.get(f"/api/v1/runs/{run_id}")
    assert reloaded.status_code == 200
    body = reloaded.json()
    assert body["status"] == "ok"
    assert body["schema_version"] == "1.11"
    # The reshaped result must match the original run exactly (byte-identical reload).
    assert body["result"] == original["result"]


def test_reload_unknown_run_is_404(api_client, mlflow_store) -> None:
    """An unknown run id is a clean 404, not a 500."""
    # Touch the store first so it exists (empty), then ask for a bogus id.
    _run_with_mlflow(api_client)
    resp = api_client.get("/api/v1/runs/does-not-exist-0000")
    assert resp.status_code == 404


def test_list_runs_empty_store_is_ok(api_client, mlflow_store) -> None:
    """A reachable-but-empty store returns an empty list (not an error)."""
    resp = api_client.get("/api/v1/runs")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["runs"] == []
    assert payload["tracking_uri"] == mlflow_store
