"""Post-training PERMUTATION feature importance — the model-agnostic counterpart.

Native feature importance (``ModelWrapper.feature_importance``) reads numbers the
estimator produced *while training* — tree impurity/gain or ``|coef|``. Two of the six
ClassifyOS models expose none (the RBF-kernel ``SVM`` and ``GaussianNB``), so those
columns are blank on the post-training importance screen.

Permutation importance fills that gap. It treats the fitted model as a black box and
measures, empirically, **how much the model's predictive performance drops when one
feature's values are shuffled** on a held-out set:

1. Score the fitted model on the held-out data (baseline F1-weighted — the engine's
   primary metric, the same one the dashboard leads with).
2. For each feature, randomly permute that one column (breaking its link to the target
   while leaving its marginal distribution intact) and re-score. Repeat ``n_repeats``
   times and average.
3. ``importance = baseline − mean(permuted score)`` — a big drop means the model leaned
   heavily on that feature; ~0 means it was ignorable; a small *negative* value is noise
   (shuffling happened to help by chance) and is kept as-is so ranking stays honest.

Because step 2 only ever calls ``model.predict`` it works for **every** wrapper —
including SVM and NaiveBayes — so it is the one importance measure comparable across all
six models (same unit: drop in F1-weighted). The trade-offs vs. native importance:

* **Cost.** One predict pass per (feature × repeat) plus the baseline — far more compute
  than reading a trained attribute. Bounded here by a modest ``n_repeats`` default.
* **Correlated features.** Shuffling one of two correlated columns lets the model lean on
  its untouched twin, so both can look unimportant even when the information is used.
  [RISK] interpret low permutation importance on correlated features with care.

[RISK] leakage — this is computed on the HELD-OUT TEST split (the same data the reported
metrics use). It is read-only: nothing is fitted, no estimator state changes, and the
caller's feature matrix is never mutated (we shuffle a private copy). It reports on the
model; it does not train it.

Determinism: a single seeded ``numpy`` generator drives every shuffle, so a run with a
fixed ``random_state`` reproduces byte-for-byte.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score

logger = logging.getLogger(__name__)

#: Number of shuffles averaged per feature. 5 matches scikit-learn's
#: ``permutation_importance`` default — enough to damp the shuffle noise without
#: multiplying the predict cost (which scales with ``n_features × n_repeats``) excessively.
DEFAULT_N_REPEATS = 5


def _f1_weighted(y_true: Any, y_pred: Any) -> float:
    """F1-weighted scorer shared by baseline and permuted passes.

    ``average="weighted"`` works for binary, multiclass (1-D labels) and multilabel
    (2-D indicator matrices) alike, so one scorer serves every problem type. ``zero_division=0``
    keeps a degenerate permuted prediction (e.g. all one class) from raising.
    """
    return float(f1_score(y_true, y_pred, average="weighted", zero_division=0))


def permutation_importance(
    model: Any,
    X: pd.DataFrame,
    y_true: Any,
    problem_type: str,
    *,
    n_repeats: int = DEFAULT_N_REPEATS,
    random_state: int = 42,
) -> dict[str, float] | None:
    """Compute permutation importance for one fitted model on held-out data.

    Args:
        model: A fitted :class:`~classifyos.models.base.ModelWrapper`. Only its
            :meth:`predict` is used, so the measure is model-agnostic (SVM/NaiveBayes
            included).
        X: The held-out (TEST) feature matrix — same engineered/active columns the model
            was fitted on. Never mutated; a private copy is shuffled in place.
        y_true: Held-out truth aligned to ``X``. 1-D labels for binary/multiclass; a 2-D
            ``(n, n_labels)`` indicator matrix for multilabel (matching ``predict``'s output).
        problem_type: ``"binary"`` | ``"multiclass"`` | ``"multilabel"`` (accepted for
            symmetry with the rest of the engine; the F1-weighted scorer is uniform).
        n_repeats: Shuffles averaged per feature (default :data:`DEFAULT_N_REPEATS`).
        random_state: Seed for the single shuffle generator (reproducible).

    Returns:
        ``{feature_name: importance}`` over ``X``'s columns (drop in F1-weighted when that
        feature is shuffled; may be slightly negative), or ``None`` when ``X`` has no
        columns or scoring fails (so the run never aborts on this report-only step).
    """
    if X is None or getattr(X, "shape", (0, 0))[1] == 0 or len(X) == 0:
        return None

    rng = np.random.default_rng(random_state)
    work = X.copy()  # one copy total; columns are shuffled in place then restored.

    try:
        baseline = _f1_weighted(y_true, model.predict(work))
    except Exception:  # noqa: BLE001 — report-only; a scoring failure must not kill the run
        logger.exception("permutation_importance: baseline scoring failed; skipping")
        return None

    importances: dict[str, float] = {}
    for col in work.columns:
        saved = work[col].to_numpy(copy=True)
        drops: list[float] = []
        try:
            for _ in range(n_repeats):
                work[col] = rng.permutation(saved)
                drops.append(baseline - _f1_weighted(y_true, model.predict(work)))
        except Exception:  # noqa: BLE001 — one bad column must not kill the whole measure
            logger.exception(
                "permutation_importance: scoring failed for feature %r; recording 0.0", col
            )
            drops = [0.0]
        finally:
            work[col] = saved  # restore before moving to the next column
        importances[str(col)] = float(np.mean(drops))

    return importances
