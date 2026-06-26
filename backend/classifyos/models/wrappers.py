"""Section 11 — the six concrete :class:`ModelWrapper` implementations.

All six share one fit/predict/predict_proba/feature_importance implementation, provided
by :class:`_SklearnEstimatorWrapper`; each concrete wrapper only declares its short
``name``, how it consumes ``class_weight``, and how it builds its underlying estimator.

The wrappers are deliberately library-agnostic from the caller's point of view: whatever
the underlying library does internally (XGBoost insisting on integer labels, GaussianNB
having no ``class_weight`` argument, an RBF SVM exposing no coefficients), the public
contract — original-label predictions, ``(n, n_classes)`` probabilities aligned to
``classes_``, a ``{feature: importance}`` dict or ``None`` — is identical.

**class_weight is applied uniformly via sample-weight translation.** The loader coerces
the target to string dtype, so numeric targets arrive as ``"0"/"1"``; sklearn's native
``class_weight`` *dict* path then int-coerces those labels for lookup and fails to find
the string keys (``ValueError: classes [0, 1] are not in class_weight``). Translating the
``{class: weight}`` dict to a per-sample ``sample_weight`` vector at fit time sidesteps
that fragility and is mathematically equivalent (a class weight IS a per-sample penalty
multiplier), so it works identically across every library here. ``class_weight`` is never
silently ignored — it is always consumed as ``sample_weight`` (single-label problems).

Other library quirks handled here, verified against the installed versions
(scikit-learn 1.9.0, xgboost 3.2.0, lightgbm 4.6.0):

* **XGBoost** rejects string labels (``XGBClassifier`` wants ``0..n-1``), so this wrapper
  label-encodes ``y`` in :meth:`fit` and maps predictions back.
* **XGBoost / LightGBM** reject special characters in feature names (XGBoost: ``[ ] <``;
  LightGBM: any "special JSON character"). JSON-flattened columns like
  ``covers[0].insuranceAmount`` crash training, so both wrappers rename DataFrame columns
  to safe positional names (``f0..fn-1``) before every estimator call and map importances
  back via ``feature_names_``. See ``_needs_safe_feature_names`` / ``_safe_X``.
* **GaussianNB** has no feature importance → ``None``.
* **SVM** uses ``CalibratedClassifierCV(SVC(), ensemble=False)`` for probabilities
  (``SVC(probability=True)`` is deprecated in sklearn 1.9, removed in 1.11). Calibration
  via internal CV is slow on large data but gives a real ``predict_proba``. The calibrated
  classifier exposes no coefficients → feature importance is ``None``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.multiclass import OneVsRestClassifier
from sklearn.preprocessing import LabelEncoder

from .base import ModelWrapper


class _SklearnEstimatorWrapper(ModelWrapper):
    """Shared implementation for sklearn-compatible estimators.

    Subclasses provide :meth:`_build_estimator` and may set one class flag:

    * ``_needs_label_encoding`` — ``True`` if the library cannot handle string labels and
      ``y`` must be label-encoded to ``0..n-1`` (XGBoost).

    ``class_weight`` is consumed here (not in the subclass) by translating the
    ``{class: weight}`` dict to a ``sample_weight`` vector at fit time — see the module
    docstring for why the native ``class_weight`` dict path is avoided.
    """

    #: Estimator needs integer-encoded labels (vs. native string-label support).
    _needs_label_encoding: bool = False

    #: Estimator rejects feature names containing special characters (``[ ] <`` for
    #: XGBoost; any "special JSON character" for LightGBM). When ``True`` the DataFrame
    #: columns are renamed to safe positional names (``f0..fn-1``) before every call into
    #: the estimator. Importances map back to the real names via :attr:`feature_names_`,
    #: which is captured from the *original* (un-renamed) ``X`` in :meth:`fit`.
    _needs_safe_feature_names: bool = False

    def _build_estimator(self) -> Any:
        """Construct the underlying (unfitted) sklearn-compatible estimator."""
        raise NotImplementedError  # pragma: no cover - intermediate base

    # -- contract methods ---------------------------------------------------------

    def fit(self, X: Any, y: Any) -> "_SklearnEstimatorWrapper":
        """Fit the estimator, handling label encoding and class-weight translation.

        For ``problem_type="multilabel"`` the estimator is wrapped in
        :class:`~sklearn.multiclass.OneVsRestClassifier` and ``y`` is expected to be a
        binary indicator matrix of shape ``(n_samples, n_labels)``.
        """
        self.feature_names_ = self._feature_names(X)
        y_arr = np.asarray(y)
        is_multilabel = self.problem_type == "multilabel"

        estimator = self._build_estimator()
        if is_multilabel:
            estimator = OneVsRestClassifier(estimator)

        # XGBoost cannot take string labels — encode to 0..n-1 and map back on predict.
        self._label_encoder: LabelEncoder | None = None
        y_fit = y_arr
        if self._needs_label_encoding and not is_multilabel:
            self._label_encoder = LabelEncoder().fit(y_arr)
            y_fit = self._label_encoder.transform(y_arr)

        # class_weight is consumed as sample_weight (single-label only) so numeric-string
        # labels can't break sklearn's native class_weight-dict lookup. Never dropped.
        fit_kwargs: dict[str, Any] = {}
        if self.class_weight and not is_multilabel:
            fit_kwargs["sample_weight"] = self._sample_weights(y_arr)

        estimator.fit(self._safe_X(X), y_fit, **fit_kwargs)
        self.model = estimator

        if self._label_encoder is not None:
            self.classes_ = np.asarray(self._label_encoder.classes_)
        else:
            self.classes_ = np.asarray(estimator.classes_)
        return self

    def predict(self, X: Any) -> np.ndarray:
        """Predict labels, mapping back to the original label space if encoded."""
        pred = np.asarray(self.model.predict(self._safe_X(X)))
        if self._label_encoder is not None:
            pred = self._label_encoder.inverse_transform(pred)
        return pred

    def predict_proba(self, X: Any) -> np.ndarray:
        """Return ``(n_samples, n_classes)`` probabilities aligned to ``classes_``.

        sklearn/XGBoost/LightGBM all order ``predict_proba`` columns by the estimator's
        own ``classes_``, which we adopt as :attr:`classes_` in :meth:`fit`, so columns
        align by construction.
        """
        proba = np.asarray(self.model.predict_proba(self._safe_X(X)))
        # [RISK] downstream metrics, calibration, classify and the plots all assume a
        # 2-D ``(n, n_classes)`` proba with columns in ``classes_`` order. Guard the
        # degenerate single-column binary case defensively (none of the current
        # estimators hit it, but a future one might).
        if proba.ndim == 1:
            proba = np.column_stack([1.0 - proba, proba])
        return proba

    def feature_importance(self) -> dict[str, float] | None:
        """Return ``{feature: importance}`` from the estimator, or ``None``."""
        importances = self._extract_importances(self.model)
        if importances is None:
            return None
        return {
            name: float(value)
            for name, value in zip(self.feature_names_, importances)
        }

    # -- helpers ------------------------------------------------------------------

    def _safe_X(self, X: Any) -> Any:
        """Rename DataFrame columns to safe positional names for fussy estimators.

        XGBoost rejects ``[ ] <`` and LightGBM rejects any "special JSON character" in
        feature names. Real-world data (e.g. JSON-flattened columns like
        ``covers[0].insuranceAmount``) routinely contains these, which crashed training.
        Renaming to ``f0..fn-1`` by position is safe and reversible: importances come back
        in column order and are mapped to the original names via :attr:`feature_names_`.
        Non-DataFrame ``X`` (a bare ndarray) has no names, so it passes through untouched.
        """
        if not self._needs_safe_feature_names or not isinstance(X, pd.DataFrame):
            return X
        return X.set_axis([f"f{i}" for i in range(X.shape[1])], axis=1)

    @staticmethod
    def _feature_names(X: Any) -> list[str]:
        if isinstance(X, pd.DataFrame):
            return [str(c) for c in X.columns]
        n_cols = np.asarray(X).shape[1]
        return [f"f{i}" for i in range(n_cols)]

    def _sample_weights(self, y_arr: np.ndarray) -> np.ndarray:
        """Translate a ``{class: weight}`` dict to a per-sample weight vector."""
        lookup = {str(k): float(v) for k, v in (self.class_weight or {}).items()}
        return np.array([lookup.get(str(label), 1.0) for label in y_arr], dtype=float)

    def _extract_importances(self, estimator: Any) -> np.ndarray | None:
        """Extract a 1-D importance vector, averaging across OvR sub-estimators."""
        if isinstance(estimator, OneVsRestClassifier):
            per_label = [
                self._raw_importance(sub) for sub in estimator.estimators_
            ]
            per_label = [imp for imp in per_label if imp is not None]
            if not per_label:
                return None
            return np.mean(np.vstack(per_label), axis=0)
        return self._raw_importance(estimator)

    @staticmethod
    def _raw_importance(estimator: Any) -> np.ndarray | None:
        """Importances from ``feature_importances_`` (trees) or ``coef_`` (linear)."""
        if hasattr(estimator, "feature_importances_"):
            return np.asarray(estimator.feature_importances_, dtype=float)
        # ``coef_`` access raises AttributeError on a non-linear SVM, so hasattr is False.
        if hasattr(estimator, "coef_"):
            coef = np.asarray(estimator.coef_, dtype=float)
            return np.abs(coef).mean(axis=0) if coef.ndim > 1 else np.abs(coef)
        return None


class LogisticRegressionModel(_SklearnEstimatorWrapper):
    """Logistic regression (``sklearn.linear_model.LogisticRegression``).

    Feature importance is the mean absolute coefficient per feature (averaged across
    classes for multiclass). For multilabel the base estimator is wrapped in
    :class:`OneVsRestClassifier` by the base class.
    """

    name = "LogisticRegression"

    def _build_estimator(self) -> Any:
        from sklearn.linear_model import LogisticRegression

        kwargs: dict[str, Any] = {
            "max_iter": 1000,  # scaled features still need headroom to converge
            "random_state": self.random_state,
        }
        kwargs.update(self.params)
        return LogisticRegression(**kwargs)


class RandomForestModel(_SklearnEstimatorWrapper):
    """Random forest (``sklearn.ensemble.RandomForestClassifier``).

    Feature importance from ``feature_importances_``.
    """

    name = "RandomForest"

    def _build_estimator(self) -> Any:
        from sklearn.ensemble import RandomForestClassifier

        kwargs: dict[str, Any] = {
            "n_estimators": 200,
            "random_state": self.random_state,
            "n_jobs": -1,
        }
        kwargs.update(self.params)
        return RandomForestClassifier(**kwargs)


class XGBoostModel(_SklearnEstimatorWrapper):
    """Gradient-boosted trees (``xgboost.XGBClassifier``).

    XGBoost rejects string labels, so this wrapper label-encodes ``y`` and maps
    predictions back. Feature importance comes from the booster's
    ``feature_importances_`` (gain-based).
    """

    name = "XGBoost"
    _needs_label_encoding = True  # XGBClassifier requires 0..n-1 labels
    _needs_safe_feature_names = True  # XGBoost rejects [, ], < in feature names

    def _build_estimator(self) -> Any:
        from xgboost import XGBClassifier

        kwargs: dict[str, Any] = {
            "n_estimators": 200,
            "random_state": self.random_state,
            "tree_method": "hist",
            "eval_metric": "logloss",
            "verbosity": 0,
            "n_jobs": -1,
        }
        kwargs.update(self.params)
        return XGBClassifier(**kwargs)


class LightGBMModel(_SklearnEstimatorWrapper):
    """Gradient-boosted trees (``lightgbm.LGBMClassifier``).

    Handles string labels directly. Feature importance from the booster's
    ``feature_importances_`` (split-count based).
    """

    name = "LightGBM"
    _needs_safe_feature_names = True  # LightGBM rejects special JSON chars in feature names

    def _build_estimator(self) -> Any:
        from lightgbm import LGBMClassifier

        kwargs: dict[str, Any] = {
            "n_estimators": 200,
            "random_state": self.random_state,
            "verbose": -1,  # silence LightGBM's per-fit chatter
            "n_jobs": -1,
        }
        kwargs.update(self.params)
        return LGBMClassifier(**kwargs)


class SVMModel(_SklearnEstimatorWrapper):
    """Support vector classifier — ``CalibratedClassifierCV(SVC(), ensemble=False)``.

    ``SVC(probability=True)`` is deprecated in sklearn 1.9 (removed in 1.11), so
    probabilities come from a calibrated wrapper (Platt/isotonic via internal CV — slow
    on large datasets, but a real ``predict_proba``). ``sample_weight`` (the translated
    ``class_weight``) is routed through the calibrator to the underlying SVC.

    [RISK] feature importance: the calibrated classifier exposes no coefficients, so
    :meth:`feature_importance` returns ``None`` (true for the default RBF kernel anyway).
    """

    name = "SVM"

    def _build_estimator(self) -> Any:
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.svm import SVC

        svc_keys = {"C", "kernel", "degree", "gamma", "coef0", "shrinking", "tol"}
        svc_params = {k: v for k, v in self.params.items() if k in svc_keys}
        calib_params = {k: v for k, v in self.params.items() if k not in svc_keys}
        svc = SVC(random_state=self.random_state, **svc_params)
        return CalibratedClassifierCV(svc, ensemble=False, **calib_params)


class NaiveBayesModel(_SklearnEstimatorWrapper):
    """Gaussian naive Bayes (``sklearn.naive_bayes.GaussianNB``).

    GaussianNB has no ``random_state`` argument; a ``class_weight`` dict is consumed as
    ``sample_weight`` by the base class at fit time. It exposes no feature importance
    → :meth:`feature_importance` returns ``None``.
    """

    name = "NaiveBayes"

    def _build_estimator(self) -> Any:
        from sklearn.naive_bayes import GaussianNB

        # GaussianNB takes no random_state.
        return GaussianNB(**self.params)
