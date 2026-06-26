"""Per-column exploratory data profiling for the upload/inspect screen.

This is a *read-only* profiling helper that runs once on a freshly-uploaded
dataset (before any run is configured), so the browser's "Data Profile" page can
show the analyst what's actually in their file: a distribution histogram and
summary statistics for each numeric column, a value-frequency breakdown for each
categorical/binary column, a date range for datetime columns, a missingness
overview across all columns, and a Pearson correlation matrix over the numeric
columns.

It is deliberately a **pure function of a DataFrame** (no file I/O, no config) so
it is trivially unit-testable and so it can reuse the frame ``inspect_file``
already loaded — there is never a second read. It computes nothing about the
target and fits nothing that feeds a model, so there is no leakage surface here:
profiling runs on the raw uploaded frame and influences only what is *displayed*.

The column-type grouping mirrors ``inspect_file``'s (the caller passes the same
``numeric_cols`` / ``categorical_cols`` / ``binary_cols`` / ``datetime_cols``
lists), with one display refinement: a binary column — even a numeric 0/1 one —
is profiled as a *frequency* breakdown (two bars) rather than a histogram,
because that is the more useful view of a two-value column.

All returned values are plain JSON-friendly Python types; non-finite floats
(e.g. the std of a constant column, an undefined correlation) come back as
``None`` so the payload survives strict JSON encoding.
"""

from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np
import pandas as pd

# How many top categories to list before bucketing the rest into "other".
DEFAULT_TOP_K = 12
# Histogram bin count for numeric columns.
DEFAULT_MAX_BINS = 20
# Above this row count, histograms/correlation are computed on a random sample
# (the cheap stats stay full-data) so re-inspecting a large file stays fast.
DEFAULT_MAX_ROWS = 50_000
# Cap the correlation matrix width so a very wide file can't produce an O(c^2)
# matrix that dwarfs the rest of the payload.
DEFAULT_MAX_CORR_COLS = 30


def _finite_or_none(value: Any) -> float | None:
    """Return ``value`` as a float, or ``None`` if it is missing / non-finite."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _json_scalar(value: Any) -> Any:
    """Coerce a pandas/numpy scalar to a plain, JSON-friendly Python scalar."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    if pd.isna(value):
        return None
    if hasattr(value, "item"):  # numpy scalar
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _numeric_profile(series: pd.Series, max_bins: int) -> dict[str, Any]:
    """Summary stats + a histogram for one numeric column (non-null values only)."""
    clean = pd.to_numeric(series, errors="coerce").dropna()
    count = int(clean.shape[0])

    if count == 0:
        return {"stats": None, "histogram": None}

    quantiles = clean.quantile([0.25, 0.5, 0.75])
    mode = clean.mode()
    stats = {
        "count": count,
        "mean": _finite_or_none(clean.mean()),
        "std": _finite_or_none(clean.std()),
        "min": _finite_or_none(clean.min()),
        "p25": _finite_or_none(quantiles.loc[0.25]),
        "median": _finite_or_none(quantiles.loc[0.5]),
        "p75": _finite_or_none(quantiles.loc[0.75]),
        "max": _finite_or_none(clean.max()),
        # mode() can be empty (all-NaN handled above) or multi-modal — take the first.
        "mode": _finite_or_none(mode.iloc[0]) if not mode.empty else None,
        # skew is NaN with <3 points or a constant column → None.
        "skew": _finite_or_none(clean.skew()),
    }

    # numpy.histogram needs at least one finite value; a constant column yields a
    # single degenerate bin, which we widen so the edges stay distinct.
    lo, hi = float(clean.min()), float(clean.max())
    if lo == hi:
        bin_edges = [lo, hi]
        counts = [count]
    else:
        raw_counts, raw_edges = np.histogram(clean.to_numpy(), bins=max_bins)
        counts = [int(c) for c in raw_counts]
        bin_edges = [_finite_or_none(e) for e in raw_edges]

    return {"stats": stats, "histogram": {"bin_edges": bin_edges, "counts": counts}}


def _categorical_profile(series: pd.Series, top_k: int) -> dict[str, Any]:
    """Top-``top_k`` value frequencies (+ an 'other' bucket) for one column."""
    counts = series.value_counts(dropna=True)
    total = int(counts.sum())
    top = counts.head(top_k)

    top_values = [
        {
            "value": str(_json_scalar(idx)),
            "count": int(cnt),
            "pct": _finite_or_none(cnt / total * 100) if total else None,
        }
        for idx, cnt in top.items()
    ]
    other_count = int(counts.iloc[top_k:].sum()) if counts.shape[0] > top_k else 0

    return {
        "top_values": top_values,
        "other_count": other_count,
        "truncated": counts.shape[0] > top_k,
    }


def _datetime_profile(series: pd.Series) -> dict[str, Any]:
    """Min/max range (ISO strings) for one datetime column."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(series, errors="coerce")
    clean = parsed.dropna()
    if clean.empty:
        return {"min": None, "max": None}
    return {"min": clean.min().isoformat(), "max": clean.max().isoformat()}


def _correlation(
    df: pd.DataFrame, numeric_cols: list[str], max_cols: int
) -> dict[str, Any] | None:
    """Pearson correlation over (up to ``max_cols``) numeric columns.

    Returns ``None`` when fewer than two numeric columns are available. NaN cells
    (e.g. a constant column has no correlation) become ``None``.
    """
    cols = [c for c in numeric_cols if c in df.columns][:max_cols]
    if len(cols) < 2:
        return None

    corr = df[cols].apply(pd.to_numeric, errors="coerce").corr(numeric_only=True)
    matrix = [[_finite_or_none(v) for v in row] for row in corr.to_numpy()]
    return {
        "columns": list(corr.columns),
        "matrix": matrix,
        "truncated": len(cols) < len([c for c in numeric_cols if c in df.columns]),
    }


def profile_dataframe(
    df: pd.DataFrame,
    *,
    numeric_cols: list[str],
    categorical_cols: list[str],
    binary_cols: list[str],
    datetime_cols: list[str],
    max_bins: int = DEFAULT_MAX_BINS,
    top_k: int = DEFAULT_TOP_K,
    max_rows: int = DEFAULT_MAX_ROWS,
    max_corr_cols: int = DEFAULT_MAX_CORR_COLS,
    random_state: int = 42,
) -> dict[str, Any]:
    """Profile every column of ``df`` for the upload-screen data-exploration view.

    Args:
        df: The raw uploaded frame (as loaded by ``inspect_file``).
        numeric_cols/categorical_cols/binary_cols/datetime_cols: the column-type
            groups from ``inspect_file`` (passed in so the grouping never drifts).
        max_bins: histogram bin count for numeric columns.
        top_k: number of top categories listed before an "other" bucket.
        max_rows: above this, histograms + correlation use a random row sample
            (cheap per-column stats still use the full column).
        max_corr_cols: cap on the correlation matrix width.
        random_state: seed for the large-file row sample (deterministic output).

    Returns:
        ``{"column_profiles": [...], "correlation": {...}|None, "sampled": bool,
        "n_rows_profiled": int}``. Each column profile carries ``name``,
        ``dtype_group`` (``numeric``|``categorical``|``datetime``), ``n_missing``,
        ``missing_pct``, ``n_unique``, plus group-specific blocks: numeric →
        ``stats`` + ``histogram``; categorical/binary → ``top_values`` +
        ``other_count`` + ``truncated``; datetime → ``min`` + ``max``.
    """
    n_rows = int(len(df))

    # Heavy work (histograms, correlation) runs on a sample for very large files;
    # missingness and value counts are cheap, so they always use the full frame.
    sampled = n_rows > max_rows
    heavy_df = df.sample(n=max_rows, random_state=random_state) if sampled else df

    binary_set = set(binary_cols)
    datetime_set = set(datetime_cols)
    numeric_set = set(numeric_cols)

    profiles: list[dict[str, Any]] = []
    for col in df.columns:
        series = df[col]
        n_missing = int(series.isna().sum())
        base: dict[str, Any] = {
            "name": col,
            "n_missing": n_missing,
            "missing_pct": _finite_or_none(n_missing / n_rows * 100) if n_rows else None,
            "n_unique": int(series.dropna().nunique()),
        }

        if col in datetime_set:
            base["dtype_group"] = "datetime"
            base.update(_datetime_profile(series))
        elif col in binary_set:
            # A two-value column (numeric 0/1 or object) reads best as frequencies.
            base["dtype_group"] = "categorical"
            base.update(_categorical_profile(series, top_k))
        elif col in numeric_set:
            base["dtype_group"] = "numeric"
            base.update(_numeric_profile(heavy_df[col], max_bins))
        else:
            base["dtype_group"] = "categorical"
            base.update(_categorical_profile(series, top_k))

        profiles.append(base)

    correlation = _correlation(heavy_df, numeric_cols, max_corr_cols)

    return {
        "column_profiles": profiles,
        "correlation": correlation,
        "sampled": sampled,
        "n_rows_profiled": int(len(heavy_df)),
    }
