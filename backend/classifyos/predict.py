"""Section 13 — ``classify``.

Turns a fitted model and the test matrices into a tidy, per-sample predictions table:
one row per test sample, with the actual label, the predicted label, a probability
column per class, the confidence (max probability), and a correctness flag. This is the
"predictions" payload the dashboard renders as a table and the engine writes to
``OUTPUT_DIR``.

The column names are stable and JSON-friendly so the frontend can rely on them:
``actual``, ``predicted``, ``probability_<class>`` (one per class), ``confidence``,
``correct_flag``. The row index is aligned to ``X_test``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .models.base import ModelWrapper
from .multilabel import join_labels, parse_label_sets


def classify(
    model: ModelWrapper,
    X_test: pd.DataFrame,
    y_test: Any,
    classes: Any,
) -> pd.DataFrame:
    """Build a per-sample predictions DataFrame for the test set.

    Args:
        model: A fitted :class:`~classifyos.models.base.ModelWrapper`.
        X_test: Test feature matrix (the model's ``predict``/``predict_proba`` input).
        y_test: True test labels, aligned to ``X_test`` rows. For multilabel this is the
            delimited target column (e.g. ``"Auto|Home"``).
        classes: Class labels in ``predict_proba`` column order (the model's
            ``classes_``). Determines the ``probability_<class>`` column order.

    Returns:
        A DataFrame indexed like ``X_test`` with columns ``actual``, ``predicted``,
        one ``probability_<class>`` per class, ``confidence`` (row-max probability),
        and ``correct_flag`` (``actual == predicted``). For binary/multiclass the
        per-row probabilities sum to ~1.

        For **multilabel** problems ``actual``/``predicted`` are the delimited label SETS
        (sorted, e.g. ``"Auto|Home"``), one ``probability_<label>`` per label, ``confidence``
        is the row-max per-label probability, and ``correct_flag`` is the exact-set match
        (subset accuracy). The columns are identical so the API/CSV layout is unchanged.
    """
    if getattr(model, "problem_type", None) == "multilabel":
        return _classify_multilabel(model, X_test, y_test, classes)

    proba = np.asarray(model.predict_proba(X_test))
    pred = np.asarray(model.predict(X_test))
    class_labels = [str(c) for c in np.asarray(classes).tolist()]

    index = X_test.index if isinstance(X_test, pd.DataFrame) else pd.RangeIndex(len(pred))
    actual = np.asarray(y_test)

    df = pd.DataFrame(index=index)
    df["actual"] = actual
    df["predicted"] = pred
    for col_idx, label in enumerate(class_labels):
        df[f"probability_{label}"] = proba[:, col_idx]
    df["confidence"] = proba.max(axis=1)
    df["correct_flag"] = df["actual"].astype(str) == df["predicted"].astype(str)
    return df


def _classify_multilabel(
    model: ModelWrapper,
    X_test: pd.DataFrame,
    y_test: Any,
    classes: Any,
) -> pd.DataFrame:
    """Per-sample predictions table for a multilabel run (indicator → delimited sets).

    The model returns a ``(n, n_labels)`` indicator prediction and ``(n, n_labels)``
    per-label probabilities; we render both the true and predicted label SETS as the same
    delimited strings the single-label table uses, so the contract layout is unchanged.
    ``correct_flag`` is the exact-set match (subset accuracy), ``confidence`` the row-max
    per-label probability.
    """
    proba = np.asarray(model.predict_proba(X_test), dtype=float)
    pred_ind = np.asarray(model.predict(X_test))
    labels = [str(c) for c in np.asarray(classes).tolist()]

    index = X_test.index if isinstance(X_test, pd.DataFrame) else pd.RangeIndex(len(pred_ind))
    true_sets = [set(s) for s in parse_label_sets(np.asarray(y_test).tolist())]
    pred_sets = [
        {labels[j] for j in range(len(labels)) if pred_ind[i, j]}
        for i in range(pred_ind.shape[0])
    ]

    df = pd.DataFrame(index=index)
    df["actual"] = [join_labels(s) for s in true_sets]
    df["predicted"] = [join_labels(s) for s in pred_sets]
    for col_idx, label in enumerate(labels):
        df[f"probability_{label}"] = proba[:, col_idx]
    df["confidence"] = proba.max(axis=1) if proba.size else 0.0
    df["correct_flag"] = [t == p for t, p in zip(true_sets, pred_sets)]
    return df
