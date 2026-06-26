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
# config — default has NO wall-clock cap; n_trials is the bound                #
# --------------------------------------------------------------------------- #


def test_default_timeout_is_uncapped() -> None:
    """By owner request (plan_tweak #43, reversing #25) there is no default per-model
    wall-clock cap — ``timeout_seconds`` defaults to None so a study runs all trials."""
    assert DEFAULT_CONFIG["tuning"]["timeout_seconds"] is None


def test_default_n_trials_is_the_bound() -> None:
    """With no default timeout, ``n_trials`` is the SOLE bound on a study, so it must
    stay a finite positive int (otherwise an enabled tune-all run is open-ended)."""
    n = DEFAULT_CONFIG["tuning"]["n_trials"]
    assert isinstance(n, int) and not isinstance(n, bool) and n > 0


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
        "gamma",
    }.issubset(best)
    # the returned params are real estimator kwargs (correct types)
    assert isinstance(best["max_depth"], int)
    assert 0.0 < best["learning_rate"] < 1.0
    # gamma (min_split_loss) is a uniform float regulariser over 0..5
    assert isinstance(best["gamma"], float) and 0.0 <= best["gamma"] <= 5.0


def test_tune_lightgbm_includes_max_depth(binary_matrices) -> None:
    """Tuning LightGBM returns ``max_depth`` within 3…12 (the leaf-wise growth bound).

    ``max_depth`` was added alongside the existing ``num_leaves`` to cap LightGBM's leaf-wise
    tree growth (the ``num_leaves ≲ 2^max_depth`` guard); it must surface in the best params.
    """
    bm = binary_matrices
    cfg = _lapse_config(
        algorithms=["LightGBM"], tuning=_tuning_cfg(models=["LGBM"], n_trials=3)
    )
    best = tune_model("LightGBM", bm.X_train, bm.y_train, "binary", cfg, random_state=42)

    assert isinstance(best, dict) and best
    assert "num_leaves" in best  # unchanged, still tuned
    assert "max_depth" in best
    assert isinstance(best["max_depth"], int) and 3 <= best["max_depth"] <= 12


# --------------------------------------------------------------------------- #
# unit — SVM conditional kernel/gamma space                                   #
# --------------------------------------------------------------------------- #


class _RecordingTrial:
    """A minimal stub trial that returns a fixed categorical pick and midpoint numerics.

    Lets the SVM space's conditional branch (``gamma`` only on ``rbf``) be tested
    deterministically WITHOUT a real Optuna study or any slow calibrated-SVC fit.
    """

    def __init__(self, kernel: str) -> None:
        self._kernel = kernel
        self.suggested: dict[str, object] = {}

    def suggest_float(self, name, low, high, log=False):  # noqa: ANN001
        value = (low * high) ** 0.5 if log else (low + high) / 2.0
        self.suggested[name] = value
        return value

    def suggest_int(self, name, low, high, log=False):  # noqa: ANN001
        value = (low + high) // 2
        self.suggested[name] = value
        return value

    def suggest_categorical(self, name, choices):  # noqa: ANN001
        value = self._kernel if name == "kernel" else choices[0]
        self.suggested[name] = value
        return value


def test_svm_space_kernel_is_a_real_choice() -> None:
    """The SVM kernel categorical now offers two kernels (no longer the no-op ``["rbf"]``)."""
    from classifyos.tuning import _space_svm

    rbf = _space_svm(_RecordingTrial("rbf"), {})
    linear = _space_svm(_RecordingTrial("linear"), {})
    assert rbf["kernel"] == "rbf"
    assert linear["kernel"] == "linear"
    assert "C" in rbf and "C" in linear


def test_svm_space_gamma_is_conditional() -> None:
    """``gamma`` is suggested only for ``rbf`` (SVC ignores it on a linear kernel)."""
    from classifyos.tuning import _space_svm

    rbf = _space_svm(_RecordingTrial("rbf"), {})
    linear = _space_svm(_RecordingTrial("linear"), {})
    # rbf branch carries a numeric gamma; linear branch carries none.
    assert "gamma" in rbf and isinstance(rbf["gamma"], float)
    assert "gamma" not in linear


def test_tune_svm_either_kernel_roundtrips(binary_matrices) -> None:
    """A real (tiny-budget) SVM study returns one of the two kernels with a matching space.

    SVM is the slow model (calibrated SVC re-runs internal CV per trial), so this uses the
    minimal trial count the speed contract allows. Whichever kernel the winning trial picks,
    the returned params must be self-consistent: ``gamma`` present iff ``kernel == "rbf"``.
    """
    bm = binary_matrices
    cfg = _lapse_config(
        algorithms=["SVM"],
        tuning=_tuning_cfg(models=["SVM"], n_trials=2, cv_folds=2),
    )
    best = tune_model("SVM", bm.X_train, bm.y_train, "binary", cfg, random_state=42)

    assert isinstance(best, dict) and best
    assert "C" in best
    assert best["kernel"] in {"rbf", "linear"}
    if best["kernel"] == "rbf":
        assert "gamma" in best
    else:
        assert "gamma" not in best  # conditional space: no dead gamma on linear


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
    """The LogisticRegression space tunes C only — no deprecated penalty/solver args."""
    bm = binary_matrices
    cfg = _lapse_config(
        algorithms=["LogisticRegression"],
        tuning=_tuning_cfg(models=["LR"], n_trials=4),
    )
    best = tune_model("LogisticRegression", bm.X_train, bm.y_train, "binary", cfg)
    assert "C" in best and best["C"] > 0
    # solver/penalty are intentionally NOT tuned (sklearn 1.9 deprecated `penalty`;
    # `liblinear` breaks multiclass) — they must stay at the wrapper defaults.
    assert "penalty" not in best and "solver" not in best


def test_logreg_tuning_multiclass_no_failed_trials(multiclass_matrices, monkeypatch) -> None:
    """LR tuning on a 3-class target runs every trial to completion (regression guard).

    With the old solver/penalty space, ``liblinear`` trials errored on multiclass; here every
    trial must fit cleanly, so build_model is called exactly n_trials × cv_folds times.
    """
    mm = multiclass_matrices
    calls = {"n": 0}
    real_build = tuning.build_model

    def _counting(*args, **kwargs):
        calls["n"] += 1
        return real_build(*args, **kwargs)

    monkeypatch.setattr(tuning, "build_model", _counting)
    cfg = build_config(
        "risk_tier.csv",
        "risk_tier",
        ["age", "bmi"],  # placeholders; tune_model scores the matrices passed in
        problem_type="multiclass",
        tuning=_tuning_cfg(models=["LR"], n_trials=3, cv_folds=2),
    )
    best = tune_model("LogisticRegression", mm.X_train, mm.y_train, "multiclass", cfg)
    assert "C" in best
    assert calls["n"] == 3 * 2  # no trial errored mid-fold


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
