"""Tests for Section 7B (``InteractionFeatureBuilder`` + ``plot_interaction_summary``).

All cases run on the real sample CSVs from ``DATA_DIR`` through the Phase 1–3 pipeline
(load → split → preprocess), then apply the interaction layer. A couple of cases run
the full load → split → preprocess → features → interactions chain.
"""

from __future__ import annotations

import copy
import os
from typing import Any

import numpy as np
import pandas as pd
import pytest

from classifyos.config import build_config
from classifyos.io.loader import data_loader
from classifyos.io.storage import StorageAdapter
from classifyos.preprocessing.features import FeatureBuilder
from classifyos.preprocessing.interactions import (
    PLOT_PNG_KEY,
    InteractionFeatureBuilder,
    plot_interaction_summary,
)
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

# Explicit pairs that exercise one of each operation on original numeric columns
# (these survive preprocessing under their original names).
EXPLICIT_PAIRS = {
    "age+annual_premium": "multiply",
    "annual_premium+sum_assured": "ratio",
    "age+policy_tenure_years": "diff",
}


def _interaction_cfg(lapse_csv: str, **interaction_overrides: Any) -> dict[str, Any]:
    base = {
        "enabled": True,
        "interaction_pairs": {},
        "default_interactions": ["multiply"],
        "drop_original_if_interacted": False,
        "max_auto_pairs": 0,
        "fill_method": "zero",
    }
    base.update(interaction_overrides)
    return build_config(
        lapse_csv, "will_lapse", LAPSE_FEATURES, interaction_features=base
    )


def _preprocessed(
    config: dict[str, Any], storage: StorageAdapter
) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = data_loader(config, storage)
    train, test = train_test_split_cls(df, config)
    pp = Preprocessor(config)
    return pp.fit_transform(train), pp.transform(test)


# ------------------------------------------------------------------- naming ----


def test_naming_conventions(storage: StorageAdapter, lapse_csv: str) -> None:
    """multiply → a_x_b, ratio → a_div_b, diff → a_minus_b (exact contract names)."""
    cfg = _interaction_cfg(lapse_csv, interaction_pairs=EXPLICIT_PAIRS)
    train_pp, _ = _preprocessed(cfg, storage)
    ib = InteractionFeatureBuilder(cfg)
    out = ib.fit_transform(train_pp, "will_lapse")

    assert "age_x_annual_premium" in out.columns
    assert "annual_premium_div_sum_assured" in out.columns
    assert "age_minus_policy_tenure_years" in out.columns
    # No auto pairs were requested, so only the three explicit columns exist.
    assert ib.interaction_cols_ == [
        "age_x_annual_premium",
        "annual_premium_div_sum_assured",
        "age_minus_policy_tenure_years",
    ]
    # Values match the raw operations.
    assert np.allclose(
        out["age_x_annual_premium"],
        train_pp["age"].astype(float) * train_pp["annual_premium"].astype(float),
    )
    assert np.allclose(
        out["age_minus_policy_tenure_years"],
        train_pp["age"].astype(float) - train_pp["policy_tenure_years"].astype(float),
    )


def test_all_op_expands(storage: StorageAdapter, lapse_csv: str) -> None:
    """A pair mapped to "all" yields all three named columns."""
    cfg = _interaction_cfg(lapse_csv, interaction_pairs={"age+annual_premium": "all"})
    train_pp, _ = _preprocessed(cfg, storage)
    ib = InteractionFeatureBuilder(cfg).fit(train_pp, "will_lapse")
    assert ib.pairs_used_["age+annual_premium"] == ["multiply", "ratio", "diff"]
    assert set(ib.interaction_cols_) == {
        "age_x_annual_premium",
        "age_div_annual_premium",
        "age_minus_annual_premium",
    }


# ------------------------------------------------------------------ leakage ----


def test_auto_discovery_no_leakage(storage: StorageAdapter, lapse_csv: str) -> None:
    """pairs_used_ is fixed at fit; transforming poisoned test never re-discovers."""
    cfg = _interaction_cfg(lapse_csv, max_auto_pairs=5)
    train_pp, test_pp = _preprocessed(cfg, storage)
    ib = InteractionFeatureBuilder(cfg).fit(train_pp, "will_lapse")
    pairs_before = copy.deepcopy(ib.pairs_used_)
    cols_before = list(ib.interaction_cols_)
    assert pairs_before  # discovery actually found something

    poisoned = test_pp.copy()
    for col in ib.sources_used_:
        poisoned[col] = poisoned[col].astype(float) * 1000.0
    # Also scramble the test target — must not influence the (already fixed) plan.
    poisoned["will_lapse"] = poisoned["will_lapse"].sample(frac=1.0, random_state=1).to_numpy()
    ib.transform(poisoned)

    assert ib.pairs_used_ == pairs_before
    assert ib.interaction_cols_ == cols_before


def test_max_auto_pairs_respected(storage: StorageAdapter, lapse_csv: str) -> None:
    """At most max_auto_pairs pairs are discovered."""
    cfg = _interaction_cfg(lapse_csv, max_auto_pairs=3)
    train_pp, _ = _preprocessed(cfg, storage)
    ib = InteractionFeatureBuilder(cfg).fit(train_pp, "will_lapse")
    assert len(ib.pairs_used_) <= 3


# -------------------------------------------------------------- ratio guard ----


def test_ratio_guard_zero_fill(storage: StorageAdapter, lapse_csv: str) -> None:
    """A zero denominator yields 0.0 under fill_method='zero' — no inf."""
    cfg = _interaction_cfg(
        lapse_csv,
        interaction_pairs={"annual_premium+sum_assured": "ratio"},
        fill_method="zero",
    )
    train_pp, test_pp = _preprocessed(cfg, storage)
    ib = InteractionFeatureBuilder(cfg).fit(train_pp, "will_lapse")

    poisoned = test_pp.copy()
    poisoned.loc[poisoned.index[0], "sum_assured"] = 0.0
    out = ib.transform(poisoned)
    col = "annual_premium_div_sum_assured"
    assert np.isfinite(out[col]).all()
    assert out[col].iloc[0] == 0.0


def test_ratio_guard_median_fill(storage: StorageAdapter, lapse_csv: str) -> None:
    """A zero denominator yields the stored TRAIN median under fill_method='median'."""
    cfg = _interaction_cfg(
        lapse_csv,
        interaction_pairs={"annual_premium+sum_assured": "ratio"},
        fill_method="median",
    )
    train_pp, test_pp = _preprocessed(cfg, storage)
    ib = InteractionFeatureBuilder(cfg).fit(train_pp, "will_lapse")
    col = "annual_premium_div_sum_assured"
    assert col in ib.ratio_medians_

    poisoned = test_pp.copy()
    poisoned.loc[poisoned.index[0], "sum_assured"] = 0.0
    out = ib.transform(poisoned)
    assert np.isfinite(out[col]).all()
    assert out[col].iloc[0] == pytest.approx(ib.ratio_medians_[col])


# ----------------------------------------------------------- drop originals ----


def test_drop_original_if_interacted(storage: StorageAdapter, lapse_csv: str) -> None:
    """Sources used in interactions are dropped; interaction cols & target remain."""
    cfg = _interaction_cfg(
        lapse_csv,
        interaction_pairs={"age+annual_premium": "multiply"},
        drop_original_if_interacted=True,
    )
    train_pp, _ = _preprocessed(cfg, storage)
    ib = InteractionFeatureBuilder(cfg)
    out = ib.fit_transform(train_pp, "will_lapse")

    assert "age" not in out.columns
    assert "annual_premium" not in out.columns
    assert "age_x_annual_premium" in out.columns
    assert "will_lapse" in out.columns  # target is never dropped
    # A numeric column not used in any interaction is retained.
    assert "sum_assured" in out.columns


# ------------------------------------------------------------ toggles/config ----


def test_enabled_false_passthrough(storage: StorageAdapter, lapse_csv: str) -> None:
    """enabled=False → transform returns the frame unchanged."""
    cfg = _interaction_cfg(
        lapse_csv, enabled=False, interaction_pairs=EXPLICIT_PAIRS, max_auto_pairs=5
    )
    train_pp, test_pp = _preprocessed(cfg, storage)
    ib = InteractionFeatureBuilder(cfg)
    out = ib.fit_transform(train_pp, "will_lapse")
    assert ib.interaction_cols_ == []
    pd.testing.assert_frame_equal(out, train_pp)
    pd.testing.assert_frame_equal(ib.transform(test_pp), test_pp)


def test_config_not_mutated(storage: StorageAdapter, lapse_csv: str) -> None:
    """The config dict is identical before and after fit + transform."""
    cfg = _interaction_cfg(
        lapse_csv, interaction_pairs=EXPLICIT_PAIRS, max_auto_pairs=4
    )
    snapshot = copy.deepcopy(cfg)
    train_pp, test_pp = _preprocessed(cfg, storage)
    ib = InteractionFeatureBuilder(cfg)
    ib.fit_transform(train_pp, "will_lapse")
    ib.transform(test_pp)
    assert cfg == snapshot


def test_input_frame_not_mutated(storage: StorageAdapter, lapse_csv: str) -> None:
    """Neither fit nor transform mutates the caller's DataFrames."""
    cfg = _interaction_cfg(
        lapse_csv, interaction_pairs=EXPLICIT_PAIRS, max_auto_pairs=4
    )
    train_pp, test_pp = _preprocessed(cfg, storage)
    train_snap, test_snap = train_pp.copy(deep=True), test_pp.copy(deep=True)
    ib = InteractionFeatureBuilder(cfg)
    ib.fit_transform(train_pp, "will_lapse")
    ib.transform(test_pp)
    pd.testing.assert_frame_equal(train_pp, train_snap)
    pd.testing.assert_frame_equal(test_pp, test_snap)


# -------------------------------------------------------------------- plot6 ----


def test_plot6_written(
    storage: StorageAdapter, lapse_csv: str, output_dir: Any
) -> None:
    """plot6_interaction_summary.png is written and is a non-trivial PNG (>10 KB).

    Runs the full pipeline load → split → preprocess → features → interactions.
    """
    cfg = _interaction_cfg(lapse_csv, interaction_pairs=EXPLICIT_PAIRS, max_auto_pairs=5)
    train_pp, _ = _preprocessed(cfg, storage)
    fb = FeatureBuilder(cfg)
    train_f = fb.fit_transform(train_pp, "will_lapse")
    ib = InteractionFeatureBuilder(cfg)
    train_i = ib.fit_transform(train_f, "will_lapse")

    plot_interaction_summary(train_i, "will_lapse", ib.interaction_cols_, storage)
    assert storage.exists(PLOT_PNG_KEY)
    path = storage.path_for(PLOT_PNG_KEY, output=True)
    assert os.path.getsize(path) > 10_000
