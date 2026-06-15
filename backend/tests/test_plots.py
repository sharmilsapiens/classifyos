"""Tests for Section 14 (``plot_results`` — confusion / ROC-PR / importance / calibration).

Plots are produced as a side effect of a full :class:`ModelRunner` run (and directly via
``plot_results``). Each test runs its own runner and asserts immediately on the freshly
written PNGs so a later test's run can never overwrite the file under assertion.
"""

from __future__ import annotations

from pathlib import Path

from classifyos.config import build_config
from classifyos.evaluation.plots import (
    PLOT1_KEY,
    PLOT2_KEY,
    PLOT3_KEY,
    PLOT5_KEY,
    plot_results,
)
from classifyos.runner import ModelRunner

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

_MIN_PNG_BYTES = 1000  # a real matplotlib PNG is comfortably larger than this


def _size(output_dir: Path, key: str) -> int:
    return (output_dir / key).stat().st_size


def test_plots_binary_all_written(storage, output_dir) -> None:
    """A binary run writes plot1/2/3/5 as non-trivial PNGs."""
    cfg = build_config(
        "policy_lapse.csv",
        "will_lapse",
        LAPSE_FEATURES,
        algorithms=["LogisticRegression", "RandomForest"],
        class_balance="class_weight",
    )
    ModelRunner(cfg, storage).run()
    for key in (PLOT1_KEY, PLOT2_KEY, PLOT3_KEY, PLOT5_KEY):
        assert storage.exists(key)
        assert _size(output_dir, key) > _MIN_PNG_BYTES


def test_plot_results_returns_keys(storage) -> None:
    """plot_results returns the four logical keys it wrote."""
    cfg = build_config(
        "policy_lapse.csv",
        "will_lapse",
        LAPSE_FEATURES,
        algorithms=["LogisticRegression", "RandomForest"],
        class_balance="class_weight",
    )
    runner = ModelRunner(cfg, storage).run()
    written = plot_results(runner, storage)
    assert set(written) == {PLOT1_KEY, PLOT2_KEY, PLOT3_KEY, PLOT5_KEY}


def test_plot3_guard_no_importance(storage, output_dir) -> None:
    """A model with no feature importances (NaiveBayes) still yields a plot3 placeholder."""
    cfg = build_config(
        "policy_lapse.csv",
        "will_lapse",
        LAPSE_FEATURES,
        algorithms=["NaiveBayes"],
        class_balance="class_weight",
    )
    ModelRunner(cfg, storage).run()
    # plot3 is written (as a labelled placeholder) even when nothing exposes importances.
    assert storage.exists(PLOT3_KEY)
    assert _size(output_dir, PLOT3_KEY) > _MIN_PNG_BYTES


def test_plots_multiclass(storage, output_dir) -> None:
    """Multiclass: ROC (plot2) is written; calibration (plot5) falls back to placeholder."""
    cfg = build_config(
        "risk_tier.csv",
        "risk_tier",
        RISK_FEATURES,
        problem_type="multiclass",
        algorithms=["LogisticRegression", "RandomForest"],
    )
    ModelRunner(cfg, storage).run()
    # plot2 (one-vs-rest ROC) and plot5 (binary-only placeholder) both exist.
    assert storage.exists(PLOT2_KEY)
    assert _size(output_dir, PLOT2_KEY) > _MIN_PNG_BYTES
    assert storage.exists(PLOT5_KEY)  # placeholder, still a valid PNG
    assert _size(output_dir, PLOT5_KEY) > _MIN_PNG_BYTES
