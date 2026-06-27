"""Post-training PERMUTATION feature importance — the model-agnostic counterpart.

Native feature importance (``ModelWrapper.feature_importance``) reads numbers the
estimator produced *while training* — tree impurity/gain or ``|coef|``. Two of the six
ClassifyOS models expose none (the RBF-kernel ``SVM`` and ``GaussianNB``), so those
columns are blank on the post-training importance screen.

Permutation importance fills that gap. It treats the fitted model as a black box and
measures, empirically, **how much the model's predictive performance drops when one
feature's values are shuffled** on a held-out set:

1. Score the fitted model on the held-out data (the baseline, in a configurable metric —
   F1-weighted by default, the engine's primary metric).
2. For each feature, randomly permute that one column (breaking its link to the target
   while leaving its marginal distribution intact) and re-score. Repeat ``n_repeats``
   times and average.
3. ``importance = baseline − mean(permuted score)`` — a big drop means the model leaned
   heavily on that feature; ~0 means it was ignorable; a small *negative* value is noise
   (shuffling happened to help by chance) and is kept as-is so ranking stays honest.

Because step 2 only ever calls ``model.predict`` (and ``model.predict_proba`` for the
probability-based metrics) it works for **every** wrapper — including SVM and NaiveBayes —
so it is the one importance measure comparable across all six models (same unit: the drop
in the chosen metric). The trade-offs vs. native importance:

* **Cost.** One predict pass per (feature × repeat) plus the baseline — far more compute
  than reading a trained attribute. Bounded here by a modest ``n_repeats`` default; a
  probability-based metric additionally calls ``predict_proba`` each pass (notably slow on
  the calibrated SVM).
* **Correlated features.** Shuffling one of two correlated columns lets the model lean on
  its untouched twin, so both can look unimportant even when the information is used.
  [RISK] interpret low permutation importance on correlated features with care.

**Metric.** The scorer reuses :func:`classifyos.evaluation.metrics.evaluate_model` so the
permutation score is computed *identically* to the metric the dashboard reports — no
second definition to drift (binary positive-class, multiclass one-vs-rest ROC-AUC,
multilabel handling are all inherited). All metrics are higher-is-better except
``log_loss``, which is negated so the drop stays positive for an important feature. When a
metric is undefined for the problem type (``pr_auc`` on multiclass, ``log_loss`` on
multilabel, etc.) ``evaluate_model`` returns ``None`` for it; the baseline is then ``None``
and this function returns ``None`` (no importances) rather than inventing a number.

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

from ..evaluation.metrics import evaluate_model

logger = logging.getLogger(__name__)

#: Number of shuffles averaged per feature. 5 matches scikit-learn's
#: ``permutation_importance`` default — enough to damp the shuffle noise without
#: multiplying the predict cost (which scales with ``n_features × n_repeats``) excessively.
DEFAULT_N_REPEATS = 5

#: Metrics that need class probabilities (``predict_proba``) rather than just labels. For
#: every other metric the (often expensive) ``predict_proba`` call is skipped.
_PROBA_METRICS = frozenset({"roc_auc", "pr_auc", "log_loss"})

#: Metrics where LOWER is better — negated so "higher = better" holds for the baseline−permuted
#: subtraction (an important feature then yields a positive importance).
_LOWER_IS_BETTER = frozenset({"log_loss"})


def _score(
    model: Any,
    X: pd.DataFrame,
    y_true: Any,
    problem_type: str,
    classes: Any,
    metric: str,
    needs_proba: bool,
) -> float | None:
    """Score the model on ``X`` in ``metric`` via ``evaluate_model`` (higher = better).

    ``predict_proba`` is called only when ``metric`` is probability-based; otherwise a
    correctly-shaped UNIFORM proba array (rows summing to 1) is passed (``evaluate_model``
    needs a proba argument, but the chosen label metric ignores it — its proba-derived keys
    are simply not read) so we avoid an expensive ``predict_proba`` pass. Uniform (not zeros)
    keeps ``evaluate_model``'s internal log-loss/ROC-AUC calls from warning about probabilities
    that don't sum to one. Returns ``None`` when the metric is undefined for this input.
    """
    y_pred = model.predict(X)
    if needs_proba:
        y_proba = model.predict_proba(X)
    else:
        n_cols = len(np.asarray(classes))
        y_proba = np.full((len(X), n_cols), 1.0 / n_cols, dtype=float)
    metrics = evaluate_model(y_true, y_pred, y_proba, problem_type, np.asarray(classes))
    value = metrics.get(metric)
    if value is None:
        return None
    return -float(value) if metric in _LOWER_IS_BETTER else float(value)


def permutation_importance(
    model: Any,
    X: pd.DataFrame,
    y_true: Any,
    problem_type: str,
    classes: Any,
    *,
    metric: str = "f1_weighted",
    n_repeats: int = DEFAULT_N_REPEATS,
    random_state: int = 42,
) -> dict[str, float] | None:
    """Compute permutation importance for one fitted model on held-out data.

    Args:
        model: A fitted :class:`~classifyos.models.base.ModelWrapper`. Only its
            :meth:`predict` (and :meth:`predict_proba` for probability-based metrics) is
            used, so the measure is model-agnostic (SVM/NaiveBayes included).
        X: The held-out (TEST) feature matrix — same engineered/active columns the model
            was fitted on. Never mutated; a private copy is shuffled in place.
        y_true: Held-out truth aligned to ``X``. 1-D labels for binary/multiclass; a 2-D
            ``(n, n_labels)`` indicator matrix for multilabel (matching ``predict``'s output).
        problem_type: ``"binary"`` | ``"multiclass"`` | ``"multilabel"``.
        classes: The model's ``classes_`` (proba-column order) — forwarded to
            :func:`evaluate_model` so the score matches the reported metric exactly.
        metric: An ``evaluate_model`` metric key (see ``config.PERMUTATION_METRICS``); the
            importance is the drop in this metric. Default F1-weighted.
        n_repeats: Shuffles averaged per feature (default :data:`DEFAULT_N_REPEATS`).
        random_state: Seed for the single shuffle generator (reproducible).

    Returns:
        ``{feature_name: importance}`` over ``X``'s columns (drop in ``metric`` when that
        feature is shuffled; may be slightly negative), or ``None`` when ``X`` has no
        columns, scoring fails, or ``metric`` is undefined for this run (baseline ``None``) —
        so the run never aborts on this report-only step.
    """
    if X is None or getattr(X, "shape", (0, 0))[1] == 0 or len(X) == 0:
        return None

    needs_proba = metric in _PROBA_METRICS
    rng = np.random.default_rng(random_state)
    work = X.copy()  # one copy total; columns are shuffled in place then restored.

    try:
        baseline = _score(model, work, y_true, problem_type, classes, metric, needs_proba)
    except Exception:  # noqa: BLE001 — report-only; a scoring failure must not kill the run
        logger.exception("permutation_importance: baseline scoring failed; skipping")
        return None

    if baseline is None:
        # ``metric`` is undefined for this problem type/model (e.g. pr_auc on multiclass) —
        # there is nothing to measure a drop against, so report no importances honestly.
        logger.info(
            "permutation_importance: metric %r is undefined for this run; no importances", metric
        )
        return None

    importances: dict[str, float] = {}
    for col in work.columns:
        saved = work[col].to_numpy(copy=True)
        drops: list[float] = []
        try:
            for _ in range(n_repeats):
                work[col] = rng.permutation(saved)
                score = _score(model, work, y_true, problem_type, classes, metric, needs_proba)
                # A permuted score can be None (metric momentarily undefined) — count it as
                # no measurable drop for that repeat rather than discarding the feature.
                drops.append(0.0 if score is None else baseline - score)
        except Exception:  # noqa: BLE001 — one bad column must not kill the whole measure
            logger.exception(
                "permutation_importance: scoring failed for feature %r; recording 0.0", col
            )
            drops = [0.0]
        finally:
            work[col] = saved  # restore before moving to the next column
        importances[str(col)] = float(np.mean(drops))

    return importances
