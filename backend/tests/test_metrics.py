"""Tests for Section 10 (``evaluate_model``) on real, fully-engineered data.

Every returned dict must be JSON-serializable (``json.dumps`` succeeds) — this catches
stray numpy scalars, which is a recurring serialization bug at the API boundary.
"""

from __future__ import annotations

import json

import numpy as np

from classifyos.evaluation.metrics import evaluate_model
from classifyos.models.registry import build_model


def _fit_and_score(d, problem_type):
    """Fit a fast model and return (y_true, y_pred, y_proba, classes)."""
    model = build_model("RandomForest", problem_type=problem_type, n_estimators=60)
    model.fit(d.X_train, d.y_train)
    y_proba = model.predict_proba(d.X_test)
    y_pred = model.predict(d.X_test)
    return np.asarray(d.y_test), y_pred, y_proba, np.asarray(model.classes_)


def test_evaluate_model_binary(binary_matrices) -> None:
    """All core metrics present; 2x2 confusion; both classes in the report; JSON-safe."""
    y_true, y_pred, y_proba, classes = _fit_and_score(binary_matrices, "binary")
    result = evaluate_model(y_true, y_pred, y_proba, "binary", classes)

    for key in (
        "accuracy",
        "precision_weighted",
        "precision_macro",
        "recall_weighted",
        "recall_macro",
        "f1_weighted",
        "f1_macro",
        "roc_auc",
        "pr_auc",
        "log_loss",
        "mcc",
    ):
        assert key in result

    assert result["roc_auc"] is not None and 0.0 <= result["roc_auc"] <= 1.0
    assert result["pr_auc"] is not None
    assert result["log_loss"] is not None and result["log_loss"] >= 0.0

    cm = result["confusion_matrix"]
    assert len(cm) == 2 and all(len(row) == 2 for row in cm)

    report = result["classification_report"]
    for cls in classes:
        assert str(cls) in report
        assert {"precision", "recall", "f1-score", "support"} <= set(report[str(cls)])

    calib = result["calibration_curve"]
    assert calib is not None
    assert len(calib["fraction_of_positives"]) == len(calib["mean_predicted_value"])

    # JSON-serializable: no stray numpy scalars anywhere in the structure.
    json.dumps(result)


def test_evaluate_model_multiclass(multiclass_matrices) -> None:
    """3-class: macro/weighted metrics present, 3x3 confusion, ROC-AUC via ovr."""
    y_true, y_pred, y_proba, classes = _fit_and_score(multiclass_matrices, "multiclass")
    result = evaluate_model(y_true, y_pred, y_proba, "multiclass", classes)

    assert result["f1_weighted"] is not None
    assert result["f1_macro"] is not None
    assert result["roc_auc"] is not None  # ovr-weighted multiclass AUC
    assert result["pr_auc"] is None  # PR-AUC is a binary-only metric here
    assert result["calibration_curve"] is None  # binary-only

    cm = result["confusion_matrix"]
    assert len(cm) == 3 and all(len(row) == 3 for row in cm)
    assert len(result["labels"]) == 3

    json.dumps(result)


def test_imbalanced_metrics(fraud_smote_matrices) -> None:
    """On fraud (SMOTE train, raw test) MCC and ROC-AUC are computed and finite."""
    y_true, y_pred, y_proba, classes = _fit_and_score(fraud_smote_matrices, "binary")
    result = evaluate_model(y_true, y_pred, y_proba, "binary", classes)

    assert result["mcc"] is not None and np.isfinite(result["mcc"])
    assert result["roc_auc"] is not None and np.isfinite(result["roc_auc"])
    assert result["pr_auc"] is not None and np.isfinite(result["pr_auc"])
    json.dumps(result)


def test_single_class_present_guards(binary_matrices) -> None:
    """ROC-AUC/calibration return None (not raise) when y_true has only one class."""
    d = binary_matrices
    model = build_model("RandomForest", problem_type="binary", n_estimators=40)
    model.fit(d.X_train, d.y_train)
    classes = np.asarray(model.classes_)

    # Degenerate evaluation set: all true labels are a single class.
    one = classes[0]
    n = 20
    y_true = np.array([one] * n)
    y_proba = model.predict_proba(d.X_test.iloc[:n])
    y_pred = model.predict(d.X_test.iloc[:n])
    result = evaluate_model(y_true, y_pred, y_proba, "binary", classes)

    assert result["roc_auc"] is None
    assert result["pr_auc"] is None
    assert result["calibration_curve"] is None
    assert result["accuracy"] is not None  # still computable
    json.dumps(result)
