"""Section 10 — ``evaluate_model``.

Computes a single, JSON-serializable dict of classification metrics from true labels,
predicted labels, and predicted probabilities. The same function serves binary,
multiclass, and multilabel problems; metrics that are undefined for a given input
(ROC-AUC with only one class present, calibration for non-binary, log-loss when a
probability column is degenerate) are guarded and returned as ``None`` rather than
raising.

[RISK] Accuracy is misleading on imbalanced data (a 99% no-fraud baseline scores 0.99 by
predicting "never fraud"). The default stance is **F1-weighted as the primary metric**,
with **MCC** and **PR-AUC (average precision)** emphasised on imbalanced binary problems
— all three are reported here so the dashboard never leads with accuracy alone.

Every value in the returned dict is a plain Python type (``float``/``int``/``list``/
``dict``/``None``) — no numpy scalars — so ``json.dumps`` on the result always succeeds.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.calibration import calibration_curve
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    classification_report,
    confusion_matrix,
    f1_score,
    log_loss,
    matthews_corrcoef,
    precision_score,
    recall_score,
    roc_auc_score,
)


def evaluate_model(
    y_true: Any,
    y_pred: Any,
    y_proba: Any,
    problem_type: str,
    classes: Any,
) -> dict[str, Any]:
    """Compute a JSON-serializable dict of classification metrics.

    Args:
        y_true: True labels. For binary/multiclass a 1-D array of class labels; for
            multilabel a 2-D ``(n_samples, n_labels)`` binary indicator matrix.
        y_pred: Predicted labels, same shape/space as ``y_true``.
        y_proba: Predicted probabilities of shape ``(n_samples, n_classes)`` with
            columns ordered to match ``classes`` (i.e. a model wrapper's
            ``predict_proba`` output).
        problem_type: ``"binary"`` | ``"multiclass"`` | ``"multilabel"``.
        classes: The class labels in the same order as ``y_proba`` columns (a model
            wrapper's ``classes_``).

    Returns:
        A dict with accuracy, weighted+macro precision/recall/F1, ROC-AUC, PR-AUC
        (binary), log-loss, MCC, the confusion matrix (nested list in ``classes``
        order), a per-class classification report, and binary calibration-curve data.
        Undefined metrics are ``None``.
    """
    classes_list = [_native(c) for c in np.asarray(classes).tolist()]

    if problem_type == "multilabel":
        result = _evaluate_multilabel(y_true, y_pred, y_proba, classes_list)
    else:
        result = _evaluate_single_label(
            y_true, y_pred, y_proba, problem_type, classes, classes_list
        )

    result["problem_type"] = problem_type
    result["labels"] = classes_list
    return _jsonify(result)


def _evaluate_single_label(
    y_true: Any,
    y_pred: Any,
    y_proba: Any,
    problem_type: str,
    classes: Any,
    classes_list: list[Any],
) -> dict[str, Any]:
    """Metrics for binary / multiclass single-label problems."""
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    y_proba = np.asarray(y_proba)
    labels = np.asarray(classes)

    result: dict[str, Any] = {
        "accuracy": accuracy_score(y_true, y_pred),
        "precision_weighted": precision_score(
            y_true, y_pred, average="weighted", zero_division=0
        ),
        "precision_macro": precision_score(
            y_true, y_pred, average="macro", zero_division=0
        ),
        "recall_weighted": recall_score(
            y_true, y_pred, average="weighted", zero_division=0
        ),
        "recall_macro": recall_score(
            y_true, y_pred, average="macro", zero_division=0
        ),
        # F1-weighted is the PRIMARY metric (see module [RISK] note).
        "f1_weighted": f1_score(y_true, y_pred, average="weighted", zero_division=0),
        "f1_macro": f1_score(y_true, y_pred, average="macro", zero_division=0),
        "mcc": matthews_corrcoef(y_true, y_pred),
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        "classification_report": classification_report(
            y_true,
            y_pred,
            labels=labels,
            target_names=[str(c) for c in classes_list],
            output_dict=True,
            zero_division=0,
        ),
        "roc_auc": None,
        "pr_auc": None,
        "log_loss": None,
        "calibration_curve": None,
    }

    # ROC-AUC / log-loss need ≥2 classes actually present in y_true.
    n_present = len(np.unique(y_true))

    if problem_type == "binary":
        positive = labels[-1]  # lexicographically-last label is the positive class
        proba_pos = y_proba[:, -1]
        y_true_bin = (y_true == positive).astype(int)
        if n_present >= 2:
            result["roc_auc"] = _safe(roc_auc_score, y_true_bin, proba_pos)
            result["pr_auc"] = _safe(average_precision_score, y_true_bin, proba_pos)
            result["calibration_curve"] = _calibration(y_true_bin, proba_pos)
    else:  # multiclass
        if n_present >= 2:
            result["roc_auc"] = _safe(
                roc_auc_score,
                y_true,
                y_proba,
                multi_class="ovr",
                average="weighted",
                labels=labels,
            )

    result["log_loss"] = _safe(log_loss, y_true, y_proba, labels=labels)
    return result


def _evaluate_multilabel(
    y_true: Any,
    y_pred: Any,
    y_proba: Any,
    classes_list: list[Any],
) -> dict[str, Any]:
    """Metrics for multilabel problems (2-D indicator inputs)."""
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    y_proba = np.asarray(y_proba)

    return {
        # subset accuracy: a row counts as correct only if ALL labels match.
        "accuracy": accuracy_score(y_true, y_pred),
        "precision_weighted": precision_score(
            y_true, y_pred, average="weighted", zero_division=0
        ),
        "precision_macro": precision_score(
            y_true, y_pred, average="macro", zero_division=0
        ),
        "recall_weighted": recall_score(
            y_true, y_pred, average="weighted", zero_division=0
        ),
        "recall_macro": recall_score(
            y_true, y_pred, average="macro", zero_division=0
        ),
        "f1_weighted": f1_score(y_true, y_pred, average="weighted", zero_division=0),
        "f1_macro": f1_score(y_true, y_pred, average="macro", zero_division=0),
        # MCC is undefined for multilabel indicator input; report None.
        "mcc": None,
        "roc_auc": _safe(roc_auc_score, y_true, y_proba, average="weighted"),
        "pr_auc": _safe(
            average_precision_score, y_true, y_proba, average="weighted"
        ),
        "log_loss": None,
        # Per-label confusion matrices are large; the per-label report covers it.
        "confusion_matrix": None,
        "classification_report": classification_report(
            y_true,
            y_pred,
            target_names=[str(c) for c in classes_list],
            output_dict=True,
            zero_division=0,
        ),
        "calibration_curve": None,
    }


def _calibration(y_true_bin: np.ndarray, proba_pos: np.ndarray) -> dict[str, list] | None:
    """Calibration-curve data for binary problems (reliability diagram)."""
    try:
        n_bins = min(10, max(2, len(np.unique(proba_pos))))
        frac_pos, mean_pred = calibration_curve(
            y_true_bin, proba_pos, n_bins=n_bins, strategy="uniform"
        )
        return {
            "fraction_of_positives": frac_pos.tolist(),
            "mean_predicted_value": mean_pred.tolist(),
        }
    except (ValueError, IndexError):
        return None


def _safe(func: Any, *args: Any, **kwargs: Any) -> float | None:
    """Run a metric, returning ``None`` (not raising) on the undefined-case errors."""
    try:
        value = func(*args, **kwargs)
    except (ValueError, IndexError):
        return None
    value = float(value)
    return value if np.isfinite(value) else None


def _native(value: Any) -> Any:
    """Coerce a single numpy scalar to a plain Python type."""
    if isinstance(value, np.generic):
        return value.item()
    return value


def _jsonify(obj: Any) -> Any:
    """Recursively convert numpy scalars/arrays in a structure to plain Python types."""
    if isinstance(obj, dict):
        return {_jsonify(k): _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonify(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _jsonify(obj.tolist())
    if isinstance(obj, np.generic):
        return obj.item()
    return obj
