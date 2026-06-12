"""Tests for Section 4 (io/loader.py) on real sample data."""

from __future__ import annotations

import pandas as pd
import pytest

from classifyos.config import build_config
from classifyos.io.loader import data_loader


def test_loader_missing_file_raises(storage) -> None:
    cfg = build_config("nope_does_not_exist.csv", "will_lapse", ["age"])
    with pytest.raises(FileNotFoundError):
        data_loader(cfg, storage)


def test_loader_missing_feature_column_raises(storage, lapse_csv) -> None:
    cfg = build_config(lapse_csv, "will_lapse", ["age", "not_a_real_column"])
    with pytest.raises(ValueError, match="not_a_real_column"):
        data_loader(cfg, storage)


def test_loader_loads_all_samples(storage, lapse_csv, fraud_csv, risk_csv) -> None:
    cases = [
        (lapse_csv, "will_lapse", ["age", "annual_premium", "channel"]),
        (fraud_csv, "is_fraud", ["claim_amount", "incident_type"]),
        (risk_csv, "risk_tier", ["age", "bmi", "occupation_class"]),
    ]
    for path, target, features in cases:
        cfg = build_config(path, target, features)
        df = data_loader(cfg, storage)
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0
        assert target in df.columns
        # target coerced to string/categorical, not float
        assert df[target].dtype == object
        assert df[target].nunique() >= 2


def test_loader_drops_target_nan_rows(storage, lapse_csv, monkeypatch) -> None:
    # Sanity: loading still succeeds and leaves no NaN in the target.
    cfg = build_config(lapse_csv, "will_lapse", ["age"])
    df = data_loader(cfg, storage)
    assert df["will_lapse"].isna().sum() == 0


def test_loader_time_split_col_parsed(storage, lapse_csv) -> None:
    cfg = build_config(
        lapse_csv, "will_lapse", ["age"], time_split_col="policy_start_date"
    )
    df = data_loader(cfg, storage)
    assert pd.api.types.is_datetime64_any_dtype(df["policy_start_date"])


def test_loader_unparseable_time_col_raises(storage, lapse_csv) -> None:
    cfg = build_config(lapse_csv, "will_lapse", ["age"], time_split_col="occupation")
    with pytest.raises(ValueError, match="could not be parsed"):
        data_loader(cfg, storage)
