"""Tests for Section 5 (analysis/feature_impact.py) on real sample data.

Runs the screen against the real sample CSVs via the Phase 1 loader and asserts the
contract: column set, applicability of each metric per problem type, the id_like
flag, output artifacts, input immutability, and graceful handling of a zero-variance
feature.
"""

from __future__ import annotations

import pandas as pd
import pytest

from classifyos.analysis.feature_impact import (
    PLOT_PNG_KEY,
    SUMMARY_CSV_KEY,
    analyze_feature_impact,
)
from classifyos.config import build_config
from classifyos.io.loader import data_loader

# Features chosen to exercise every code path: numeric, categorical, and an ID col.
_LAPSE_FEATURES = [
    "policy_id",
    "age",
    "annual_premium",
    "num_late_payments",
    "claims_count",
    "occupation",
    "channel",
]
_RISK_FEATURES = [
    "age",
    "bmi",
    "is_smoker",
    "annual_income",
    "credit_score",
    "prior_violations",
    "occupation_class",
]

_EXPECTED_COLUMNS = [
    "feature",
    "dtype_group",
    "anova_f",
    "anova_p",
    "mutual_info",
    "point_biserial",
    "corr_ratio",
    "composite_score",
    "id_like",
    "rank",
]


def _load(storage, path, target, features):
    cfg = build_config(path, target, features)
    return data_loader(cfg, storage), cfg


def test_binary_lapse_metrics(storage, lapse_csv) -> None:
    df, cfg = _load(storage, lapse_csv, "will_lapse", _LAPSE_FEATURES)
    result = analyze_feature_impact(df, cfg, storage)

    # one row per feature, exact contract columns
    assert list(result.columns) == _EXPECTED_COLUMNS
    assert len(result) == len(_LAPSE_FEATURES)
    assert set(result["feature"]) == set(_LAPSE_FEATURES)

    by_feature = result.set_index("feature")

    # num_late_payments drives the target by construction -> above-median composite
    median_score = result["composite_score"].median()
    assert by_feature.loc["num_late_payments", "composite_score"] > median_score

    # point-biserial: non-NaN for numeric features, NaN for categorical (occupation)
    assert pd.notna(by_feature.loc["age", "point_biserial"])
    assert pd.notna(by_feature.loc["annual_premium", "point_biserial"])
    assert pd.isna(by_feature.loc["occupation", "point_biserial"])

    # categorical feature still gets a mutual-information value
    assert pd.notna(by_feature.loc["occupation", "mutual_info"])

    # ANOVA only applies to numeric features
    assert pd.notna(by_feature.loc["age", "anova_f"])
    assert pd.isna(by_feature.loc["occupation", "anova_f"])

    # corr_ratio is the multiclass metric -> all-NaN on a binary problem
    assert result["corr_ratio"].isna().all()

    # ID column flagged, normal columns not
    assert bool(by_feature.loc["policy_id", "id_like"]) is True
    assert bool(by_feature.loc["age", "id_like"]) is False


def test_multiclass_risk_metrics(storage, risk_csv) -> None:
    df, cfg = _load(storage, risk_csv, "risk_tier", _RISK_FEATURES)
    cfg["problem_type"] = "multiclass"
    result = analyze_feature_impact(df, cfg, storage)

    assert list(result.columns) == _EXPECTED_COLUMNS

    # point-biserial is not defined for multiclass; corr_ratio takes over for numerics
    assert result["point_biserial"].isna().all()
    by_feature = result.set_index("feature")
    for numeric_feat in ("age", "bmi", "annual_income", "credit_score"):
        assert pd.notna(by_feature.loc[numeric_feat, "corr_ratio"])

    # is_smoker is a strong driver -> ranks in the top 5 by composite score
    top5 = set(result.sort_values("rank").head(5)["feature"])
    assert "is_smoker" in top5


def test_outputs_written(storage, lapse_csv, output_dir) -> None:
    df, cfg = _load(storage, lapse_csv, "will_lapse", _LAPSE_FEATURES)
    analyze_feature_impact(df, cfg, storage)

    csv_path = output_dir / SUMMARY_CSV_KEY
    png_path = output_dir / PLOT_PNG_KEY
    assert csv_path.exists()
    assert png_path.exists()
    # PNG should be a real rendered figure, not an empty stub
    assert png_path.stat().st_size > 10 * 1024

    # the CSV round-trips to the same contract columns
    reloaded = pd.read_csv(csv_path)
    assert list(reloaded.columns) == _EXPECTED_COLUMNS


def test_input_not_mutated(storage, lapse_csv) -> None:
    df, cfg = _load(storage, lapse_csv, "will_lapse", _LAPSE_FEATURES)
    before = df.copy(deep=True)
    analyze_feature_impact(df, cfg, storage)
    pd.testing.assert_frame_equal(df, before)


def test_zero_variance_feature_handled(storage, lapse_csv) -> None:
    df, _ = _load(storage, lapse_csv, "will_lapse", ["age"])
    df["constant_col"] = 1.0  # zero-variance numeric feature
    cfg = build_config(lapse_csv, "will_lapse", ["age", "constant_col"])

    # must not raise on the degenerate column
    result = analyze_feature_impact(df, cfg, storage)
    const_row = result.set_index("feature").loc["constant_col"]

    # composite is gracefully 0 or NaN; F/eta/point-biserial are undefined (NaN)
    score = const_row["composite_score"]
    assert pd.isna(score) or score == 0.0
    assert pd.isna(const_row["anova_f"])
    assert pd.isna(const_row["point_biserial"])
