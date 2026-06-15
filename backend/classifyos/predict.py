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
        y_test: True test labels, aligned to ``X_test`` rows.
        classes: Class labels in ``predict_proba`` column order (the model's
            ``classes_``). Determines the ``probability_<class>`` column order.

    Returns:
        A DataFrame indexed like ``X_test`` with columns ``actual``, ``predicted``,
        one ``probability_<class>`` per class, ``confidence`` (row-max probability),
        and ``correct_flag`` (``actual == predicted``). For binary/multiclass the
        per-row probabilities sum to ~1.

    Note:
        This single-label layout (scalar ``actual``/``predicted``) does not cover
        multilabel problems, where each row carries several labels; multilabel
        prediction export is out of scope for v1.0.
    """
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
