"""Tests for Section 3 (io/inspect.py) on real sample data."""

from __future__ import annotations

import pytest

from classifyos.io.inspect import inspect_file


def test_inspect_policy_lapse_structure(storage, lapse_csv) -> None:
    info = inspect_file(lapse_csv, storage, target="will_lapse")

    assert "occupation" in info["categorical_cols"]
    assert "has_agent" in info["binary_cols"]
    assert "policy_start_date" in info["datetime_cols"]

    # target supplied → distribution + suggestion present
    assert len(info["class_distribution"]) == 2
    assert info["suggested_problem_type"] == "binary"

    # contract keys present and well-formed
    for key in (
        "columns",
        "dtypes",
        "numeric_cols",
        "categorical_cols",
        "binary_cols",
        "datetime_cols",
        "n_rows",
        "n_missing",
        "sample",
    ):
        assert key in info
    assert info["n_rows"] == 3000
    assert len(info["sample"]) == 5
    # missing values were injected into occupation
    assert info["n_missing"]["occupation"] > 0


def test_inspect_sample_nan_to_none(storage, lapse_csv) -> None:
    info = inspect_file(lapse_csv, storage)
    # every sample value is JSON-friendly (no float NaN)
    for row in info["sample"]:
        for value in row.values():
            if isinstance(value, float):
                assert value == value  # NaN != NaN; None would not be a float


def test_inspect_risk_tier_multiclass(storage, risk_csv) -> None:
    info = inspect_file(risk_csv, storage, target="risk_tier")
    assert info["suggested_problem_type"] == "multiclass"
    assert len(info["class_distribution"]) == 3


def test_inspect_missing_target_raises(storage, lapse_csv) -> None:
    with pytest.raises(ValueError, match="not found"):
        inspect_file(lapse_csv, storage, target="does_not_exist")
