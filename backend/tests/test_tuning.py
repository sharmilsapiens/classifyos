"""Tests for Section 8B (``classifyos.tuning`` — the Optuna hyperparameter tuning layer).

Two levels:

* **Unit** — :func:`tune_model` / the scoring helpers on the session-scoped engineered
  ``binary_matrices`` fixture (the PRE-balance, sampled policy-lapse TRAIN matrix). Fast,
  deterministic (TPE sampler + CV splits are seeded), and never touch the test split.
* **Integration** — :class:`ModelRunner` end to end with tuning enabled, asserting only the
  requested models are tuned, the audit trail lands in ``run_profile.json``, the caller's
  config is never mutated, and disabling tuning is a no-op vs the default pipeline.

**Speed contract (deliberate).** Tuning multiplies fits, so every test here uses a TINY
budget: ``n_trials <= 5``, ``cv_folds=2``, and an explicit short ``timeout_seconds`` safety
cap. The only fast wrappers are exercised (XGBoost / LogisticRegression) — the slow SVM
(calibrated SVC, internal CV per trial) and the rarely-useful NaiveBayes are deliberately
NOT tuned in the suite. The timeout test stubs the scorer so it can never hang.
"""

from __future__ import annotations

import copy
import inspect
import json
import time

import pandas as pd

from classifyos.config import DEFAULT_CONFIG, build_config
from classifyos.runner import RUN_PROFILE_KEY, ModelRunner
from classifyos import tuning
from classifyos.tuning import (
    SEARCH_SPACES,
    _score_params,
    _should_tune,
    should_tune_model,
    tune_model,
)

LAPSE_FEATURES = [
    "age",
    "occupation",
    "region",
    "policy_type",
    "channel",
    "payment_frequency",
    "policy_tenure_years",
    "annual_premium",
    "sum_assured",
    "num_late_payments",
    "claims_count",
    "has_agent",
]


# Cap the expensive bounds (tree counts / depth / leaves) to trivially small ranges in
# tests. This keeps each candidate fit ~instant while still exercising the FULL tuning
# machinery (sampler, CV scoring, best-trial extraction, runner integration). Production
# uses the real (rich) spaces — only the tests shrink them.
_FAST_SPACE: dict[str, dict] = {
    "XGBoost": {
        "n_estimators": {"low": 10, "high": 30},
        "max_depth": {"low": 2, "high": 4},
    },
    "LightGBM": {
        "n_estimators": {"low": 10, "high": 30},
        "num_leaves": {"low": 7, "high": 31},
    },
    "RandomForest": {
        "n_estimators": {"low": 10, "high": 30},
        "max_depth": {"low": 3, "high": 8},
    },
}


def _tuning_cfg(
    *,
    enabled: bool = True,
    models: list[str] | None = None,
    metric: str = "f1_weighted",
    cv: bool = True,
    cv_folds: int = 2,  # minimum folds → fastest CV in tests
    n_trials: int = 3,  # tiny budget
    timeout_seconds: float | None = 30,  # hard safety cap so a test can never run long
    search_space_overrides: dict | None = None,
) -> dict:
    """A complete ``tuning`` sub-dict for use as a ``build_config`` override (tiny budget).

    Defaults to the :data:`_FAST_SPACE` bound caps so test fits are instant; pass an
    explicit ``search_space_overrides`` to use a different (still small) space.
    """
    return {
        "enabled": enabled,
        "models": models if models is not None else [],
        "metric": metric,
        "cv": cv,
        "cv_folds": cv_folds,
        "n_trials": n_trials,
        "timeout_seconds": timeout_seconds,
        "search_space_overrides": _FAST_SPACE if search_space_overrides is None else search_space_overrides,
    }


# Disable interaction auto-discovery in tests — the MI scan over ~105 candidate pairs is
# a large slice of the base ModelRunner cost and is unrelated to tuning (same speed trick
# the shared conftest matrices use).
_NO_AUTO_INTERACTIONS = {
    "enabled": True,
    "interaction_pairs": {},
    "default_interactions": ["multiply"],
    "drop_original_if_interacted": False,
    "max_auto_pairs": 0,
    "fill_method": "zero",
}


def _lapse_config(**overrides):
    base = dict(
        problem_type="binary",
        algorithms=["XGBoost"],
        class_balance="class_weight",
        interaction_features=_NO_AUTO_INTERACTIONS,
    )
    base.update(overrides)
    return build_config("policy_lapse.csv", "will_lapse", LAPSE_FEATURES, **base)


# --------------------------------------------------------------------------- #
# config — the hard default timeout                                           #
# --------------------------------------------------------------------------- #


def test_default_timeout_is_bounded() -> None:
    """The shipped default must cap every tuning run (never None/unbounded by default)."""
    t = DEFAULT_CONFIG["tuning"]["timeout_seconds"]
    assert t is not None and isinstance(t, (int, float)) and t > 0


# --------------------------------------------------------------------------- #
# unit — tune_model behaviour                                                 #
# --------------------------------------------------------------------------- #


def test_tune_xgboost_returns_params(binary_matrices) -> None:
    """Tuning XGBoost (5 trials) returns a non-empty dict with the expected keys."""
    bm = binary_matrices
    cfg = _lapse_config(tuning=_tuning_cfg(models=["XGB"], n_trials=3))
    best = tune_model("XGBoost", bm.X_train, bm.y_train, "binary", cfg, random_state=42)

    assert isinstance(best, dict) and best
    assert {
        "learning_rate",
        "max_depth",
        "n_estimators",
        "subsample",
        "colsample_bytree",
    }.issubset(best)
    # the returned params are real estimator kwargs (correct types)
    assert isinstance(best["max_depth"], int)
    assert 0.0 < best["learning_rate"] < 1.0


def test_tuning_improves_or_matches(binary_matrices) -> None:
    """The tuned model's CV score is >= the default model's on the SAME (seeded) folds.

    Uses LogisticRegression — the "tuning shouldn't make it worse" property is
    model-agnostic, and LR fits in milliseconds (XGBoost's per-fit overhead made this the
    slowest test by far). Deterministic: the TPE sampler and StratifiedKFold are seeded, so
    it either always passes or always fails — never flaky.
    """
    bm = binary_matrices
    cfg = _lapse_config(tuning=_tuning_cfg(models=["LR"], n_trials=5, cv_folds=2))
    best = tune_model(
        "LogisticRegression", bm.X_train, bm.y_train, "binary", cfg, random_state=42
    )

    X = bm.X_train.reset_index(drop=True)
    y = pd.Series(bm.y_train).reset_index(drop=True)
    default_score = _score_params(
        "LogisticRegression", X, y, {}, "binary", None, 42, "f1_weighted", True, 2
    )
    tuned_score = _score_params(
        "LogisticRegression", X, y, best, "binary", None, 42, "f1_weighted", True, 2
    )
    assert tuned_score >= default_score - 1e-9


def test_test_set_untouched() -> None:
    """Structural leakage guard: tune_model's signature admits TRAIN data only.

    There is physically no parameter through which the test split could reach the tuner;
    every trial is scored on folds carved from ``X_train``/``y_train``.
    """
    params = set(inspect.signature(tune_model).parameters)
    assert "X_train" in params and "y_train" in params
    assert not any("test" in name.lower() for name in params)


def test_model_not_in_list_uses_defaults(binary_matrices) -> None:
    """A model not in the tune list is not tuned (returns {} → defaults)."""
    bm = binary_matrices
    cfg = _lapse_config(tuning=_tuning_cfg(models=["XGB"], n_trials=3))
    # XGB is in the list → tuned
    assert tune_model("XGBoost", bm.X_train, bm.y_train, "binary", cfg)
    # RandomForest / LogisticRegression are NOT → empty (use defaults)
    assert tune_model("RandomForest", bm.X_train, bm.y_train, "binary", cfg) == {}
    assert tune_model("LogisticRegression", bm.X_train, bm.y_train, "binary", cfg) == {}


def test_disabled_is_noop(binary_matrices) -> None:
    """enabled=False short-circuits to {} regardless of the model list (no study runs)."""
    bm = binary_matrices
    cfg = _lapse_config(tuning=_tuning_cfg(enabled=False, models=["all"], n_trials=5))
    assert tune_model("XGBoost", bm.X_train, bm.y_train, "binary", cfg) == {}


def test_tuning_failure_falls_back(binary_matrices) -> None:
    """A study whose every trial errors returns {} (and the run would use defaults).

    An inverted bound (low > high) makes ``suggest_int`` raise on every trial; Optuna
    records them as FAILED, ``study.best_trial`` then raises, and tune_model swallows it.
    """
    bm = binary_matrices
    bad = {"XGBoost": {"max_depth": {"low": 10, "high": 3}}}
    cfg = _lapse_config(
        tuning=_tuning_cfg(models=["XGB"], n_trials=3, search_space_overrides=bad)
    )
    assert tune_model("XGBoost", bm.X_train, bm.y_train, "binary", cfg) == {}


def test_n_trials_respected(binary_matrices, monkeypatch) -> None:
    """The study runs exactly ``n_trials`` trials × ``cv_folds`` model fits."""
    bm = binary_matrices
    calls = {"n": 0}
    real_build = tuning.build_model

    def _counting(*args, **kwargs):
        calls["n"] += 1
        return real_build(*args, **kwargs)

    monkeypatch.setattr(tuning, "build_model", _counting)
    cfg = _lapse_config(tuning=_tuning_cfg(models=["XGB"], n_trials=3, cv_folds=2))
    tune_model("XGBoost", bm.X_train, bm.y_train, "binary", cfg)
    # binary lapse has plenty of both classes in the sampled train → folds == 2
    assert calls["n"] == 3 * 2


def test_timeout_honored(binary_matrices, monkeypatch) -> None:
    """A small per-model timeout stops the study well short of a large trial budget.

    The scorer is stubbed to a ~50ms sleep so the test is bounded by the timeout, not by
    real model fitting — and can never hang even if the timeout were broken (a 500-trial
    cap × 50ms = 25s worst case).
    """
    bm = binary_matrices
    calls = {"n": 0}

    def _slow_score(*args, **kwargs):
        calls["n"] += 1
        time.sleep(0.05)
        return 0.5

    monkeypatch.setattr(tuning, "_score_params", _slow_score)
    cfg = _lapse_config(
        tuning=_tuning_cfg(models=["XGB"], n_trials=500, cv_folds=2, timeout_seconds=1)
    )
    t0 = time.perf_counter()
    best = tune_model("XGBoost", bm.X_train, bm.y_train, "binary", cfg)
    elapsed = time.perf_counter() - t0

    assert elapsed < 10  # the 1s timeout cut it far short of 500 trials
    assert calls["n"] < 500  # the timeout (not n_trials) was the binding constraint
    assert isinstance(best, dict)


def test_single_split_alternative(binary_matrices) -> None:
    """cv=False uses a single train-internal validation split and still returns params."""
    bm = binary_matrices
    cfg = _lapse_config(tuning=_tuning_cfg(models=["XGB"], n_trials=4, cv=False))
    best = tune_model("XGBoost", bm.X_train, bm.y_train, "binary", cfg)
    assert isinstance(best, dict) and best


def test_config_not_mutated_by_tune_model(binary_matrices) -> None:
    """tune_model only reads config — it never mutates the dict it is handed."""
    bm = binary_matrices
    cfg = _lapse_config(tuning=_tuning_cfg(models=["XGB"], n_trials=3))
    before = copy.deepcopy(cfg)
    tune_model("XGBoost", bm.X_train, bm.y_train, "binary", cfg)
    assert cfg == before


def test_logreg_space_is_valid(binary_matrices) -> None:
    """The LogisticRegression space yields a compatible solver/penalty pair + C."""
    bm = binary_matrices
    cfg = _lapse_config(
        algorithms=["LogisticRegression"],
        tuning=_tuning_cfg(models=["LR"], n_trials=4),
    )
    best = tune_model("LogisticRegression", bm.X_train, bm.y_train, "binary", cfg)
    assert {"C", "solver", "penalty"}.issubset(best)
    assert (best["solver"], best["penalty"]) in {
        ("lbfgs", "l2"),
        ("liblinear", "l2"),
        ("liblinear", "l1"),
    }


# --------------------------------------------------------------------------- #
# unit — tune-list resolution                                                 #
# --------------------------------------------------------------------------- #


def test_should_tune_resolution() -> None:
    """Empty / ['all'] → tune everything; an explicit list resolves aliases."""
    assert _should_tune("XGBoost", [])  # empty → all
    assert _should_tune("RandomForest", ["all"])  # all
    assert _should_tune("XGBoost", ["XGB"])  # alias resolves
    assert _should_tune("LogisticRegression", ["LR", "RF"])
    assert not _should_tune("RandomForest", ["XGB"])


def test_should_tune_model_respects_enabled() -> None:
    """should_tune_model couples the enabled flag with the tune list."""
    on = _lapse_config(tuning=_tuning_cfg(models=["XGB"]))
    off = _lapse_config(tuning=_tuning_cfg(enabled=False, models=["XGB"]))
    assert should_tune_model("XGBoost", on)
    assert not should_tune_model("RandomForest", on)
    assert not should_tune_model("XGBoost", off)


def test_every_registry_model_has_a_search_space() -> None:
    """Uniform mechanism: all six wrappers are tunable (richness varies — see comments)."""
    from classifyos.models.registry import MODEL_REGISTRY

    assert set(SEARCH_SPACES) == set(MODEL_REGISTRY)


# --------------------------------------------------------------------------- #
# integration — ModelRunner with tuning                                       #
# --------------------------------------------------------------------------- #


def test_runner_tunes_only_requested_and_records_audit(storage, output_dir) -> None:
    """End to end: only the listed model is tuned; the audit lands in run_profile; the
    caller's config is never mutated; every model still trains."""
    cfg = _lapse_config(
        algorithms=["RandomForest", "XGBoost"],
        tuning=_tuning_cfg(models=["XGB"], n_trials=2, cv_folds=2),
    )
    before = copy.deepcopy(cfg)
    runner = ModelRunner(cfg, storage).run()

    # only XGBoost was tuned; RandomForest stayed on defaults
    assert set(runner.tuned_params_) == {"XGBoost"}
    assert runner.tuned_params_["XGBoost"]

    # _run_config isolation still holds with tuning in the loop
    assert cfg == before

    # both models trained successfully (tuning never aborts the run)
    assert (runner.metrics_df_["status"] == "ok").all()
    assert set(runner.models_) == {"RandomForest", "XGBoost"}

    # run_profile.json carries the tuning audit trail
    with open(output_dir / RUN_PROFILE_KEY, encoding="utf-8") as fh:
        profile = json.load(fh)
    t = profile["tuning"]
    assert t["enabled"] is True
    assert t["metric"] == "f1_weighted"
    assert t["tuned_models"] == ["XGBoost"]
    assert "XGBoost" in t["best_params"] and t["best_params"]["XGBoost"]


def test_runner_disabled_is_noop(storage) -> None:
    """A run with tuning disabled matches the default (no-tuning) pipeline exactly."""
    cfg_base = _lapse_config(algorithms=["LogisticRegression"])
    cfg_off = _lapse_config(
        algorithms=["LogisticRegression"],
        tuning=_tuning_cfg(enabled=False, models=["all"]),
    )
    base = ModelRunner(cfg_base, storage).run()
    off = ModelRunner(cfg_off, storage).run()

    assert off.tuned_params_ == {}
    m_base = base.metrics_df_.set_index("model")["f1_weighted"]
    m_off = off.metrics_df_.set_index("model")["f1_weighted"]
    for model in m_base.index:
        assert abs(float(m_base[model]) - float(m_off[model])) < 1e-9
