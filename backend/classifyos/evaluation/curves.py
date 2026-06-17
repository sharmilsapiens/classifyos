"""ROC / PR curve *points* — the single source of truth for both plots and the API.

``compute_curve_points`` turns the held-out test set's true labels and predicted
probabilities into the coordinate arrays a chart needs: per class, the ROC curve
(``fpr``/``tpr``/``thresholds``) and the Precision-Recall curve
(``precision``/``recall``/``thresholds``), plus the scalar ROC-AUC and average precision.

Why a dedicated module (Phase 8, sanctioned engine edit):
    The Phase 9 frontend draws ROC/PR curves with Chart.js, which needs the raw point
    arrays — not a PNG. Section 14's ``plot_results`` already derives those same points to
    render ``plot2``. Having TWO places compute curve math (the plot, and the web layer)
    invites drift: the PNG and the interactive chart could silently disagree. So the math
    lives here once; ``plot_results`` (plot2) and the API's ``/run`` response both call this
    function. The web layer therefore re-derives no ML — it reshapes this output.

[RISK] leakage — this function reads ALREADY-PRODUCED predictions from the **held-out
    test set** (``y_true`` + the model's ``predict_proba`` output on the test matrix). It
    fits nothing, learns nothing, and must NEVER be handed training data: doing so would
    report optimistic, leaked curves. Curve points are always computed on the FULL test set
    (never the sampled predictions table the API returns for display).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import (
    auc,
    average_precision_score,
    precision_recall_curve,
    roc_curve,
)

#: Cap on points kept per curve. Each curve is uniformly downsampled to at most this many
#: coordinates (endpoints always preserved) so the JSON payload stays bounded for a large
#: test set while the curve shape is faithful. ``roc_curve``'s own ``drop_intermediate``
#: already prunes collinear ROC points; this also bounds the (un-pruned) PR curve.
MAX_CURVE_POINTS = 500


def compute_curve_points(
    y_true: Any,
    y_proba: Any,
    classes: Any,
    problem_type: str,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Compute ROC and PR curve points (one-vs-rest per class) from test predictions.

    Args:
        y_true: True test labels (1-D array of class labels, as strings). NOT training
            data — see the module-level [RISK] note.
        y_proba: Predicted probabilities of shape ``(n_samples, n_classes)`` with columns
            ordered to match ``classes`` (a model wrapper's ``predict_proba`` output).
        classes: Class labels in ``y_proba`` column order (a wrapper's ``classes_``).
        problem_type: ``"binary"`` | ``"multiclass"`` | ``"multilabel"``.

    Returns:
        ``{"roc": {<class>: {...}}, "pr": {<class>: {...}}}`` where each ROC entry holds
        ``fpr``/``tpr``/``thresholds`` lists and a scalar ``auc``, and each PR entry holds
        ``precision``/``recall``/``thresholds`` lists and a scalar ``ap``. For **binary**
        there is a single entry keyed by the positive class (the lexicographically-last
        label, matching ``evaluate_model``/``plot_results``). For **multiclass** there is
        one one-vs-rest entry per class. A class with fewer than two distinct truth values
        present (so ROC/PR is undefined) is omitted. ``multilabel`` is not supported here
        and returns empty dicts.
    """
    roc: dict[str, dict[str, Any]] = {}
    pr: dict[str, dict[str, Any]] = {}

    if problem_type == "multilabel":
        # Multilabel curve export is out of scope for v1.0 (mirrors classify()/plots).
        return {"roc": roc, "pr": pr}

    y_true_arr = np.asarray(y_true).astype(str)
    proba = np.asarray(y_proba, dtype=float)
    class_labels = [str(c) for c in np.asarray(classes).tolist()]

    if problem_type == "binary":
        # Positive class = last column / lexicographically-last label, matching the
        # convention in metrics.py and plots.py so the curve and the scalar AUC agree.
        positive = class_labels[-1]
        targets = [(positive, proba[:, -1])]
    else:  # multiclass — one-vs-rest per class
        targets = [(lbl, proba[:, i]) for i, lbl in enumerate(class_labels)]

    for label, score in targets:
        y_bin = (y_true_arr == label).astype(int)
        if len(np.unique(y_bin)) < 2:
            # Only one class present in truth → ROC/PR undefined; skip this class.
            continue
        roc[label] = _roc_points(y_bin, score)
        pr[label] = _pr_points(y_bin, score)

    return {"roc": roc, "pr": pr}


def _roc_points(y_bin: np.ndarray, score: np.ndarray) -> dict[str, Any]:
    """ROC points + AUC for a single one-vs-rest target."""
    fpr, tpr, thresholds = roc_curve(y_bin, score)
    roc_auc = _finite(auc(fpr, tpr))
    fpr, tpr, thresholds = _downsample(fpr, tpr, thresholds)
    return {
        "fpr": _to_list(fpr),
        "tpr": _to_list(tpr),
        "thresholds": _to_list(thresholds),
        "auc": roc_auc,
    }


def _pr_points(y_bin: np.ndarray, score: np.ndarray) -> dict[str, Any]:
    """Precision-Recall points + average precision for a single one-vs-rest target."""
    precision, recall, thresholds = precision_recall_curve(y_bin, score)
    ap = _finite(average_precision_score(y_bin, score))
    # precision_recall_curve returns one fewer threshold than precision/recall points
    # (the final point is (recall=0, precision=1) with no threshold). Pad so the three
    # arrays line up for downsampling, then expose the padded thresholds.
    thresholds = np.append(thresholds, np.nan)
    precision, recall, thresholds = _downsample(precision, recall, thresholds)
    return {
        "precision": _to_list(precision),
        "recall": _to_list(recall),
        "thresholds": _to_list(thresholds),
        "ap": ap,
    }


def _downsample(
    a: np.ndarray, b: np.ndarray, c: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Uniformly subsample three aligned arrays to <= ``MAX_CURVE_POINTS`` (keep ends)."""
    n = len(a)
    if n <= MAX_CURVE_POINTS:
        return a, b, c
    idx = np.linspace(0, n - 1, MAX_CURVE_POINTS).round().astype(int)
    idx = np.unique(idx)  # guard against duplicate rounded indices
    return a[idx], b[idx], c[idx]


def _to_list(arr: np.ndarray) -> list[float | None]:
    """Convert an array to a JSON-safe list (numpy floats → float, NaN/Inf → None)."""
    out: list[float | None] = []
    for v in np.asarray(arr, dtype=float).tolist():
        out.append(v if (v == v and v not in (float("inf"), float("-inf"))) else None)
    return out


def _finite(value: Any) -> float | None:
    """Coerce a scalar to a finite float, or ``None`` if NaN/Inf/undefined."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None
