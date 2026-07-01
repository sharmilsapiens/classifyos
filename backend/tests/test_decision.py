"""Tests for the decision policy — probability calibration + the binary decision threshold.

These exercise :mod:`classifyos.models.decision` through the real model wrappers on
fully-engineered insurance matrices (see ``conftest.build_matrices``). The contract:

* calibration applies to binary + multiclass and survives native feature importance
  (the calibration wrapper hides ``coef_``/``feature_importances_`` — we must unwrap);
* the binary threshold is honoured (fixed) or chosen leakage-safe on TRAIN folds (tuned);
* multiclass/multilabel ignore the threshold (no single scalar cut);
* ``class_weight`` (→ sample_weight) still reaches the fit when a threshold wrapper is the
  outermost estimator (the metadata-routing path);
* the effective threshold + calibration status are reported on the wrapper.
"""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import FixedThresholdClassifier, TunedThresholdClassifierCV

from classifyos.models.decision import (
    fit_policy,
    unwrap_base_estimator,
)
from classifyos.models.registry import build_model


def _policy_model(name, matrices, *, class_weight=None, **policy):
    """Build a wrapper, set the decision policy, fit on binary/multiclass matrices."""
    model = build_model(
        name, problem_type=matrices.config["problem_type"], class_weight=class_weight
    )
    model.set_decision_policy(
        calibrate=policy.get("calibrate", True),
        threshold_mode=policy.get("threshold_mode", "default"),
        threshold=policy.get("threshold", 0.5),
        threshold_metric=policy.get("threshold_metric", "f1"),
    )
    model.fit(matrices.X_train, matrices.y_train)
    return model


# --- calibration -----------------------------------------------------------------------

def test_calibration_applied_and_importance_survives(binary_matrices) -> None:
    """Default policy calibrates; native importance still works through the wrapper."""
    model = _policy_model("LogisticRegression", binary_matrices, calibrate=True)
    assert model._decision_info.calibrated is True
    assert model._decision_info.threshold == 0.5  # default argmax operating point
    # The fitted model is a CalibratedClassifierCV; importance must still come back.
    assert isinstance(model.model, CalibratedClassifierCV)
    importances = model.feature_importance()
    assert importances is not None and len(importances) == binary_matrices.X_train.shape[1]


def test_calibrate_off_leaves_estimator_bare(binary_matrices) -> None:
    """calibrate=False → not calibrated, plain estimator, 0.5 operating point."""
    model = _policy_model("LogisticRegression", binary_matrices, calibrate=False)
    assert model._decision_info.calibrated is False
    assert not isinstance(model.model, CalibratedClassifierCV)
    assert model._decision_info.threshold == 0.5


def test_svm_reports_calibrated_even_when_off(binary_matrices) -> None:
    """The SVM is intrinsically calibrated, so ``calibrated`` is True even with the flag off."""
    model = _policy_model("SVM", binary_matrices, calibrate=False)
    assert model._decision_info.calibrated is True


# --- fixed threshold -------------------------------------------------------------------

def test_fixed_threshold_cuts_at_value(binary_matrices) -> None:
    """Fixed mode applies the configured cut: predict positive iff P(pos) >= threshold."""
    model = _policy_model(
        "LogisticRegression", binary_matrices, threshold_mode="fixed", threshold=0.3
    )
    assert model._decision_info.threshold == 0.3
    assert isinstance(model.model, FixedThresholdClassifier)

    proba = model.predict_proba(binary_matrices.X_test)
    pred = model.predict(binary_matrices.X_test)
    positive = model.classes_[-1]  # engine convention: positive = last class
    expected_positive = proba[:, -1] >= 0.3
    got_positive = pred == positive
    np.testing.assert_array_equal(got_positive, expected_positive)


# --- tuned threshold -------------------------------------------------------------------

def test_tuned_threshold_is_chosen_and_valid(binary_matrices) -> None:
    """Tuned mode selects a finite operating threshold in (0, 1) from TRAIN CV."""
    model = _policy_model(
        "LogisticRegression", binary_matrices, threshold_mode="tuned", threshold_metric="f1"
    )
    assert isinstance(model.model, TunedThresholdClassifierCV)
    thr = model._decision_info.threshold
    assert thr is not None and 0.0 < thr < 1.0
    # best_threshold_ is the source of truth and matches what we report.
    assert thr == pytest.approx(float(model.model.best_threshold_))


def test_tuned_threshold_does_not_touch_test_set(binary_matrices) -> None:
    """The tuned threshold is identical whether or not a test set ever exists (TRAIN-only).

    Fitting twice on the same TRAIN matrices (the test set is never passed to fit) must yield
    the same operating threshold — a guard that the cut is a TRAIN-CV property, not leakage.
    """
    m1 = _policy_model("LogisticRegression", binary_matrices, threshold_mode="tuned")
    m2 = _policy_model("LogisticRegression", binary_matrices, threshold_mode="tuned")
    assert m1._decision_info.threshold == pytest.approx(m2._decision_info.threshold)


# --- class_weight routing through the threshold wrapper --------------------------------

def test_sample_weight_routes_through_threshold(binary_matrices) -> None:
    """class_weight (→ sample_weight) reaches the fit even under an outer threshold wrapper."""
    classes = list(binary_matrices.y_train.unique())
    class_weight = {str(c): (3.0 if i else 1.0) for i, c in enumerate(sorted(classes))}
    model = _policy_model(
        "LogisticRegression",
        binary_matrices,
        class_weight=class_weight,
        threshold_mode="fixed",
        threshold=0.3,
    )
    # The model fit successfully (no UnsetMetadataPassedError) and still predicts/importance.
    assert model._decision_info.threshold == 0.3
    assert model.feature_importance() is not None
    assert model.predict(binary_matrices.X_test).shape == (len(binary_matrices.X_test),)


def test_sample_weight_routes_for_svm(binary_matrices) -> None:
    """SVM (already-calibrated base) + class_weight + tuned threshold fits without error."""
    classes = sorted(binary_matrices.y_train.unique())
    class_weight = {str(c): (2.0 if i else 1.0) for i, c in enumerate(classes)}
    model = _policy_model(
        "SVM", binary_matrices, class_weight=class_weight, threshold_mode="tuned"
    )
    thr = model._decision_info.threshold
    assert thr is not None and 0.0 < thr < 1.0


# --- multiclass ignores the threshold --------------------------------------------------

def test_multiclass_calibrates_but_ignores_threshold(multiclass_matrices) -> None:
    """Multiclass calibrates, but the (binary-only) threshold is not applied → None."""
    model = _policy_model(
        "LogisticRegression", multiclass_matrices, threshold_mode="tuned"
    )
    assert model._decision_info.calibrated is True
    assert model._decision_info.threshold is None  # no single scalar cut for multiclass
    assert not isinstance(model.model, (FixedThresholdClassifier, TunedThresholdClassifierCV))


# --- unwrap helper ---------------------------------------------------------------------

def test_unwrap_base_estimator_peels_all_layers() -> None:
    """unwrap_base_estimator reaches the base through threshold → calibration → base."""
    X = np.random.RandomState(0).randn(120, 3)
    y = (X[:, 0] > 0).astype(int)  # classes {0,1} → default "f1" scorer (pos_label=1) is valid
    base = LogisticRegression(max_iter=500)
    cal = CalibratedClassifierCV(base, cv=3, ensemble=False)
    tuned = TunedThresholdClassifierCV(cal, scoring="f1", cv=3).fit(X, y)
    unwrapped = unwrap_base_estimator(tuned)
    assert isinstance(unwrapped, LogisticRegression)
    assert hasattr(unwrapped, "coef_")
    # A plain fitted estimator is returned unchanged.
    plain = LogisticRegression(max_iter=500).fit(X, y)
    assert unwrap_base_estimator(plain) is plain


def test_fit_policy_returns_info_directly(binary_matrices) -> None:
    """fit_policy returns the fitted estimator + a DecisionInfo describing what it did."""
    est = build_model("LogisticRegression", problem_type="binary")._build_estimator()
    fitted, info = fit_policy(
        est,
        binary_matrices.X_train,
        binary_matrices.y_train,
        problem_type="binary",
        calibrate=True,
        threshold_mode="fixed",
        threshold=0.4,
        scoring="f1",
    )
    assert info.calibrated is True
    assert info.threshold == 0.4
    assert isinstance(fitted, FixedThresholdClassifier)
