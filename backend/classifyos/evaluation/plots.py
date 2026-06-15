"""Section 14 — ``plot_results`` (confusion / ROC-PR / importance / calibration plots).

Renders the four result figures the dashboard displays, from a *completed*
:class:`~classifyos.runner.ModelRunner`:

* ``plot1_confusion_matrix.png``  — raw + row-normalized confusion matrix per algorithm.
* ``plot2_roc_pr_curves.png``     — ROC (and PR for binary) curves; AUC/AP in the legend.
* ``plot3_feature_importance.png``— top features per model that exposes importances.
* ``plot5_calibration_curve.png`` — reliability diagram per algorithm (binary only).

``plot4`` (feature impact) and ``plot6`` (interaction summary) are written earlier in the
pipeline (Sections 5 and 7B respectively), so this module does NOT reproduce them.

Every figure is rendered on the headless ``Agg`` backend at ``dpi=150`` with a white
facecolor, written through the :class:`StorageAdapter` (never a raw ``open``/``savefig``
to a path), and the figure is ALWAYS closed after saving to bound memory across runs.
Each plot guards its own degenerate cases (a model without importances is skipped in
plot3; multiclass — where the binary PR/calibration views are ill-defined — falls back to
a clearly-labelled placeholder) and never raises into the caller: a plotting failure must
not invalidate an otherwise-successful run.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import matplotlib

matplotlib.use("Agg")  # headless safety: non-interactive backend before pyplot

import matplotlib.pyplot as plt  # noqa: E402  (must follow matplotlib.use)
import numpy as np  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    auc,
    average_precision_score,
    precision_recall_curve,
    roc_curve,
)
from sklearn.preprocessing import label_binarize  # noqa: E402

from ..io.storage import StorageAdapter  # noqa: E402

if TYPE_CHECKING:  # avoid a runtime import cycle (runner imports this module lazily)
    from ..runner import ModelRunner

logger = logging.getLogger(__name__)

# Logical output keys (part of the future output contract).
PLOT1_KEY = "plot1_confusion_matrix.png"
PLOT2_KEY = "plot2_roc_pr_curves.png"
PLOT3_KEY = "plot3_feature_importance.png"
PLOT5_KEY = "plot5_calibration_curve.png"

#: Top-N features shown per model in the importance plot.
_TOP_IMPORTANCES = 15

_DARK = "#222222"


def plot_results(runner: "ModelRunner", storage: StorageAdapter) -> list[str]:
    """Render plot1/2/3/5 from a completed ``runner`` and write them via ``storage``.

    Args:
        runner: A :class:`~classifyos.runner.ModelRunner` whose :meth:`run` has finished
            (``models_``, ``metrics_``, ``X_test_``, ``y_test_``, ``classes_`` populated).
        storage: Storage adapter — every PNG is written through it.

    Returns:
        The list of logical keys successfully written (a subset of plot1/2/3/5).
    """
    written: list[str] = []
    for key, fn in (
        (PLOT1_KEY, _plot_confusion),
        (PLOT2_KEY, _plot_roc_pr),
        (PLOT3_KEY, _plot_importance),
        (PLOT5_KEY, _plot_calibration),
    ):
        try:
            fn(runner, storage)
            written.append(key)
        except Exception:  # noqa: BLE001 — one bad plot must not sink the others
            logger.exception("plot_results: %s failed", key)
    return written


# --------------------------------------------------------------------------- #
# plot1 — confusion matrices (raw + row-normalized) per algorithm             #
# --------------------------------------------------------------------------- #


def _plot_confusion(runner: "ModelRunner", storage: StorageAdapter) -> None:
    """Raw and row-normalized confusion matrix for every successful model."""
    items = [
        (name, m) for name, m in runner.metrics_.items() if m.get("confusion_matrix")
    ]
    n = len(items)
    if n == 0:
        _placeholder(PLOT1_KEY, "no confusion matrices to plot", storage)
        return

    fig, axes = plt.subplots(n, 2, figsize=(11, 4.2 * n), facecolor="white", squeeze=False)
    for row, (name, metrics) in enumerate(items):
        cm = np.asarray(metrics["confusion_matrix"], dtype=float)
        labels = [str(c) for c in (metrics.get("labels") or range(cm.shape[0]))]
        with np.errstate(invalid="ignore", divide="ignore"):
            norm = cm / cm.sum(axis=1, keepdims=True)
        norm = np.nan_to_num(norm)
        _draw_matrix(axes[row][0], cm, labels, f"{name} — counts", fmt="{:.0f}")
        _draw_matrix(axes[row][1], norm, labels, f"{name} — row-normalized", fmt="{:.2f}")

    fig.suptitle("Confusion matrices", color=_DARK)
    _save(fig, PLOT1_KEY, storage)


def _draw_matrix(ax: Any, mat: np.ndarray, labels: list[str], title: str, fmt: str) -> None:
    """Draw one annotated confusion-matrix heatmap on ``ax``."""
    im = ax.imshow(mat, cmap="Blues", aspect="auto")
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right", color=_DARK)
    ax.set_yticklabels(labels, color=_DARK)
    ax.set_xlabel("predicted", color=_DARK)
    ax.set_ylabel("actual", color=_DARK)
    ax.set_title(title, color=_DARK)
    hi = mat.max() if mat.size else 1.0
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            # Pick a contrasting text colour against the cell shade.
            colour = "white" if mat[i, j] > hi * 0.6 else _DARK
            ax.text(j, i, fmt.format(mat[i, j]), ha="center", va="center", color=colour)
    ax.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.04)


# --------------------------------------------------------------------------- #
# plot2 — ROC / PR curves                                                     #
# --------------------------------------------------------------------------- #


def _plot_roc_pr(runner: "ModelRunner", storage: StorageAdapter) -> None:
    """ROC + PR (binary) or one-vs-rest ROC (multiclass) for every successful model."""
    if not runner.models_:
        _placeholder(PLOT2_KEY, "no fitted models to plot", storage)
        return

    if runner.problem_type_ == "binary":
        _plot_roc_pr_binary(runner, storage)
    else:
        _plot_roc_ovr_multiclass(runner, storage)


def _plot_roc_pr_binary(runner: "ModelRunner", storage: StorageAdapter) -> None:
    """ROC and Precision-Recall curves, one line per algorithm (positive = last class)."""
    X_test, y_test = runner.X_test_, np.asarray(runner.y_test_).astype(str)
    fig, (ax_roc, ax_pr) = plt.subplots(1, 2, figsize=(14, 6), facecolor="white")

    for name, model in runner.models_.items():
        classes = np.asarray(model.classes_).astype(str)
        positive = classes[-1]  # lexicographically-last label (matches metrics.py)
        proba_pos = np.asarray(model.predict_proba(X_test))[:, -1]
        y_bin = (y_test == positive).astype(int)
        if len(np.unique(y_bin)) < 2:
            continue  # ROC/PR undefined with a single class present

        fpr, tpr, _ = roc_curve(y_bin, proba_pos)
        ax_roc.plot(fpr, tpr, label=f"{name} (AUC={auc(fpr, tpr):.3f})")

        prec, rec, _ = precision_recall_curve(y_bin, proba_pos)
        ap = average_precision_score(y_bin, proba_pos)
        ax_pr.plot(rec, prec, label=f"{name} (AP={ap:.3f})")

    ax_roc.plot([0, 1], [0, 1], "--", color="#999999", label="chance")
    ax_roc.set_xlabel("false positive rate", color=_DARK)
    ax_roc.set_ylabel("true positive rate", color=_DARK)
    ax_roc.set_title("ROC curves", color=_DARK)
    ax_roc.legend(fontsize=8)
    ax_roc.tick_params(colors=_DARK)

    ax_pr.set_xlabel("recall", color=_DARK)
    ax_pr.set_ylabel("precision", color=_DARK)
    ax_pr.set_title("Precision-Recall curves", color=_DARK)
    ax_pr.legend(fontsize=8)
    ax_pr.tick_params(colors=_DARK)

    _save(fig, PLOT2_KEY, storage)


def _plot_roc_ovr_multiclass(runner: "ModelRunner", storage: StorageAdapter) -> None:
    """One subplot per algorithm with one-vs-rest ROC curves per class.

    PR curves are skipped for multiclass — a single combined PR view is ill-defined; the
    per-class one-vs-rest ROC is the clearer comparison.
    """
    X_test, y_test = runner.X_test_, np.asarray(runner.y_test_).astype(str)
    models = list(runner.models_.items())
    n = len(models)
    fig, axes = plt.subplots(1, n, figsize=(6 * n, 5.5), facecolor="white", squeeze=False)

    for col, (name, model) in enumerate(models):
        ax = axes[0][col]
        classes = np.asarray(model.classes_).astype(str)
        proba = np.asarray(model.predict_proba(X_test))
        y_bin = label_binarize(y_test, classes=classes)
        for i, cls in enumerate(classes):
            if i >= y_bin.shape[1] or len(np.unique(y_bin[:, i])) < 2:
                continue
            fpr, tpr, _ = roc_curve(y_bin[:, i], proba[:, i])
            ax.plot(fpr, tpr, label=f"{cls} (AUC={auc(fpr, tpr):.3f})")
        ax.plot([0, 1], [0, 1], "--", color="#999999")
        ax.set_xlabel("false positive rate", color=_DARK)
        ax.set_ylabel("true positive rate", color=_DARK)
        ax.set_title(f"{name} — one-vs-rest ROC", color=_DARK)
        ax.legend(fontsize=8)
        ax.tick_params(colors=_DARK)

    _save(fig, PLOT2_KEY, storage)


# --------------------------------------------------------------------------- #
# plot3 — feature importance                                                  #
# --------------------------------------------------------------------------- #


def _plot_importance(runner: "ModelRunner", storage: StorageAdapter) -> None:
    """Top-``_TOP_IMPORTANCES`` features per model that exposes importances.

    Models without importances (RBF SVM, GaussianNB) are simply skipped. If NO model
    exposes any, a labelled placeholder is written so the artifact always exists.
    """
    items: list[tuple[str, dict[str, float]]] = []
    for name, model in runner.models_.items():
        imp = model.feature_importance()
        if imp:
            items.append((name, imp))

    if not items:
        _placeholder(PLOT3_KEY, "no models expose feature importances", storage)
        return

    n = len(items)
    fig, axes = plt.subplots(n, 1, figsize=(10, 4.5 * n), facecolor="white", squeeze=False)
    for row, (name, imp) in enumerate(items):
        ax = axes[row][0]
        top = sorted(imp.items(), key=lambda kv: abs(kv[1]), reverse=True)[:_TOP_IMPORTANCES]
        top = top[::-1]  # strongest at the top of the horizontal bar chart
        names = [k for k, _ in top]
        values = [v for _, v in top]
        ax.barh(names, values, color="#3b6ea5")
        ax.set_xlabel("importance", color=_DARK)
        ax.set_title(f"{name} — top {len(top)} features", color=_DARK)
        ax.tick_params(colors=_DARK)

    fig.suptitle("Feature importances", color=_DARK)
    _save(fig, PLOT3_KEY, storage)


# --------------------------------------------------------------------------- #
# plot5 — calibration (reliability) curves — binary only                      #
# --------------------------------------------------------------------------- #


def _plot_calibration(runner: "ModelRunner", storage: StorageAdapter) -> None:
    """Reliability diagram per algorithm vs the perfect-calibration diagonal (binary)."""
    if runner.problem_type_ != "binary":
        _placeholder(
            PLOT5_KEY, "calibration curve is defined for binary problems only", storage
        )
        return

    curves = [
        (name, m["calibration_curve"])
        for name, m in runner.metrics_.items()
        if m.get("calibration_curve")
    ]
    if not curves:
        _placeholder(PLOT5_KEY, "no calibration data available", storage)
        return

    fig, ax = plt.subplots(figsize=(8, 7), facecolor="white")
    ax.plot([0, 1], [0, 1], "--", color="#999999", label="perfectly calibrated")
    for name, cal in curves:
        ax.plot(
            cal["mean_predicted_value"],
            cal["fraction_of_positives"],
            marker="o",
            label=name,
        )
    ax.set_xlabel("mean predicted probability", color=_DARK)
    ax.set_ylabel("fraction of positives", color=_DARK)
    ax.set_title("Calibration curves", color=_DARK)
    ax.legend(fontsize=8)
    ax.tick_params(colors=_DARK)
    _save(fig, PLOT5_KEY, storage)


# --------------------------------------------------------------------------- #
# shared helpers                                                              #
# --------------------------------------------------------------------------- #


def _save(fig: Any, key: str, storage: StorageAdapter) -> None:
    """Write ``fig`` as a PNG through ``storage`` and ALWAYS close it afterwards."""
    fig.tight_layout()
    try:
        with storage.open_write(key, binary=True) as fh:
            fig.savefig(fh, format="png", dpi=150, facecolor="white")
    finally:
        plt.close(fig)
    logger.info("Wrote %s", key)


def _placeholder(key: str, message: str, storage: StorageAdapter) -> None:
    """Write a small labelled placeholder figure (keeps the artifact set complete)."""
    fig, ax = plt.subplots(figsize=(8, 3), facecolor="white")
    ax.text(0.5, 0.5, message, ha="center", va="center", color=_DARK, wrap=True)
    ax.axis("off")
    _save(fig, key, storage)
