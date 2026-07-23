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


# --------------------------------------------------------------------------- #
# Per-user Runs on the Databricks backend (all MLflow/Databricks mocked — CI   #
# never contacts a live workspace or tracking store).                          #
# --------------------------------------------------------------------------- #


class _FakeExp:
    experiment_id = "1"
    name = "/Shared/classifyos"


class _FakeRun:
    def __init__(self, tags: dict) -> None:
        self.data = type("D", (), {"tags": tags})()


class _FakeReadClient:
    """Stand-in for ``MlflowClient`` in the read-path unit tests: records the search filter and
    serves a single tagged run for the ownership check."""

    def __init__(self, run_tags: dict | None = None) -> None:
        self.filter_string: str | None = None
        self._run_tags = run_tags or {}

    def search_experiments(self):
        return [_FakeExp()]

    def search_runs(self, experiment_ids, filter_string="", **kw):
        self.filter_string = filter_string
        return []

    def get_run(self, run_id):
        return _FakeRun(self._run_tags)

    def list_artifacts(self, run_id, path):
        return []


def test_list_runs_builds_owner_filter(monkeypatch) -> None:
    """``list_runs`` adds a backticked ``user_email`` tag filter when scoped; none when not."""
    from api import mlflow_read

    fake = _FakeReadClient()
    monkeypatch.setattr(mlflow_read, "_client", lambda: fake)

    mlflow_read.list_runs(user_email="me_sapiens.com")
    assert fake.filter_string == "tags.`classifyos.user_email` = 'me_sapiens.com'"

    mlflow_read.list_runs(user_email=None)
    assert fake.filter_string == ""


def test_load_run_rejects_another_users_run(monkeypatch) -> None:
    """A run owned by a DIFFERENT user is ``RunNotFound`` (no cross-user reload); same owner proceeds."""
    from api import mlflow_read

    monkeypatch.setattr(
        mlflow_read,
        "_client",
        lambda: _FakeReadClient(run_tags={mlflow_read.USER_EMAIL_TAG: "owner_a.com"}),
    )
    with pytest.raises(mlflow_read.RunNotFound):
        mlflow_read.load_run("r1", user_email="someone_else.com")
    # Same owner → allowed through; no snapshot artifact present → None (not an error).
    assert mlflow_read.load_run("r1", user_email="owner_a.com") is None


def test_snapshot_envelope_sets_owner_and_reloadable_tags(monkeypatch) -> None:
    """``snapshot_envelope`` logs the artifact + reloadable tag, and the owner tag only when given."""
    import mlflow.tracking

    from classifyos import mlflow_logging

    calls: dict = {"tags": [], "artifacts": 0}

    class _FakeWriteClient:
        def log_artifact(self, run_id, local_path, artifact_path=None):
            calls["artifacts"] += 1

        def set_tag(self, run_id, key, value):
            calls["tags"].append((key, value))

    monkeypatch.setattr(mlflow.tracking, "MlflowClient", _FakeWriteClient)

    assert mlflow_logging.snapshot_envelope("r1", {"status": "ok"}, user_email="me_sapiens.com") is True
    assert calls["artifacts"] == 1
    assert (mlflow_logging.SNAPSHOT_TAG, mlflow_logging.SNAPSHOT_PATH) in calls["tags"]
    assert (mlflow_logging.USER_EMAIL_TAG, "me_sapiens.com") in calls["tags"]

    # Without an email (the local /run path), the owner tag is NOT set.
    calls["tags"].clear()
    mlflow_logging.snapshot_envelope("r1", {"status": "ok"})
    assert all(k != mlflow_logging.USER_EMAIL_TAG for k, _ in calls["tags"])


def test_databricks_runs_require_pat(api_client, monkeypatch) -> None:
    """Databricks backend: ``/runs`` and ``/runs/{id}`` without the PAT header → 401 (UI prompts)."""
    monkeypatch.setenv("CLASSIFYOS_EXECUTION_BACKEND", "databricks")
    assert api_client.get("/api/v1/runs").status_code == 401
    assert api_client.get("/api/v1/runs/anything").status_code == 401


def test_databricks_runs_expired_pat_is_401(api_client, monkeypatch) -> None:
    """Databricks backend: a PAT that no longer resolves (→ ``unknown_user``) is a 401, not an empty list."""
    monkeypatch.setenv("CLASSIFYOS_EXECUTION_BACKEND", "databricks")
    monkeypatch.setattr("api.routes.runs.get_user_email", lambda pat: "unknown_user")
    resp = api_client.get("/api/v1/runs", headers={"X-Databricks-Token": "dapi-expired"})
    assert resp.status_code == 401


def test_databricks_runs_filtered_by_caller(api_client, monkeypatch) -> None:
    """Databricks backend: the caller's resolved email is forwarded to the list filter + reload check."""
    monkeypatch.setenv("CLASSIFYOS_EXECUTION_BACKEND", "databricks")
    monkeypatch.setattr("api.routes.runs.get_user_email", lambda pat: "sharmil.basa_sapiens.com")

    captured: dict = {}
    monkeypatch.setattr(
        "api.routes.runs.list_runs",
        lambda user_email=None: (captured.__setitem__("list", user_email) or {"tracking_uri": "databricks", "runs": []}),
    )
    resp = api_client.get("/api/v1/runs", headers={"X-Databricks-Token": "dapi-x"})
    assert resp.status_code == 200
    assert captured["list"] == "sharmil.basa_sapiens.com"

    monkeypatch.setattr(
        "api.routes.runs.load_run",
        lambda run_id, user_email=None: (
            captured.__setitem__("load", user_email)
            or {"status": "ok", "schema_version": "1.11", "result": None, "error": None}
        ),
    )
    r2 = api_client.get("/api/v1/runs/r1", headers={"X-Databricks-Token": "dapi-x"})
    assert r2.status_code == 200
    assert captured["load"] == "sharmil.basa_sapiens.com"
