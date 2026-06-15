"""Section 8 — ``handle_class_imbalance`` (class-imbalance handling, TRAIN ONLY).

Pipeline position: ``split → preprocess → build_features → interactions →
handle_class_imbalance (TRAIN ONLY) → train``. This stage rebalances the *training*
class distribution (or computes class weights for the model to consume); the input it
receives is the fully-engineered, all-numeric training matrix.

[RISK] The single most important rule of this stage: it operates ONLY on the training
features/labels passed in and has NO access to the test set by design. Resampling or
reweighting anything but the training split (SMOTE synthesising on test rows, an
undersampler discarding test rows, class weights computed from the full dataset)
inflates evaluation metrics and is leakage. The test set is NEVER resampled or
reweighted — on ``class_weight`` the weights pass through to the model, which applies
them during training only.

Strategies (``config["class_balance"]``):

* ``smote``        — imbalanced-learn SMOTE oversampling. Returns ``(X_res, y_res,
  None)``. ``k_neighbors`` is auto-reduced when the minority class is small; a minority
  of size ≤1 falls back to random oversampling.
* ``undersample``  — imbalanced-learn RandomUnderSampler. Returns ``(X_res, y_res,
  None)``; logs how many majority rows were dropped.
* ``class_weight`` — NO resampling. Returns ``(X_train, y_train, class_weight)`` where
  ``class_weight`` is a ``"balanced"`` dict for the model. The ONLY strategy returning a
  non-``None`` class weight.
* ``none``         — returns the inputs unchanged with ``class_weight=None``.

Multilabel targets cannot be resampled by SMOTE/undersampling (a single row carries
several labels); they fall back to ``class_weight`` with a logged warning.

The return is always a 3-tuple ``(X_res, y_res, class_weight)`` with ``X_res`` columns
identical to ``X_train`` (order preserved). Neither the inputs nor the config is mutated.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

import numpy as np
import pandas as pd
from imblearn.over_sampling import SMOTE, RandomOverSampler
from imblearn.under_sampling import RandomUnderSampler
from sklearn.utils.class_weight import compute_class_weight

logger = logging.getLogger(__name__)

#: SMOTE's default neighbour count (matches imbalanced-learn's own default).
_DEFAULT_K_NEIGHBORS = 5


def handle_class_imbalance(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.Series, dict[Any, float] | None]:
    """Rebalance the TRAIN split per ``config["class_balance"]`` (train only).

    Args:
        X_train: TRAIN feature matrix (all-numeric after the engineering stages).
            Never mutated.
        y_train: TRAIN labels aligned with ``X_train``. Never mutated.
        config: Run config. Reads ``class_balance``, ``problem_type``, ``random_state``.

    Returns:
        A 3-tuple ``(X_res, y_res, class_weight)``:

        * ``X_res`` — resampled (smote/undersample) or unchanged (class_weight/none)
          feature frame; columns identical to ``X_train`` in the same order.
        * ``y_res`` — labels aligned with ``X_res`` (a ``pd.Series``).
        * ``class_weight`` — a ``{class_label: weight}`` dict for ``class_weight``;
          ``None`` for every other strategy.

    Raises:
        ValueError: If ``class_balance`` is not one of
            ``smote | undersample | class_weight | none``.
    """
    strategy = config.get("class_balance", "none")
    problem_type = config.get("problem_type", "binary")
    random_state = config.get("random_state", 42)

    # Work on independent copies so the caller's arrays are never touched. [RISK] the
    # function is handed TRAIN only; it must not (and cannot) see the test set.
    X = X_train.copy()
    y = pd.Series(y_train).copy()
    y.name = getattr(y_train, "name", None)

    if strategy not in ("smote", "undersample", "class_weight", "none"):
        raise ValueError(
            "config['class_balance'] must be one of "
            f"['smote', 'undersample', 'class_weight', 'none'], got {strategy!r}"
        )

    # Multilabel: SMOTE / undersampling are not applicable (one row carries multiple
    # labels, so there is no single class to resample on). [RISK] multilabel resampling
    # is unsupported in v1.0 — fall back to class weights (plan_tweak entry).
    if problem_type == "multilabel" and strategy in ("smote", "undersample"):
        logger.warning(
            "class_balance=%r is not supported for multilabel targets; "
            "falling back to 'class_weight'.",
            strategy,
        )
        strategy = "class_weight"

    if strategy == "none":
        return X, y, None

    if strategy == "class_weight":
        return X, y, _compute_class_weight(y)

    if strategy == "smote":
        return _apply_smote(X, y, random_state)

    # undersample
    return _apply_undersample(X, y, random_state)


def _compute_class_weight(y: pd.Series) -> dict[Any, float]:
    """Compute a ``"balanced"`` ``{class: weight}`` dict (no resampling).

    This is the only path that returns class weights; the model applies them during
    training, so the test set is never altered.
    """
    classes = np.unique(y.to_numpy())
    weights = compute_class_weight("balanced", classes=classes, y=y.to_numpy())
    class_weight = {cls: float(w) for cls, w in zip(classes, weights)}
    logger.info("class_weight (balanced): %s", class_weight)
    return class_weight


def _apply_smote(
    X: pd.DataFrame, y: pd.Series, random_state: int
) -> tuple[pd.DataFrame, pd.Series, None]:
    """Oversample the minority class(es) with SMOTE, guarding tiny minorities.

    SMOTE interpolates between a sample and its ``k_neighbors`` nearest same-class
    neighbours, so it needs ``k_neighbors < minority_count``. We auto-reduce
    ``k_neighbors`` to ``minority_count - 1`` when the default (5) is too large, and
    fall back to random oversampling when the minority has ≤1 sample (SMOTE cannot
    interpolate from a single point).
    """
    counts = y.value_counts()
    minority_count = int(counts.min())

    if minority_count <= 1:
        # [RISK] tiny minority classes (fraud at ~1% / extreme ratios): SMOTE cannot
        # synthesise from a single example. Duplicate existing minority rows instead.
        logger.warning(
            "Minority class has %d sample(s); SMOTE needs ≥2. Falling back to "
            "random oversampling (duplicates minority rows, adds no synthetic variety).",
            minority_count,
        )
        sampler = RandomOverSampler(random_state=random_state)
    else:
        k_neighbors = min(_DEFAULT_K_NEIGHBORS, minority_count - 1)
        if k_neighbors < _DEFAULT_K_NEIGHBORS:
            logger.warning(
                "Smallest class has %d samples; reducing SMOTE k_neighbors from %d "
                "to %d.",
                minority_count,
                _DEFAULT_K_NEIGHBORS,
                k_neighbors,
            )
        sampler = SMOTE(random_state=random_state, k_neighbors=k_neighbors)

    X_res, y_res = sampler.fit_resample(X, y)
    X_res, y_res = _coerce(X_res, y_res, X.columns, y.name)
    logger.info(
        "SMOTE: %d → %d train rows (minority was %d).",
        len(X),
        len(X_res),
        minority_count,
    )
    return X_res, y_res, None


def _apply_undersample(
    X: pd.DataFrame, y: pd.Series, random_state: int
) -> tuple[pd.DataFrame, pd.Series, None]:
    """Randomly undersample the majority class(es) to balance the train split.

    [RISK] undersampling discards majority-class rows — information is thrown away.
    The number of dropped rows is logged so the trade-off is visible.
    """
    sampler = RandomUnderSampler(random_state=random_state)
    X_res, y_res = sampler.fit_resample(X, y)
    X_res, y_res = _coerce(X_res, y_res, X.columns, y.name)
    dropped = len(X) - len(X_res)
    logger.info(
        "RandomUnderSampler: %d → %d train rows (%d majority rows dropped).",
        len(X),
        len(X_res),
        dropped,
    )
    return X_res, y_res, None


def _coerce(
    X_res: Any, y_res: Any, columns: pd.Index, y_name: Any
) -> tuple[pd.DataFrame, pd.Series]:
    """Normalise resampler output to a DataFrame (column order preserved) + Series.

    imbalanced-learn preserves DataFrame columns on resample, but we re-impose the
    original column order and rebuild a clean index defensively so downstream code can
    rely on ``X_res.columns == X_train.columns`` exactly.
    """
    if not isinstance(X_res, pd.DataFrame):
        X_res = pd.DataFrame(X_res, columns=list(columns))
    else:
        X_res = X_res[list(columns)]
    X_res = X_res.reset_index(drop=True)

    if not isinstance(y_res, pd.Series):
        y_res = pd.Series(y_res)
    y_res = y_res.reset_index(drop=True)
    y_res.name = y_name
    return X_res, y_res
