"""Tests for Section 15 (``ModelRunner`` — the pipeline orchestrator).

These run the *whole* engine end to end on the real sample CSVs, writing artifacts to the
session temp ``OUTPUT_DIR`` (the ``storage`` fixture). They assert the canonical order
produces populated state, that every output file lands, that the ``_run_config`` isolation
guarantee holds, and that one failing algorithm never aborts a run.
"""

from __future__ import annotations

import copy
import json

import pandas as pd

from classifyos.config import build_config
from classifyos.runner import (
    CLASS_REPORT_CSV_KEY,
    FEATURE_IMPORTANCE_CSV_KEY,
    METRICS_CSV_KEY,
    PERMUTATION_IMPORTANCE_CSV_KEY,
    RESULTS_CSV_KEY,
    RUN_PROFILE_KEY,
    ModelRunner,
)

# Small, fast feature/algorithm sets — enough to exercise every stage without the
# slow models (SVM calibration). RandomForest gives a real feature-importance plot.
LAPSE_FEATURES = [
    "age",
    "occupation",
    "region",
    "policy_type",
    "channel",
    "payment_frequency",
    "policy_tenure_years",
    "annual_premium",
    "sum_assured",
    "num_late_payments",
    "claims_count",
    "has_agent",
]

RISK_FEATURES = [
    "age",
    "bmi",
    "is_smoker",
    "annual_income",
    "credit_score",
    "prior_violations",
    "occupation_class",
    "vehicle_age",
    "region",
]


def _lapse_config(**overrides):
    base = dict(
        problem_type="binary",
        algorithms=["LogisticRegression", "RandomForest"],
        class_balance="class_weight",
    )
    base.update(overrides)
    return build_config("policy_lapse.csv", "will_lapse", LAPSE_FEATURES, **base)


def test_runner_end_to_end_binary(storage) -> None:
    """ModelRunner on policy_lapse completes with populated state and all outputs."""
    cfg = _lapse_config()
    runner = ModelRunner(cfg, storage).run()

    # state populated
    assert runner.raw_df_ is not None and len(runner.raw_df_) == 3000
    assert runner.train_df_ is not None and runner.test_df_ is not None
    assert runner.feature_impact_ is not None and not runner.feature_impact_.empty
    assert not runner.predictions_df_.empty
    assert runner.metrics_df_ is not None and len(runner.metrics_df_) == 2
    assert set(runner.models_) == {"LogisticRegression", "RandomForest"}

    # every model succeeded; metrics are real numbers
    assert (runner.metrics_df_["status"] == "ok").all()
    assert runner.metrics_df_["f1_weighted"].notna().all()

    # predictions: one block per model, tagged, sized to the test set
    assert set(runner.predictions_df_["model"].unique()) == {
        "LogisticRegression",
        "RandomForest",
    }
    n_test = len(runner.test_df_)
    per_model = runner.predictions_df_.groupby("model").size()
    assert (per_model == n_test).all()

    # [TEMP — interaction AND feature-engineering features unwired] Both Section 7B
    # interactions and Section 7 derived features (ratio/bin/poly) are force-disabled in
    # the runner, so none of their markers should appear in active_features_. "_div_" is
    # shared by both (Section 7 ratios `{num}_div_{denom}` and interaction ratios), and
    # with Section 7 off it no longer appears either. Restore the original assertion (any
    # "_x_"/"_div_" present) when re-enabling.
    assert not any(
        "_x_" in c or "_minus_" in c or "_div_" in c for c in runner.active_features_
    )


def test_native_feature_importance_captured(storage, output_dir) -> None:
    """Post-training native importance is captured per model and written to CSV.

    A tree model (RandomForest) exposes a {feature: importance} dict over the active
    feature columns; a model with no native importance (NaiveBayes, RBF-SVM) maps to None.
    The CSV holds ranked rows only for the models that expose importances.
    """
    cfg = _lapse_config(algorithms=["RandomForest", "NaiveBayes"])
    runner = ModelRunner(cfg, storage).run()

    # RandomForest exposes importances keyed by the engineered/active feature columns.
    rf_imp = runner.feature_importances_["RandomForest"]
    assert isinstance(rf_imp, dict) and rf_imp
    assert set(rf_imp) <= set(runner.active_features_)
    assert all(isinstance(v, float) for v in rf_imp.values())

    # GaussianNB exposes none → None (omitted from the CSV / API block).
    assert runner.feature_importances_["NaiveBayes"] is None

    # CSV: ranked long-form rows for RandomForest only; NaiveBayes contributes nothing.
    imp_df = pd.read_csv(output_dir / FEATURE_IMPORTANCE_CSV_KEY)
    assert list(imp_df.columns) == ["model", "feature", "importance", "rank"]
    assert set(imp_df["model"].unique()) == {"RandomForest"}
    rf_rows = imp_df[imp_df["model"] == "RandomForest"].sort_values("rank")
    assert rf_rows["rank"].tolist() == list(range(1, len(rf_rows) + 1))
    # ranked descending by importance
    assert rf_rows["importance"].is_monotonic_decreasing


def test_permutation_importance_captured_for_all_models(storage, output_dir) -> None:
    """Permutation importance is model-AGNOSTIC: it is produced even for NaiveBayes/SVM.

    The whole point of the permutation measure is to cover the models that expose no native
    importance. NaiveBayes returns ``None`` from ``feature_importance()`` but DOES get a
    permutation importance dict; both are keyed by the active feature columns.
    """
    cfg = _lapse_config(algorithms=["RandomForest", "NaiveBayes"])
    runner = ModelRunner(cfg, storage).run()

    # NaiveBayes has no NATIVE importance ...
    assert runner.feature_importances_["NaiveBayes"] is None
    # ... but it DOES get a permutation importance (model-agnostic).
    for name in ("RandomForest", "NaiveBayes"):
        perm = runner.permutation_importances_[name]
        assert isinstance(perm, dict) and perm
        assert set(perm) <= set(runner.active_features_)
        assert all(isinstance(v, float) for v in perm.values())

    # CSV: ranked long-form rows for BOTH models (unlike the native CSV, which omits NB).
    perm_df = pd.read_csv(output_dir / PERMUTATION_IMPORTANCE_CSV_KEY)
    assert list(perm_df.columns) == ["model", "feature", "importance", "rank"]
    assert set(perm_df["model"].unique()) == {"RandomForest", "NaiveBayes"}
    for name in ("RandomForest", "NaiveBayes"):
        rows = perm_df[perm_df["model"] == name].sort_values("rank")
        assert rows["rank"].tolist() == list(range(1, len(rows) + 1))
        assert rows["importance"].is_monotonic_decreasing


def test_permutation_importance_honours_configured_metric(storage) -> None:
    """A probability-based permutation metric (roc_auc) drives the proba path end-to-end.

    Exercises predict_proba scoring (not just label-based F1) and confirms the configured
    metric flows config -> runner -> permutation_importance and yields a real dict.
    """
    cfg = _lapse_config(algorithms=["RandomForest"], permutation_metric="roc_auc")
    runner = ModelRunner(cfg, storage).run()

    perm = runner.permutation_importances_["RandomForest"]
    assert isinstance(perm, dict) and perm
    assert set(perm) <= set(runner.active_features_)
    assert all(isinstance(v, float) for v in perm.values())


def test_runner_multiclass(storage) -> None:
    """risk_tier 3-class end-to-end: metrics computed per model; 3 classes learned."""
    cfg = build_config(
        "risk_tier.csv",
        "risk_tier",
        RISK_FEATURES,
        problem_type="multiclass",
        algorithms=["LogisticRegression", "RandomForest"],
    )
    runner = ModelRunner(cfg, storage).run()

    assert len(runner.classes_) == 3
    assert (runner.metrics_df_["status"] == "ok").all()
    assert runner.metrics_df_["accuracy"].notna().all()
    # multiclass confusion matrices are 3x3
    for name in runner.models_:
        cm = runner.metrics_[name]["confusion_matrix"]
        assert len(cm) == 3 and all(len(r) == 3 for r in cm)


def test_config_not_mutated(storage) -> None:
    """The _run_config isolation guarantee: run() never mutates the caller's config."""
    cfg = _lapse_config()
    before = copy.deepcopy(cfg)
    runner = ModelRunner(cfg, storage)
    runner.run()
    assert cfg == before  # unchanged after a full run
    # ...and runner.config is the same object the caller passed (not mutated either)
    assert runner.config is cfg
    assert runner.config == before


def test_runner_handles_bad_algo(storage) -> None:
    """A failing algorithm is recorded as 'failed'; the others still complete."""
    cfg = _lapse_config(
        algorithms=["LogisticRegression", "DefinitelyNotAModel", "RandomForest"]
    )
    runner = ModelRunner(cfg, storage).run()

    statuses = dict(zip(runner.metrics_df_["model"], runner.metrics_df_["status"]))
    assert statuses["LogisticRegression"] == "ok"
    assert statuses["RandomForest"] == "ok"
    assert statuses["DefinitelyNotAModel"] == "failed"

    # the failed row carries an error message and no metrics
    bad = runner.metrics_df_[runner.metrics_df_["model"] == "DefinitelyNotAModel"].iloc[0]
    assert isinstance(bad["error"], str) and "DefinitelyNotAModel" in bad["error"]
    assert pd.isna(bad["accuracy"])

    # the good models are still fitted and produced predictions
    assert set(runner.models_) == {"LogisticRegression", "RandomForest"}
    assert "DefinitelyNotAModel" not in runner.predictions_df_["model"].unique()


def test_all_output_files(storage, output_dir) -> None:
    """Every expected artifact exists in OUTPUT_DIR after a binary run."""
    from classifyos.analysis.feature_impact import (
        PLOT_PNG_KEY as PLOT4_KEY,
        SUMMARY_CSV_KEY,
    )
    from classifyos.evaluation.plots import PLOT1_KEY, PLOT2_KEY, PLOT3_KEY, PLOT5_KEY
    from classifyos.preprocessing.interactions import PLOT_PNG_KEY as PLOT6_KEY

    # OUTPUT_DIR is session-scoped and shared, so another test (test_interactions'
    # test_plot6_written) may have left a plot6 here. Clear it first so the
    # "plot6 must NOT be produced" assertion below tests THIS runner's behaviour,
    # not stale cross-test state. [TEMP — remove with the interaction unwiring.]
    (output_dir / PLOT6_KEY).unlink(missing_ok=True)

    cfg = _lapse_config()
    ModelRunner(cfg, storage).run()

    expected = [
        RESULTS_CSV_KEY,
        METRICS_CSV_KEY,
        CLASS_REPORT_CSV_KEY,
        FEATURE_IMPORTANCE_CSV_KEY,
        RUN_PROFILE_KEY,
        SUMMARY_CSV_KEY,
        PLOT1_KEY,
        PLOT2_KEY,
        PLOT3_KEY,
        PLOT4_KEY,
        PLOT5_KEY,
        # PLOT6_KEY,  # [TEMP — interaction features unwired] plot6 not written; restore on re-enable
    ]
    for key in expected:
        assert storage.exists(key), f"missing output: {key}"

    # [TEMP — interaction features unwired] plot6 must NOT be produced while disabled.
    assert not storage.exists(PLOT6_KEY)

    # run_profile.json is valid JSON with the documented keys (read from OUTPUT_DIR)
    with open(output_dir / RUN_PROFILE_KEY, encoding="utf-8") as fh:
        profile = json.load(fh)
    for key in (
        "input_file",
        "target",
        "features",
        "active_features",
        "problem_type",
        "class_distribution",
        "algorithms",
        "timestamp",
    ):
        assert key in profile, f"run_profile missing key: {key}"
    assert profile["target"] == "will_lapse"
    assert profile["class_distribution"] == {"0": 1995, "1": 1005}


def test_class_report_csv_per_model(storage, output_dir) -> None:
    """class_report.csv has per-class rows for every successful model."""
    cfg = _lapse_config()
    ModelRunner(cfg, storage).run()
    report = pd.read_csv(output_dir / CLASS_REPORT_CSV_KEY)
    assert set(report["model"].unique()) == {"LogisticRegression", "RandomForest"}
    assert {"model", "class", "precision", "recall", "f1_score", "support"}.issubset(
        report.columns
    )
