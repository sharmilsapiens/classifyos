"""Tests for per-row SHAP explanations (:mod:`classifyos.analysis.explain`).

These exercise ``explain_rows`` through the real model wrappers on fully-engineered
insurance matrices (see ``conftest.build_matrices``). The contract:

* the explanation is **additive** — ``base_value + Σ contributions == prediction`` — for
  BOTH explainer families (TreeExplainer for the tree models, KernelExplainer for the rest);
* every model is covered, including the RBF-SVM / GaussianNB that expose no native importance;
* it is **leakage-safe** — nothing is refit and the explained TEST matrix is never mutated;
* multiclass explains the predicted class; multilabel is unsupported (returns ``None``).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from classifyos.analysis.explain import explain_rows
from classifyos.models.registry import build_model


def _fitted(name, matrices, *, calibrate=True):
    """Build a wrapper with the default decision policy and fit it on the matrices."""
    model = build_model(name, problem_type=matrices.config["problem_type"])
    if hasattr(model, "set_decision_policy"):
        model.set_decision_policy(
            calibrate=calibrate, threshold_mode="default", threshold=0.5, threshold_metric="f1"
        )
    model.fit(matrices.X_train, matrices.y_train)
    return model


def _explain(model, matrices, *, sample_rows=4):
    return explain_rows(
        model,
        matrices.X_train,
        matrices.X_test.head(sample_rows),
        matrices.config["problem_type"],
        background_size=40,
        random_state=0,
    )


@pytest.mark.parametrize(
    "name,expected_method",
    [
        ("RandomForest", "shap.TreeExplainer"),
        ("XGBoost", "shap.TreeExplainer"),
        ("LogisticRegression", "shap.KernelExplainer"),
        ("SVM", "shap.KernelExplainer"),
        ("NaiveBayes", "shap.KernelExplainer"),
    ],
)
def test_explanations_additive_for_all_model_families(name, expected_method, binary_matrices) -> None:
    """Every model is explained, and each row is SHAP-additive (base + Σ == prediction).

    Covers both explainer families and both no-native-importance models (SVM, NaiveBayes).
    """
    model = _fitted(name, binary_matrices)
    result = _explain(model, binary_matrices)
    assert result is not None
    assert result["method"] == expected_method
    assert len(result["rows"]) == 4
    for row in result["rows"]:
        assert set(row["contributions"]) == set(binary_matrices.X_test.columns)
        recon = row["base_value"] + sum(row["contributions"].values())
        assert math.isclose(recon, row["prediction"], abs_tol=1e-6)


def test_explanation_does_not_mutate_test_matrix(binary_matrices) -> None:
    """Leakage/side-effect guard: the explained TEST matrix is untouched (a private read)."""
    model = _fitted("RandomForest", binary_matrices)
    X = binary_matrices.X_test.head(4)
    before = X.copy(deep=True)
    explain_rows(model, binary_matrices.X_train, X, "binary", background_size=40, random_state=0)
    assert X.equals(before)


def test_multiclass_explains_predicted_class(multiclass_matrices) -> None:
    """Multiclass: each row's ``explained_class`` is a real class label and stays additive."""
    model = _fitted("RandomForest", multiclass_matrices)
    result = _explain(model, multiclass_matrices)
    assert result is not None
    classes = {str(c) for c in np.asarray(model.classes_)}
    for row in result["rows"]:
        assert row["explained_class"] in classes
        recon = row["base_value"] + sum(row["contributions"].values())
        assert math.isclose(recon, row["prediction"], abs_tol=1e-6)


def test_multilabel_is_unsupported(binary_matrices) -> None:
    """Multilabel has no single waterfall to draw → ``None`` (unsupported in v1)."""
    model = _fitted("RandomForest", binary_matrices)
    # problem_type is what gates support, independent of the fitted matrices here.
    assert explain_rows(
        model, binary_matrices.X_train, binary_matrices.X_test.head(2), "multilabel"
    ) is None


def test_empty_explain_set_returns_none(binary_matrices) -> None:
    """Nothing to explain (no rows) → ``None`` rather than an empty structure."""
    model = _fitted("RandomForest", binary_matrices)
    empty = binary_matrices.X_test.head(0)
    assert explain_rows(model, binary_matrices.X_train, empty, "binary") is None
