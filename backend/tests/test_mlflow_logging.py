"""Tests for the opt-in MLflow logging + model-persistence layer (Databricks integration Phase A).

Two layers are covered:

* **Pure helpers** (``_flatten_params`` / ``_headline_metrics`` / ``_maybe_allow_file_store`` /
  the report-only ``log_run`` degradation) — fast, no training, no MLflow store.
* **A real end-to-end run** — ``ModelRunner`` on the policy-lapse sample with ``mlflow.enabled``
  on and ``MLFLOW_TRACKING_URI`` pointed at a temp file store, asserting the run appears in
  MLflow with params, per-model metrics, the artifact files, and a **loadable** saved model per
  algorithm across all three flavors (sklearn / xgboost / lightgbm). It also confirms an
  ``mlflow``-OFF run logs nothing (``mlflow_run_`` stays ``None``).
"""

from __future__ import annotations

import math
import re
from types import SimpleNamespace

import pandas as pd
import pytest

from classifyos import mlflow_logging
from classifyos.config import build_config
from classifyos.runner import ModelRunner

LAPSE_TARGET = "will_lapse"
# A small feature subset keeps the (calibrated) 3-algorithm run cheap while staying realistic.
LAPSE_FEATURES = [
    "age",
    "annual_premium",
    "num_late_payments",
    "policy_tenure_years",
    "claims_count",
]


# --------------------------------------------------------------------------- #
# config validation (mirrors explainability.enabled discipline)               #
# --------------------------------------------------------------------------- #


def test_build_config_accepts_mlflow_block() -> None:
    cfg = build_config(
        "f.csv", "t", ["a"], mlflow={"enabled": True, "experiment": "exp", "run_name": "r"}
    )
    assert cfg["mlflow"] == {"enabled": True, "experiment": "exp", "run_name": "r"}


def test_build_config_defaults_mlflow_off() -> None:
    cfg = build_config("f.csv", "t", ["a"])
    assert cfg["mlflow"]["enabled"] is False
    assert cfg["mlflow"]["experiment"] == "classifyos"


@pytest.mark.parametrize(
    "bad",
    [
        {"enabled": "yes"},   # not a bool
        {"experiment": ""},   # empty string
        {"experiment": 3},    # not a string
        {"run_name": 5},      # not a string/None
    ],
)
def test_build_config_rejects_bad_mlflow(bad: dict) -> None:
    with pytest.raises(ValueError):
        build_config("f.csv", "t", ["a"], mlflow=bad)


# --------------------------------------------------------------------------- #
# pure helpers                                                                #
# --------------------------------------------------------------------------- #


def test_flatten_params_nested_and_types() -> None:
    flat = mlflow_logging._flatten_params(
        {"a": 1, "b": {"c": 2, "d": True}, "e": [1, 2], "f": None, "g": {}}
    )
    assert flat["a"] == "1"
    assert flat["b.c"] == "2"
    assert flat["b.d"] == "True"
    assert flat["e"] == "[1, 2]"
    assert flat["f"] == "None"
    assert flat["g"] == "{}"  # empty dict is not dropped


def test_flatten_params_sanitizes_bad_keys_and_truncates() -> None:
    # A JSON-flattened column name (illegal as an MLflow param key) is sanitized, not left raw.
    flat = mlflow_logging._flatten_params(
        {"explainability": {"column_context": {"covers[0].amt": "x"}, "dataset_context": "y" * 999}}
    )
    key = "explainability.column_context.covers_0_.amt"
    assert key in flat
    assert len(flat["explainability.dataset_context"]) <= mlflow_logging._PARAM_VALUE_MAX


def test_headline_metrics_skips_failed_none_and_nonfinite() -> None:
    records = [
        {"model": "LR", "status": "ok", "f1_weighted": 0.9, "accuracy": None, "roc_auc": math.nan},
        {"model": "Bad", "status": "failed", "f1_weighted": 0.5},  # failed → excluded
    ]
    metrics = mlflow_logging._headline_metrics(records)
    assert metrics == {"LR.f1_weighted": 0.9}  # None + NaN dropped; failed row excluded


def test_maybe_allow_file_store_sets_optout_for_file_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    monkeypatch.delenv("MLFLOW_ALLOW_FILE_STORE", raising=False)
    mlflow_logging._maybe_allow_file_store()
    import os

    assert os.environ.get("MLFLOW_ALLOW_FILE_STORE") == "true"


def test_maybe_allow_file_store_leaves_db_uri_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "postgresql://u@h/db")
    monkeypatch.delenv("MLFLOW_ALLOW_FILE_STORE", raising=False)
    mlflow_logging._maybe_allow_file_store()
    import os

    assert os.environ.get("MLFLOW_ALLOW_FILE_STORE") is None


def test_log_run_returns_none_when_mlflow_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    # Report-only: if mlflow can't be imported, log_run degrades to None (never raises).
    monkeypatch.setattr(mlflow_logging, "_load_mlflow", lambda: None)
    out = mlflow_logging.log_run(
        config={"target": "t"},
        metrics_records=[],
        models={},
        artifact_paths=[],
        experiment="classifyos",
        run_name=None,
    )
    assert out is None


# --------------------------------------------------------------------------- #
# default run name — "<target> · <YYYY-MM-DD HH:MM>", reusing the run-profile   #
# timestamp; an explicit mlflow.run_name still wins                            #
# --------------------------------------------------------------------------- #


def _capture_forwarded_run_name(storage, monkeypatch: pytest.MonkeyPatch, cfg: dict, *,
                                timestamp: str | None = "2026-07-08T14:30:59.123456+00:00") -> str | None:
    """Call ``ModelRunner._log_to_mlflow`` with ``log_run`` stubbed to capture ``run_name``.

    Avoids a full (expensive) training run: we construct the runner, seed only the run-profile
    timestamp the default name reuses, and stub ``log_run`` (imported lazily inside the method) to
    record the ``run_name`` the runner forwards.
    """
    captured: dict = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return {"run_id": "r", "experiment_id": "0", "tracking_uri": "file:x", "models": {}}

    monkeypatch.setattr(mlflow_logging, "log_run", _capture)
    runner = ModelRunner(cfg, storage)
    runner.run_profile_ = {"timestamp": timestamp} if timestamp is not None else None
    runner._log_to_mlflow(cfg)
    return captured.get("run_name")


def test_default_run_name_uses_target_and_profile_timestamp(storage) -> None:
    """No config run_name → ``"<target> · <YYYY-MM-DD HH:MM>"`` from the run-profile timestamp."""
    cfg = build_config("policy_lapse.csv", "will_lapse", ["age"], mlflow={"enabled": True})
    runner = ModelRunner(cfg, storage)
    runner.run_profile_ = {"timestamp": "2026-07-08T14:30:59.123456+00:00"}
    # minute precision (seconds/micros dropped); UTC as stored on the profile.
    assert runner._default_mlflow_run_name(cfg) == "will_lapse · 2026-07-08 14:30"


def test_default_run_name_falls_back_when_no_profile_timestamp(storage) -> None:
    """Missing/absent run profile → still a well-formed ``"<target> · <date time>"`` (no crash)."""
    cfg = build_config("policy_lapse.csv", "will_lapse", ["age"], mlflow={"enabled": True})
    runner = ModelRunner(cfg, storage)  # run_profile_ is None (nothing computed yet)
    name = runner._default_mlflow_run_name(cfg)
    assert re.fullmatch(r"will_lapse · \d{4}-\d{2}-\d{2} \d{2}:\d{2}", name)


def test_log_to_mlflow_defaults_run_name_when_unset(storage, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the config supplies no run_name, the runner forwards the meaningful default."""
    cfg = build_config("policy_lapse.csv", "will_lapse", ["age"], mlflow={"enabled": True})
    assert _capture_forwarded_run_name(storage, monkeypatch, cfg) == "will_lapse · 2026-07-08 14:30"


def test_log_to_mlflow_keeps_explicit_run_name(storage, monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit ``mlflow.run_name`` wins — the default is NOT applied over it."""
    cfg = build_config(
        "policy_lapse.csv", "will_lapse", ["age"],
        mlflow={"enabled": True, "run_name": "quarterly-refresh"},
    )
    assert _capture_forwarded_run_name(storage, monkeypatch, cfg) == "quarterly-refresh"


# --------------------------------------------------------------------------- #
# end-to-end: a real run logged to a temp MLflow file store                   #
# --------------------------------------------------------------------------- #


@pytest.fixture()
def mlflow_tracking_dir(tmp_path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Point MLflow at a throwaway per-test file store and return its tracking URI."""
    uri = "file:" + (tmp_path / "mlruns").as_posix()
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    monkeypatch.delenv("MLFLOW_ALLOW_FILE_STORE", raising=False)  # the layer sets this itself
    return uri


def _run_with_mlflow(storage, experiment: str, algorithms: list[str]):
    cfg = build_config(
        "policy_lapse.csv",
        LAPSE_TARGET,
        LAPSE_FEATURES,
        problem_type="binary",
        class_balance="none",
        algorithms=algorithms,
        interaction_features={"max_auto_pairs": 0},  # keep it fast
        mlflow={"enabled": True, "experiment": experiment, "run_name": "pytest-run"},
    )
    return ModelRunner(cfg, storage).run()


def test_run_logs_to_mlflow_with_loadable_models(storage, mlflow_tracking_dir: str) -> None:
    """A real run with ``mlflow.enabled`` logs params/metrics/artifacts + one loadable model per flavor.

    LogisticRegression exercises ``mlflow.sklearn`` (unwrapped from the calibration wrapper, which
    is on by default), XGBoost ``mlflow.xgboost`` and LightGBM ``mlflow.lightgbm`` — all three
    flavors, each unwrapped to its base estimator the way ``feature_importance()`` does.
    """
    import mlflow
    import mlflow.lightgbm
    import mlflow.sklearn
    import mlflow.xgboost

    algorithms = ["LogisticRegression", "XGBoost", "LightGBM"]
    runner = _run_with_mlflow(storage, "classifyos_pytest", algorithms)

    # The runner recorded the MLflow pointer.
    info = runner.mlflow_run_
    assert isinstance(info, dict)
    assert info["run_id"] and info["experiment_id"]
    assert info["tracking_uri"].endswith("mlruns")
    assert set(info["models"]) == set(algorithms)  # a model URI per successful algorithm

    # The run is queryable in the store: params + per-model metrics + artifacts.
    client = mlflow.tracking.MlflowClient(tracking_uri=mlflow_tracking_dir)
    run = client.get_run(info["run_id"])
    assert run.data.params["target"] == LAPSE_TARGET
    assert run.data.params["problem_type"] == "binary"
    # headline metric present per model, namespaced <model>.<metric>
    assert "LogisticRegression.f1_weighted" in run.data.metrics
    assert "XGBoost.accuracy" in run.data.metrics
    # the engine artifacts were attached under the "classifyos" folder
    artifact_names = {a.path.split("/")[-1] for a in client.list_artifacts(info["run_id"], "classifyos")}
    assert {"classification_results.csv", "metrics_comparison.csv", "run_profile.json"} <= artifact_names

    # every logged model loads back through its flavor and predicts.
    n = min(3, len(runner.X_test_))
    X = runner.X_test_.to_numpy()[:n]  # positional (base XGB/LGBM were fit on renamed columns)
    loaders = {
        "LogisticRegression": mlflow.sklearn.load_model,
        "XGBoost": mlflow.xgboost.load_model,
        "LightGBM": mlflow.lightgbm.load_model,
    }
    for name, load in loaders.items():
        model = load(info["models"][name])
        assert len(model.predict(X)) == n


def test_run_mlflow_off_logs_nothing(storage, monkeypatch: pytest.MonkeyPatch) -> None:
    """With ``mlflow`` OFF (the default), the runner logs nothing — ``mlflow_run_`` stays None.

    ``log_run`` is monkeypatched to raise if ever called, proving the OFF path never touches it.
    """
    def _boom(*args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("MLflow logging must not run when mlflow.enabled is False")

    monkeypatch.setattr(mlflow_logging, "log_run", _boom)
    cfg = build_config(
        "policy_lapse.csv",
        LAPSE_TARGET,
        LAPSE_FEATURES,
        problem_type="binary",
        class_balance="none",
        algorithms=["LogisticRegression"],
        interaction_features={"max_auto_pairs": 0},
    )
    runner = ModelRunner(cfg, storage).run()
    assert runner.mlflow_run_ is None


# --------------------------------------------------------------------------- #
# model signature — passing an input_example makes MLflow INFER a signature,   #
# removing the "Model logged without a signature and input example" warning    #
# --------------------------------------------------------------------------- #


def _tiny_fitted_lr() -> tuple[object, pd.DataFrame]:
    """A tiny fitted LogisticRegression + its (engineered-style) feature frame."""
    from sklearn.linear_model import LogisticRegression

    X = pd.DataFrame({"a": [0.1, 0.2, 0.3, 0.4, 0.5], "b": [1.0, 0.0, 1.0, 0.0, 1.0]})
    return LogisticRegression(max_iter=200).fit(X, [0, 1, 0, 1, 0]), X


def _log_one(mlflow, experiment: str, **kw) -> str:
    lr, _ = _tiny_fitted_lr()
    mlflow_logging._maybe_allow_file_store()
    mlflow.set_experiment(experiment)
    with mlflow.start_run():
        return mlflow_logging._log_one_model(mlflow, "model", SimpleNamespace(model=lr), **kw)


def test_log_one_model_input_example_infers_signature(mlflow_tracking_dir: str) -> None:
    """With an input_example the logged model carries an inferred signature (warning gone)."""
    import mlflow

    _, X = _tiny_fitted_lr()
    uri = _log_one(mlflow, "sig_on", input_example=X.head(3))
    assert uri
    assert mlflow.models.get_model_info(uri).signature is not None


def test_log_one_model_without_input_example_has_no_signature(mlflow_tracking_dir: str) -> None:
    """Without an input_example the model logs signature-less (the prior behaviour is preserved)."""
    import mlflow

    uri = _log_one(mlflow, "sig_off")
    assert uri
    assert mlflow.models.get_model_info(uri).signature is None
