"""Section 12 — :data:`MODEL_REGISTRY` and :func:`build_model`.

The registry is the single place models are wired into the engine. The "additive
sections" rule (CLAUDE.md) means a new model is added HERE — a new wrapper class plus an
entry in :data:`MODEL_REGISTRY` — and never by editing an existing wrapper. The browser
sends algorithm names as strings; :func:`build_model` resolves a name (or a short alias)
to a wrapper class and constructs it.
"""

from __future__ import annotations

from typing import Any

from .base import ModelWrapper
from .wrappers import (
    LightGBMModel,
    LogisticRegressionModel,
    NaiveBayesModel,
    RandomForestModel,
    SVMModel,
    XGBoostModel,
)

#: Canonical name → wrapper class. New models are added here ONLY (additive rule).
MODEL_REGISTRY: dict[str, type[ModelWrapper]] = {
    "LogisticRegression": LogisticRegressionModel,
    "RandomForest": RandomForestModel,
    "XGBoost": XGBoostModel,
    "LightGBM": LightGBMModel,
    "SVM": SVMModel,
    "NaiveBayes": NaiveBayesModel,
}

#: Short aliases (upper-cased) → canonical key. Convenience for configs/CLI.
_ALIASES: dict[str, str] = {
    "LR": "LogisticRegression",
    "LOGREG": "LogisticRegression",
    "RF": "RandomForest",
    "XGB": "XGBoost",
    "LGBM": "LightGBM",
    "GBM": "LightGBM",
    "NB": "NaiveBayes",
    "GAUSSIANNB": "NaiveBayes",
    "SVC": "SVM",
}


def _resolve(name: str) -> str:
    """Resolve a model name or alias (case-insensitive) to a canonical registry key."""
    if name in MODEL_REGISTRY:
        return name
    upper = name.strip().upper()
    for key in MODEL_REGISTRY:
        if key.upper() == upper:
            return key
    if upper in _ALIASES:
        return _ALIASES[upper]
    raise ValueError(
        f"unknown model {name!r}; valid keys: {sorted(MODEL_REGISTRY)} "
        f"(aliases: {sorted(_ALIASES)})"
    )


def build_model(
    name: str,
    problem_type: str,
    class_weight: dict[Any, float] | None = None,
    random_state: int = 42,
    **params: Any,
) -> ModelWrapper:
    """Construct a model wrapper by name (or alias).

    Args:
        name: A registry key (e.g. ``"RandomForest"``) or a short alias (``"RF"``,
            ``"LR"``, ``"XGB"``, ``"LGBM"``, ``"SVM"``, ``"NB"``); case-insensitive.
        problem_type: ``"binary"`` | ``"multiclass"`` | ``"multilabel"``.
        class_weight: Optional ``{class: weight}`` dict from
            :func:`classifyos.preprocessing.balance.handle_class_imbalance`.
        random_state: Seed forwarded to estimators that accept one.
        **params: Extra estimator keyword arguments.

    Returns:
        An unfitted :class:`~classifyos.models.base.ModelWrapper` instance.

    Raises:
        ValueError: If ``name`` resolves to no known model (lists valid keys/aliases).
    """
    key = _resolve(name)
    wrapper_cls = MODEL_REGISTRY[key]
    return wrapper_cls(
        problem_type=problem_type,
        class_weight=class_weight,
        random_state=random_state,
        **params,
    )
