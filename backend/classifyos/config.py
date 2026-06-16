"""Sections 1–2 — master configuration and ``build_config``.

This module defines :data:`DEFAULT_CONFIG`, the single source of truth for every
tunable in the ClassifyOS pipeline, and :func:`build_config`, which produces a
validated, *independent* config dict for a run.

The browser builds a config from these defaults, POSTs it to the API, and the ML
engine executes it. Keeping the defaults and their allowed values here (rather than
scattered across sections) is what lets the frontend, API, and engine agree on one
contract.
"""

from __future__ import annotations

import copy
from typing import Any

# --- allowed value sets (kept next to the defaults so validation can't drift) ---
PROBLEM_TYPES = ("binary", "multiclass", "multilabel")
CLASS_BALANCE = ("smote", "undersample", "class_weight", "none")
MISSING_STRATEGIES = ("median", "mean", "mode", "ffill", "drop")
ENCODING_METHODS = ("onehot", "label", "ordinal", "target")
SCALING_METHODS = ("standard", "minmax", "robust", "none")
OUTLIER_METHODS = ("iqr", "zscore", "none")
#: Metrics a tuning study may optimise (Section 8B). These reuse ``evaluate_model``'s
#: own metric keys so the value a trial maximises is exactly the value reported later.
#: All are higher-is-better except ``log_loss`` (the tuner negates it internally).
TUNING_METRICS = (
    "f1_weighted",
    "f1_macro",
    "accuracy",
    "precision_weighted",
    "precision_macro",
    "recall_weighted",
    "recall_macro",
    "roc_auc",
    "pr_auc",
    "mcc",
    "log_loss",
)


DEFAULT_CONFIG: dict[str, Any] = {
    # --- required (placeholders here; build_config fills them) ---
    "input_file": "",
    "target": "",
    "feature_cols": [],
    # --- problem framing ---
    "problem_type": "binary",
    "test_size": 0.2,
    "stratify": True,
    "time_split_col": None,
    # --- modelling ---
    "algorithms": ["LogisticRegression", "RandomForest", "XGBoost"],
    "class_balance": "smote",
    "missing_strategy": "median",
    "encoding_method": "onehot",
    "scaling_method": "standard",
    "outlier_method": "iqr",
    "high_cardinality_threshold": 20,
    "threshold": 0.5,
    "calibrate_probs": True,
    # --- feature engineering (Section 7; FeatureBuilder) ---
    # Each capability is individually toggleable. Polynomial defaults OFF: squared
    # terms are usually redundant with tree models and risk column explosion.
    "feature_engineering": {
        "enabled": True,
        "polynomial": False,
        "ratios": True,
        "binning": True,
        "max_poly_features": 8,
    },
    # --- interaction features (Section 7B; InteractionFeatureBuilder) ---
    "interaction_features": {
        "enabled": True,
        "interaction_pairs": {},
        "default_interactions": ["multiply"],
        "drop_original_if_interacted": False,
        "max_auto_pairs": 10,
        "fill_method": "zero",
    },
    # --- hyperparameter tuning (Section 8B; Optuna) -------------------------------
    # OFF by default. AutoML/search was scope v1.5; pulled into v1.0 as a sanctioned
    # deviation (see plan_tweak.md). One uniform mechanism for all six models, fully
    # controlled at RUN TIME: which models to tune, how hard, and which metric are
    # config dials, not build-time choices.
    "tuning": {
        "enabled": False,  # OFF by default
        "models": [],  # [] or ["all"] → every algorithm in the run; else only these
        "metric": "f1_weighted",  # optimised metric; must be a TUNING_METRICS name
        "cv": True,  # True = k-fold CV within train; False = single train-internal split
        "cv_folds": 3,
        "n_trials": 30,  # per model
        # [RISK] runaway tuning — a HARD per-model wall-clock cap (seconds) so a tuning run
        # can NEVER go unbounded. With models=[] (tune all), enabling tuning would otherwise
        # run a 30-trial study for every algorithm including the slow SVM (calibrated SVC,
        # internal CV per trial); without a cap that is an open-ended run. 600s/model is a
        # safety ceiling, not a target — n_trials usually binds first. Set explicitly to
        # ``None`` to opt out (only do so when scoping with a short ``models`` list).
        "timeout_seconds": 600,  # per model; reach the cap OR n_trials, whichever first
        "search_space_overrides": {},  # optional per-model bound overrides
    },
    "random_state": 42,
}


def _require_non_empty_str(value: Any, field: str) -> str:
    """Validate that ``value`` is a non-empty/whitespace string."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field!r} is required and must be a non-empty string")
    return value


def _require_choice(value: Any, allowed: tuple[str, ...], field: str) -> str:
    """Validate that ``value`` is one of ``allowed``."""
    if value not in allowed:
        raise ValueError(
            f"{field!r} must be one of {list(allowed)}, got {value!r}"
        )
    return value


def build_config(
    input_file: str,
    target: str,
    feature_cols: list[str],
    **overrides: Any,
) -> dict[str, Any]:
    """Build a validated run config from the defaults plus caller overrides.

    A fresh deep copy of :data:`DEFAULT_CONFIG` is produced, the three required
    arguments are applied, then any ``overrides`` are layered on and the whole
    config is validated. The returned dict is independent of both
    :data:`DEFAULT_CONFIG` and the inputs.

    Args:
        input_file: Logical key of the input dataset (resolved by the StorageAdapter).
        target: Name of the target column. Must not appear in ``feature_cols``.
        feature_cols: Feature column names (at least one).
        **overrides: Any other ``DEFAULT_CONFIG`` key to override (e.g.
            ``problem_type="multiclass"``, ``test_size=0.3``).

    Returns:
        A new, validated config dict.

    Raises:
        ValueError: If a required field is empty, ``feature_cols`` is empty, the
            target is also a feature, ``test_size`` is outside ``(0, 0.5]``, an
            unknown override key is supplied, or any enum-valued field is invalid.
    """
    # [RISK] config mutation — we deep-copy the defaults so DEFAULT_CONFIG is never
    # mutated, and the returned dict shares no nested objects (e.g. the
    # interaction_features sub-dict) with it. This is the root of the
    # _run_config isolation pattern that ModelRunner relies on later: configs must
    # be safe to copy and mutate per-run without leaking state across runs.
    config = copy.deepcopy(DEFAULT_CONFIG)

    config["input_file"] = input_file
    config["target"] = target
    config["feature_cols"] = list(feature_cols) if feature_cols is not None else []

    for key, value in overrides.items():
        if key not in DEFAULT_CONFIG:
            raise ValueError(
                f"unknown config key {key!r}; allowed keys: {sorted(DEFAULT_CONFIG)}"
            )
        config[key] = value

    _validate_config(config)
    return config


def _validate_config(config: dict[str, Any]) -> None:
    """Validate a fully-assembled config in place, raising on the first problem."""
    _require_non_empty_str(config["input_file"], "input_file")
    _require_non_empty_str(config["target"], "target")

    feature_cols = config["feature_cols"]
    if not isinstance(feature_cols, list) or len(feature_cols) < 1:
        raise ValueError("'feature_cols' must be a list with at least one column")

    if config["target"] in feature_cols:
        raise ValueError(
            f"target {config['target']!r} must not also appear in feature_cols"
        )

    test_size = config["test_size"]
    if not isinstance(test_size, (int, float)) or not (0 < test_size <= 0.5):
        raise ValueError(f"'test_size' must be in the interval (0, 0.5], got {test_size!r}")

    _require_choice(config["problem_type"], PROBLEM_TYPES, "problem_type")
    _require_choice(config["class_balance"], CLASS_BALANCE, "class_balance")
    _require_choice(config["missing_strategy"], MISSING_STRATEGIES, "missing_strategy")
    _require_choice(config["encoding_method"], ENCODING_METHODS, "encoding_method")
    _require_choice(config["scaling_method"], SCALING_METHODS, "scaling_method")
    _require_choice(config["outlier_method"], OUTLIER_METHODS, "outlier_method")

    threshold = config["high_cardinality_threshold"]
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 1:
        raise ValueError(
            f"'high_cardinality_threshold' must be a positive integer, got {threshold!r}"
        )

    _validate_feature_engineering(config["feature_engineering"])
    _validate_tuning(config["tuning"])


def _validate_tuning(t: Any) -> None:
    """Validate the ``tuning`` sub-dict (Section 8B — Optuna tuning layer)."""
    if not isinstance(t, dict):
        raise ValueError("'tuning' must be a dict")
    for flag in ("enabled", "cv"):
        if flag in t and not isinstance(t[flag], bool):
            raise ValueError(f"'tuning.{flag}' must be a bool, got {t[flag]!r}")

    models = t.get("models", [])
    if not isinstance(models, list) or not all(isinstance(m, str) for m in models):
        raise ValueError("'tuning.models' must be a list of model-name strings")

    metric = t.get("metric", "f1_weighted")
    if metric not in TUNING_METRICS:
        raise ValueError(
            f"'tuning.metric' must be one of {list(TUNING_METRICS)}, got {metric!r}"
        )

    folds = t.get("cv_folds", 3)
    if not isinstance(folds, int) or isinstance(folds, bool) or folds < 2:
        raise ValueError(f"'tuning.cv_folds' must be an integer >= 2, got {folds!r}")

    n_trials = t.get("n_trials", 30)
    if not isinstance(n_trials, int) or isinstance(n_trials, bool) or n_trials < 1:
        raise ValueError(
            f"'tuning.n_trials' must be a positive integer, got {n_trials!r}"
        )

    timeout = t.get("timeout_seconds", None)
    if timeout is not None and (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or timeout <= 0
    ):
        raise ValueError(
            "'tuning.timeout_seconds' must be a positive number or None, "
            f"got {timeout!r}"
        )

    overrides = t.get("search_space_overrides", {})
    if not isinstance(overrides, dict):
        raise ValueError("'tuning.search_space_overrides' must be a dict")


def _validate_feature_engineering(fe: Any) -> None:
    """Validate the ``feature_engineering`` sub-dict (Section 7 — FeatureBuilder)."""
    if not isinstance(fe, dict):
        raise ValueError("'feature_engineering' must be a dict")
    for flag in ("enabled", "polynomial", "ratios", "binning"):
        if flag in fe and not isinstance(fe[flag], bool):
            raise ValueError(
                f"'feature_engineering.{flag}' must be a bool, got {fe[flag]!r}"
            )
    max_poly = fe.get("max_poly_features", 8)
    if not isinstance(max_poly, int) or isinstance(max_poly, bool) or max_poly < 1:
        raise ValueError(
            "'feature_engineering.max_poly_features' must be a positive integer, "
            f"got {max_poly!r}"
        )
