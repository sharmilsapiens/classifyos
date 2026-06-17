"""Tests for the sanctioned Phase 8 curve helper (``evaluation/curves.py``) + plot2 regression.

``compute_curve_points`` is the single source of ROC/PR coordinates for both ``plot2`` and the
API's JSON ``curves``. These tests check the points are well-formed, that multiclass yields
one-vs-rest entries per class, that the helper is structurally incapable of seeing training
data (it fits nothing and takes only test arrays), and that ``plot2`` still renders after the
refactor that routes it through this helper.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import numpy as np

from classifyos.evaluation.curves import compute_curve_points
from classifyos.evaluation.plots import PLOT2_KEY, plot_results
from classifyos.models.registry import build_model


def _binary_proba(y_true: list[str]) -> np.ndarray:
    """Build a 2-column proba aligned to classes ['0','1'] that separates the labels well."""
    pos = np.array([0.9 if y == "1" else 0.15 for y in y_true])
    return np.column_stack([1 - pos, pos])


def test_roc_pr_points_well_formed_binary() -> None:
    """On a known binary split the ROC/PR arrays are aligned, bounded, and monotone."""
    y_true = ["0"] * 50 + ["1"] * 50
    proba = _binary_proba(y_true)
    points = compute_curve_points(y_true, proba, ["0", "1"], "binary")

    # Binary → one entry keyed by the positive (lexicographically-last) class "1".
    assert set(points["roc"]) == {"1"}
    assert set(points["pr"]) == {"1"}

    roc = points["roc"]["1"]
    assert len(roc["fpr"]) == len(roc["tpr"]) == len(roc["thresholds"])
    fpr = np.array(roc["fpr"])
    tpr = np.array(roc["tpr"])
    # roc_curve returns both fpr and tpr in non-decreasing order.
    assert np.all(np.diff(fpr) >= -1e-9)
    assert np.all(np.diff(tpr) >= -1e-9)
    assert fpr.min() >= 0.0 and fpr.max() <= 1.0
    assert tpr.min() >= 0.0 and tpr.max() <= 1.0
    assert 0.0 <= roc["auc"] <= 1.0
    # Well-separated scores → strong AUC.
    assert roc["auc"] > 0.9

    pr = points["pr"]["1"]
    assert len(pr["precision"]) == len(pr["recall"]) == len(pr["thresholds"])
    assert all(0.0 <= p <= 1.0 for p in pr["precision"])
    assert all(0.0 <= r <= 1.0 for r in pr["recall"])
    assert 0.0 <= pr["ap"] <= 1.0


def test_curve_points_multiclass_one_vs_rest() -> None:
    """Multiclass returns a one-vs-rest ROC/PR entry per class present."""
    classes = ["A", "B", "C"]
    y_true = (["A"] * 20) + (["B"] * 20) + (["C"] * 20)
    rng = np.random.default_rng(0)
    proba = rng.dirichlet(np.ones(3), size=60)
    points = compute_curve_points(y_true, proba, classes, "multiclass")
    assert set(points["roc"]) == set(classes)
    assert set(points["pr"]) == set(classes)
    for cls in classes:
        assert "fpr" in points["roc"][cls] and "auc" in points["roc"][cls]


def test_single_class_present_is_omitted() -> None:
    """A target class with only one truth value present is omitted (ROC/PR undefined)."""
    y_true = ["1"] * 30  # only the positive class present
    proba = _binary_proba(y_true)
    points = compute_curve_points(y_true, proba, ["0", "1"], "binary")
    assert points["roc"] == {}
    assert points["pr"] == {}


def test_helper_takes_only_test_arrays_no_training_data() -> None:
    """Structural leakage guard: the signature exposes no way to pass training data."""
    params = list(inspect.signature(compute_curve_points).parameters)
    assert params == ["y_true", "y_proba", "classes", "problem_type"]
    # It is a plain function — no model/estimator to fit.
    assert not hasattr(compute_curve_points, "fit")


def test_plot2_still_renders_via_helper(binary_matrices, storage, output_dir) -> None:
    """Regression: plot2 is produced when its points come from compute_curve_points."""
    model = build_model("LogisticRegression", problem_type="binary")
    model.fit(binary_matrices.X_train, binary_matrices.y_train)
    runner = SimpleNamespace(
        models_={model.name: model},
        metrics_={},  # plot1/5 fall back to placeholders; we only assert plot2 here
        X_test_=binary_matrices.X_test,
        y_test_=binary_matrices.y_test,
        classes_=list(model.classes_),
        problem_type_="binary",
    )
    written = plot_results(runner, storage)
    assert PLOT2_KEY in written
    assert (output_dir / PLOT2_KEY).stat().st_size > 1000
