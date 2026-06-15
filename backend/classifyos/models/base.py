"""Section 11 — :class:`ModelWrapper`, the abstract model contract.

Every concrete model in ClassifyOS (logistic regression, random forest, XGBoost,
LightGBM, SVM, naive Bayes — see :mod:`classifyos.models.wrappers`) subclasses
:class:`ModelWrapper` and obeys the same interface, so the rest of the engine
(evaluation, ``classify``, ``ModelRunner``, the API serializers) can treat any model
uniformly regardless of the underlying library.

The contract every wrapper must honour:

* ``fit(X, y) -> self`` — train on the (already preprocessed, engineered, balanced)
  TRAIN matrices. Sets ``classes_``.
* ``predict(X) -> np.ndarray`` — predicted labels in the ORIGINAL label space (strings),
  not an internal integer encoding.
* ``predict_proba(X) -> np.ndarray`` — **always** shape ``(n_samples, n_classes)`` with
  columns ordered to match ``classes_``. For binary this is two columns (never one); for
  multilabel it is ``(n_samples, n_labels)``.
* ``feature_importance() -> dict[str, float] | None`` — per-feature importance, or
  ``None`` when the model exposes none (e.g. an RBF-kernel SVM, GaussianNB).

[RISK] The ``(n_samples, n_classes)`` proba shape and the ``classes_`` column ordering
are an engine-wide assumption: metrics (ROC-AUC, log-loss, calibration), ``classify``,
and the plots all index proba columns by ``classes_``. A wrapper that returns a
single-column binary proba, or columns in a different order than ``classes_``, silently
corrupts every downstream metric. New wrappers MUST be validated against this shape
(see ``tests/test_models.py::test_all_wrappers_fit_predict``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import numpy as np


class ModelWrapper(ABC):
    """Abstract base class all ClassifyOS model wrappers implement.

    Args:
        problem_type: One of ``"binary"``, ``"multiclass"``, ``"multilabel"``.
        class_weight: Optional ``{class_label: weight}`` dict produced by
            :func:`classifyos.preprocessing.balance.handle_class_imbalance` when
            ``class_balance="class_weight"``. Each wrapper consumes it explicitly —
            either as a native estimator parameter or, where the library has no
            ``class_weight`` argument (XGBoost, GaussianNB), translated to per-sample
            weights at fit time. It is NEVER silently ignored.
        random_state: Seed for reproducibility (passed to estimators that accept it).
        **params: Extra keyword arguments forwarded to the underlying estimator,
            overriding the wrapper's defaults.

    Attributes:
        name: Short registry key (e.g. ``"RandomForest"``); set on each subclass.
        classes_: Learned class labels (a ``np.ndarray``), set in :meth:`fit`. Defines
            the column order of :meth:`predict_proba`.
    """

    #: Short key matching :data:`classifyos.models.registry.MODEL_REGISTRY`.
    name: str = ""

    def __init__(
        self,
        problem_type: str,
        class_weight: dict[Any, float] | None = None,
        random_state: int = 42,
        **params: Any,
    ) -> None:
        if problem_type not in ("binary", "multiclass", "multilabel"):
            raise ValueError(
                "problem_type must be one of ['binary', 'multiclass', 'multilabel'], "
                f"got {problem_type!r}"
            )
        self.problem_type = problem_type
        self.class_weight = class_weight
        self.random_state = random_state
        self.params: dict[str, Any] = dict(params)
        #: Underlying fitted estimator; ``None`` until :meth:`fit` is called.
        self.model: Any = None
        #: Learned class labels; ``None`` until :meth:`fit` is called.
        self.classes_: np.ndarray | None = None

    @abstractmethod
    def fit(self, X: Any, y: Any) -> "ModelWrapper":
        """Train the model on TRAIN matrices and return ``self``."""

    @abstractmethod
    def predict(self, X: Any) -> np.ndarray:
        """Return predicted labels (original label space) of shape ``(n_samples,)``."""

    @abstractmethod
    def predict_proba(self, X: Any) -> np.ndarray:
        """Return class probabilities of shape ``(n_samples, n_classes)``.

        Columns are ordered to match :attr:`classes_`. Binary problems return two
        columns; multilabel returns ``(n_samples, n_labels)``.
        """

    @abstractmethod
    def feature_importance(self) -> dict[str, float] | None:
        """Return ``{feature_name: importance}`` or ``None`` if unavailable."""
