"""Tests for Section 12 (``MODEL_REGISTRY`` / ``build_model``)."""

from __future__ import annotations

import pytest

from classifyos.models.base import ModelWrapper
from classifyos.models.registry import MODEL_REGISTRY, build_model


def test_registry_has_six_models() -> None:
    """The registry exposes exactly the six scoped models, all ModelWrapper subclasses."""
    assert set(MODEL_REGISTRY) == {
        "LogisticRegression",
        "RandomForest",
        "XGBoost",
        "LightGBM",
        "SVM",
        "NaiveBayes",
    }
    assert all(issubclass(cls, ModelWrapper) for cls in MODEL_REGISTRY.values())
    # Each wrapper's ``name`` matches its registry key (the registry is the contract).
    assert all(cls.name == key for key, cls in MODEL_REGISTRY.items())


def test_build_model_returns_wrapper() -> None:
    """build_model returns an unfitted wrapper of the right type."""
    model = build_model("RandomForest", problem_type="binary", random_state=7)
    assert isinstance(model, MODEL_REGISTRY["RandomForest"])
    assert model.problem_type == "binary"
    assert model.random_state == 7
    assert model.classes_ is None  # unfitted


@pytest.mark.parametrize(
    "alias,expected",
    [
        ("LR", "LogisticRegression"),
        ("lr", "LogisticRegression"),
        ("RF", "RandomForest"),
        ("XGB", "XGBoost"),
        ("xgb", "XGBoost"),
        ("LGBM", "LightGBM"),
        ("LightGBM", "LightGBM"),
        ("lightgbm", "LightGBM"),
        ("SVM", "SVM"),
        ("svc", "SVM"),
        ("NB", "NaiveBayes"),
    ],
)
def test_aliases_resolve(alias, expected) -> None:
    """Short aliases (case-insensitive) resolve to the canonical wrapper class."""
    model = build_model(alias, problem_type="binary")
    assert isinstance(model, MODEL_REGISTRY[expected])
    assert model.name == expected


def test_registry_unknown() -> None:
    """An unknown name raises ValueError that lists the valid keys."""
    with pytest.raises(ValueError) as exc:
        build_model("nope", problem_type="binary")
    msg = str(exc.value)
    assert "nope" in msg
    for key in MODEL_REGISTRY:
        assert key in msg  # the error is actionable — every valid key is listed


def test_extra_params_forwarded() -> None:
    """Extra kwargs land on the wrapper's params (forwarded to the estimator)."""
    model = build_model("RandomForest", problem_type="binary", n_estimators=11)
    assert model.params.get("n_estimators") == 11
