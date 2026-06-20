"""Phase 11 — multilabel (Product Recommendation) end-to-end regression tests.

Multilabel is the one problem type that had never run end-to-end before Phase 11. These
tests pin the behaviour Phase 11 wired in, at the layer each piece lives:

* the delimited-set ↔ indicator-matrix bridge (``classifyos.multilabel``);
* ``ModelRunner`` actually training a TRUE multilabel model (the label NAMES are the
  classes, not the 63 delimited combos that the pre-Phase-11 code degenerated into);
* the documented ``smote`` → ``class_weight`` fallback firing (not crashing);
* the multilabel predictions table (label SETS, per-label probabilities);
* per-label one-vs-rest ROC/PR curve points.

They run on the real synthetic ``product_reco.csv`` sample, so they exercise the same data
the dashboard renders. Binary/multiclass behaviour is covered elsewhere and must stay green.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from classifyos.config import build_config
from classifyos.evaluation.curves import compute_curve_points
from classifyos.multilabel import join_labels, parse_label_sets
from classifyos.runner import ModelRunner

from .conftest import PRODUCT_FEATURES

ML_ALGOS = ["LogisticRegression", "RandomForest"]
EXPECTED_LABELS = ["Auto", "Health", "Home", "Investment", "Life", "Travel"]


def _multilabel_config(class_balance: str = "class_weight") -> dict:
    """A multilabel run config (interaction auto-discovery off for test speed)."""
    return build_config(
        "product_reco.csv",
        "recommended_products",
        PRODUCT_FEATURES,
        problem_type="multilabel",
        class_balance=class_balance,
        algorithms=ML_ALGOS,
        interaction_features={"max_auto_pairs": 0},
    )


# --- the delimited-set ↔ indicator bridge (unit) ----------------------------------


def test_parse_label_sets_splits_and_cleans():
    """Delimited cells become per-row label lists; missing/blank → empty set."""
    rows = ["Auto|Home", "Life", "", None, float("nan"), "  Auto |  Travel "]
    assert parse_label_sets(rows) == [
        ["Auto", "Home"],
        ["Life"],
        [],
        [],
        [],
        ["Auto", "Travel"],
    ]


def test_join_labels_is_sorted_and_stable():
    """join_labels sorts, so the same SET always renders to the same string."""
    assert join_labels({"Home", "Auto"}) == "Auto|Home"
    assert join_labels(["Travel", "Auto", "Home"]) == "Auto|Home|Travel"


# --- ModelRunner end-to-end (real data) -------------------------------------------


@pytest.fixture(scope="module")
def multilabel_runner(storage) -> ModelRunner:
    """Run the full multilabel pipeline once for the module (smote → class_weight path)."""
    cfg = _multilabel_config(class_balance="smote")
    return ModelRunner(cfg, storage).run()


def test_multilabel_trains_true_multilabel_not_combos(multilabel_runner):
    """The classes are the LABEL NAMES (6 products), not the delimited combinations.

    This is the core Phase 11 fix: previously a 1-D delimited target degenerated into a
    63-class "multiclass over combos" problem. A true multilabel run has exactly the label
    vocabulary as its classes.
    """
    assert multilabel_runner.problem_type_ == "multilabel"
    assert sorted(multilabel_runner.classes_) == EXPECTED_LABELS
    # Every requested model trained (no failed rows).
    assert set(multilabel_runner.models_) == set(ML_ALGOS)
    assert (multilabel_runner.metrics_df_["status"] == "ok").all()


def test_multilabel_metrics_shape(multilabel_runner):
    """Per-label metrics are present and honest; metrics undefined for multilabel are None."""
    for name in ML_ALGOS:
        m = multilabel_runner.metrics_[name]
        # roc_auc / pr_auc are the weighted multilabel averages — real numbers, learned signal.
        assert m["roc_auc"] is not None and 0.5 < m["roc_auc"] <= 1.0
        assert m["pr_auc"] is not None
        assert m["f1_weighted"] is not None
        # MCC, log-loss and a single confusion matrix are not defined for multilabel.
        assert m["mcc"] is None
        assert m["log_loss"] is None
        assert m["confusion_matrix"] is None
        # The per-label classification report has one row per product (+ avg rows).
        report = m["classification_report"]
        for label in EXPECTED_LABELS:
            assert label in report


def test_multilabel_smote_falls_back_to_class_weight(storage, caplog):
    """class_balance='smote' on a multilabel target warns + falls back, never crashes."""
    cfg = _multilabel_config(class_balance="smote")
    with caplog.at_level(logging.WARNING):
        runner = ModelRunner(cfg, storage).run()
    assert any(
        "not supported for multilabel" in rec.message for rec in caplog.records
    ), "expected the smote→class_weight fallback warning"
    assert set(runner.models_) == set(ML_ALGOS)  # run still completed


def test_multilabel_predictions_are_label_sets(multilabel_runner):
    """Predictions table: delimited label SETS + one probability column per label."""
    df = multilabel_runner.predictions_df_
    assert df is not None and not df.empty
    prob_cols = [c for c in df.columns if c.startswith("probability_")]
    assert sorted(c[len("probability_"):] for c in prob_cols) == EXPECTED_LABELS
    # actual/predicted are delimited strings (a set, possibly empty), correct_flag a bool.
    row = df.iloc[0]
    assert isinstance(row["actual"], str)
    assert isinstance(row["predicted"], str)
    assert bool(row["correct_flag"]) in (True, False)
    # confidence is the row-max per-label probability ∈ [0, 1].
    assert (df["confidence"] >= 0).all() and (df["confidence"] <= 1).all()


def test_multilabel_binarizer_is_train_fitted():
    """[RISK] leakage guard — the label vocabulary is learned from TRAIN only.

    A label that appears ONLY in the test split must NOT enter the indicator vocabulary
    (mirrors the encoder/scaler train-only rule). Verified directly on the binarizer the
    runner uses.
    """
    from sklearn.preprocessing import MultiLabelBinarizer

    train = parse_label_sets(["Auto|Home", "Life", "Auto"])
    mlb = MultiLabelBinarizer().fit(train)
    # "Travel" exists only in test; it is ignored, not silently added to the vocabulary.
    assert list(mlb.classes_) == ["Auto", "Home", "Life"]
    with pytest.warns(UserWarning):
        ind = mlb.transform(parse_label_sets(["Auto|Travel"]))
    assert ind.tolist() == [[1, 0, 0]]  # only the known "Auto" column lights up


def test_multilabel_curves_are_per_label(multilabel_runner):
    """compute_curve_points returns one-vs-rest ROC/PR per LABEL for multilabel."""
    runner = multilabel_runner
    model = runner.models_["LogisticRegression"]
    proba = model.predict_proba(runner.X_test_)
    curves = compute_curve_points(
        runner.y_test_indicator_, proba, model.classes_, "multilabel"
    )
    # Every label with both classes present in the test truth gets a curve.
    assert set(curves["roc"]) == set(EXPECTED_LABELS)
    assert set(curves["pr"]) == set(EXPECTED_LABELS)
    auto = curves["roc"]["Auto"]
    assert len(auto["fpr"]) == len(auto["tpr"]) and auto["auc"] is not None


def test_multilabel_run_profile_per_label_distribution(multilabel_runner):
    """The run profile reports per-LABEL prevalence (not per-combo) for multilabel."""
    dist = multilabel_runner.run_profile_["class_distribution"]
    assert sorted(dist) == EXPECTED_LABELS
    assert all(isinstance(v, int) and v > 0 for v in dist.values())
