"""Section 9 — ``train_test_split_cls``.

Splits a loaded dataframe into train/test partitions. Two modes:

* **Random stratified** (default) — preserves class proportions across the split.
* **Temporal** — when ``time_split_col`` is set, the most recent ``test_size``
  fraction becomes the test set, with no shuffling.

The split is the leakage boundary for everything downstream: encoders, scalers,
and SMOTE are fitted on the train partition only.
"""

from __future__ import annotations

import logging
import warnings
from typing import Any

import pandas as pd
from sklearn.model_selection import train_test_split

logger = logging.getLogger(__name__)


def train_test_split_cls(
    df: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split ``df`` into ``(train_df, test_df)`` per ``config``.

    Args:
        df: The loaded, validated dataframe (target already categorical).
        config: Run config; uses ``target``, ``test_size``, ``stratify``,
            ``time_split_col``, and ``random_state``.

    Returns:
        A ``(train_df, test_df)`` tuple. Row indices are reset on both frames.
    """
    target = config["target"]
    test_size = config["test_size"]
    time_split_col = config.get("time_split_col")
    random_state = config.get("random_state", 42)

    if time_split_col is not None:
        # [RISK] temporal leakage — for time-ordered insurance data a random split
        # would let the model "see the future" (train on later policies, test on
        # earlier ones). Sorting by time and holding out the most recent rows is the
        # correct, leakage-free default whenever a time column is available.
        ordered = df.sort_values(time_split_col, ascending=True, kind="stable")
        n_test = max(1, int(round(len(ordered) * test_size)))
        n_test = min(n_test, len(ordered) - 1)  # keep at least one train row
        train_df = ordered.iloc[:-n_test].reset_index(drop=True)
        test_df = ordered.iloc[-n_test:].reset_index(drop=True)
        return train_df, test_df

    stratify_requested = config.get("stratify", True)
    y = df[target]
    stratify = y if stratify_requested else None

    # Edge case: stratification requires ≥2 members per class. If any class is too
    # small, fall back to a non-stratified split rather than crashing.
    if stratify is not None and y.value_counts().min() < 2:
        warnings.warn(
            "a class has fewer than 2 members; falling back to a non-stratified split",
            stacklevel=2,
        )
        logger.warning(
            "Stratified split not possible (a class has <2 members); using non-stratified split"
        )
        stratify = None

    train_df, test_df = train_test_split(
        df,
        test_size=test_size,
        random_state=random_state,
        stratify=stratify,
        shuffle=True,
    )
    return train_df.reset_index(drop=True), test_df.reset_index(drop=True)
