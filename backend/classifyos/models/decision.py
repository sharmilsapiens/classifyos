"""Decision policy — probability calibration + the binary decision threshold.

This module is the *single* place ClassifyOS composes the two post-fit decisions an analyst
controls but the model does not learn on its own:

* **Calibration** (``calibrate_probs``) — reshape the predicted *probabilities* so they are
  trustworthy (a predicted 0.8 reflects ~80% observed frequency), via sklearn's
  :class:`~sklearn.calibration.CalibratedClassifierCV` (binary + multiclass).
* **Decision threshold** (``threshold_mode``) — choose *where* a binary probability is cut to
  assign the positive class. ``fixed`` applies an analyst value
  (:class:`~sklearn.model_selection.FixedThresholdClassifier`); ``tuned`` searches for the
  cutoff that maximises a metric (:class:`~sklearn.model_selection.TunedThresholdClassifierCV`).

These are orthogonal: calibration makes a threshold *meaningful*; it does not pick one.

The engine never re-implements either — it composes sklearn-native meta-estimators around the
built estimator, so the maths is sklearn's and survives version upgrades. Composition order
(binary, both on) is ``Threshold( Calibrate( base ) )`` so the threshold cuts a calibrated
probability and ``predict_proba`` still returns the calibrated columns (the threshold wrappers
delegate ``predict_proba`` to the inner estimator and only change ``predict``).

[RISK] leakage — every wrapper fits via internal CV on the TRAIN matrices it is handed; the
TUNED threshold is selected on internal CV folds of TRAIN, NEVER the held-out test set. The
test set still only ever sees ``predict``/``predict_proba``.

[RISK] class_weight routing — when a threshold wrapper is the OUTERMOST estimator, sklearn does
NOT pass ``sample_weight`` through to the inner ``fit`` unless metadata routing is enabled
(verified on scikit-learn 1.9.0). The engine translates ``class_balance="class_weight"`` into a
per-sample weight, so for that combination we fit inside a scoped
``config_context(enable_metadata_routing=True)`` and explicitly request ``sample_weight`` on the
base + calibration layers, while explicitly *not* requesting it on the threshold-selection
scorer (so the operating point is chosen on the natural class distribution, not the reweighted
one). This routing is sklearn-version-sensitive; it is exercised by a dedicated unit test.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any, NamedTuple

import numpy as np
import sklearn
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    f1_score,
    make_scorer,
    precision_score,
    recall_score,
)
from sklearn.model_selection import (
    FixedThresholdClassifier,
    TunedThresholdClassifierCV,
)

#: k-fold used by both the calibrator and the tuned-threshold search. Kept small (3) so the
#: extra refits calibration introduces on every run stay cheap; the tuned path nests this
#: inside its own CV, so a tuned + calibrated model does cv*cv base fits — opt-in and slow.
DECISION_CV = 3


class DecisionInfo(NamedTuple):
    """What the decision policy actually did, for reporting on the run result.

    Attributes:
        calibrated: ``True`` if the probabilities are calibrated (an applied calibration OR a
            model that is intrinsically calibrated, e.g. the SVM wrapper).
        threshold: The effective positive-class operating threshold for a BINARY problem
            (the tuned best threshold, the fixed value, or 0.5 for the default argmax).
            ``None`` for multiclass/multilabel, where the threshold is not a single scalar.
    """

    calibrated: bool
    threshold: float | None


def _is_calibrated(estimator: Any) -> bool:
    """True if ``estimator`` is already a calibrated classifier (avoid double-wrapping)."""
    return isinstance(estimator, CalibratedClassifierCV)


def _build_threshold_scorer(metric: str, pos_label: Any) -> Any:
    """Scorer a TUNED threshold maximises, with the positive class wired in.

    The engine coerces targets to strings, so the default integer ``pos_label=1`` of sklearn's
    string scorers is invalid (``pos_label=1 is not a valid label: ['0','1']``). The
    positive-class metrics (f1/precision/recall) are therefore built with the engine's
    positive class — the lexicographically-last label, matching ``curves.py``/``metrics.py``.
    The averaged/global metrics (weighted/macro F1, accuracy, balanced accuracy) ignore
    ``pos_label`` but still vary with the cut, so they tune meaningfully too.
    """
    if metric == "f1":
        return make_scorer(f1_score, pos_label=pos_label)
    if metric == "precision":
        return make_scorer(precision_score, pos_label=pos_label, zero_division=0)
    if metric == "recall":
        return make_scorer(recall_score, pos_label=pos_label, zero_division=0)
    if metric == "f1_weighted":
        return make_scorer(f1_score, average="weighted")
    if metric == "f1_macro":
        return make_scorer(f1_score, average="macro")
    if metric == "balanced_accuracy":
        return make_scorer(balanced_accuracy_score)
    # "accuracy" (the remaining THRESHOLD_METRICS member)
    return make_scorer(accuracy_score)


def fit_policy(
    base_estimator: Any,
    X: Any,
    y: Any,
    *,
    problem_type: str,
    calibrate: bool,
    threshold_mode: str,
    threshold: float,
    scoring: str,
    cv: int = DECISION_CV,
    sample_weight: Any | None = None,
) -> tuple[Any, DecisionInfo]:
    """Wrap ``base_estimator`` with the requested policy, fit it, and report what was applied.

    Calibration applies to binary + multiclass (skipped when ``base_estimator`` is already a
    :class:`CalibratedClassifierCV`, i.e. the SVM). The threshold policy applies to BINARY only;
    multiclass/multilabel keep the argmax and ``threshold``/``threshold_mode`` are ignored.

    Args:
        base_estimator: The unfitted sklearn-compatible estimator from a model wrapper.
        X, y: TRAIN matrices (already preprocessed/engineered/balanced by the runner).
        problem_type: ``"binary"``, ``"multiclass"`` or ``"multilabel"``.
        calibrate: Whether to calibrate probabilities.
        threshold_mode: ``"default"`` | ``"fixed"`` | ``"tuned"`` (binary only).
        threshold: The cutoff used in ``"fixed"`` mode.
        scoring: sklearn scorer name maximised in ``"tuned"`` mode.
        cv: Internal CV folds for calibration / threshold search.
        sample_weight: Optional per-sample weights (the class_weight translation); routed to
            the base + calibration fit, never to the threshold-selection scorer.

    Returns:
        ``(fitted_estimator, DecisionInfo)``.
    """
    needs_threshold = problem_type == "binary" and threshold_mode in ("fixed", "tuned")
    # sample_weight only fails to route through the OUTER threshold wrapper; calibration alone
    # consumes it natively. So we only need the (version-sensitive) routing context for the
    # threshold + weighted combination.
    use_routing = needs_threshold and sample_weight is not None
    ctx = (
        sklearn.config_context(enable_metadata_routing=True)
        if use_routing
        else nullcontext()
    )

    with ctx:
        est = base_estimator
        if use_routing:
            # Every layer must opt into sample_weight under metadata routing. Request it on the
            # base AND on a nested inner estimator (e.g. the SVM wrapper is already a
            # CalibratedClassifierCV(SVC) — the inner SVC needs the request too).
            est = est.set_fit_request(sample_weight=True)
            inner = getattr(est, "estimator", None)
            if inner is not None and hasattr(inner, "set_fit_request"):
                inner.set_fit_request(sample_weight=True)

        calibrate_applied = False
        if calibrate and problem_type in ("binary", "multiclass") and not _is_calibrated(est):
            est = CalibratedClassifierCV(est, cv=cv, ensemble=False)
            if use_routing:
                est = est.set_fit_request(sample_weight=True)
            calibrate_applied = True

        if needs_threshold:
            # Positive class = lexicographically-last label (the proba last column), matching
            # the engine's binary convention in curves.py / metrics.py.
            pos_label = sorted(np.unique(y).tolist())[-1]
            if threshold_mode == "fixed":
                est = FixedThresholdClassifier(
                    est,
                    threshold=threshold,
                    pos_label=pos_label,
                    response_method="predict_proba",
                )
            else:  # tuned
                scorer = _build_threshold_scorer(scoring, pos_label)
                if use_routing:
                    # The operating point is tuned on the NATURAL distribution: the scorer must
                    # not consume sample_weight even though the base fit does.
                    scorer = scorer.set_score_request(sample_weight=False)
                est = TunedThresholdClassifierCV(
                    est, scoring=scorer, cv=cv, refit=True
                )

        if sample_weight is not None:
            est.fit(X, y, sample_weight=sample_weight)
        else:
            est.fit(X, y)

    calibrated = calibrate_applied or _is_calibrated(base_estimator)
    info = DecisionInfo(
        calibrated=calibrated,
        threshold=effective_threshold(est, problem_type, threshold),
    )
    return est, info


def effective_threshold(
    fitted: Any, problem_type: str, fixed_threshold: float
) -> float | None:
    """Read back the positive-class operating threshold actually in force (binary only).

    ``TunedThresholdClassifierCV`` exposes the chosen cutoff as ``best_threshold_``; a
    ``FixedThresholdClassifier`` uses the supplied value; an unwrapped binary model uses the
    implicit 0.5 argmax. Returns ``None`` for multiclass/multilabel.
    """
    if problem_type != "binary":
        return None
    if isinstance(fitted, TunedThresholdClassifierCV):
        return float(fitted.best_threshold_)
    if isinstance(fitted, FixedThresholdClassifier):
        return float(fixed_threshold)
    return 0.5


def unwrap_base_estimator(fitted: Any) -> Any:
    """Peel the decision-policy wrappers off a fitted model to reach the scoring estimator.

    Native feature importance reads ``coef_`` / ``feature_importances_``, which the calibration
    and threshold meta-estimators do not expose. This unwraps
    ``[Tuned|Fixed]ThresholdClassifier`` → ``CalibratedClassifierCV`` → the underlying fitted
    estimator (the one trained on the full TRAIN split when ``ensemble=False``), so importances
    survive a calibrated/thresholded run. A plain estimator or an ``OneVsRestClassifier``
    (multilabel — never wrapped by a policy) is returned unchanged.
    """
    est = fitted
    if isinstance(est, (TunedThresholdClassifierCV, FixedThresholdClassifier)):
        est = getattr(est, "estimator_", est)
    if isinstance(est, CalibratedClassifierCV):
        calibrated = getattr(est, "calibrated_classifiers_", None)
        if calibrated:
            inner = getattr(calibrated[0], "estimator", None)
            if inner is not None:
                est = inner
    return est
