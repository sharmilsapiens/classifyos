"""Per-row SHAP explanations — *local* explainability (why THIS prediction?).

The two importance screens ClassifyOS already ships are **global**: native
``feature_importance`` and model-agnostic ``permutation_importance`` each rank features
across the whole test set. This module answers the complementary, per-row question an
underwriter or claims adjuster actually asks: *"why did the model predict this for **this**
policy/claim?"* — the reason-code / adverse-action need that is close to mandatory in
insurance.

It uses **SHAP** (SHapley Additive exPlanations). SHAP's defining property is that the
contributions are **additive**::

    base_value  (the model's average output)  +  Σ feature contributions  =  the prediction

so a "waterfall" starting at the population-average probability and adding each feature's
push (up or down) lands exactly on this row's predicted probability. That reconstruction is
what the Explainability page charts.

**Explainer per model** (chosen so every one of the six models is covered, in probability
space, additively):

* Tree models (``RandomForest`` / ``XGBoost`` / ``LightGBM``) → :class:`shap.TreeExplainer`
  with ``model_output="probability"`` on the *unwrapped* base estimator (peeled past the
  calibration/threshold policy wrappers via
  :func:`classifyos.models.decision.unwrap_base_estimator`, exactly as native importance
  does). Fast and exact; explains the base tree's probability. When probability calibration
  is on the calibrated proba differs slightly (a monotone post-transform) — the waterfall
  reflects the underlying model.
* Everything else (``LogisticRegression`` / ``SVM`` / ``NaiveBayes``) → the model-agnostic
  :class:`shap.KernelExplainer` over the wrapper's ``predict_proba``. Slower (hence the
  small kmeans background + bounded sample), but it needs only ``predict_proba`` so it
  covers the RBF-SVM and GaussianNB that expose no native importance at all — additive to
  the (calibrated) probability the dashboard reports.

Which class is explained: the **positive class** for binary (the engine's
lexicographically-last convention — the "event": lapse/fraud/claim), the **predicted
(argmax) class** for multiclass. Multilabel is not supported in v1 (returns ``None``).

[RISK] leakage — nothing is fitted here. The SHAP *background* (reference distribution) is
sampled from the TRAIN matrix (a reference only, never trained on); the rows explained are
read-only TEST rows. No estimator state changes and no input frame is mutated. This reports
on the model; it does not train it.

Determinism: the background sample is seeded, so a run with a fixed ``random_state``
reproduces the same reference.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from ..models.decision import unwrap_base_estimator

logger = logging.getLogger(__name__)

#: Registry keys whose fitted estimator is tree-based, so ``shap.TreeExplainer`` applies
#: (fast + exact). Every other model falls to the model-agnostic ``KernelExplainer``.
_TREE_MODELS = frozenset({"RandomForest", "XGBoost", "LightGBM"})

#: Default number of TRAIN rows sampled as the SHAP background (reference distribution).
DEFAULT_BACKGROUND_SIZE = 100

#: KernelExplainer cost scales with the background size, so the sampled background is further
#: summarised to at most this many k-means clusters before explaining (keeps the opt-in
#: SVM/NaiveBayes path affordable without materially changing the reference).
_KERNEL_CLUSTERS = 20

#: Bounded number of coalition samples per explained row for KernelExplainer (vs shap's
#: ``2·n_features + 2048`` default) — keeps the cost predictable on the slow calibrated SVM.
#: SHAP's local-accuracy constraint keeps the values additive at this count.
_KERNEL_NSAMPLES = 200


def explain_rows(
    model: Any,
    X_background: pd.DataFrame,
    X_explain: pd.DataFrame,
    problem_type: str,
    *,
    background_size: int = DEFAULT_BACKGROUND_SIZE,
    random_state: int = 42,
) -> dict[str, Any] | None:
    """Compute per-row SHAP contributions for one fitted model.

    Args:
        model: A fitted :class:`~classifyos.models.base.ModelWrapper`. Tree models are
            unwrapped to their base estimator for :class:`shap.TreeExplainer`; the rest are
            explained through their ``predict_proba`` with :class:`shap.KernelExplainer`.
        X_background: TRAIN feature matrix — sampled as the SHAP reference distribution.
            Reference only; never fitted on, never mutated.
        X_explain: The (small) set of held-out TEST rows to explain — same engineered/active
            columns the model was fitted on. Read-only.
        problem_type: ``"binary"`` | ``"multiclass"`` | ``"multilabel"``.
        background_size: TRAIN rows to sample as the background (default
            :data:`DEFAULT_BACKGROUND_SIZE`).
        random_state: Seed for the background sample (reproducible).

    Returns:
        ``{"method": <explainer name>, "rows": [{"sample_index", "explained_class",
        "base_value", "prediction", "contributions": {feature: value}}, …]}`` — one entry per
        row of ``X_explain``, where ``prediction == base_value + Σ contributions`` (the
        SHAP-consistent landing point of the waterfall). Returns ``None`` for multilabel
        (unsupported in v1), when there is nothing to explain (no rows/columns), or when the
        explainer fails — so this report-only step never aborts the run.
    """
    if problem_type == "multilabel":
        # OneVsRest, one estimator per label — no single waterfall to draw. Out of scope for v1.
        return None
    if X_explain is None or getattr(X_explain, "shape", (0, 0))[1] == 0 or len(X_explain) == 0:
        return None
    if X_background is None or len(X_background) == 0:
        return None

    import shap  # lazy — the (optional) SHAP dependency is only imported when explaining.

    cols = list(X_explain.columns)
    classes = list(np.asarray(model.classes_))
    n_classes = len(classes)

    # Background: a seeded sample of TRAIN rows (reference distribution; not fitted on).
    n_bg = min(int(background_size), len(X_background))
    background = shap.sample(X_background, n_bg, random_state=random_state)

    is_tree = getattr(model, "name", "") in _TREE_MODELS
    values: np.ndarray
    base: np.ndarray
    method: str
    kind: str

    if is_tree:
        try:
            base_est = unwrap_base_estimator(model.model)
            explainer = shap.TreeExplainer(
                base_est,
                data=background,
                model_output="probability",
                feature_perturbation="interventional",
            )
            expl = explainer(X_explain)
            values = np.asarray(expl.values)
            base = np.asarray(expl.base_values)
            method, kind = "shap.TreeExplainer", "tree"
        except Exception:  # noqa: BLE001 — fall back to the model-agnostic explainer
            logger.exception(
                "explain_rows: TreeExplainer failed for %r; falling back to KernelExplainer",
                getattr(model, "name", "?"),
            )
            is_tree = False

    if not is_tree:
        try:
            summary = shap.kmeans(background, min(len(background), _KERNEL_CLUSTERS))
            predict_proba = lambda data: model.predict_proba(  # noqa: E731
                pd.DataFrame(data, columns=cols)
            )
            explainer = shap.KernelExplainer(predict_proba, summary, silent=True)
            values = np.asarray(
                explainer.shap_values(X_explain, nsamples=_KERNEL_NSAMPLES, silent=True)
            )
            base = np.asarray(explainer.expected_value)
            method, kind = "shap.KernelExplainer", "kernel"
        except Exception:  # noqa: BLE001 — report-only; a failure must not kill the run
            logger.exception(
                "explain_rows: KernelExplainer failed for %r; no explanations",
                getattr(model, "name", "?"),
            )
            return None

    # For multiclass we explain the predicted (argmax) class per row; for binary the positive
    # class (classes_[-1], the engine's lexicographically-last "event" convention).
    try:
        proba = np.asarray(model.predict_proba(X_explain))
    except Exception:  # noqa: BLE001
        logger.exception("explain_rows: predict_proba failed for %r", getattr(model, "name", "?"))
        return None

    rows: list[dict[str, Any]] = []
    for i in range(len(X_explain)):
        tgt = (n_classes - 1) if problem_type == "binary" else int(np.argmax(proba[i]))
        contrib, base_value = _row_contribution(values, base, i, tgt, kind, n_classes)
        contributions = {str(feat): float(c) for feat, c in zip(cols, contrib)}
        rows.append(
            {
                "sample_index": i,
                "explained_class": str(classes[tgt]),
                "base_value": float(base_value),
                # The SHAP-consistent landing point — guaranteed to equal the drawn waterfall.
                "prediction": float(base_value + sum(contributions.values())),
                "contributions": contributions,
            }
        )

    return {"method": method, "rows": rows}


def _row_contribution(
    values: np.ndarray,
    base: np.ndarray,
    i: int,
    tgt: int,
    kind: str,
    n_classes: int,
) -> tuple[np.ndarray, float]:
    """Normalise the (per-explainer) SHAP output shapes to (contrib_vector, base_scalar).

    The two explainer families return different shapes, and even within a family a binary
    single-output model (XGBoost/LightGBM) differs from a per-class one (RandomForest):

    * ``values`` is either ``(rows, features, classes)`` (per-class) or ``(rows, features)``
      (single-output = the positive class) → take the target-class column, else the row.
    * ``base`` is ``(rows, classes)`` / ``(rows,)`` for TreeExplainer's ``base_values`` (a
      value per explained row), but ``(classes,)`` / scalar for KernelExplainer's
      ``expected_value`` (a value per class, shared across rows). ``kind`` disambiguates the
      1-D case, which is otherwise ambiguous when ``n_rows == n_classes``.
    """
    contrib = values[i, :, tgt] if values.ndim == 3 else values[i]

    if kind == "kernel":
        if base.ndim >= 1:
            base_value = base[tgt] if base.shape[0] == n_classes else base[0]
        else:
            base_value = base
    else:  # tree — base_values carries one entry per explained row
        if base.ndim == 2:
            base_value = base[i, tgt]
        elif base.ndim == 1:
            base_value = base[i]
        else:
            base_value = base

    return np.asarray(contrib, dtype=float), float(base_value)
