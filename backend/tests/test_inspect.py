"""Tests for Section 3 (io/inspect.py) on real sample data."""

from __future__ import annotations

import pandas as pd
import pytest

from classifyos.io.inspect import _read_dataframe, inspect_dataframe, inspect_file


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


# --- inspect_dataframe: the shared profiling core (also feeds the Databricks table-profile sample) --


def test_inspect_dataframe_matches_inspect_file(storage, lapse_csv) -> None:
    """inspect_file just reads the frame then delegates — same result for the same data.

    Guards the behaviour-preserving refactor: the file path (and thus /upload + Postgres) stays
    byte-identical while inspect_dataframe becomes reusable for an in-memory frame.
    """
    via_file = inspect_file(lapse_csv, storage, target="will_lapse", profile=True)
    frame = _read_dataframe(lapse_csv, storage)
    via_frame = inspect_dataframe(frame, target="will_lapse", profile=True, source=lapse_csv)
    assert via_frame == via_file


def test_inspect_dataframe_profiles_in_memory_frame() -> None:
    """Profiling an already-loaded frame yields the full profile blocks (the Databricks-sample path).

    Values are repeated so no column trips the near-unique "identifier" flag — the numeric columns
    keep their distribution + the correlation matrix, exactly as a small CSV upload would.
    """
    # has_agent as strings ("yes"/"no") mirrors the real Databricks path — JSON_ARRAY returns every
    # cell as a string, so a boolean column arrives object-typed → categorical + binary (not numeric).
    df = pd.DataFrame(
        {
            "age": [30, 41, 29, 52, 38, 45] * 20,
            "region": ["north", "south", "east", "west"] * 30,
            "has_agent": ["yes", "no"] * 60,
            "premium": [100.0 + (i % 25) for i in range(120)],
        }
    )
    info = inspect_dataframe(df, target="has_agent", profile=True, source="cat.sch.tbl")

    assert info["n_rows"] == 120
    assert set(info["numeric_cols"]) == {"age", "premium"}
    assert info["categorical_cols"] == ["region", "has_agent"]  # two-value string column groups here
    assert info["binary_cols"] == ["has_agent"]
    assert info["suggested_problem_type"] == "binary"
    # The Data-Profile blocks — the whole point of the Databricks fix — are present.
    assert info["column_profiles"] and len(info["column_profiles"]) == 4
    assert info["correlation"] is not None  # ≥2 non-identifier numeric columns
    assert len(info["sample"]) == 5


def test_inspect_dataframe_missing_target_uses_source_label() -> None:
    """A bad target names the given source label (a catalog.schema.table for the Databricks path)."""
    df = pd.DataFrame({"a": [1, 2, 3]})
    with pytest.raises(ValueError, match="cat.sch.tbl"):
        inspect_dataframe(df, target="missing", source="cat.sch.tbl")
