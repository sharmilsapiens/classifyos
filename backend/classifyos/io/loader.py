"""Section 4 — ``data_loader``.

Loads the configured dataset into a validated :class:`pandas.DataFrame`, applying
the structural guarantees the rest of the pipeline depends on (target present and
categorical with ≥2 classes, all features present, optional time column parseable).
All I/O is routed through the StorageAdapter.
"""

from __future__ import annotations

import logging
import warnings
from typing import Any

import pandas as pd

from .storage import StorageAdapter

logger = logging.getLogger(__name__)


def _read_by_suffix(path: str, storage: StorageAdapter) -> pd.DataFrame:
    """Dispatch to the right pandas reader based on the file suffix."""
    suffix = path.lower().rsplit(".", 1)[-1] if "." in path else ""
    if suffix in ("xlsx", "xls"):
        with storage.open_read(path, binary=True) as fh:
            return pd.read_excel(fh)
    if suffix in ("parquet", "pq"):
        with storage.open_read(path, binary=True) as fh:
            return pd.read_parquet(fh)
    if suffix == "csv":
        with storage.open_read(path) as fh:
            return pd.read_csv(fh)
    raise ValueError(
        f"unsupported file type {suffix!r} for {path!r}; expected csv, xlsx, or parquet"
    )


def data_loader(config: dict[str, Any], storage: StorageAdapter) -> pd.DataFrame:
    """Load and validate the dataset described by ``config``.

    Args:
        config: A run config (see :func:`classifyos.config.build_config`). Uses
            ``input_file``, ``target``, ``feature_cols``, and optionally
            ``time_split_col``.
        storage: Storage adapter used for all I/O.

    Returns:
        The loaded dataframe with the target coerced to string (categorical) dtype
        and target-NaN rows dropped.

    Raises:
        FileNotFoundError: If ``input_file`` does not exist in storage.
        ValueError: If the target or any feature column is missing, the target has
            fewer than two classes, or ``time_split_col`` cannot be parsed as dates.
    """
    path = config["input_file"]
    target = config["target"]
    feature_cols = config["feature_cols"]
    time_split_col = config.get("time_split_col")

    if not storage.exists(path):
        raise FileNotFoundError(f"input_file not found in storage: {path!r}")

    df = _read_by_suffix(path, storage)

    if target not in df.columns:
        raise ValueError(f"target column {target!r} not found in {path!r}")

    missing_features = [col for col in feature_cols if col not in df.columns]
    if missing_features:
        raise ValueError(
            f"feature columns missing from {path!r}: {missing_features}"
        )

    # [RISK] target NaN rows — rows with no label cannot train or evaluate. Drop
    # them up front (never impute a label) and log how many were removed so the
    # discrepancy between file rows and modelled rows is auditable.
    n_target_nan = int(df[target].isna().sum())
    if n_target_nan:
        warnings.warn(
            f"dropping {n_target_nan} row(s) with missing target {target!r}",
            stacklevel=2,
        )
        logger.warning("Dropped %d row(s) with missing target %r", n_target_nan, target)
        df = df[df[target].notna()].reset_index(drop=True)

    n_classes = df[target].nunique(dropna=True)
    if n_classes < 2:
        raise ValueError(
            f"target {target!r} has {n_classes} class(es); at least 2 are required"
        )

    # Coerce the target to a categorical/string dtype so it is never treated as a
    # continuous float by downstream sklearn estimators.
    df[target] = df[target].astype(str)

    if time_split_col is not None:
        if time_split_col not in df.columns:
            raise ValueError(
                f"time_split_col {time_split_col!r} not found in {path!r}"
            )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            parsed = pd.to_datetime(df[time_split_col], errors="coerce")
        if parsed.notna().sum() == 0:
            raise ValueError(
                f"time_split_col {time_split_col!r} could not be parsed as dates"
            )
        df[time_split_col] = parsed

    return df
