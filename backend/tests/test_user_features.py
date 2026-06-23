"""Tests for ``UserFeatureBuilder`` (user-defined structured features).

Builder-level cases run on small, constructed frames with known values; the
integration cases drive the real ``ModelRunner`` on a sample CSV. The central safety
property — only fixed-allowlist operations are applied to known columns, never an
eval'd formula — is exercised by the validation/skip tests below.
"""

from __future__ import annotations

import copy
import io

import joblib
import numpy as np
import pandas as pd
import pytest

from classifyos.config import DEFAULT_CONFIG, build_config
from classifyos.preprocessing.user_features import UserFeatureBuilder
from classifyos.runner import ModelRunner

_N_BINS_MINUS_1 = 4  # _N_BINS (5) - 1: index of the top quantile bin


def _cfg(specs: list[dict], fill_method: str = "zero") -> dict:
    """Minimal config the builder reads (bypasses build_config for skip-path tests)."""
    return {
        "user_features": specs,
        "interaction_features": {"fill_method": fill_method},
        "random_state": 42,
    }


# --------------------------------------------------------------- datetime_diff --


def test_datetime_diff_days_correct_values() -> None:
    df = pd.DataFrame(
        {
            "start": ["2021-01-01", "2021-01-10", "2021-02-01"],
            "end": ["2021-01-03", "2021-01-12", "2021-02-06"],
            "y": ["0", "1", "0"],
        }
    )
    spec = {
        "name": "dur_days",
        "op": "subtract",
        "type": "datetime_diff",
        "col_a": "end",
        "col_b": "start",
        "unit": "days",
    }
    ufb = UserFeatureBuilder(_cfg([spec]))
    out = ufb.fit_transform(df, "y")
    assert ufb.created_features_ == ["dur_days"]
    assert out["dur_days"].tolist() == [2.0, 2.0, 5.0]


def test_datetime_diff_seconds_unit() -> None:
    df = pd.DataFrame(
        {
            "start": ["2021-01-01 00:00:00", "2021-01-01 00:00:00"],
            "end": ["2021-01-01 00:01:00", "2021-01-01 01:00:00"],
            "y": ["0", "1"],
        }
    )
    spec = {
        "name": "dur_s",
        "op": "subtract",
        "type": "datetime_diff",
        "col_a": "end",
        "col_b": "start",
        "unit": "seconds",
    }
    out = UserFeatureBuilder(_cfg([spec])).fit_transform(df, "y")
    assert out["dur_s"].tolist() == [60.0, 3600.0]


def test_datetime_diff_unparseable_row_filled_not_nan() -> None:
    df = pd.DataFrame(
        {
            "start": ["2021-01-01", "not-a-date"],
            "end": ["2021-01-03", "2021-01-05"],
            "y": ["0", "1"],
        }
    )
    spec = {
        "name": "dur",
        "op": "subtract",
        "type": "datetime_diff",
        "col_a": "end",
        "col_b": "start",
    }  # unit defaults to days
    out = UserFeatureBuilder(_cfg([spec])).fit_transform(df, "y")
    assert out["dur"].tolist() == [2.0, 0.0]  # NaT diff → 0.0, never NaN
    assert not out["dur"].isna().any()


# --------------------------------------------------------------- numeric ops --


def test_numeric_divide_guard_fills_zero_no_inf() -> None:
    df = pd.DataFrame({"a": [10.0, 20.0, 5.0], "b": [2.0, 0.0, 1.0], "y": ["0", "1", "0"]})
    spec = {"name": "r", "op": "divide", "type": "numeric", "col_a": "a", "col_b": "b"}
    out = UserFeatureBuilder(_cfg([spec], fill_method="zero")).fit_transform(df, "y")
    assert out["r"].tolist() == [5.0, 0.0, 5.0]  # near-zero denom → 0.0
    assert np.isfinite(out["r"]).all()  # no inf


def test_numeric_divide_median_fill() -> None:
    df = pd.DataFrame({"a": [10.0, 20.0, 5.0], "b": [2.0, 0.0, 1.0], "y": ["0", "1", "0"]})
    spec = {"name": "r", "op": "ratio", "type": "numeric", "col_a": "a", "col_b": "b"}
    ufb = UserFeatureBuilder(_cfg([spec], fill_method="median"))
    out = ufb.fit_transform(df, "y")
    # train ratios = [5.0, NaN, 5.0] → median 5.0 → the guarded row is filled with 5.0
    assert ufb.ratio_fill_medians_["r"] == 5.0
    assert out["r"].tolist() == [5.0, 5.0, 5.0]


def test_numeric_add_subtract_multiply() -> None:
    df = pd.DataFrame({"a": [3.0, 4.0], "b": [1.0, 2.0], "y": ["0", "1"]})
    specs = [
        {"name": "s", "op": "add", "type": "numeric", "col_a": "a", "col_b": "b"},
        {"name": "d", "op": "subtract", "type": "numeric", "col_a": "a", "col_b": "b"},
        {"name": "m", "op": "multiply", "type": "numeric", "col_a": "a", "col_b": "b"},
    ]
    out = UserFeatureBuilder(_cfg(specs)).fit_transform(df, "y")
    assert out["s"].tolist() == [4.0, 6.0]
    assert out["d"].tolist() == [2.0, 2.0]
    assert out["m"].tolist() == [3.0, 8.0]


# --------------------------------------------------------------- single ops --


def test_single_log_and_abs() -> None:
    df = pd.DataFrame({"x": [0.0, 9.0], "z": [-3.0, 4.0], "y": ["0", "1"]})
    specs = [
        {"name": "lx", "op": "log", "type": "single", "col_a": "x"},
        {"name": "az", "op": "abs", "type": "single", "col_a": "z"},
    ]
    out = UserFeatureBuilder(_cfg(specs)).fit_transform(df, "y")
    assert out["lx"].tolist() == pytest.approx([0.0, np.log1p(9.0)])
    assert out["az"].tolist() == [3.0, 4.0]


def test_single_log_negative_train_rejected() -> None:
    df = pd.DataFrame({"x": [-1.0, 9.0], "y": ["0", "1"]})
    spec = {"name": "lx", "op": "log", "type": "single", "col_a": "x"}
    ufb = UserFeatureBuilder(_cfg([spec]))
    ufb.fit(df, "y")
    assert ufb.created_features_ == []  # rejected: negative train values
    assert ufb.skipped_specs_ and "non-negative" in ufb.skipped_specs_[0][1]


def test_single_bin_edges_are_train_only() -> None:
    train = pd.DataFrame({"x": np.arange(100.0), "y": ["0", "1"] * 50})
    spec = {"name": "xb", "op": "bin", "type": "single", "col_a": "x"}
    ufb = UserFeatureBuilder(_cfg([spec]))
    ufb.fit(train, "y")
    edges_after_fit = ufb.bin_edges_["xb"].copy()

    # Poison the test split with extreme values; edges must NOT change, and the extreme
    # value must clip into the top bin (outer edges are ±inf).
    test = pd.DataFrame({"x": [-1e9, 50.0, 1e9], "y": ["0", "1", "0"]})
    out = ufb.transform(test)
    np.testing.assert_array_equal(ufb.bin_edges_["xb"], edges_after_fit)
    assert out["xb"].iloc[0] == 0  # below train range → lowest bin
    assert out["xb"].iloc[-1] == _N_BINS_MINUS_1  # above train range → highest bin
    assert not out["xb"].isna().any()


def test_single_date_part_extraction() -> None:
    df = pd.DataFrame({"d": ["2021-03-15", "2022-12-25"], "y": ["0", "1"]})
    specs = [
        {"name": "yr", "op": "year", "type": "single", "col_a": "d"},
        {"name": "mo", "op": "month", "type": "single", "col_a": "d"},
    ]
    out = UserFeatureBuilder(_cfg(specs)).fit_transform(df, "y")
    assert out["yr"].tolist() == [2021, 2022]
    assert out["mo"].tolist() == [3, 12]


# --------------------------------------------------------------- validation --


def test_missing_column_is_skipped_not_crash() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0], "y": ["0", "1"]})
    spec = {"name": "r", "op": "divide", "type": "numeric", "col_a": "a", "col_b": "ghost"}
    ufb = UserFeatureBuilder(_cfg([spec]))
    out = ufb.fit_transform(df, "y")  # must not raise
    assert ufb.created_features_ == []
    assert "r" not in out.columns
    assert ufb.skipped_specs_ and "ghost" in ufb.skipped_specs_[0][1]


def test_wrong_column_type_is_skipped() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0], "txt": ["x", "y"], "y": ["0", "1"]})
    spec = {"name": "r", "op": "multiply", "type": "numeric", "col_a": "a", "col_b": "txt"}
    ufb = UserFeatureBuilder(_cfg([spec]))
    ufb.fit_transform(df, "y")
    assert ufb.created_features_ == []
    assert ufb.skipped_specs_ and "not numeric" in ufb.skipped_specs_[0][1]


def test_unknown_op_at_builder_is_skipped() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0], "y": ["0", "1"]})
    spec = {"name": "r", "op": "power", "type": "numeric", "col_a": "a", "col_b": "b"}
    ufb = UserFeatureBuilder(_cfg([spec]))
    ufb.fit_transform(df, "y")
    assert ufb.created_features_ == []


def test_target_as_source_is_skipped() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0], "y": [0.0, 1.0]})
    spec = {"name": "r", "op": "add", "type": "numeric", "col_a": "a", "col_b": "y"}
    ufb = UserFeatureBuilder(_cfg([spec]))
    ufb.fit_transform(df, "y")
    assert ufb.created_features_ == []
    assert ufb.skipped_specs_ and "target" in ufb.skipped_specs_[0][1]


def test_name_collision_with_existing_column_rejected() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0], "y": ["0", "1"]})
    spec = {"name": "a", "op": "add", "type": "numeric", "col_a": "a", "col_b": "b"}
    ufb = UserFeatureBuilder(_cfg([spec]))
    out = ufb.fit_transform(df, "y")
    assert ufb.created_features_ == []
    assert out["a"].tolist() == [1.0, 2.0]  # original column never overwritten
    assert ufb.skipped_specs_ and "collides" in ufb.skipped_specs_[0][1]


def test_valid_and_invalid_specs_coexist() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0], "y": ["0", "1"]})
    specs = [
        {"name": "good", "op": "add", "type": "numeric", "col_a": "a", "col_b": "b"},
        {"name": "bad", "op": "divide", "type": "numeric", "col_a": "a", "col_b": "ghost"},
    ]
    ufb = UserFeatureBuilder(_cfg(specs))
    out = ufb.fit_transform(df, "y")
    assert ufb.created_features_ == ["good"]  # only the valid one survives
    assert out["good"].tolist() == [4.0, 6.0]
    assert len(ufb.skipped_specs_) == 1


# --------------------------------------------------------------- config boundary --


def test_build_config_rejects_unknown_op() -> None:
    with pytest.raises(ValueError, match="op"):
        build_config(
            "policy_lapse.csv",
            "will_lapse",
            ["age"],
            user_features=[
                {"name": "r", "op": "power", "type": "numeric", "col_a": "a", "col_b": "b"}
            ],
        )


def test_build_config_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="type"):
        build_config(
            "policy_lapse.csv",
            "will_lapse",
            ["age"],
            user_features=[{"name": "r", "op": "add", "type": "bogus", "col_a": "a"}],
        )


def test_build_config_rejects_duplicate_name() -> None:
    with pytest.raises(ValueError, match="duplicated"):
        build_config(
            "policy_lapse.csv",
            "will_lapse",
            ["age"],
            user_features=[
                {"name": "x", "op": "abs", "type": "single", "col_a": "a"},
                {"name": "x", "op": "log", "type": "single", "col_a": "b"},
            ],
        )


def test_build_config_default_user_features_empty() -> None:
    cfg = build_config("policy_lapse.csv", "will_lapse", ["age"])
    assert cfg["user_features"] == []


# --------------------------------------------------------------- immutability / pickle --


def test_input_df_and_config_not_mutated() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0], "y": ["0", "1"]})
    df_before = df.copy(deep=True)
    cfg = _cfg([{"name": "s", "op": "add", "type": "numeric", "col_a": "a", "col_b": "b"}])
    cfg_before = copy.deepcopy(cfg)

    ufb = UserFeatureBuilder(cfg)
    ufb.fit_transform(df, "y")

    pd.testing.assert_frame_equal(df, df_before)  # input frame untouched
    assert cfg == cfg_before  # config untouched


def test_joblib_round_trip() -> None:
    df = pd.DataFrame({"x": np.arange(50.0), "y": ["0", "1"] * 25})
    spec = {"name": "xb", "op": "bin", "type": "single", "col_a": "x"}
    ufb = UserFeatureBuilder(_cfg([spec])).fit(df, "y")
    expected = ufb.transform(df)

    buf = io.BytesIO()
    joblib.dump(ufb, buf)
    buf.seek(0)
    loaded = joblib.load(buf)
    pd.testing.assert_frame_equal(loaded.transform(df), expected)


# --------------------------------------------------------------- ModelRunner integration --


def _run(storage, **overrides) -> ModelRunner:
    cfg = build_config(
        "policy_lapse.csv",
        "will_lapse",
        ["age", "annual_premium", "sum_assured", "num_late_payments"],
        problem_type="binary",
        algorithms=["LogisticRegression"],
        class_balance="none",
        interaction_features={"max_auto_pairs": 0},
        **overrides,
    )
    return ModelRunner(cfg, storage).run()


def test_empty_user_features_is_noop(storage) -> None:
    baseline = _run(storage)  # default user_features == []
    explicit = _run(storage, user_features=[])
    assert set(baseline.active_features_) == set(explicit.active_features_)
    # deterministic LogisticRegression → identical metrics
    assert baseline.metrics_df_["f1_weighted"].tolist() == pytest.approx(
        explicit.metrics_df_["f1_weighted"].tolist()
    )


def test_user_feature_adds_active_feature_column(storage) -> None:
    baseline = _run(storage)
    runner = _run(
        storage,
        user_features=[
            {
                "name": "prem_per_sum",
                "op": "divide",
                "type": "numeric",
                "col_a": "annual_premium",
                "col_b": "sum_assured",
            },
            # date-part from a RAW datetime column that is NOT a model feature — proves
            # user features read the raw post-split frame, not the preprocessed one.
            {"name": "start_month", "op": "month", "type": "single", "col_a": "policy_start_date"},
        ],
    )
    assert "prem_per_sum" not in baseline.active_features_
    assert "prem_per_sum" in runner.active_features_
    assert "start_month" in runner.active_features_
    # the run still succeeds end-to-end
    assert (runner.metrics_df_["status"] == "ok").all()
