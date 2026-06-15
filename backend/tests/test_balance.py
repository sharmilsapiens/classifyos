"""Tests for Section 8 (``handle_class_imbalance`` — class-imbalance handling).

The realistic cases run the real sample CSVs through the full Phase 1–4 pipeline
(load → split → preprocess → features → interactions) and feed the resulting
*post-interaction* train matrix to the balancer. The tiny-minority guards are exercised
on small hand-built numeric frames so the edge counts (minority = 3, = 1) are exact.

The cardinal rule under test: the balancer only ever touches the TRAIN arrays it is
handed; the test split is never resampled or reweighted.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

import numpy as np
import pandas as pd
import pytest

from classifyos.config import build_config
from classifyos.io.loader import data_loader
from classifyos.io.storage import StorageAdapter
from classifyos.preprocessing.balance import handle_class_imbalance
from classifyos.preprocessing.features import FeatureBuilder
from classifyos.preprocessing.interactions import InteractionFeatureBuilder
from classifyos.preprocessing.preprocess import Preprocessor
from classifyos.split import train_test_split_cls

FRAUD_FEATURES = [
    "claim_amount",
    "policy_age_months",
    "report_delay_days",
    "num_prior_claims",
    "incident_type",
    "has_police_report",
    "has_witness",
    "claimant_age",
    "region",
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


# --------------------------------------------------------------------- helpers ----


def _cfg(
    input_file: str,
    target: str,
    features: list[str],
    **overrides: Any,
) -> dict[str, Any]:
    """A config that runs interactions cheaply (no auto-discovery) for the fixtures."""
    overrides.setdefault(
        "interaction_features",
        {
            "enabled": True,
            "interaction_pairs": {},
            "default_interactions": ["multiply"],
            "drop_original_if_interacted": False,
            "max_auto_pairs": 0,
            "fill_method": "zero",
        },
    )
    return build_config(input_file, target, features, **overrides)


def _engineered(
    config: dict[str, Any], storage: StorageAdapter
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    """Run load → split → preprocess → features → interactions; split off the target.

    Returns ``(X_train, y_train, X_test, y_test)`` — the post-interaction matrices the
    balancer consumes (features only) plus the aligned labels.
    """
    target = config["target"]
    df = data_loader(config, storage)
    train, test = train_test_split_cls(df, config)
    pp = Preprocessor(config)
    train_pp, test_pp = pp.fit_transform(train), pp.transform(test)
    fb = FeatureBuilder(config)
    train_f, test_f = fb.fit_transform(train_pp, target), fb.transform(test_pp)
    ib = InteractionFeatureBuilder(config)
    train_i, test_i = ib.fit_transform(train_f, target), ib.transform(test_f)
    return (
        train_i.drop(columns=[target]),
        train_i[target],
        test_i.drop(columns=[target]),
        test_i[target],
    )


def _tiny_train(
    minority_n: int, majority_n: int = 30, n_features: int = 4, seed: int = 0
) -> tuple[pd.DataFrame, pd.Series]:
    """A small all-numeric two-class frame with an exact minority count."""
    rng = np.random.default_rng(seed)
    X = pd.DataFrame(
        np.vstack(
            [
                rng.normal(0.0, 1.0, (majority_n, n_features)),
                rng.normal(4.0, 1.0, (minority_n, n_features)),
            ]
        ),
        columns=[f"f{i}" for i in range(n_features)],
    )
    y = pd.Series(["0"] * majority_n + ["1"] * minority_n, name="target")
    return X, y


@pytest.fixture(scope="module")
def fraud_engineered(
    storage: StorageAdapter, fraud_csv: str
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    """Post-interaction fraud matrices (binary, ~99:1). Built once per module."""
    cfg = _cfg(fraud_csv, "is_fraud", FRAUD_FEATURES, problem_type="binary")
    return _engineered(cfg, storage)


@pytest.fixture(scope="module")
def risk_engineered(
    storage: StorageAdapter, risk_csv: str
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    """Post-interaction risk-tier matrices (3-class multiclass). Built once per module."""
    cfg = _cfg(risk_csv, "risk_tier", RISK_FEATURES, problem_type="multiclass")
    return _engineered(cfg, storage)


# ----------------------------------------------------------------------- smote ----


def test_smote_balances_train(fraud_engineered) -> None:
    """SMOTE lifts the ~1% minority share to (near) parity on the train split."""
    X_train, y_train, _, _ = fraud_engineered
    before = y_train.value_counts(normalize=True).min()
    assert before < 0.05  # the fixture really is heavily imbalanced

    cfg = _cfg("fraud_claims.csv", "is_fraud", FRAUD_FEATURES, class_balance="smote")
    X_res, y_res, class_weight = handle_class_imbalance(X_train, y_train, cfg)

    after = y_res.value_counts(normalize=True).min()
    assert class_weight is None
    assert after > 0.45  # minority share rose substantially toward 50%
    assert len(X_res) == len(y_res)
    counts = y_res.value_counts()
    assert counts.max() == counts.min()  # SMOTE 'auto' balances to the majority count


def test_test_set_untouched(fraud_engineered) -> None:
    """The balancer never receives test data and never mutates the train arrays."""
    X_train, y_train, X_test, y_test = fraud_engineered
    X_train_snap = X_train.copy(deep=True)
    y_train_snap = y_train.copy(deep=True)
    X_test_snap = X_test.copy(deep=True)
    y_test_snap = y_test.copy(deep=True)

    cfg = _cfg("fraud_claims.csv", "is_fraud", FRAUD_FEATURES, class_balance="smote")
    handle_class_imbalance(X_train, y_train, cfg)

    # Inputs unchanged...
    pd.testing.assert_frame_equal(X_train, X_train_snap)
    pd.testing.assert_series_equal(y_train, y_train_snap)
    # ...and the test arrays the balancer never saw are obviously untouched.
    pd.testing.assert_frame_equal(X_test, X_test_snap)
    pd.testing.assert_series_equal(y_test, y_test_snap)


def test_smote_tiny_minority(caplog) -> None:
    """minority=3 → k_neighbors auto-reduced (no crash); minority=1 → random oversample."""
    # minority count = 3: SMOTE needs k_neighbors < 3, so it is auto-reduced.
    X3, y3 = _tiny_train(minority_n=3)
    cfg = build_config("dummy.csv", "target", list(X3.columns), class_balance="smote")
    with caplog.at_level(logging.WARNING):
        X_res, y_res, cw = handle_class_imbalance(X3, y3, cfg)
    assert cw is None
    counts = y_res.value_counts()
    assert counts.min() == counts.max()  # balanced, no crash
    assert any("k_neighbors" in r.message for r in caplog.records)

    # minority count = 1: SMOTE cannot interpolate → random-oversample fallback.
    caplog.clear()
    X1, y1 = _tiny_train(minority_n=1)
    with caplog.at_level(logging.WARNING):
        X_res1, y_res1, _ = handle_class_imbalance(X1, y1, cfg)
    counts1 = y_res1.value_counts()
    assert counts1.min() == counts1.max()  # balanced via duplication, no crash
    assert any("random oversampling" in r.message for r in caplog.records)


def test_multiclass_smote(risk_engineered) -> None:
    """3-class risk_tier: every class is balanced after SMOTE."""
    X_train, y_train, _, _ = risk_engineered
    assert y_train.nunique() == 3

    cfg = _cfg(
        "risk_tier.csv",
        "risk_tier",
        RISK_FEATURES,
        problem_type="multiclass",
        class_balance="smote",
    )
    X_res, y_res, cw = handle_class_imbalance(X_train, y_train, cfg)
    assert cw is None
    counts = y_res.value_counts()
    assert len(counts) == 3
    assert counts.min() == counts.max()


# ----------------------------------------------------------------- undersample ----


def test_undersample_reduces_majority(fraud_engineered, caplog) -> None:
    """Majority shrinks to the minority count; the minority count is unchanged."""
    X_train, y_train, _, _ = fraud_engineered
    counts_before = y_train.value_counts()
    minority_label = counts_before.idxmin()
    minority_before = int(counts_before.min())
    majority_before = int(counts_before.max())

    cfg = _cfg(
        "fraud_claims.csv", "is_fraud", FRAUD_FEATURES, class_balance="undersample"
    )
    with caplog.at_level(logging.INFO):
        X_res, y_res, cw = handle_class_imbalance(X_train, y_train, cfg)

    counts_after = y_res.value_counts()
    assert cw is None
    assert int(counts_after[minority_label]) == minority_before  # minority untouched
    assert int(counts_after.max()) < majority_before  # majority dropped
    assert counts_after.min() == counts_after.max()  # balanced
    assert len(X_res) == len(y_res)
    assert any("dropped" in r.message for r in caplog.records)


# ---------------------------------------------------------------- class_weight ----


def test_class_weight_no_resample(risk_engineered) -> None:
    """class_weight: rows unchanged, one weight per class; smote/undersample give None."""
    X_train, y_train, _, _ = risk_engineered
    n_classes = y_train.nunique()

    cfg = _cfg(
        "risk_tier.csv",
        "risk_tier",
        RISK_FEATURES,
        problem_type="multiclass",
        class_balance="class_weight",
    )
    X_res, y_res, class_weight = handle_class_imbalance(X_train, y_train, cfg)

    assert len(X_res) == len(X_train)  # no resampling
    assert len(y_res) == len(y_train)
    assert isinstance(class_weight, dict)
    assert len(class_weight) == n_classes
    assert set(class_weight) == set(y_train.unique())
    assert all(isinstance(w, float) for w in class_weight.values())

    # Only class_weight returns a non-None weight.
    for strategy in ("smote", "undersample"):
        cfg_s = _cfg(
            "risk_tier.csv",
            "risk_tier",
            RISK_FEATURES,
            problem_type="multiclass",
            class_balance=strategy,
        )
        assert handle_class_imbalance(X_train, y_train, cfg_s)[2] is None


# ------------------------------------------------------------------------ none ----


def test_none_passthrough(fraud_engineered) -> None:
    """class_balance='none' returns the inputs unchanged with class_weight=None."""
    X_train, y_train, _, _ = fraud_engineered
    cfg = _cfg("fraud_claims.csv", "is_fraud", FRAUD_FEATURES, class_balance="none")
    X_res, y_res, class_weight = handle_class_imbalance(X_train, y_train, cfg)

    assert class_weight is None
    pd.testing.assert_frame_equal(
        X_res.reset_index(drop=True), X_train.reset_index(drop=True)
    )
    pd.testing.assert_series_equal(
        y_res.reset_index(drop=True), y_train.reset_index(drop=True)
    )


# ------------------------------------------------------------- shapes / safety ----


def test_column_order_preserved(fraud_engineered) -> None:
    """X_res columns are exactly X_train's columns, in the same order, after SMOTE."""
    X_train, y_train, _, _ = fraud_engineered
    cfg = _cfg("fraud_claims.csv", "is_fraud", FRAUD_FEATURES, class_balance="smote")
    X_res, _, _ = handle_class_imbalance(X_train, y_train, cfg)
    assert list(X_res.columns) == list(X_train.columns)


def test_no_mutation(risk_engineered) -> None:
    """Inputs and config are deep-equal before and after every strategy."""
    X_train, y_train, _, _ = risk_engineered
    for strategy in ("smote", "undersample", "class_weight", "none"):
        cfg = _cfg(
            "risk_tier.csv",
            "risk_tier",
            RISK_FEATURES,
            problem_type="multiclass",
            class_balance=strategy,
        )
        cfg_snap = copy.deepcopy(cfg)
        X_snap = X_train.copy(deep=True)
        y_snap = y_train.copy(deep=True)

        handle_class_imbalance(X_train, y_train, cfg)

        assert cfg == cfg_snap
        pd.testing.assert_frame_equal(X_train, X_snap)
        pd.testing.assert_series_equal(y_train, y_snap)


def test_invalid_strategy_raises(fraud_engineered) -> None:
    """An unknown class_balance value raises ValueError (defence in depth)."""
    X_train, y_train, _, _ = fraud_engineered
    # build_config would reject this, so poke the assembled dict directly.
    cfg = _cfg("fraud_claims.csv", "is_fraud", FRAUD_FEATURES, class_balance="none")
    cfg["class_balance"] = "bogus"
    with pytest.raises(ValueError, match="class_balance"):
        handle_class_imbalance(X_train, y_train, cfg)
