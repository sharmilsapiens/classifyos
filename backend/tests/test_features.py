"""Tests for Section 7 (``FeatureBuilder`` — polynomial, ratio, binning features).

All cases run on the real sample CSVs from ``DATA_DIR`` through the Phase 1–3
pipeline (load → split → preprocess → features), mirroring the corrected canonical
pipeline order.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from classifyos.config import build_config
from classifyos.io.loader import data_loader
from classifyos.io.storage import StorageAdapter
from classifyos.preprocessing.features import FeatureBuilder
from classifyos.preprocessing.preprocess import Preprocessor
from classifyos.split import train_test_split_cls

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


def _preprocessed(
    config: dict[str, Any], storage: StorageAdapter
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run load → split → preprocess and return ``(train_pp, test_pp)``."""
    df = data_loader(config, storage)
    train, test = train_test_split_cls(df, config)
    pp = Preprocessor(config)
    return pp.fit_transform(train), pp.transform(test)


def _lapse_cfg(lapse_csv: str, **overrides: Any) -> dict[str, Any]:
    return build_config(lapse_csv, "will_lapse", LAPSE_FEATURES, **overrides)


# ------------------------------------------------------------------ binning ----


def test_binning_fires_on_skewed_fraud(
    storage: StorageAdapter, fraud_csv: str
) -> None:
    """claim_amount is lognormal → |skew| > 1.5 → it gets a 5-bin companion.

    Outlier capping is disabled so the heavy right tail (and thus the skew) survives
    into the frame the FeatureBuilder sees.
    """
    cfg = build_config(
        fraud_csv, "is_fraud", FRAUD_FEATURES, outlier_method="none"
    )
    train_pp, _ = _preprocessed(cfg, storage)
    assert abs(train_pp["claim_amount"].skew()) > 1.5

    fb = FeatureBuilder(cfg)
    out = fb.fit_transform(train_pp, "is_fraud")
    assert "claim_amount_bin" in fb.created_features_
    assert "claim_amount_bin" in out.columns
    codes = out["claim_amount_bin"]
    assert pd.api.types.is_integer_dtype(codes)
    n_bins = len(fb.bin_edges_["claim_amount"]) - 1
    assert codes.min() >= 0 and codes.max() <= n_bins - 1
    # The original column is kept alongside the companion.
    assert "claim_amount" in out.columns


def test_binning_no_leakage(storage: StorageAdapter, fraud_csv: str) -> None:
    """Train bin edges survive a poisoned test set; extremes clip to outer bins."""
    cfg = build_config(
        fraud_csv, "is_fraud", FRAUD_FEATURES, outlier_method="none"
    )
    train_pp, test_pp = _preprocessed(cfg, storage)
    fb = FeatureBuilder(cfg).fit(train_pp, "is_fraud")
    assert "claim_amount" in fb.bin_edges_

    edges_before = {k: v.copy() for k, v in fb.bin_edges_.items()}
    n_bins = len(fb.bin_edges_["claim_amount"]) - 1

    poisoned = test_pp.copy()
    poisoned.loc[poisoned.index[0], "claim_amount"] = 1e12  # far above train range
    poisoned.loc[poisoned.index[1], "claim_amount"] = -1e12  # far below train range
    out = fb.transform(poisoned)

    # Edges are unchanged by transforming (poisoned) data — no re-fitting.
    assert all(
        np.array_equal(edges_before[k], fb.bin_edges_[k]) for k in edges_before
    )
    assert out["claim_amount_bin"].iloc[0] == n_bins - 1  # extreme high → top bin
    assert out["claim_amount_bin"].iloc[1] == 0  # extreme low → bottom bin


# --------------------------------------------------------------- polynomial ----


def test_polynomial_off_by_default(storage: StorageAdapter, lapse_csv: str) -> None:
    """With the default config (polynomial=False) no squared columns are created."""
    cfg = _lapse_cfg(lapse_csv)
    train_pp, _ = _preprocessed(cfg, storage)
    fb = FeatureBuilder(cfg).fit(train_pp, "will_lapse")
    assert not any(name.endswith("_sq") for name in fb.created_features_)


def test_polynomial_capped(storage: StorageAdapter, lapse_csv: str) -> None:
    """polynomial=True caps squared terms at max_poly_features (ranked on train)."""
    cfg = _lapse_cfg(
        lapse_csv,
        feature_engineering={
            "enabled": True,
            "polynomial": True,
            "ratios": False,
            "binning": False,
            "max_poly_features": 3,
        },
    )
    train_pp, test_pp = _preprocessed(cfg, storage)
    fb = FeatureBuilder(cfg)
    out = fb.fit_transform(train_pp, "will_lapse")
    sq_cols = [c for c in fb.created_features_ if c.endswith("_sq")]
    assert len(sq_cols) == 3
    # Each squared column equals the square of its source on the (test) transform.
    test_out = fb.transform(test_pp)
    base = sq_cols[0][: -len("_sq")]
    assert np.allclose(test_out[sq_cols[0]], test_pp[base].astype(float) ** 2)


# -------------------------------------------------------------------- ratios ----


def test_ratio_guard(storage: StorageAdapter, lapse_csv: str) -> None:
    """A zero-denominator row yields the fill value (0.0) — never inf/NaN."""
    cfg = _lapse_cfg(
        lapse_csv,
        feature_engineering={
            "enabled": True,
            "polynomial": False,
            "ratios": True,
            "binning": False,
            "max_poly_features": 8,
        },
    )
    train_pp, test_pp = _preprocessed(cfg, storage)
    fb = FeatureBuilder(cfg).fit(train_pp, "will_lapse")
    denom = fb.ratio_denominator_
    assert denom is not None
    ratio_col = f"{fb.ratio_numerators_[0]}_div_{denom}"

    poisoned = test_pp.copy()
    poisoned.loc[poisoned.index[0], denom] = 0.0  # force the guard
    out = fb.transform(poisoned)
    assert np.isfinite(out[ratio_col]).all()
    assert out[ratio_col].iloc[0] == 0.0


# ------------------------------------------------------- toggles & contracts ----


def test_enabled_false_passthrough(storage: StorageAdapter, lapse_csv: str) -> None:
    """enabled=False → transform returns the frame unchanged."""
    cfg = _lapse_cfg(
        lapse_csv,
        feature_engineering={
            "enabled": False,
            "polynomial": True,
            "ratios": True,
            "binning": True,
            "max_poly_features": 8,
        },
    )
    train_pp, test_pp = _preprocessed(cfg, storage)
    fb = FeatureBuilder(cfg)
    out = fb.fit_transform(train_pp, "will_lapse")
    assert fb.created_features_ == []
    pd.testing.assert_frame_equal(out, train_pp)
    pd.testing.assert_frame_equal(fb.transform(test_pp), test_pp)


def test_config_not_mutated(storage: StorageAdapter, lapse_csv: str) -> None:
    """The config dict is identical before and after fit + transform."""
    import copy

    cfg = _lapse_cfg(
        lapse_csv,
        feature_engineering={
            "enabled": True,
            "polynomial": True,
            "ratios": True,
            "binning": True,
            "max_poly_features": 5,
        },
    )
    snapshot = copy.deepcopy(cfg)
    train_pp, test_pp = _preprocessed(cfg, storage)
    fb = FeatureBuilder(cfg)
    fb.fit_transform(train_pp, "will_lapse")
    fb.transform(test_pp)
    assert cfg == snapshot


def test_input_frame_not_mutated(storage: StorageAdapter, lapse_csv: str) -> None:
    """Neither fit nor transform mutates the caller's DataFrames."""
    cfg = _lapse_cfg(lapse_csv)
    train_pp, test_pp = _preprocessed(cfg, storage)
    train_snap, test_snap = train_pp.copy(deep=True), test_pp.copy(deep=True)
    fb = FeatureBuilder(cfg)
    fb.fit_transform(train_pp, "will_lapse")
    fb.transform(test_pp)
    pd.testing.assert_frame_equal(train_pp, train_snap)
    pd.testing.assert_frame_equal(test_pp, test_snap)
