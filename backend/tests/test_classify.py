"""Tests for Section 13 (``classify`` — per-sample predictions table)."""

from __future__ import annotations

import numpy as np

from classifyos.models.registry import build_model
from classifyos.predict import classify


def _fit(d, problem_type, name="RandomForest"):
    model = build_model(name, problem_type=problem_type, n_estimators=60)
    return model.fit(d.X_train, d.y_train)


def test_classify_output_binary(binary_matrices) -> None:
    """Predictions df has the locked columns; rows == test rows; probs sum to ~1."""
    d = binary_matrices
    model = _fit(d, "binary")
    classes = np.asarray(model.classes_)

    df = classify(model, d.X_test, d.y_test, classes)

    assert len(df) == len(d.X_test)
    assert list(df.index) == list(d.X_test.index)  # index aligned to X_test

    prob_cols = [f"probability_{c}" for c in classes]
    expected = ["actual", "predicted", *prob_cols, "confidence", "correct_flag"]
    assert list(df.columns) == expected

    # Probabilities per row sum to ~1; confidence is the row-max probability.
    prob_sum = df[prob_cols].sum(axis=1)
    np.testing.assert_allclose(prob_sum.to_numpy(), 1.0, atol=1e-6)
    np.testing.assert_allclose(
        df["confidence"].to_numpy(), df[prob_cols].max(axis=1).to_numpy(), atol=1e-9
    )

    # correct_flag is the actual-vs-predicted match.
    expected_flag = df["actual"].astype(str) == df["predicted"].astype(str)
    assert df["correct_flag"].equals(expected_flag)
    assert df["correct_flag"].dtype == bool


def test_classify_output_multiclass(multiclass_matrices) -> None:
    """3-class: one probability column per class; probs sum to ~1."""
    d = multiclass_matrices
    model = _fit(d, "multiclass")
    classes = np.asarray(model.classes_)

    df = classify(model, d.X_test, d.y_test, classes)

    prob_cols = [f"probability_{c}" for c in classes]
    assert len(prob_cols) == 3
    assert all(col in df.columns for col in prob_cols)
    np.testing.assert_allclose(df[prob_cols].sum(axis=1).to_numpy(), 1.0, atol=1e-6)
    assert set(df["predicted"].unique()).issubset(set(map(str, classes)) | set(classes))


def test_classify_confidence_bounds(binary_matrices) -> None:
    """Confidence is a probability in (0, 1] and ≥ 1/n_classes."""
    d = binary_matrices
    model = _fit(d, "binary")
    classes = np.asarray(model.classes_)
    df = classify(model, d.X_test, d.y_test, classes)
    assert (df["confidence"] > 0).all()
    assert (df["confidence"] <= 1.0 + 1e-9).all()
    assert (df["confidence"] >= 1.0 / len(classes) - 1e-9).all()
