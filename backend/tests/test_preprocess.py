"""Tests for Section 6 (preprocessing) — the leakage tests are the heart of Phase 3.

All cases run on the real sample CSVs from ``DATA_DIR`` (see conftest fixtures).
"""

from __future__ import annotations

from typing import Any

import joblib
import numpy as np
import pandas as pd
import pytest

from classifyos.config import MISSING_STRATEGIES, build_config
from classifyos.io.loader import data_loader
from classifyos.io.storage import StorageAdapter
from classifyos.preprocessing.preprocess import TARGET_SMOOTHING_M, Preprocessor
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


def _lapse_config(lapse_csv: str, **overrides: Any) -> dict[str, Any]:
    return build_config(lapse_csv, "will_lapse", LAPSE_FEATURES, **overrides)


def _load_split(
    config: dict[str, Any], storage: StorageAdapter
) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = data_loader(config, storage)
    return train_test_split_cls(df, config)


def _smoothed_mean(df: pd.DataFrame, col: str, category: str, target: str) -> float:
    """Reference m-estimate smoothed target mean, computed independently."""
    y = (df[target].astype(str) == "1").astype(float)
    global_mean = y.mean()
    sub = y[df[col].astype(str) == category]
    return float(
        (len(sub) * sub.mean() + TARGET_SMOOTHING_M * global_mean)
        / (len(sub) + TARGET_SMOOTHING_M)
    )


# --------------------------------------------------------------- leakage ----


def test_no_leakage_scaler(storage: StorageAdapter, lapse_csv: str) -> None:
    """Scaler statistics come from train only and survive a poisoned test set."""
    cfg = _lapse_config(
        lapse_csv,
        scaling_method="standard",
        outlier_method="none",
        missing_strategy="median",
    )
    train, test = _load_split(cfg, storage)
    pp = Preprocessor(cfg).fit(train)

    # Stored mean equals the value computed manually from the imputed TRAIN column.
    col_idx = pp.numeric_cols_.index("annual_premium")
    expected_mean = (
        train["annual_premium"].fillna(train["annual_premium"].median()).mean()
    )
    assert np.isclose(pp.scaler_.mean_[col_idx], expected_mean)

    # Poison the test split ×1000 — transform must not move the fitted parameters.
    mean_before = pp.scaler_.mean_.copy()
    scale_before = pp.scaler_.scale_.copy()
    poisoned = test.copy()
    poisoned["annual_premium"] = poisoned["annual_premium"] * 1000
    pp.transform(poisoned)
    assert np.array_equal(pp.scaler_.mean_, mean_before)
    assert np.array_equal(pp.scaler_.scale_, scale_before)


def test_no_leakage_target_encoding(storage: StorageAdapter, lapse_csv: str) -> None:
    """Encoded values equal the smoothed TRAIN-only mean, not the full-data mean."""
    cfg = _lapse_config(lapse_csv, encoding_method="target")
    df = data_loader(cfg, storage)
    train = df.iloc[:2000].reset_index(drop=True)
    test = df.iloc[2000:].reset_index(drop=True).copy()
    # Force every test-set "South" row to the positive class so the full-data
    # mean for the category provably differs from the train-only mean.
    test.loc[test["region"] == "South", "will_lapse"] = "1"

    pp = Preprocessor(cfg).fit(train)
    out = pp.transform(test)

    expected_train_only = _smoothed_mean(train, "region", "South", "will_lapse")
    full = pd.concat([train, test], ignore_index=True)
    full_data_mean = _smoothed_mean(full, "region", "South", "will_lapse")
    assert not np.isclose(expected_train_only, full_data_mean)

    south_encoded = out.loc[test["region"] == "South", "region"].unique()
    assert len(south_encoded) == 1
    assert south_encoded[0] == pytest.approx(expected_train_only)
    assert south_encoded[0] != pytest.approx(full_data_mean)


def test_unseen_category(storage: StorageAdapter, lapse_csv: str) -> None:
    """A category present only in test transforms cleanly under onehot and target."""
    # occupation has 24 levels — raise the threshold so onehot actually applies.
    cfg = _lapse_config(lapse_csv, high_cardinality_threshold=100)
    df = data_loader(cfg, storage)
    train = df[df["occupation"] != "Nurse"].reset_index(drop=True)
    test = df[df["occupation"] == "Nurse"].reset_index(drop=True)
    assert len(test) > 0

    # onehot: the unseen category becomes an all-zeros block.
    pp = Preprocessor(cfg).fit(train)
    out = pp.transform(test)
    occ_block = [c for c in pp.feature_names_out_ if c.startswith("occupation_")]
    assert "occupation_Nurse" not in occ_block
    assert (out[occ_block].to_numpy().sum(axis=1) == 0).all()

    # target: the unseen category maps to the global TRAIN target mean.
    cfg_t = _lapse_config(lapse_csv, encoding_method="target")
    pp_t = Preprocessor(cfg_t).fit(train)
    out_t = pp_t.transform(test)
    global_train_mean = (train["will_lapse"].astype(str) == "1").mean()
    assert out_t["occupation"].unique() == pytest.approx([global_train_mean])


# --------------------------------------------------- per-step behaviours ----


@pytest.mark.parametrize("strategy", MISSING_STRATEGIES)
def test_missing_strategies(
    storage: StorageAdapter, lapse_csv: str, strategy: str
) -> None:
    """Every strategy runs end-to-end; none of them ever drops a test row."""
    cfg = _lapse_config(lapse_csv, missing_strategy=strategy)
    train, test = _load_split(cfg, storage)
    # Leading NaN exercises the ffill fallback (no prior row to fill from).
    test = test.copy()
    test.loc[test.index[0], "age"] = np.nan

    pp = Preprocessor(cfg)
    train_out = pp.fit_transform(train)
    test_out = pp.transform(test)

    assert len(test_out) == len(test), f"{strategy!r} dropped test rows"
    assert not train_out[pp.feature_names_out_].isna().any().any()
    assert not test_out[pp.feature_names_out_].isna().any().any()
    if strategy == "drop":
        assert len(train_out) < len(train)  # complete-case training did drop


def test_outlier_capping(storage: StorageAdapter, lapse_csv: str) -> None:
    """An injected extreme value in test is clipped to the train-derived fence."""
    cfg = _lapse_config(
        lapse_csv,
        outlier_method="iqr",
        scaling_method="none",
        missing_strategy="median",
    )
    train, test = _load_split(cfg, storage)
    pp = Preprocessor(cfg).fit(train)

    imputed = train["annual_premium"].fillna(train["annual_premium"].median())
    q1, q3 = imputed.quantile([0.25, 0.75])
    expected_hi = q3 + 1.5 * (q3 - q1)

    poisoned = test.copy()
    poisoned.loc[poisoned.index[0], "annual_premium"] = 1e9
    out = pp.transform(poisoned)
    assert out["annual_premium"].iloc[0] == pytest.approx(expected_hi)
    assert (out["annual_premium"] <= expected_hi + 1e-9).all()


def test_target_untouched(storage: StorageAdapter, lapse_csv: str) -> None:
    """Target values are byte-identical before and after transform."""
    cfg = _lapse_config(lapse_csv)
    train, test = _load_split(cfg, storage)
    pp = Preprocessor(cfg).fit(train)
    out = pp.transform(test)
    assert out["will_lapse"].tolist() == test["will_lapse"].tolist()
    # Target column is appended last and is not part of the feature contract.
    assert "will_lapse" not in pp.feature_names_out_
    assert list(out.columns) == pp.feature_names_out_ + ["will_lapse"]


def test_multiclass_high_cardinality(storage: StorageAdapter, risk_csv: str) -> None:
    """A 30-level column on a multiclass target falls back to frequency encoding."""
    cfg = build_config(
        risk_csv,
        "risk_tier",
        RISK_FEATURES + ["agent_code"],
        problem_type="multiclass",
    )
    df = data_loader(
        build_config(risk_csv, "risk_tier", RISK_FEATURES, problem_type="multiclass"),
        storage,
    )
    rng = np.random.RandomState(0)
    df["agent_code"] = [f"AG{i:02d}" for i in rng.randint(0, 30, len(df))]
    train, test = train_test_split_cls(df, cfg)

    pp = Preprocessor(cfg).fit(train)
    out = pp.transform(test)

    assert "agent_code" in pp.high_card_cols_
    assert "agent_code" in pp.freq_maps_  # frequency, not target-mean
    assert "agent_code" in out.columns
    some_code = train["agent_code"].iloc[0]
    expected_freq = (train["agent_code"] == some_code).mean()
    encoded = out.loc[test["agent_code"] == some_code, "agent_code"].unique()
    assert encoded == pytest.approx([expected_freq])


def test_picklable(
    storage: StorageAdapter, lapse_csv: str, tmp_path: Any
) -> None:
    """joblib round-trip: the reloaded instance transforms identically."""
    cfg = _lapse_config(lapse_csv)
    train, test = _load_split(cfg, storage)
    pp = Preprocessor(cfg).fit(train)

    path = tmp_path / "preprocessor.joblib"
    joblib.dump(pp, path)
    reloaded = joblib.load(path)

    pd.testing.assert_frame_equal(pp.transform(test), reloaded.transform(test))


# ----------------------------------------------------------- config keys ----


def test_config_new_keys_validated(lapse_csv: str) -> None:
    """The Phase 3 config keys exist, default sanely, and reject bad values."""
    cfg = _lapse_config(lapse_csv)
    assert cfg["outlier_method"] == "iqr"
    assert cfg["high_cardinality_threshold"] == 20
    with pytest.raises(ValueError, match="outlier_method"):
        _lapse_config(lapse_csv, outlier_method="winsor")
    with pytest.raises(ValueError, match="high_cardinality_threshold"):
        _lapse_config(lapse_csv, high_cardinality_threshold=0)


def test_input_frames_not_mutated(storage: StorageAdapter, lapse_csv: str) -> None:
    """Neither fit nor transform mutates the caller's DataFrames."""
    cfg = _lapse_config(lapse_csv)
    train, test = _load_split(cfg, storage)
    train_snapshot, test_snapshot = train.copy(deep=True), test.copy(deep=True)
    pp = Preprocessor(cfg)
    pp.fit_transform(train)
    pp.transform(test)
    pd.testing.assert_frame_equal(train, train_snapshot)
    pd.testing.assert_frame_equal(test, test_snapshot)
