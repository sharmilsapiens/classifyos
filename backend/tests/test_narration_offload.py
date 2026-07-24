"""Engine side of moving LLM narration OFF the run and ONTO FastAPI.

On the Databricks backend the run executes on a cluster that cannot reach the Azure OpenAI private
endpoint (403), so the engine must be able to (a) SKIP the in-process narrate call via a flag while
(b) still serializing the whole-run narration context as a side artifact the off-cluster FastAPI
step reads. These tests cover that flag, the context builder, and the ``log_run`` artifact — all
WITHOUT a live Azure/MLflow (a fake mlflow module is injected).

The in-engine narrator itself and its prompt are covered by ``test_llm_explain.py`` (unchanged); the
off-cluster narrate step by ``test_api_narrate.py``.
"""

from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd

from classifyos import mlflow_logging
from classifyos.config import build_config
from classifyos.runner import ModelRunner, _narrate_in_engine


# --------------------------------------------------------------------------- #
# The CLASSIFYOS_NARRATE_IN_ENGINE flag                                        #
# --------------------------------------------------------------------------- #


def test_narrate_in_engine_defaults_true(monkeypatch) -> None:
    """Unset → True, so the LOCAL backend narrates in-process exactly as before."""
    monkeypatch.delenv("CLASSIFYOS_NARRATE_IN_ENGINE", raising=False)
    assert _narrate_in_engine() is True


def test_narrate_in_engine_false_values_disable(monkeypatch) -> None:
    """Only false/0/no (case-insensitive) disable it — the Databricks Job sets 'false'."""
    for value in ("false", "False", "0", "no", "NO"):
        monkeypatch.setenv("CLASSIFYOS_NARRATE_IN_ENGINE", value)
        assert _narrate_in_engine() is False
    for value in ("true", "1", "yes", ""):
        monkeypatch.setenv("CLASSIFYOS_NARRATE_IN_ENGINE", value)
        assert _narrate_in_engine() is True


# --------------------------------------------------------------------------- #
# _build_narration_context — the side-artifact payload                         #
# --------------------------------------------------------------------------- #


def _runner_with_frames(storage) -> ModelRunner:
    """A ModelRunner with just the raw/test frames the context builder reads (no pipeline run)."""
    cfg = build_config(
        "f.csv",
        "will_lapse",
        ["num_late_payments", "region"],
        explainability={
            "enabled": True,
            "llm_narratives": True,
            "context_mode": "both",
            "dataset_context": "policy lapse dataset",
            "column_context": {"region": "customer region"},
        },
    )
    runner = ModelRunner(cfg, storage)
    # a NaN cell proves the JSON-safety step (safe_jsonify → None, so json.dumps never raises)
    runner.raw_df_ = pd.DataFrame(
        {
            "num_late_payments": [0, 3, 1, np.nan],
            "region": ["West", "East", "West", "North"],
            "will_lapse": ["0", "1", "0", "1"],
        }
    )
    runner.test_df_ = runner.raw_df_.iloc[:2].copy()
    return runner, cfg


def test_build_narration_context_carries_the_api_needs(storage) -> None:
    """The context carries exactly the fields the API can't get from the /run envelope, JSON-safe."""
    runner, cfg = _runner_with_frames(storage)
    ctx = runner._build_narration_context(cfg, "binary")

    assert ctx is not None
    assert ctx["context_mode"] == "both"
    assert ctx["dataset_context"] == "policy lapse dataset"
    assert ctx["column_context"] == {"region": "customer region"}
    assert ctx["feature_cols"] == ["num_late_payments", "region"]
    # data-derived facts (mode=both): a per-column schema line + a couple of sample rows
    assert any("num_late_payments" in line for line in ctx["derived_schema"])
    assert any("region" in line for line in ctx["derived_schema"])
    assert isinstance(ctx["sample_rows"], list) and ctx["sample_rows"]
    # JSON-safe (numpy → python, NaN → None) so it survives strict json.dump on the way to MLflow
    json.dumps(ctx)


def test_build_narration_context_given_mode_omits_derived(storage) -> None:
    """context_mode='given' keeps the analyst text but drops the data-derived schema/sample rows."""
    runner, cfg = _runner_with_frames(storage)
    cfg["explainability"]["context_mode"] = "given"
    ctx = runner._build_narration_context(cfg, "binary")
    assert ctx["context_mode"] == "given"
    assert ctx["derived_schema"] == []
    assert ctx["sample_rows"] == []
    # ...but the analyst-supplied context is still carried
    assert ctx["dataset_context"] == "policy lapse dataset"


def test_build_narration_context_multilabel_is_none(storage) -> None:
    """Multilabel is never narrated, so no context is serialized."""
    runner, cfg = _runner_with_frames(storage)
    assert runner._build_narration_context(cfg, "multilabel") is None


# --------------------------------------------------------------------------- #
# log_run attaches the narration context as api/narration_context.json         #
# --------------------------------------------------------------------------- #


class _FakeRunInfo:
    run_id = "run-123"
    experiment_id = "exp-1"


class _FakeRun:
    info = _FakeRunInfo()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeMlflow:
    """Minimal mlflow stand-in that records ``log_artifact(path, artifact_path)`` calls."""

    def __init__(self) -> None:
        self.artifacts: list[tuple[str, str | None]] = []

    def set_experiment(self, experiment):  # noqa: D401 — no-op
        pass

    def start_run(self, run_name=None):
        return _FakeRun()

    def log_params(self, params):
        pass

    def set_tags(self, tags):
        pass

    def log_metrics(self, metrics):
        pass

    def log_artifact(self, path, artifact_path=None):
        self.artifacts.append((os.path.basename(path), artifact_path))

    def get_tracking_uri(self):
        return "file:/tmp/mlruns"


def test_log_run_logs_narration_context_when_given(monkeypatch) -> None:
    """A non-None narration_context is written to api/narration_context.json on the run."""
    fake = _FakeMlflow()
    monkeypatch.setattr(mlflow_logging, "_load_mlflow", lambda: fake)

    out = mlflow_logging.log_run(
        config={"target": "will_lapse", "problem_type": "binary"},
        metrics_records=[],
        models={},  # no models → no flavor log_model calls
        artifact_paths=[],
        experiment="classifyos",
        run_name="test",
        narration_context={"context_mode": "both", "derived_schema": ["- x (numeric)"]},
    )
    assert out is not None and out["run_id"] == "run-123"
    assert ("narration_context.json", "api") in fake.artifacts


def test_log_run_skips_narration_context_when_none(monkeypatch) -> None:
    """Without a narration_context (the default) nothing extra is logged — byte-identical."""
    fake = _FakeMlflow()
    monkeypatch.setattr(mlflow_logging, "_load_mlflow", lambda: fake)

    mlflow_logging.log_run(
        config={"target": "y"},
        metrics_records=[],
        models={},
        artifact_paths=[],
        experiment="classifyos",
        run_name="test",
    )
    assert all(name != "narration_context.json" for name, _ in fake.artifacts)
