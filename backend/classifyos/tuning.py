"""Section 8B — Optuna hyperparameter tuning layer.

A single, uniform tuning mechanism for all six model wrappers, fully controlled at RUN
TIME by ``config["tuning"]`` (see :data:`classifyos.config.DEFAULT_CONFIG`). Tuning is a
NEW module that wraps *around* the Phase 6 wrappers and the registry — it never modifies
either. :func:`tune_model` builds candidate models exactly the way the rest of the engine
does (via :func:`classifyos.models.registry.build_model`), so a tuned model is the same
estimator the runner would have built, only with better hyperparameters.

Design (deliberate):

* **One mechanism, runtime dials.** *Which* models to tune, *how hard* (``n_trials`` /
  ``timeout_seconds``), and *which metric* are config values, not build-time choices.
  Search spaces live in code (:data:`SEARCH_SPACES`) but per-model bounds are overridable
  via ``config["tuning"]["search_space_overrides"]``.
* **Per-model isolation.** Each model gets its own Optuna study wrapped in try/except: a
  model whose study errors (or whose every trial fails) returns ``{}`` and falls back to
  defaults — it never affects the other models or aborts the run (same robustness pattern
  as the Phase 6/7 per-algorithm isolation).
* **OFF by default.** :func:`tune_model` returns ``{}`` immediately unless tuning is
  enabled AND this model is in the tune list.

[RISK] Leakage — the non-negotiable rule. Every trial is scored INSIDE the training split
only; the test set is never passed to this module. The default scoring is k-fold
cross-validation carved from the training matrix (a single train-internal validation split
is the faster alternative, ``cv=False``). Class **balancing (SMOTE/undersampling) is NOT
applied inside the CV folds** — doing so before CV would leak synthetic minority rows
across folds, and integrating per-fold balancing is deferred (plan_tweak). We therefore
use the prompt's documented *safe default*: tune on the pre-balance train folds and let
ModelRunner balance only the final fit. ``class_weight`` (computed once on the full train
split) is passed through to ``build_model`` during tuning — a mild, standard approximation
(it is a per-class reweighting, not synthetic data), noted here for the leakage audit.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedKFold, train_test_split

from .config import DEFAULT_CONFIG, TUNING_METRICS
from .evaluation.metrics import evaluate_model
from .models.registry import _resolve, build_model

logger = logging.getLogger(__name__)

#: Metrics where lower is better — the tuner maximises ``-value`` for these.
_MINIMIZE_METRICS = {"log_loss"}

#: Effective tuning defaults (single source of truth — mirrors the config sub-dict).
_TUNING_DEFAULTS: dict[str, Any] = DEFAULT_CONFIG["tuning"]

#: Held-out fraction for the single-split alternative (``cv=False``).
_SINGLE_SPLIT_TEST_SIZE = 0.25


# --------------------------------------------------------------------------- #
# search spaces — one function per model (trial, per-model overrides) -> params #
# --------------------------------------------------------------------------- #
#
# Honest note on coverage: the search spaces below are RICH for the models that actually
# benefit from tuning (XGBoost, LightGBM, RandomForest, LogisticRegression) and MINIMAL
# for the rest — SVM is slow (its calibrated wrapper re-fits via internal CV every trial)
# and GaussianNB's single knob (``var_smoothing``) rarely moves the needle. They are still
# tunable for uniformity, just don't expect much from the last two.


def _b(ov: Any, param: str, **default: Any) -> dict[str, Any]:
    """Merge a per-model bound override into a ``suggest_float/int`` kwargs dict.

    ``ov`` is the override sub-dict for one model (may be ``None``/empty). If it carries a
    dict for ``param`` (e.g. ``{"low": 3, "high": 6}``) those keys overlay the defaults.
    """
    override = ov.get(param) if isinstance(ov, dict) else None
    if isinstance(override, dict):
        merged = dict(default)
        merged.update(override)
        return merged
    return default


def _ch(ov: Any, param: str, default_choices: list[Any]) -> list[Any]:
    """Return categorical choices for ``param``, overridable by a list in ``ov``."""
    override = ov.get(param) if isinstance(ov, dict) else None
    if isinstance(override, (list, tuple)):
        return list(override)
    return default_choices


def _space_xgboost(trial: Any, ov: Any) -> dict[str, Any]:
    """Rich XGBoost space — the model that benefits most from tuning."""
    return {
        "learning_rate": trial.suggest_float(
            "learning_rate", **_b(ov, "learning_rate", low=0.01, high=0.3, log=True)
        ),
        "max_depth": trial.suggest_int("max_depth", **_b(ov, "max_depth", low=3, high=10)),
        "n_estimators": trial.suggest_int(
            "n_estimators", **_b(ov, "n_estimators", low=100, high=800)
        ),
        "subsample": trial.suggest_float(
            "subsample", **_b(ov, "subsample", low=0.6, high=1.0)
        ),
        "colsample_bytree": trial.suggest_float(
            "colsample_bytree", **_b(ov, "colsample_bytree", low=0.6, high=1.0)
        ),
        "min_child_weight": trial.suggest_int(
            "min_child_weight", **_b(ov, "min_child_weight", low=1, high=10)
        ),
        "reg_alpha": trial.suggest_float(
            "reg_alpha", **_b(ov, "reg_alpha", low=1e-3, high=10.0, log=True)
        ),
        "reg_lambda": trial.suggest_float(
            "reg_lambda", **_b(ov, "reg_lambda", low=1e-3, high=10.0, log=True)
        ),
        # ``gamma`` (a.k.a. ``min_split_loss``): the minimum loss reduction required to make
        # a further partition on a leaf node. A direct complexity regulariser distinct from
        # depth and the L1/L2 (``reg_alpha``/``reg_lambda``) terms — larger gamma → more
        # conservative trees. 0.0 (the XGBoost default) is included so the search can stay
        # unregularised on this axis when that wins.
        "gamma": trial.suggest_float("gamma", **_b(ov, "gamma", low=0.0, high=5.0)),
    }


def _space_lightgbm(trial: Any, ov: Any) -> dict[str, Any]:
    """Rich LightGBM space.

    ``bagging_freq`` is suggested (1–7) rather than left at LightGBM's default of 0, because
    with ``bagging_freq=0`` the ``bagging_fraction`` knob is inert; this keeps the tuned
    bagging actually effective.

    [RISK] overfitting — LightGBM grows **leaf-wise**, so with its default ``max_depth=-1``
    (unbounded) and ``num_leaves`` tuned up to 255, individual trees can become very deep and
    overfit on smaller datasets. ``max_depth`` (3–12) now bounds that leaf-wise growth — the
    standard ``num_leaves ≲ 2^max_depth`` guard pairing depth with the leaf count. ``num_leaves``
    is left as-is; the depth cap is the structural backstop on tree complexity.
    """
    return {
        "num_leaves": trial.suggest_int(
            "num_leaves", **_b(ov, "num_leaves", low=15, high=255)
        ),
        "max_depth": trial.suggest_int("max_depth", **_b(ov, "max_depth", low=3, high=12)),
        "learning_rate": trial.suggest_float(
            "learning_rate", **_b(ov, "learning_rate", low=0.01, high=0.3, log=True)
        ),
        "n_estimators": trial.suggest_int(
            "n_estimators", **_b(ov, "n_estimators", low=100, high=800)
        ),
        "feature_fraction": trial.suggest_float(
            "feature_fraction", **_b(ov, "feature_fraction", low=0.6, high=1.0)
        ),
        "bagging_fraction": trial.suggest_float(
            "bagging_fraction", **_b(ov, "bagging_fraction", low=0.6, high=1.0)
        ),
        "bagging_freq": trial.suggest_int(
            "bagging_freq", **_b(ov, "bagging_freq", low=1, high=7)
        ),
        "min_child_samples": trial.suggest_int(
            "min_child_samples", **_b(ov, "min_child_samples", low=5, high=100)
        ),
        "reg_alpha": trial.suggest_float(
            "reg_alpha", **_b(ov, "reg_alpha", low=1e-3, high=10.0, log=True)
        ),
        "reg_lambda": trial.suggest_float(
            "reg_lambda", **_b(ov, "reg_lambda", low=1e-3, high=10.0, log=True)
        ),
    }


def _space_randomforest(trial: Any, ov: Any) -> dict[str, Any]:
    """RandomForest space.

    ``max_depth`` is searched over a bounded integer range (3–30); the ``None`` (unlimited
    depth) option is deliberately excluded to keep tree size — and therefore fit cost —
    bounded during the search.
    """
    return {
        "n_estimators": trial.suggest_int(
            "n_estimators", **_b(ov, "n_estimators", low=100, high=600)
        ),
        "max_depth": trial.suggest_int("max_depth", **_b(ov, "max_depth", low=3, high=30)),
        "max_features": trial.suggest_categorical(
            "max_features", _ch(ov, "max_features", ["sqrt", "log2", 0.5, 0.75, 1.0])
        ),
        "min_samples_leaf": trial.suggest_int(
            "min_samples_leaf", **_b(ov, "min_samples_leaf", low=1, high=10)
        ),
        "min_samples_split": trial.suggest_int(
            "min_samples_split", **_b(ov, "min_samples_split", low=2, high=20)
        ),
    }


def _space_logreg(trial: Any, ov: Any) -> dict[str, Any]:
    """LogisticRegression space — regularisation strength ``C`` only.

    Only ``C`` is tuned; the solver/penalty are left at the wrapper defaults (``lbfgs`` + L2).
    Two reasons the older "compatible solver/penalty pairs" idea was dropped (both verified
    against the installed scikit-learn 1.9):

    * **``penalty`` is deprecated** (warns since 1.8, slated for removal in 1.10) — passing it
      raises a ``FutureWarning``; the replacement is ``C`` / ``l1_ratio``.
    * **``liblinear`` rejects multiclass** (``n_classes >= 3``) — offering it as a choice made
      every liblinear trial error on multiclass targets.

    Tuning the regularisation *type* cleanly now needs ``solver="saga"`` + ``l1_ratio``, which
    is markedly slower per fit and risks non-convergence at our fixed ``max_iter`` — deferred.
    ``C`` is LR's dominant knob regardless, and tuning it alone is warning-free and works
    identically for binary and multiclass.
    """
    return {
        "C": trial.suggest_float("C", **_b(ov, "C", low=1e-3, high=1e2, log=True)),
    }


def _space_svm(trial: Any, ov: Any) -> dict[str, Any]:
    """SVM space — minimal. NOTE: slow. The SVM wrapper re-runs internal calibration CV on
    every trial, so each evaluation is expensive; keep ``n_trials`` small for SVM.

    ``kernel`` is a real categorical (``["rbf", "linear"]``), not the former no-op
    single-element list. ``linear`` is cheaper per fit and sometimes wins on standard-scaled
    data; ``rbf`` captures non-linearity at higher cost. The space is **conditional**:
    ``gamma`` is an RBF-only knob (SVC ignores ``gamma`` when ``kernel="linear"``), so it is
    suggested only on the ``rbf`` branch — a linear trial returns no ``gamma`` at all rather
    than a dead parameter. The slow-model guidance still stands: keep ``n_trials`` small for
    SVM regardless of kernel.
    """
    params: dict[str, Any] = {
        "C": trial.suggest_float("C", **_b(ov, "C", low=1e-2, high=1e2, log=True)),
        "kernel": trial.suggest_categorical("kernel", _ch(ov, "kernel", ["rbf", "linear"])),
    }
    # Conditional: gamma only matters (and is only suggested) for the rbf kernel.
    if params["kernel"] == "rbf":
        params["gamma"] = trial.suggest_float(
            "gamma", **_b(ov, "gamma", low=1e-4, high=1e0, log=True)
        )
    return params


def _space_naivebayes(trial: Any, ov: Any) -> dict[str, Any]:
    """GaussianNB space — minimal. NOTE: ``var_smoothing`` rarely changes results
    materially; tuning it is supported for uniformity, not because it usually helps."""
    return {
        "var_smoothing": trial.suggest_float(
            "var_smoothing", **_b(ov, "var_smoothing", low=1e-12, high=1e-6, log=True)
        ),
    }


#: Canonical model name → search-space function. Keyed to the registry's canonical names.
SEARCH_SPACES: dict[str, Callable[[Any, Any], dict[str, Any]]] = {
    "XGBoost": _space_xgboost,
    "LightGBM": _space_lightgbm,
    "RandomForest": _space_randomforest,
    "LogisticRegression": _space_logreg,
    "SVM": _space_svm,
    "NaiveBayes": _space_naivebayes,
}


# --------------------------------------------------------------------------- #
# settings + tune-list resolution                                             #
# --------------------------------------------------------------------------- #


def _settings(config: dict[str, Any]) -> dict[str, Any]:
    """Return the effective tuning settings, filling any missing key with its default.

    Tolerant of a partial ``tuning`` sub-dict (e.g. the CLI sending only ``enabled``), the
    same way the feature-engineering config is read.
    """
    t = config.get("tuning") or {}
    return {key: t.get(key, default) for key, default in _TUNING_DEFAULTS.items()}


def _should_tune(model_name: str, models: list[str]) -> bool:
    """Decide whether ``model_name`` should be tuned given the configured tune list.

    Empty list or ``["all"]`` (case-insensitive) → tune every algorithm; otherwise tune
    only the listed models (aliases like ``"XGB"`` resolve to canonical names).
    """
    if not models:
        return True
    if any(str(m).strip().lower() == "all" for m in models):
        return True
    try:
        canon = _resolve(model_name)
    except ValueError:
        return False
    requested: set[str] = set()
    for m in models:
        try:
            requested.add(_resolve(m))
        except ValueError:
            continue
    return canon in requested


def should_tune_model(model_name: str, config: dict[str, Any]) -> bool:
    """Public helper for ModelRunner: is tuning enabled AND requested for this model?"""
    settings = _settings(config)
    return bool(settings["enabled"]) and _should_tune(model_name, settings["models"])


# --------------------------------------------------------------------------- #
# scoring (TRAIN-only, leakage-safe)                                          #
# --------------------------------------------------------------------------- #


def _effective_folds(y: pd.Series, requested: int) -> int:
    """Clamp the requested fold count to the smallest class size (StratifiedKFold needs
    at least ``n_splits`` members per class)."""
    min_count = int(pd.Series(y).value_counts().min())
    return max(0, min(requested, min_count))


def _fit_eval(
    key: str,
    X_tr: pd.DataFrame,
    y_tr: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    params: dict[str, Any],
    problem_type: str,
    class_weight: dict[Any, float] | None,
    random_state: int,
    metric: str,
) -> float:
    """Fit ONE candidate on a fold's train portion and score it on the fold's val portion.

    [RISK] leakage — both ``X_tr``/``X_val`` here are carved from the TRAINING split only;
    the test set is never seen. Balancing is intentionally NOT applied to the fold train
    (safe default — avoids synthetic rows leaking across folds); ``class_weight`` is passed
    through (mild approximation, see module docstring).
    """
    model = build_model(
        key,
        problem_type=problem_type,
        class_weight=class_weight,
        random_state=random_state,
        **params,
    )
    model.fit(X_tr, y_tr)
    classes = np.asarray(model.classes_)
    y_proba = model.predict_proba(X_val)
    y_pred = model.predict(X_val)
    metrics = evaluate_model(y_val, y_pred, y_proba, problem_type, classes)
    value = metrics.get(metric)
    if value is None:
        # The metric is undefined for this fold (e.g. pr_auc on multiclass). Prune the
        # trial rather than scoring it 0 — a pruned trial just can't win.
        import optuna

        raise optuna.TrialPruned(f"metric {metric!r} is undefined for this fold")
    return -float(value) if metric in _MINIMIZE_METRICS else float(value)


def _score_params(
    key: str,
    X: pd.DataFrame,
    y: pd.Series,
    params: dict[str, Any],
    problem_type: str,
    class_weight: dict[Any, float] | None,
    random_state: int,
    metric: str,
    cv: bool,
    folds: int,
) -> float:
    """Score a parameter set via k-fold CV (default) or a single train-internal split."""
    if cv:
        skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=random_state)
        scores = [
            _fit_eval(
                key,
                X.iloc[tr_idx],
                y.iloc[tr_idx],
                X.iloc[val_idx],
                y.iloc[val_idx],
                params,
                problem_type,
                class_weight,
                random_state,
                metric,
            )
            for tr_idx, val_idx in skf.split(X, y)
        ]
        return float(np.mean(scores))

    X_tr, X_val, y_tr, y_val = train_test_split(
        X,
        y,
        test_size=_SINGLE_SPLIT_TEST_SIZE,
        stratify=y,
        random_state=random_state,
    )
    return _fit_eval(
        key, X_tr, y_tr, X_val, y_val, params, problem_type, class_weight,
        random_state, metric,
    )


# --------------------------------------------------------------------------- #
# public entry point                                                          #
# --------------------------------------------------------------------------- #


def tune_model(
    model_name: str,
    X_train: pd.DataFrame,
    y_train: pd.Series,
    problem_type: str,
    config: dict[str, Any],
    class_weight: dict[Any, float] | None = None,
    random_state: int = 42,
) -> dict[str, Any]:
    """Tune one model's hyperparameters with Optuna and return the best params.

    Args:
        model_name: A registry name or alias (e.g. ``"XGBoost"`` / ``"XGB"``).
        X_train: The (pre-balance) TRAIN feature matrix. The test set is NEVER passed in —
            every trial is scored on folds carved from this matrix only (the leakage rule).
        y_train: TRAIN labels aligned with ``X_train``.
        problem_type: ``"binary"`` | ``"multiclass"`` | ``"multilabel"``.
        config: Run config; reads the ``tuning`` sub-dict (enabled/models/metric/cv/
            cv_folds/n_trials/timeout_seconds/search_space_overrides).
        class_weight: Optional ``{class: weight}`` from the balancer, passed through to
            ``build_model`` for every trial (mild approximation — see module docstring).
        random_state: Seed for the TPE sampler and the CV splits (reproducibility).

    Returns:
        The best hyperparameters found as a dict ready to splat into ``build_model``, or
        ``{}`` when tuning is disabled, this model is not in the tune list, the model has
        no defined search space, the metric is unknown, or the study fails entirely
        (every case falls back to the wrapper defaults — tuning never raises).
    """
    settings = _settings(config)
    if not settings["enabled"]:
        return {}
    if not _should_tune(model_name, settings["models"]):
        return {}

    try:
        key = _resolve(model_name)
    except ValueError:
        logger.info("tune_model: unknown model %r; using defaults.", model_name)
        return {}

    space_fn = SEARCH_SPACES.get(key)
    if space_fn is None:
        logger.info("tune_model: no search space for %r; using defaults.", key)
        return {}

    metric = settings["metric"]
    if metric not in TUNING_METRICS:
        logger.warning(
            "tune_model(%s): unknown metric %r; skipping tuning (defaults).", key, metric
        )
        return {}

    # [RISK] per-model isolation — the whole study runs inside this try/except. A study
    # that errors (or whose every trial fails) returns {} and the model falls back to
    # defaults; it never affects the other models or aborts the run.
    try:
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)

        X = X_train.reset_index(drop=True)
        y = pd.Series(y_train).reset_index(drop=True)

        cv = bool(settings["cv"])
        folds = 0
        if cv:
            folds = _effective_folds(y, int(settings["cv_folds"]))
            if folds < 2:
                logger.warning(
                    "tune_model(%s): too few samples per class for %d-fold CV; "
                    "using a single validation split instead.",
                    key,
                    int(settings["cv_folds"]),
                )
                cv = False

        model_ov = (settings["search_space_overrides"] or {}).get(key, {})
        sampler = optuna.samplers.TPESampler(seed=random_state)
        study = optuna.create_study(direction="maximize", sampler=sampler)

        def objective(trial: Any) -> float:
            params = space_fn(trial, model_ov)
            # Store the exact estimator params on the trial so the returned best params
            # match what was scored, even when the space transforms a suggestion (e.g. the
            # LogisticRegression "solver|penalty" categorical splits into two kwargs).
            trial.set_user_attr("tuned_params", params)
            return _score_params(
                key, X, y, params, problem_type, class_weight, random_state,
                metric, cv, folds,
            )

        # catch=(Exception,) → a single failing trial is recorded as FAILED and skipped,
        # never fatal (TrialPruned is handled by Optuna independently of `catch`).
        study.optimize(
            objective,
            n_trials=int(settings["n_trials"]),
            timeout=settings["timeout_seconds"],
            catch=(Exception,),
        )

        # study.best_trial raises if no trial completed (all failed/pruned) — caught below.
        best = dict(study.best_trial.user_attrs.get("tuned_params", {}))
        logger.info(
            "tune_model(%s): best %s=%.4f over %d trial(s) → %s",
            key,
            metric,
            study.best_value,
            len(study.trials),
            best,
        )
        return best
    except Exception:  # noqa: BLE001 — one failed study must never kill the run
        logger.exception("tune_model(%s): tuning failed; falling back to defaults.", key)
        return {}
