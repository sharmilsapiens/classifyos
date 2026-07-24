"""Off-cluster LLM narration — ``api.narrate`` + ``POST /api/v1/runs/{run_id}/narrate``.

On the Databricks backend a run executes on a cluster that cannot reach Azure OpenAI, so the engine
ships SHAP + a ``narration_context`` side artifact and FastAPI narrates from the stored run. These
tests exercise that off-cluster path with a STUB Azure client (no live endpoint) and the MLflow
read/persist helpers monkeypatched (no live tracking store) — exactly as CI requires.

The in-engine narrator + prompt are covered by ``test_llm_explain.py``; the engine flag + the side
artifact by ``test_narration_offload.py``.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

import classifyos.analysis.llm_explain as llm_explain
from api import narrate as narrate_mod
from api.narrate import _reconstruct_original_row, narrate_envelope


# --------------------------------------------------------------------------- #
# A stub Azure client (any object exposing chat.completions.create)            #
# --------------------------------------------------------------------------- #


class _StubClient:
    def __init__(self, content: str = "This case is well above the typical rate.") -> None:
        self._content = content
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self._content), finish_reason="stop"
                )
            ]
        )


def _stub_narrator(content: str = "This case is well above the typical rate."):
    return llm_explain.AzureNarrator(_StubClient(content), "deploy")


def _use_stub_narrator(monkeypatch, content: str = "This case is well above the typical rate.") -> None:
    """Make ``narrator_from_env()`` return a stub narrator (no creds / no live endpoint needed)."""
    monkeypatch.setattr(llm_explain, "narrator_from_env", lambda **kw: _stub_narrator(content))


def _no_narrator(monkeypatch) -> None:
    """Make ``narrator_from_env()`` return None — the unconfigured-credentials path."""
    monkeypatch.setattr(llm_explain, "narrator_from_env", lambda **kw: None)


# --------------------------------------------------------------------------- #
# Fixtures — a minimal /run envelope + its narration_context side artifact      #
# --------------------------------------------------------------------------- #


def _envelope() -> dict:
    """A minimal /run envelope with a SHAP block whose rows carry NO narrative yet."""
    return {
        "status": "ok",
        "schema_version": "1.11",
        "error": None,
        "result": {
            "run": {
                "target": "will_lapse",
                "problem_type": "binary",
                "features": ["num_late_payments", "region"],
                "class_distribution": {"0": 80, "1": 20},
            },
            "models": [
                {"name": "RandomForest", "status": "ok", "f1_weighted": 0.83, "accuracy": 0.86}
            ],
            "permutation_importance": {
                "RandomForest": [{"feature": "num_late_payments", "importance": 0.3, "rank": 1}]
            },
            "feature_impact": [{"feature": "num_late_payments", "composite_score": 0.5}],
            "explanations": {
                "RandomForest": {
                    "method": "shap.TreeExplainer",
                    "rows": [
                        {
                            "sample_index": 0,
                            "explained_class": "1",
                            "base_value": 0.3,
                            "prediction": 0.62,
                            "contributions": {"num_late_payments": 0.25, "region_West": 0.07},
                            "feature_values": {"num_late_payments": "3", "region_West": "West"},
                            "narrative": None,
                        }
                    ],
                }
            },
        },
    }


def _context() -> dict:
    return {
        "context_mode": "both",
        "dataset_context": "Policy lapse dataset; will_lapse = the policy lapsed.",
        "column_context": {"region": "customer region"},
        "derived_schema": ["- num_late_payments (numeric): min=0, median=1, max=6"],
        "sample_rows": [{"num_late_payments": 3, "region": "West"}],
        "feature_cols": ["num_late_payments", "region"],
    }


# --------------------------------------------------------------------------- #
# _reconstruct_original_row                                                    #
# --------------------------------------------------------------------------- #


def test_reconstruct_original_row_maps_features_to_source_columns() -> None:
    """Numeric passthrough, one-hot → source column (longest prefix), null skipped, empty → None."""
    fc = ["num_late_payments", "region", "age"]
    assert _reconstruct_original_row({"num_late_payments": "3"}, fc) == {"num_late_payments": "3"}
    # one-hot region_West → its source column `region`
    assert _reconstruct_original_row({"region_West": "West"}, fc) == {"region": "West"}
    # longest matching prefix wins: age_band_adult → age_band, not age
    assert _reconstruct_original_row({"age_band_adult": "adult"}, ["age", "age_band"]) == {
        "age_band": "adult"
    }
    # a null value (a derived feature with no raw source) is skipped
    assert _reconstruct_original_row({"a_x_b": None}, fc) is None
    assert _reconstruct_original_row({}, fc) is None


# --------------------------------------------------------------------------- #
# narrate_envelope                                                             #
# --------------------------------------------------------------------------- #


def test_narrate_envelope_attaches_and_does_not_mutate_input(monkeypatch) -> None:
    """With a stub narrator + context, every SHAP row gets a narrative on a DEEP COPY (input intact)."""
    _use_stub_narrator(monkeypatch, content="Because of the late payments.")
    env = _envelope()
    original = copy.deepcopy(env)

    narrated, n = narrate_envelope(env, _context())

    assert n == 1
    assert (
        narrated["result"]["explanations"]["RandomForest"]["rows"][0]["narrative"]
        == "Because of the late payments."
    )
    # the caller's envelope is never mutated (attachment happens on a deep copy)
    assert env == original
    assert env["result"]["explanations"]["RandomForest"]["rows"][0]["narrative"] is None


def test_narrate_envelope_no_creds_returns_unchanged(monkeypatch) -> None:
    """No Azure credentials (narrator_from_env → None) → the envelope is returned unchanged."""
    _no_narrator(monkeypatch)
    env = _envelope()
    narrated, n = narrate_envelope(env, _context())
    assert n == 0
    assert narrated is env  # the very same object, untouched


def test_narrate_envelope_absent_context_returns_unchanged(monkeypatch) -> None:
    """No narration_context side artifact → cannot reach full parity → unchanged (report-only)."""
    _use_stub_narrator(monkeypatch)
    env = _envelope()
    narrated, n = narrate_envelope(env, None)
    assert n == 0 and narrated is env


def test_narrate_envelope_multilabel_unchanged(monkeypatch) -> None:
    """Multilabel is never narrated (mirrors the engine)."""
    _use_stub_narrator(monkeypatch)
    env = _envelope()
    env["result"]["run"]["problem_type"] = "multilabel"
    narrated, n = narrate_envelope(env, _context())
    assert n == 0 and narrated is env


def test_narrate_envelope_no_explanations_unchanged(monkeypatch) -> None:
    """A run without a SHAP block has nothing to narrate."""
    _use_stub_narrator(monkeypatch)
    env = _envelope()
    env["result"]["explanations"] = None
    narrated, n = narrate_envelope(env, _context())
    assert n == 0 and narrated is env


def test_narrate_envelope_swallows_narrator_failure(monkeypatch) -> None:
    """A narrator that raises degrades to the unchanged envelope (never propagates)."""

    class _Boom:
        def __init__(self):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._raise)
            )

        def _raise(self, **kw):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        llm_explain, "narrator_from_env", lambda **kw: llm_explain.AzureNarrator(_Boom(), "d")
    )
    env = _envelope()
    narrated, n = narrate_envelope(env, _context())
    # narrate_rows swallows per-row failures → no narrative attached → unchanged envelope
    assert n == 0 and narrated is env


# --------------------------------------------------------------------------- #
# POST /api/v1/runs/{run_id}/narrate — the route (MLflow helpers monkeypatched) #
# --------------------------------------------------------------------------- #


def test_narrate_route_attaches_and_persists(api_client, monkeypatch) -> None:
    """Happy path: load → narrate → RE-persist the narrated envelope → return it (HTTP 200)."""
    env = _envelope()
    narrated = copy.deepcopy(env)
    narrated["result"]["explanations"]["RandomForest"]["rows"][0]["narrative"] = "note"

    monkeypatch.setattr("api.routes.runs.load_run", lambda run_id, user_email=None: env)
    monkeypatch.setattr("api.routes.runs.load_narration_context", lambda run_id: _context())
    monkeypatch.setattr("api.routes.runs.narrate_envelope", lambda e, c: (narrated, 1))
    persisted: dict = {}
    monkeypatch.setattr(
        "api.routes.runs.snapshot_result",
        lambda run_id, envelope: (persisted.update(run_id=run_id, envelope=envelope) or True),
    )

    resp = api_client.post("/api/v1/runs/RID/narrate")
    assert resp.status_code == 200, resp.text
    assert resp.json() == narrated
    # the narrated envelope was persisted back under the same run id (so a reload is instant)
    assert persisted["run_id"] == "RID"
    assert persisted["envelope"] == narrated


def test_narrate_route_no_narratives_does_not_persist(api_client, monkeypatch) -> None:
    """When nothing is attached (report-only), the run is NOT re-persisted; the envelope is returned."""
    env = _envelope()
    monkeypatch.setattr("api.routes.runs.load_run", lambda run_id, user_email=None: env)
    monkeypatch.setattr("api.routes.runs.load_narration_context", lambda run_id: None)
    monkeypatch.setattr("api.routes.runs.narrate_envelope", lambda e, c: (env, 0))
    calls = {"n": 0}
    monkeypatch.setattr(
        "api.routes.runs.snapshot_result",
        lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1) or True),
    )

    resp = api_client.post("/api/v1/runs/RID/narrate")
    assert resp.status_code == 200
    assert resp.json() == env
    assert calls["n"] == 0  # no persist when nothing changed


def test_narrate_route_unknown_run_is_404(api_client, monkeypatch) -> None:
    """An unknown run id → 404 (the run must exist to narrate)."""
    from api.mlflow_read import RunNotFound

    def _raise(run_id, user_email=None):
        raise RunNotFound(run_id)

    monkeypatch.setattr("api.routes.runs.load_run", _raise)
    assert api_client.post("/api/v1/runs/nope/narrate").status_code == 404


def test_narrate_route_no_snapshot_is_404(api_client, monkeypatch) -> None:
    """A run with no reloadable snapshot → 404 (there is no envelope to narrate)."""
    monkeypatch.setattr("api.routes.runs.load_run", lambda run_id, user_email=None: None)
    assert api_client.post("/api/v1/runs/RID/narrate").status_code == 404


def test_narrate_route_store_unavailable_is_503(api_client, monkeypatch) -> None:
    """An unreachable tracking store → 503, never a 500."""
    from api.mlflow_read import MlflowUnavailable

    def _raise(run_id, user_email=None):
        raise MlflowUnavailable("down")

    monkeypatch.setattr("api.routes.runs.load_run", _raise)
    assert api_client.post("/api/v1/runs/RID/narrate").status_code == 503


def test_narrate_route_databricks_requires_pat(api_client, monkeypatch) -> None:
    """Databricks backend: no X-Databricks-Token → 401 (same per-user scoping as reload)."""
    monkeypatch.setenv("CLASSIFYOS_EXECUTION_BACKEND", "databricks")
    assert api_client.post("/api/v1/runs/RID/narrate").status_code == 401


# --------------------------------------------------------------------------- #
# snapshot_result routes the RE-persist to the right store                     #
# --------------------------------------------------------------------------- #


def test_snapshot_result_routes_tracking_uri_by_backend(monkeypatch) -> None:
    """snapshot_result passes tracking_uri="databricks" on the databricks backend, None locally —
    so the narrate step's re-persist lands in the SAME managed store load_run reloads from (§6.1)."""
    from api import mlflow_read

    captured: dict = {}
    monkeypatch.setattr(
        "classifyos.mlflow_logging.snapshot_envelope",
        lambda run_id, envelope, tracking_uri=None: (
            captured.update(tracking_uri=tracking_uri) or True
        ),
    )

    monkeypatch.setenv("CLASSIFYOS_EXECUTION_BACKEND", "databricks")
    mlflow_read.snapshot_result("r", {"status": "ok"})
    assert captured["tracking_uri"] == "databricks"

    monkeypatch.setenv("CLASSIFYOS_EXECUTION_BACKEND", "local")
    mlflow_read.snapshot_result("r", {"status": "ok"})
    assert captured["tracking_uri"] is None


def test_narrate_module_reexports() -> None:
    """Sanity: the module exposes the two public names the route imports."""
    assert callable(narrate_mod.narrate_envelope)


# --------------------------------------------------------------------------- #
# End-to-end (local file store; ONLY the Azure narrator stubbed): a real /run   #
# writes SHAP + narration_context.json with the engine narrate call GATED OFF   #
# (as on the cluster), then /narrate fills the narratives and a reload shows     #
# them. Proves the whole off-cluster path over a real MLflow store.             #
# --------------------------------------------------------------------------- #


@pytest.fixture
def _mlflow_file_store(tmp_path, monkeypatch):
    """Point MLflow at a per-test temp ``file:`` store (same trick as test_api_runs)."""
    uri = "file:" + (tmp_path / "mlruns").as_posix()
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    monkeypatch.delenv("MLFLOW_ALLOW_FILE_STORE", raising=False)
    return uri


def test_end_to_end_offcluster_narrate_and_reload(api_client, _mlflow_file_store, monkeypatch) -> None:
    """A real run (engine narration GATED OFF, like the cluster) → /narrate → reload shows narratives."""
    from .conftest import LAPSE_FEATURES, _run_payload

    # Simulate the cluster: the engine writes SHAP + narration_context.json but does NOT narrate.
    monkeypatch.setenv("CLASSIFYOS_NARRATE_IN_ENGINE", "false")

    payload = _run_payload(
        "policy_lapse.csv",
        "will_lapse",
        LAPSE_FEATURES,
        problem_type="binary",
        algorithms=["RandomForest"],
        explainability={
            "enabled": True,
            "llm_narratives": True,
            "sample_rows": 2,
            "background_size": 20,
            "context_mode": "both",
            "dataset_context": "Policy lapse; will_lapse = the policy lapsed.",
        },
        mlflow={"enabled": True, "experiment": "classifyos_narrate_e2e"},
    )
    resp = api_client.post("/api/v1/run", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    run_id = body["result"]["mlflow"]["run_id"]

    def _row(env):
        return env["result"]["explanations"]["RandomForest"]["rows"][0]

    # The run shipped SHAP only (engine narration was gated off) — no narrative yet on reload.
    reloaded = api_client.get(f"/api/v1/runs/{run_id}").json()
    assert _row(reloaded).get("narrative") in (None, "")

    # Now narrate off-cluster with a STUB Azure client (no live endpoint).
    _use_stub_narrator(monkeypatch, content="Flagged high lapse risk due to the late payments.")
    narrated = api_client.post(f"/api/v1/runs/{run_id}/narrate")
    assert narrated.status_code == 200, narrated.text
    assert _row(narrated.json())["narrative"] == "Flagged high lapse risk due to the late payments."

    # The narrated envelope was RE-persisted, so a fresh reload shows the narrative instantly.
    reloaded2 = api_client.get(f"/api/v1/runs/{run_id}").json()
    assert _row(reloaded2)["narrative"] == "Flagged high lapse risk due to the late payments."
