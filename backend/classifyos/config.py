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
#: Legacy GLOBAL missing-value strategy (back-compat). Applies to a column type only when
#: no per-type override is set (see ``missing_strategy_numeric``/``missing_strategy_categorical``).
#: ``mean``/``median`` are numeric statistics; on a categorical column they fall back to mode
#: in the Preprocessor. ``knn``/``iterative`` are numeric-only and are therefore NOT global —
#: they can only be selected via ``missing_strategy_numeric``.
MISSING_STRATEGIES = ("median", "mean", "mode", "ffill", "bfill", "drop")
#: Strategies selectable for NUMERIC columns via ``missing_strategy_numeric``. Superset of the
#: global set plus the two model-based imputers (sklearn ``KNNImputer`` / ``IterativeImputer``).
MISSING_STRATEGIES_NUMERIC = (
    "median",
    "mean",
    "mode",
    "ffill",
    "bfill",
    "knn",
    "iterative",
    "drop",
)
#: Strategies selectable for NON-NUMERIC (categorical) columns via
#: ``missing_strategy_categorical``. Statistic-based numeric imputers (mean/median/knn/iterative)
#: are intentionally excluded — they are undefined for categorical values.
MISSING_STRATEGIES_CATEGORICAL = ("mode", "ffill", "bfill", "drop")
#: Strategies selectable for a SINGLE column via the ``missing_strategy_by_column`` override map.
#: This is the numeric superset (every strategy the engine knows). Column type is not known at
#: config-build time, so validation only checks membership here; the Preprocessor coerces a
#: numeric-only strategy set on a categorical column back to that type's default at fit time
#: (exactly like the numeric-only-global fallback), so a bad type/strategy pairing never crashes.
MISSING_STRATEGIES_BY_COLUMN = MISSING_STRATEGIES_NUMERIC
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
#: Metric the post-training PERMUTATION importance measures the drop in (the feature is
#: shuffled, the model is re-scored, importance = baseline − permuted). These are the SAME
#: ``evaluate_model`` keys as the tuning metrics — label-based ones (accuracy/F1/precision/
#: recall/MCC) need only ``predict``; probability-based ones (roc_auc/pr_auc/log_loss) need
#: ``predict_proba``. All are higher-is-better except ``log_loss`` (negated internally so the
#: drop stays positive for an important feature). A metric undefined for a problem type (e.g.
#: ``pr_auc`` on multiclass, ``log_loss`` on multilabel) yields no importances for that run.
PERMUTATION_METRICS = TUNING_METRICS

# --- decision policy: probability calibration + decision threshold -------------------
#: Decision-threshold modes (binary problems only — multiclass/multilabel always use the
#: argmax / per-label 0.5 and ignore ``threshold``/``threshold_mode``):
#:   ``default`` — sklearn's built-in 0.5 argmax (the historical behaviour);
#:   ``fixed``   — apply the analyst-supplied ``threshold`` as the positive-class cutoff;
#:   ``tuned``   — pick the cutoff that maximises ``threshold_metric`` on internal CV folds
#:                 of the TRAIN split (sklearn ``TunedThresholdClassifierCV``; leakage-safe —
#:                 the held-out test set is never used to choose the operating point).
THRESHOLD_MODES = ("default", "fixed", "tuned")
#: Metrics a TUNED threshold may maximise. These are sklearn scorer names that depend on the
#: hard label prediction, so sweeping the cutoff actually changes the score — ranking metrics
#: like ROC-AUC / average-precision are threshold-INDEPENDENT and are therefore excluded.
THRESHOLD_METRICS = (
    "f1",
    "f1_weighted",
    "f1_macro",
    "balanced_accuracy",
    "accuracy",
    "precision",
    "recall",
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
    # Missing-value treatment is split BY FEATURE TYPE. ``missing_strategy`` is the legacy
    # GLOBAL default kept for back-compat; the two per-type keys override it when set (non-None).
    # A run that sets only ``missing_strategy`` behaves exactly as before. The UI drives the two
    # per-type selectors (median for numeric, mode for categorical by default), so e.g. "mean" is
    # never wrongly applied to a non-numeric column.
    "missing_strategy": "median",
    "missing_strategy_numeric": None,  # None → inherit the global; else a MISSING_STRATEGIES_NUMERIC value
    "missing_strategy_categorical": None,  # None → inherit (mode if the global is numeric-only)
    # Optional PER-COLUMN overrides: {column_name: strategy}. A named column uses its own strategy
    # instead of the per-type default above; any column NOT listed keeps the per-type behaviour.
    # Default {} → no override, a run is byte-identical to the per-type-only behaviour. Values must
    # be a MISSING_STRATEGIES_BY_COLUMN member; a numeric-only strategy (mean/median/knn/iterative)
    # named on a categorical column is coerced back to that column's type default by the engine.
    "missing_strategy_by_column": {},
    "encoding_method": "onehot",
    "scaling_method": "standard",
    "outlier_method": "iqr",
    "high_cardinality_threshold": 20,
    # --- decision policy (binary problems) ---
    # ``threshold_mode`` chooses how predicted probabilities become a positive-class label:
    #   "default" → sklearn's 0.5 argmax (historical behaviour);
    #   "fixed"   → use ``threshold`` (below) as the cutoff;
    #   "tuned"   → maximise ``threshold_metric`` on internal CV folds of TRAIN
    #               (TunedThresholdClassifierCV — leakage-safe, never sees the test set).
    # ``threshold`` is consumed ONLY in "fixed" mode; ``threshold_metric`` ONLY in "tuned".
    # Multiclass/multilabel ignore all three (argmax / per-label 0.5). The effective operating
    # threshold actually used by each model is reported back on the run result.
    "threshold": 0.5,
    "threshold_mode": "default",
    "threshold_metric": "f1",
    # When True, each model's probabilities are calibrated via CalibratedClassifierCV (fit on
    # the TRAIN split only — leakage-safe) so a predicted 0.8 reflects ~80% observed frequency.
    # Binary + multiclass; skipped for the SVM (already internally calibrated) and multilabel.
    # [RISK] cost — calibration adds internal CV refits, so a calibrated run is slower.
    "calibrate_probs": True,
    # Metric the post-training PERMUTATION importance scores the drop in (see
    # PERMUTATION_METRICS). Default F1-weighted = the engine's primary metric. Selectable from
    # the UI; the native importance is unaffected (it has no metric).
    "permutation_metric": "f1_weighted",
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
    # --- per-row explainability (Explainability; SHAP) ---------------------------
    # OFF by default (opt-in). Computes local, per-row SHAP contributions during the run
    # (models are still fitted in memory), shipped in the /run response — the same
    # compute-during-run pattern as feature_importance / permutation_importance, so no model
    # persistence is needed. Covers ALL six models (TreeExplainer for the tree models,
    # KernelExplainer for LogisticRegression/SVM/NaiveBayes). [RISK] cost — KernelExplainer
    # (SVM/NaiveBayes) is the slow path, which is why it is opt-in and bounded to a small row
    # sample. Binary + multiclass only (multilabel returns nothing).
    "explainability": {
        "enabled": False,        # OFF by default
        "sample_rows": 20,       # first N held-out TEST rows per model to explain
        "background_size": 100,  # TRAIN rows sampled as the SHAP reference distribution
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
    num_strategy = config.get("missing_strategy_numeric")
    if num_strategy is not None:
        _require_choice(
            num_strategy, MISSING_STRATEGIES_NUMERIC, "missing_strategy_numeric"
        )
    cat_strategy = config.get("missing_strategy_categorical")
    if cat_strategy is not None:
        _require_choice(
            cat_strategy, MISSING_STRATEGIES_CATEGORICAL, "missing_strategy_categorical"
        )
    _validate_missing_by_column(config.get("missing_strategy_by_column", {}))
    _require_choice(config["encoding_method"], ENCODING_METHODS, "encoding_method")
    _require_choice(config["scaling_method"], SCALING_METHODS, "scaling_method")
    _require_choice(config["outlier_method"], OUTLIER_METHODS, "outlier_method")
    _require_choice(
        config["permutation_metric"], PERMUTATION_METRICS, "permutation_metric"
    )

    # decision policy (calibration + threshold)
    _require_choice(config["threshold_mode"], THRESHOLD_MODES, "threshold_mode")
    _require_choice(config["threshold_metric"], THRESHOLD_METRICS, "threshold_metric")
    decision_threshold = config["threshold"]
    if (
        not isinstance(decision_threshold, (int, float))
        or isinstance(decision_threshold, bool)
        or not (0.0 < decision_threshold < 1.0)
    ):
        raise ValueError(
            f"'threshold' must be a number in the open interval (0, 1), "
            f"got {decision_threshold!r}"
        )
    if not isinstance(config["calibrate_probs"], bool):
        raise ValueError(
            f"'calibrate_probs' must be a bool, got {config['calibrate_probs']!r}"
        )

    threshold = config["high_cardinality_threshold"]
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 1:
        raise ValueError(
            f"'high_cardinality_threshold' must be a positive integer, got {threshold!r}"
        )

    _validate_feature_engineering(config["feature_engineering"])
    _validate_tuning(config["tuning"])
    _validate_explainability(config["explainability"])
    _validate_user_features(config["user_features"])


def _validate_missing_by_column(by_col: Any) -> None:
    """Validate the ``missing_strategy_by_column`` override map.

    Each key must be a non-empty column-name string and each value a
    :data:`MISSING_STRATEGIES_BY_COLUMN` member. Column existence and
    numeric/categorical type-compatibility are NOT checked here (the columns are
    not known until a dataset is loaded); the Preprocessor coerces a per-type-invalid
    strategy back to the column type's default at fit time, mirroring how a
    numeric-only global falls back to mode for categorical columns.
    """
    if not isinstance(by_col, dict):
        raise ValueError("'missing_strategy_by_column' must be a dict of {column: strategy}")
    for col, strategy in by_col.items():
        if not isinstance(col, str) or not col.strip():
            raise ValueError(
                f"'missing_strategy_by_column' keys must be non-empty column names, got {col!r}"
            )
        _require_choice(
            strategy, MISSING_STRATEGIES_BY_COLUMN, f"missing_strategy_by_column[{col!r}]"
        )


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


def _validate_explainability(e: Any) -> None:
    """Validate the ``explainability`` sub-dict (per-row SHAP; opt-in)."""
    if not isinstance(e, dict):
        raise ValueError("'explainability' must be a dict")
    if "enabled" in e and not isinstance(e["enabled"], bool):
        raise ValueError(f"'explainability.enabled' must be a bool, got {e['enabled']!r}")
    for key in ("sample_rows", "background_size"):
        value = e.get(key)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 1
        ):
            raise ValueError(
                f"'explainability.{key}' must be a positive integer, got {value!r}"
            )


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
