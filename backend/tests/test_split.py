"""Tests for Section 9 (split.py) on real sample data."""

from __future__ import annotations

from classifyos.config import build_config
from classifyos.io.loader import data_loader
from classifyos.split import train_test_split_cls


def test_stratified_preserves_class_proportions(storage, risk_csv) -> None:
    cfg = build_config(risk_csv, "risk_tier", ["age", "bmi", "credit_score"], test_size=0.2)
    df = data_loader(cfg, storage)
    train_df, test_df = train_test_split_cls(df, cfg)

    assert len(train_df) + len(test_df) == len(df)

    full = df["risk_tier"].value_counts(normalize=True)
    train = train_df["risk_tier"].value_counts(normalize=True)
    for cls, full_prop in full.items():
        assert abs(train.get(cls, 0.0) - full_prop) <= 0.02, cls


def test_time_split_train_before_test(storage, lapse_csv) -> None:
    cfg = build_config(
        lapse_csv, "will_lapse", ["age", "annual_premium"],
        time_split_col="policy_start_date", test_size=0.2,
    )
    df = data_loader(cfg, storage)
    train_df, test_df = train_test_split_cls(df, cfg)

    assert len(test_df) > 0 and len(train_df) > 0
    assert train_df["policy_start_date"].max() <= test_df["policy_start_date"].min()


def test_fraud_stratified_keeps_minority_in_test(storage, fraud_csv) -> None:
    cfg = build_config(fraud_csv, "is_fraud", ["claim_amount", "report_delay_days"], test_size=0.2)
    df = data_loader(cfg, storage)
    train_df, test_df = train_test_split_cls(df, cfg)

    # "1" because the loader coerces the target to string
    assert (test_df["is_fraud"] == "1").sum() >= 1
    assert (train_df["is_fraud"] == "1").sum() >= 1


def test_stratify_fallback_no_crash(storage, risk_csv) -> None:
    # Force a singleton class to trigger the non-stratified fallback path.
    cfg = build_config(risk_csv, "risk_tier", ["age", "bmi"], test_size=0.2)
    df = data_loader(cfg, storage)
    # keep only one row of the "High" class
    high_idx = df.index[df["risk_tier"] == "High"][1:]
    df = df.drop(high_idx).reset_index(drop=True)
    train_df, test_df = train_test_split_cls(df, cfg)
    assert len(train_df) + len(test_df) == len(df)
