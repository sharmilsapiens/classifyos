"""Multilabel target support — the delimited-set ↔ indicator-matrix bridge.

ClassifyOS's request contract (``docs/api_contract.md``) has a SINGLE ``target`` column,
so a multilabel target (e.g. Product Recommendation) is encoded as one string column whose
cells hold a delimiter-separated SET of labels per row, e.g. ``"Auto|Home|Life"``. The
modelling stack, however, needs a binary *indicator matrix* of shape
``(n_samples, n_labels)`` (one column per label). This module is the small, additive bridge
between the two representations:

* :func:`parse_label_sets` turns the delimited target column into a list of label lists.
* The caller fits a :class:`sklearn.preprocessing.MultiLabelBinarizer` on the **TRAIN**
  label sets only (the leakage boundary — the label vocabulary is learned from train, and
  any label seen only in test is ignored), then transforms both partitions.
* :func:`join_labels` turns a predicted label set back into the same delimited string for
  the predictions table.

[RISK] The delimiter is fixed at ``|`` for v1.0 (documented convention). A dataset whose
labels themselves contain ``|`` would be mis-parsed; that is out of scope for v1.0.

This module adds NO new modelling behaviour — the wrappers already wrap their estimator in
:class:`~sklearn.multiclass.OneVsRestClassifier` for ``problem_type="multilabel"`` and
``evaluate_model`` already has a multilabel branch. It only supplies the missing
representation conversion the orchestrator (``ModelRunner``) needs.
"""

from __future__ import annotations

from typing import Any, Iterable

#: The fixed separator between labels inside a multilabel target cell (v1.0 convention).
MULTILABEL_DELIMITER = "|"


def parse_label_sets(values: Iterable[Any]) -> list[list[str]]:
    """Split a delimited multilabel target column into a list of per-row label lists.

    Args:
        values: An iterable of target cells, each a ``MULTILABEL_DELIMITER``-joined string
            (e.g. ``"Auto|Home"``). Missing values (``None``/NaN) become an empty set.

    Returns:
        One list of (stripped, non-empty) label strings per input row. Order within a row
        is preserved; duplicates are NOT de-duplicated here (the binarizer collapses them).
    """
    out: list[list[str]] = []
    for value in values:
        # Treat None and NaN (a float that is not equal to itself) as "no labels".
        if value is None or (isinstance(value, float) and value != value):
            out.append([])
            continue
        parts = [p.strip() for p in str(value).split(MULTILABEL_DELIMITER)]
        out.append([p for p in parts if p])
    return out


def join_labels(labels: Iterable[Any]) -> str:
    """Join a label set back into the delimited string used by the predictions table.

    Labels are sorted for a stable, comparable representation (so two predictions with the
    same set but different order compare equal in the predictions table / ``correct_flag``).
    """
    return MULTILABEL_DELIMITER.join(sorted(str(lbl) for lbl in labels))
