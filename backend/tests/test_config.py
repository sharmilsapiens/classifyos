"""Tests for Sections 1–2 (config.py)."""

from __future__ import annotations

import copy

import pytest

from classifyos.config import DEFAULT_CONFIG, build_config


def test_build_config_happy_path() -> None:
    cfg = build_config(
        input_file="policy_lapse.csv",
        target="will_lapse",
        feature_cols=["age", "annual_premium"],
        problem_type="binary",
        test_size=0.25,
    )
    assert cfg["input_file"] == "policy_lapse.csv"
    assert cfg["target"] == "will_lapse"
    assert cfg["feature_cols"] == ["age", "annual_premium"]
    assert cfg["problem_type"] == "binary"
    assert cfg["test_size"] == 0.25
    # untouched defaults carry through
    assert cfg["random_state"] == 42
    assert cfg["class_balance"] == "smote"
    assert cfg["interaction_features"]["enabled"] is True


def test_build_config_empty_target_raises() -> None:
    with pytest.raises(ValueError, match="target"):
        build_config("f.csv", "  ", ["age"])


def test_build_config_empty_feature_cols_raises() -> None:
    with pytest.raises(ValueError, match="feature_cols"):
        build_config("f.csv", "will_lapse", [])


def test_build_config_target_in_features_raises() -> None:
    with pytest.raises(ValueError, match="must not also appear"):
        build_config("f.csv", "will_lapse", ["age", "will_lapse"])


def test_build_config_bad_problem_type_raises() -> None:
    with pytest.raises(ValueError, match="problem_type"):
        build_config("f.csv", "will_lapse", ["age"], problem_type="regression")


def test_build_config_bad_test_size_raises() -> None:
    with pytest.raises(ValueError, match="test_size"):
        build_config("f.csv", "will_lapse", ["age"], test_size=0.9)
    with pytest.raises(ValueError, match="test_size"):
        build_config("f.csv", "will_lapse", ["age"], test_size=0.0)


def test_build_config_unknown_key_raises() -> None:
    with pytest.raises(ValueError, match="unknown config key"):
        build_config("f.csv", "will_lapse", ["age"], not_a_key=1)


def test_default_config_not_mutated() -> None:
    snapshot = copy.deepcopy(DEFAULT_CONFIG)
    cfg = build_config("f.csv", "will_lapse", ["age"], scaling_method="robust")
    # mutate the returned config's nested structures
    cfg["feature_cols"].append("extra")
    cfg["interaction_features"]["max_auto_pairs"] = 999
    assert DEFAULT_CONFIG == snapshot
    assert DEFAULT_CONFIG["feature_cols"] == []
    assert DEFAULT_CONFIG["interaction_features"]["max_auto_pairs"] == 10
