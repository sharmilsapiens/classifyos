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

# --- user-defined feature engineering (UserFeatureBuilder) ---------------------------
# Fixed allowlists for STRUCTURED user features. The user picks
# [column(s)] + [operation from these allowlists] + [a new name]; the engine applies
# KNOWN operations to KNOWN columns. There is NO free-text formula and NOTHING is ever
# eval()'d — keeping these allowlists next to the config validation is the safety guard
# at the config boundary (see backend/classifyos/preprocessing/user_features.py).
USER_FEATURE_TYPES = ("numeric", "datetime_diff", "single")
#: Two-column numeric operations (both columns must be numeric). ``ratio`` is an alias of
#: ``divide``; both apply the same near-zero-denominator guard as the ratio features.
USER_FEATURE_NUMERIC_OPS = ("add", "subtract", "multiply", "divide", "ratio")
#: Single-column transforms that require a NUMERIC source column.
USER_FEATURE_SINGLE_NUMERIC_OPS = ("log", "abs", "bin")
#: Single-column transforms that require a DATETIME source column (date-part extraction).
USER_FEATURE_SINGLE_DATE_OPS = ("year", "month", "day", "dayofweek", "hour")
USER_FEATURE_SINGLE_OPS = USER_FEATURE_SINGLE_NUMERIC_OPS + USER_FEATURE_SINGLE_DATE_OPS
#: Datetime-difference operations (two datetime columns → a numeric duration).
USER_FEATURE_DATETIME_DIFF_OPS = ("subtract",)
#: Allowed duration units for ``datetime_diff`` (default ``days``).
USER_FEATURE_DATETIME_UNITS = ("seconds", "minutes", "hours", "days")


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
    # --- user-defined features (UserFeatureBuilder) ------------------------------
    # A list of STRUCTURED specs derived from existing columns. Default [] → the
    # feature is OFF and a run is identical to having no key at all. Each spec is a dict,
    # e.g. {"name": "duration_days", "op": "subtract", "type": "datetime_diff",
    #       "col_a": "end_time", "col_b": "start_time", "unit": "days"}
    #       {"name": "premium_per_sum", "op": "divide", "type": "numeric",
    #        "col_a": "annual_premium", "col_b": "sum_assured"}
    #       {"name": "log_claim", "op": "log", "type": "single", "col_a": "claim_amount"}
    # NO free-text formula is ever accepted or eval()'d — only the fixed allowlists above.
    "user_features": [],
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
        "n_trials": 30,  # per model — with no timeout (below) this is the SOLE bound on a study
        # [RISK] runaway tuning — there is NO default wall-clock cap (``timeout_seconds=None``):
        # by owner request (2026-06-26, plan_tweak #43) the per-model timeout is OFF by default so
        # a study always runs the full ``n_trials``. **``n_trials`` is therefore the only thing
        # bounding a study** — it must stay a finite positive int (it always defaults to 30), or an
        # enabled ``models=[]`` (tune-all) run, which fits every algorithm incl. the slow calibrated
        # SVM, becomes open-ended. Set ``timeout_seconds`` to a positive number to re-impose a hard
        # ceiling (reach the cap OR n_trials, whichever first) — recommended for large data or a
        # long ``n_trials``. This reverses the earlier 600s default (plan_tweak #25).
        "timeout_seconds": None,  # per model; None = no cap (n_trials bounds the study)
        "search_space_overrides": {},  # optional per-model bound/choice overrides (engine ``_b``/``_ch``)
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
    _validate_user_features(config["user_features"])


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


def _validate_user_features(specs: Any) -> None:
    """Validate the ``user_features`` list (UserFeatureBuilder).

    This is the allowlist guard at the config boundary: every spec must reference a
    valid ``type`` and an ``op`` permitted for that type (rejecting unknown ops/types
    up front), supply string column references, and carry a non-empty, unique ``name``.
    Column existence and type-compatibility are NOT checked here (the columns are not
    known until a dataset is loaded) — those are validated at fit time by the builder.
    """
    if not isinstance(specs, list):
        raise ValueError("'user_features' must be a list of feature specs")

    seen_names: set[str] = set()
    for i, spec in enumerate(specs):
        where = f"user_features[{i}]"
        if not isinstance(spec, dict):
            raise ValueError(f"{where} must be a dict, got {spec!r}")

        name = spec.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{where}.name must be a non-empty string")
        if name in seen_names:
            raise ValueError(f"{where}.name {name!r} is duplicated in user_features")
        seen_names.add(name)

        ftype = spec.get("type")
        if ftype not in USER_FEATURE_TYPES:
            raise ValueError(
                f"{where}.type must be one of {list(USER_FEATURE_TYPES)}, got {ftype!r}"
            )

        op = spec.get("op")
        if ftype == "numeric":
            allowed_ops = USER_FEATURE_NUMERIC_OPS
        elif ftype == "datetime_diff":
            allowed_ops = USER_FEATURE_DATETIME_DIFF_OPS
        else:  # single
            allowed_ops = USER_FEATURE_SINGLE_OPS
        if op not in allowed_ops:
            raise ValueError(
                f"{where}.op must be one of {list(allowed_ops)} for type {ftype!r}, "
                f"got {op!r}"
            )

        if not isinstance(spec.get("col_a"), str) or not spec["col_a"].strip():
            raise ValueError(f"{where}.col_a must be a non-empty column-name string")

        # Two-column types need a second column; single transforms must not have one.
        if ftype in ("numeric", "datetime_diff"):
            if not isinstance(spec.get("col_b"), str) or not spec["col_b"].strip():
                raise ValueError(
                    f"{where}.col_b must be a non-empty column-name string for "
                    f"type {ftype!r}"
                )

        if ftype == "datetime_diff":
            unit = spec.get("unit", "days")
            if unit not in USER_FEATURE_DATETIME_UNITS:
                raise ValueError(
                    f"{where}.unit must be one of {list(USER_FEATURE_DATETIME_UNITS)}, "
                    f"got {unit!r}"
                )


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
