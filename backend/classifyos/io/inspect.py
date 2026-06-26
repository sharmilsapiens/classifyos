"""Section 3 — ``inspect_file``.

Lightweight, read-only profiling of an input dataset *before* a run is configured.
The result feeds the browser's setup screen (column pickers, problem-type
suggestion, class-distribution preview), so the keys returned here are part of the
future API contract and must stay stable.
"""

from __future__ import annotations

import re
import warnings
from typing import Any

import pandas as pd

from .storage import StorageAdapter

# Column names that strongly suggest a date/time, used as one datetime signal.
_DATE_NAME_RE = re.compile(r"(date|time|dob|timestamp|_dt$|^dt_)", re.IGNORECASE)
# Separators that distinguish a real date string ("2019-10-14") from an ID ("POL100").
_DATE_SEP_RE = re.compile(r"[-/:]")


def _read_dataframe(path: str, storage: StorageAdapter) -> pd.DataFrame:
    """Load a dataframe for inspection via the StorageAdapter (never a raw open)."""
    suffix = path.lower().rsplit(".", 1)[-1] if "." in path else ""
    if suffix in ("xlsx", "xls"):
        with storage.open_read(path, binary=True) as fh:
            return pd.read_excel(fh)
    if suffix in ("parquet", "pq"):
        with storage.open_read(path, binary=True) as fh:
            return pd.read_parquet(fh)
    # default: CSV (text)
    with storage.open_read(path) as fh:
        return pd.read_csv(fh)


def _looks_datetime(series: pd.Series) -> bool:
    """Heuristically decide whether ``series`` holds dates.

    True when the dtype is already datetime, or (for object/string columns) the
    name looks date-like or the values carry date separators *and* a sample parses
    cleanly. The separator guard keeps ID columns like ``POL100000`` from being
    misclassified as dates.
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if not pd.api.types.is_object_dtype(series):
        return False

    non_null = series.dropna()
    if non_null.empty:
        return False

    sample = non_null.astype(str).head(50)
    name_match = bool(_DATE_NAME_RE.search(str(series.name)))
    has_sep = sample.str.contains(_DATE_SEP_RE).mean() >= 0.9
    if not (name_match or has_sep):
        return False

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(sample, errors="coerce")
    return parsed.notna().mean() >= 0.9


def inspect_file(
    path: str,
    storage: StorageAdapter,
    target: str | None = None,
    profile: bool = False,
) -> dict[str, Any]:
    """Profile a dataset's structure without committing to a run config.

    Args:
        path: Logical key of the dataset, resolved by ``storage``.
        storage: Storage adapter used for all I/O.
        target: Optional target column; when given, the class distribution and a
            suggested problem type are included.
        profile: When True, also attach per-column exploratory statistics
            (``column_profiles``) and a numeric ``correlation`` matrix for the
            browser's Data Profile view. Default False leaves the result
            byte-identical to the original contract — the extra work runs on the
            frame this function already loaded, so there is never a second read.

    Returns:
        A dict with keys: ``columns``, ``dtypes``, ``numeric_cols``,
        ``categorical_cols``, ``binary_cols``, ``datetime_cols``, ``n_rows``,
        ``n_missing``, ``sample`` (first 5 rows, NaN→None). When ``target`` is
        supplied, also ``class_distribution`` and ``suggested_problem_type``.
        When ``profile`` is True, also ``column_profiles``, ``correlation``,
        ``profile_sampled`` and ``n_rows_profiled``.

    Raises:
        ValueError: If ``target`` is given but not present in the file.
    """
    df = _read_dataframe(path, storage)

    columns = list(df.columns)
    dtypes = {col: str(dtype) for col, dtype in df.dtypes.items()}

    datetime_cols = [col for col in columns if _looks_datetime(df[col])]

    numeric_cols: list[str] = []
    categorical_cols: list[str] = []
    binary_cols: list[str] = []
    for col in columns:
        if col in datetime_cols:
            continue
        series = df[col]
        if series.dropna().nunique() == 2:
            # A column with exactly two distinct non-null values is "binary"
            # regardless of being numeric (e.g. has_agent) or object-typed.
            binary_cols.append(col)
        if pd.api.types.is_numeric_dtype(series):
            numeric_cols.append(col)
        else:
            categorical_cols.append(col)

    n_missing = {col: int(df[col].isna().sum()) for col in columns}

    # NaN→None so the sample is JSON-serialisable for the UI.
    sample = df.head(5).where(pd.notnull(df.head(5)), None).to_dict(orient="records")

    result: dict[str, Any] = {
        "columns": columns,
        "dtypes": dtypes,
        "numeric_cols": numeric_cols,
        "categorical_cols": categorical_cols,
        "binary_cols": binary_cols,
        "datetime_cols": datetime_cols,
        "n_rows": int(len(df)),
        "n_missing": n_missing,
        "sample": sample,
    }

    if target is not None:
        if target not in df.columns:
            raise ValueError(f"target column {target!r} not found in {path!r}")
        counts = df[target].value_counts(dropna=True)
        # Cast keys to native types so the dict is JSON-friendly.
        result["class_distribution"] = {
            (k.item() if hasattr(k, "item") else k): int(v) for k, v in counts.items()
        }
        n_classes = int(counts.shape[0])
        result["suggested_problem_type"] = "binary" if n_classes == 2 else "multiclass"

    if profile:
        # Reuse the frame already loaded above — no second read. Pure display
        # profiling (distributions, value counts, correlation); fits nothing.
        from ..analysis.profile import profile_dataframe

        prof = profile_dataframe(
            df,
            numeric_cols=numeric_cols,
            categorical_cols=categorical_cols,
            binary_cols=binary_cols,
            datetime_cols=datetime_cols,
        )
        result["column_profiles"] = prof["column_profiles"]
        result["correlation"] = prof["correlation"]
        result["profile_sampled"] = prof["sampled"]
        result["n_rows_profiled"] = prof["n_rows_profiled"]

    return result
