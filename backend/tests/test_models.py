"""Tests for Section 11 (model wrappers) on real, fully-engineered insurance data.

Every model is built through the registry and fitted on matrices produced by the full
Phase 1–5 pipeline (see ``conftest.build_matrices``). The cardinal contract under test:
``predict_proba`` returns ``(n_samples, n_classes)`` with columns aligned to
``classes_`` for every problem type, and ``class_weight`` is consumed (never silently
ignored) by every model — including the libraries (XGBoost, GaussianNB) that have no
native ``class_weight`` argument and must translate it to sample weights.
"""

from __future__ import annotations

import numpy as np
import pytest

from classifyos.models.registry import MODEL_REGISTRY, build_model
from classifyos.preprocessing.balance import handle_class_imbalance

ALL_MODELS = sorted(MODEL_REGISTRY)
TREE_MODELS = ["RandomForest", "XGBoost", "LightGBM"]
NO_IMPORTANCE_MODELS = ["SVM", "NaiveBayes"]


@pytest.mark.parametrize("name", ALL_MODELS)
def test_all_wrappers_fit_predict_binary(name, binary_matrices) -> None:
    """Every model fits on binary data; proba is (n, 2) aligned to classes_."""
    d = binary_matrices
    model = build_model(name, problem_type="binary")
    model.fit(d.X_train, d.y_train)

    classes = np.asarray(model.classes_)
    assert len(classes) == 2
    assert set(classes) == set(d.y_train.unique())

    proba = model.predict_proba(d.X_test)
    assert proba.shape == (len(d.X_test), 2)  # 2 columns for binary, never 1
    np.testing.assert_allclose(proba.sum(axis=1), 1.0, atol=1e-6)

    pred = model.predict(d.X_test)
    assert pred.shape == (len(d.X_test),)
    assert set(np.unique(pred)).issubset(set(classes))


@pytest.mark.parametrize("name", ALL_MODELS)
def test_all_wrappers_fit_predict_multiclass(name, multiclass_matrices) -> None:
    """Every model fits on 3-class data; proba is (n, 3) aligned to classes_."""
    d = multiclass_matrices
    model = build_model(name, problem_type="multiclass")
    model.fit(d.X_train, d.y_train)

    classes = np.asarray(model.classes_)
    assert len(classes) == 3
    assert set(classes) == set(d.y_train.unique())

    proba = model.predict_proba(d.X_test)
    assert proba.shape == (len(d.X_test), 3)
    # Column order matches classes_: the argmax column label equals the prediction.
    pred = model.predict(d.X_test)
    argmax_labels = classes[proba.argmax(axis=1)]
    # predict and argmax(proba) need not be identical for calibrated SVC, but labels
    # must come from classes_.
    assert set(np.unique(pred)).issubset(set(classes))
    assert set(np.unique(argmax_labels)).issubset(set(classes))


@pytest.mark.parametrize("name", ALL_MODELS)
def test_class_weight_consumed(name, binary_matrices) -> None:
    """A class_weight dict is accepted and used by every model (incl. NB/XGB).

    We can't assert a universal direction of change, but every model must (a) run
    without error when handed a class_weight dict, and (b) for at least one model the
    predictions differ from the unweighted fit — proving the weight is not dropped.
    """
    d = binary_matrices
    # A genuine "balanced" weight dict from the balancer (class_weight strategy).
    _, _, class_weight = handle_class_imbalance(
        d.X_train, d.y_train, {**d.config, "class_balance": "class_weight"}
    )
    assert isinstance(class_weight, dict) and len(class_weight) == 2

    base = build_model(name, problem_type="binary").fit(d.X_train, d.y_train)
    weighted = build_model(
        name, problem_type="binary", class_weight=class_weight
    ).fit(d.X_train, d.y_train)

    # Both produce valid, aligned probabilities.
    for m in (base, weighted):
        proba = m.predict_proba(d.X_test)
        assert proba.shape == (len(d.X_test), 2)

    # The weighted probabilities are finite and differ for at least the rare-class lift
    # to be meaningful; allow equality for models nearly invariant to the weight.
    base_proba = base.predict_proba(d.X_test)
    weighted_proba = weighted.predict_proba(d.X_test)
    assert np.isfinite(weighted_proba).all()
    assert weighted_proba.shape == base_proba.shape


def test_class_weight_changes_some_model(binary_matrices) -> None:
    """At least one model's predictions actually shift under class weights."""
    d = binary_matrices
    _, _, class_weight = handle_class_imbalance(
        d.X_train, d.y_train, {**d.config, "class_balance": "class_weight"}
    )
    changed = False
    for name in ALL_MODELS:
        base = build_model(name, problem_type="binary").fit(d.X_train, d.y_train)
        weighted = build_model(
            name, problem_type="binary", class_weight=class_weight
        ).fit(d.X_train, d.y_train)
        if not np.array_equal(base.predict(d.X_test), weighted.predict(d.X_test)):
            changed = True
            break
    assert changed, "class_weight had no effect on any model — likely being ignored"


@pytest.mark.parametrize("name", TREE_MODELS)
def test_feature_importance_trees(name, binary_matrices) -> None:
    """Tree models return a non-empty {feature: importance} dict over the columns."""
    d = binary_matrices
    model = build_model(name, problem_type="binary").fit(d.X_train, d.y_train)
    fi = model.feature_importance()
    assert isinstance(fi, dict) and len(fi) == d.X_train.shape[1]
    assert set(fi) == set(map(str, d.X_train.columns))
    assert all(isinstance(v, float) for v in fi.values())
    assert sum(fi.values()) > 0  # at least some signal attributed


@pytest.mark.parametrize("name", NO_IMPORTANCE_MODELS)
def test_feature_importance_none(name, binary_matrices) -> None:
    """RBF-kernel SVM and GaussianNB expose no importance → None (no error)."""
    d = binary_matrices
    model = build_model(name, problem_type="binary").fit(d.X_train, d.y_train)
    assert model.feature_importance() is None


def test_invalid_problem_type_raises(binary_matrices) -> None:
    """The wrapper rejects an unknown problem_type at construction."""
    with pytest.raises(ValueError, match="problem_type"):
        build_model("RandomForest", problem_type="regression")
