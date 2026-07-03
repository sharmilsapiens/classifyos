"""Tests for the Data-Profile helper (analysis/profile.py) + its inspect wiring."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from classifyos.analysis.profile import profile_dataframe
from classifyos.io.inspect import inspect_file


@pytest.fixture()
def toy_df() -> pd.DataFrame:
    """A small mixed-type frame exercising every profiling branch."""
    return pd.DataFrame(
        {
            "age": [20, 30, 40, 50, 60, np.nan],          # numeric, one missing
            "const": [5.0, 5.0, 5.0, 5.0, 5.0, 5.0],      # constant numeric (degenerate)
            "region": ["N", "N", "S", "E", "W", "N"],     # categorical
            "flag": [0, 1, 0, 1, 0, 1],                   # binary numeric
            "joined": ["2020-01-01", "2020-06-01", "2021-01-01",
                       "2021-06-01", "2022-01-01", None],  # datetime-ish
        }
    )


def _groups(df: pd.DataFrame) -> dict:
    """The column-type groups the way inspect_file would compute them (simplified)."""
    return {
        "numeric_cols": ["age", "const", "flag"],
        "categorical_cols": ["region"],
        "binary_cols": ["flag"],
        "datetime_cols": ["joined"],
    }


def test_numeric_profile_stats_and_histogram(toy_df) -> None:
    prof = profile_dataframe(toy_df, max_bins=4, **_groups(toy_df))
    cols = {c["name"]: c for c in prof["column_profiles"]}

    age = cols["age"]
    assert age["dtype_group"] == "numeric"
    assert age["n_missing"] == 1
    assert age["missing_pct"] == pytest.approx(100 / 6)
    s = age["stats"]
    assert s["count"] == 5
    assert s["min"] == 20.0 and s["max"] == 60.0
    assert s["median"] == 40.0
    # histogram has exactly max_bins counts and max_bins+1 edges
    assert len(age["histogram"]["counts"]) == 4
    assert len(age["histogram"]["bin_edges"]) == 5
    assert sum(age["histogram"]["counts"]) == 5


def test_constant_numeric_is_finite_and_degenerate(toy_df) -> None:
    prof = profile_dataframe(toy_df, **_groups(toy_df))
    const = next(c for c in prof["column_profiles"] if c["name"] == "const")
    # std/skew of a constant column must not leak NaN into the payload.
    assert const["stats"]["std"] == 0.0
    assert const["stats"]["skew"] in (0.0, None)
    # and it is surfaced to the UI as a degenerate (zero-variance) column.
    assert const["flags"] == ["constant"]
    # degenerate histogram: a single bin spanning [v, v].
    assert const["histogram"]["counts"] == [6]
    assert const["histogram"]["bin_edges"] == [5.0, 5.0]


def test_quality_flags_constant_identifier_and_normal() -> None:
    """A constant column flags 'constant'; an all-distinct one flags 'identifier'."""
    df = pd.DataFrame(
        {
            "const": [7, 7, 7, 7, 7],            # one unique value → constant
            "policy_id": ["A1", "B2", "C3", "D4", "E5"],  # all distinct → identifier
            "region": ["N", "N", "S", "E", "W"],  # ordinary categorical → no flag
        }
    )
    prof = profile_dataframe(
        df,
        numeric_cols=["const"],
        categorical_cols=["policy_id", "region"],
        binary_cols=[],
        datetime_cols=[],
    )
    flags = {c["name"]: c["flags"] for c in prof["column_profiles"]}
    assert flags["const"] == ["constant"]
    assert flags["policy_id"] == ["identifier"]
    assert flags["region"] == []


def test_categorical_top_values_and_truncation(toy_df) -> None:
    prof = profile_dataframe(toy_df, top_k=2, **_groups(toy_df))
    region = next(c for c in prof["column_profiles"] if c["name"] == "region")
    assert region["dtype_group"] == "categorical"
    assert region["n_unique"] == 4
    assert len(region["top_values"]) == 2
    assert region["top_values"][0] == {"value": "N", "count": 3, "pct": pytest.approx(50.0)}
    assert region["truncated"] is True
    # the two listed + the "other" bucket must account for every non-null row.
    assert sum(v["count"] for v in region["top_values"]) + region["other_count"] == 6


def test_binary_numeric_profiled_as_frequency(toy_df) -> None:
    prof = profile_dataframe(toy_df, **_groups(toy_df))
    flag = next(c for c in prof["column_profiles"] if c["name"] == "flag")
    # a numeric 0/1 column is shown as a frequency breakdown, not a histogram.
    assert flag["dtype_group"] == "categorical"
    assert flag["top_values"] is not None
    assert {v["value"] for v in flag["top_values"]} == {"0", "1"}


def test_datetime_range(toy_df) -> None:
    prof = profile_dataframe(toy_df, **_groups(toy_df))
    joined = next(c for c in prof["column_profiles"] if c["name"] == "joined")
    assert joined["dtype_group"] == "datetime"
    assert joined["min"].startswith("2020-01-01")
    assert joined["max"].startswith("2022-01-01")


def test_correlation_square_symmetric_and_json_safe(toy_df) -> None:
    prof = profile_dataframe(toy_df, **_groups(toy_df))
    corr = prof["correlation"]
    n = len(corr["columns"])
    assert n >= 2
    assert all(len(row) == n for row in corr["matrix"])
    # diagonal is 1.0 (self-correlation); the constant column's cells are None (undefined).
    for i, name in enumerate(corr["columns"]):
        if name == "const":
            assert corr["matrix"][i][i] is None
        else:
            assert corr["matrix"][i][i] == pytest.approx(1.0)
    # whole payload must survive strict JSON (no NaN/Inf).
    json.dumps(prof, allow_nan=False)


def test_correlation_none_with_one_numeric_col() -> None:
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0], "g": ["a", "b", "a"]})
    prof = profile_dataframe(
        df, numeric_cols=["x"], categorical_cols=["g"], binary_cols=[], datetime_cols=[]
    )
    assert prof["correlation"] is None


def test_correlation_excludes_identifier_columns() -> None:
    """A near-unique (identifier-like) numeric column is dropped from the matrix."""
    n = 200
    df = pd.DataFrame(
        {
            "policy_id": np.arange(n),                 # all-distinct → identifier
            "age": np.random.default_rng(0).integers(20, 60, n),      # ~40 unique
            "premium_band": np.random.default_rng(1).integers(1, 20, n),  # ~19 unique
        }
    )
    prof = profile_dataframe(
        df,
        numeric_cols=["policy_id", "age", "premium_band"],
        categorical_cols=[],
        binary_cols=[],
        datetime_cols=[],
    )
    # policy_id is flagged identifier and must not appear in the correlation.
    pid = next(c for c in prof["column_profiles"] if c["name"] == "policy_id")
    assert pid["flags"] == ["identifier"]
    assert prof["correlation"] is not None
    assert "policy_id" not in prof["correlation"]["columns"]
    assert set(prof["correlation"]["columns"]) == {"age", "premium_band"}


def test_correlation_none_when_only_identifier_numeric_cols() -> None:
    """Two identifier columns leave <2 usable numeric cols → no correlation."""
    df = pd.DataFrame({"id_a": np.arange(150), "id_b": np.arange(150) * 3})
    prof = profile_dataframe(
        df, numeric_cols=["id_a", "id_b"], categorical_cols=[], binary_cols=[],
        datetime_cols=[],
    )
    assert prof["correlation"] is None


def test_large_file_samples_heavy_work() -> None:
    df = pd.DataFrame({"x": np.arange(100), "y": np.arange(100) * 2.0})
    prof = profile_dataframe(
        df, numeric_cols=["x", "y"], categorical_cols=[], binary_cols=[],
        datetime_cols=[], max_rows=10,
    )
    assert prof["sampled"] is True
    assert prof["n_rows_profiled"] == 10
    # per-column missingness still reflects the FULL frame, not the sample.
    x = next(c for c in prof["column_profiles"] if c["name"] == "x")
    assert x["n_missing"] == 0


def test_inspect_profile_flag_attaches_blocks(storage, lapse_csv) -> None:
    info = inspect_file(lapse_csv, storage, target="will_lapse", profile=True)
    assert "column_profiles" in info and "correlation" in info
    assert len(info["column_profiles"]) == len(info["columns"])
    assert info["profile_sampled"] is False
    # one profile per column, every one tagged with a display group.
    groups = {c["dtype_group"] for c in info["column_profiles"]}
    assert groups <= {"numeric", "categorical", "datetime"}


def test_inspect_default_omits_profile(storage, lapse_csv) -> None:
    info = inspect_file(lapse_csv, storage, target="will_lapse")
    # default behaviour is unchanged — no profiling keys leak into the contract.
    assert "column_profiles" not in info
    assert "correlation" not in info
