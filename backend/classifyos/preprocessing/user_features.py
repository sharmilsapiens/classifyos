"""User-defined STRUCTURED feature engineering — ``UserFeatureBuilder``.

An sklearn-style fit/transform builder that materialises the columns a USER asked for
by combining EXISTING columns through a fixed allowlist of operations. It mirrors the
leakage discipline of the Section 7 :class:`~classifyos.preprocessing.features.FeatureBuilder`
and the Section 6 ``Preprocessor``: any statistic a feature needs (quantile bin edges,
the ratio zero-denominator median fill) is computed in :meth:`fit` from the TRAINING rows
only and merely *applied* in :meth:`transform`.

[RISK] NO arbitrary code / formula evaluation. The user NEVER supplies a formula string
that this module evaluates. A spec is ``[column A] + [operation from a fixed allowlist]
+ [column B]`` (or a single-column transform from a fixed allowlist). Only KNOWN
operations are applied to KNOWN columns; ``eval``/``exec`` are never used on any user
input. The allowlists live in :mod:`classifyos.config` (so the config boundary rejects
unknown ops/types up front) and are re-checked here at fit time.

Supported operations (see the allowlists in ``config.py``):

* ``type="numeric"`` — two NUMERIC columns: ``add`` (a+b), ``subtract`` (a-b),
  ``multiply`` (a*b), ``divide`` / ``ratio`` (a/b, with the same near-zero-denominator
  guard the ratio features use, filled per the ``interaction_features.fill_method``).
* ``type="datetime_diff"`` — two DATETIME columns, ``op="subtract"`` → a numeric duration
  ``a - b`` expressed in the spec's ``unit`` (``seconds``/``minutes``/``hours``/``days``;
  default ``days``). Covers the ``duration = end_time - start_time`` use case.
* ``type="single"`` — one column:
    * ``log`` (``log1p``; numeric, requires train min ≥ 0), ``abs`` (numeric),
      ``bin`` (quantile bins, train-only edges, same approach as FeatureBuilder).
    * ``year`` / ``month`` / ``day`` / ``dayofweek`` / ``hour`` — date-part extraction
      from a DATETIME column.

Pipeline position (corrected canonical order): user features are computed from the RAW
post-split frame and their output columns are injected AFTER preprocessing + FeatureBuilder
and BEFORE the interaction step, so they can become interaction candidates and exist
before balancing/training. Reading from the RAW frame (rather than the preprocessed one)
is required so ``datetime_diff`` can see real datetime columns (the Preprocessor scales
numerics and encodes/drops datetime columns) — see plan_tweak.md.

Validation policy: an invalid spec (missing/typed-wrong column, op that does not apply to
the column type, name that collides with an existing column) is logged with a clear,
spec-identifying message and SKIPPED — it never aborts the run; the remaining valid
features are still built. The input frame and the config are never mutated; instances are
picklable via ``joblib``.
"""

from __future__ import annotations

import copy
import logging
import warnings
from typing import Any

import numpy as np
import pandas as pd

from ..config import (
    USER_FEATURE_DATETIME_DIFF_OPS,
    USER_FEATURE_DATETIME_UNITS,
    USER_FEATURE_NUMERIC_OPS,
    USER_FEATURE_SINGLE_DATE_OPS,
    USER_FEATURE_SINGLE_NUMERIC_OPS,
    USER_FEATURE_TYPES,
)

logger = logging.getLogger(__name__)

#: Denominators with magnitude below this are treated as zero (divide/ratio guard) —
#: identical to the Section 7 / 7B ratio guard.
_DENOM_EPS = 1e-9

#: Number of quantile bins for the ``bin`` transform (mirrors FeatureBuilder).
_N_BINS = 5

#: Seconds-per-unit for ``datetime_diff`` duration conversion.
_UNIT_SECONDS = {"seconds": 1.0, "minutes": 60.0, "hours": 3600.0, "days": 86400.0}


def _to_datetime(series: pd.Series) -> pd.Series:
    """Parse ``series`` to datetime (unparseable values → ``NaT``), warnings suppressed."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # silence "Could not infer format" noise
        return pd.to_datetime(series, errors="coerce")


class _SpecError(Exception):
    """Internal: a spec failed validation and should be skipped (with a logged reason)."""


class UserFeatureBuilder:
    """Train-only-fitted, allowlist-bounded user feature engineering.

    Configuration is read from ``config["user_features"]`` (a list of structured specs)
    and ``config["interaction_features"]["fill_method"]`` (reused for the divide/ratio
    zero-denominator fill). When the list is empty the builder is a no-op: :meth:`fit`
    creates nothing and :meth:`transform` returns the input frame unchanged, so a run is
    identical to one without the key.

    Attributes:
        created_features_: Names of the columns added by :meth:`transform`, in output
            order. Empty until :meth:`fit` runs (or when there are no valid specs).
        skipped_specs_: ``[(name, reason), …]`` for every spec rejected at fit time
            (kept for transparency / debugging; the run is never aborted).

    [RISK] leakage guard — like the Preprocessor and FeatureBuilder, the fit/transform
    separation IS the leakage guard: every train-only statistic (bin edges, the ratio
    median fill) is learned from the rows passed to fit(). Never fit() on test rows.
    [RISK] no-eval safety — only the fixed allowlist operations are applied; no user
    string is ever evaluated as code.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Store an independent deep copy of ``config`` (never mutated)."""
        self.config = copy.deepcopy(config)
        self.specs_cfg_ = list(self.config.get("user_features", []) or [])
        interactions = self.config.get("interaction_features", {}) or {}
        self.fill_method_ = interactions.get("fill_method", "zero")
        self.created_features_: list[str] = []
        self.skipped_specs_: list[tuple[str, str]] = []
        self.fitted_ = False

    # ------------------------------------------------------------------ fit --

    def fit(self, train_df: pd.DataFrame, target: str) -> "UserFeatureBuilder":
        """Validate the specs against ``train_df`` and learn any train-only statistics.

        Args:
            train_df: The TRAIN partition (typically the RAW post-split frame — user
                features reference original columns by name).
            target: Name of the target column. A user feature may not derive from the
                target (that would be leakage); such a spec is skipped.

        Returns:
            ``self`` (fitted), for chaining.
        """
        self.target_ = target
        self.created_features_ = []
        self.skipped_specs_ = []
        #: Prepared, validated specs (independent copies) applied in transform.
        self.plan_: list[dict[str, Any]] = []
        #: {feature_name: train-only median} for divide/ratio with fill_method="median".
        self.ratio_fill_medians_: dict[str, float] = {}
        #: {feature_name: bin edges ndarray} for the "bin" transform.
        self.bin_edges_: dict[str, np.ndarray] = {}

        existing = set(train_df.columns)
        for i, raw_spec in enumerate(self.specs_cfg_):
            spec = copy.deepcopy(raw_spec)
            name = spec.get("name") if isinstance(spec, dict) else None
            label = name if isinstance(name, str) and name.strip() else f"user_features[{i}]"
            try:
                self._fit_one(spec, train_df, target, existing)
            except _SpecError as exc:
                # [RISK] no-crash — a bad spec is logged and skipped, never aborting the run.
                logger.warning("UserFeatureBuilder: skipping %r — %s", label, exc)
                self.skipped_specs_.append((str(label), str(exc)))
                continue
            self.plan_.append(spec)
            self.created_features_.append(spec["name"])
            existing.add(spec["name"])  # a later spec may not reuse this new name either

        self.fitted_ = True
        return self

    def _fit_one(
        self,
        spec: dict[str, Any],
        train_df: pd.DataFrame,
        target: str,
        existing: set[str],
    ) -> None:
        """Validate one spec and learn its train-only statistics, or raise ``_SpecError``."""
        if not isinstance(spec, dict):
            raise _SpecError(f"spec must be a dict, got {spec!r}")

        name = spec.get("name")
        if not isinstance(name, str) or not name.strip():
            raise _SpecError("missing/empty 'name'")
        if name in existing:
            # [RISK] never overwrite an existing column.
            raise _SpecError(f"name {name!r} collides with an existing column")

        ftype = spec.get("type")
        if ftype not in USER_FEATURE_TYPES:
            raise _SpecError(f"unknown type {ftype!r}")

        op = spec.get("op")
        col_a = spec.get("col_a")
        col_b = spec.get("col_b")

        # Column references must exist and must not be the target.
        for col, role in [(col_a, "col_a")] + (
            [(col_b, "col_b")] if ftype in ("numeric", "datetime_diff") else []
        ):
            if not isinstance(col, str) or col not in train_df.columns:
                raise _SpecError(f"{role}={col!r} is not a column in the data")
            if col == target:
                raise _SpecError(f"{role}={col!r} is the target (cannot derive a feature from it)")

        if ftype == "numeric":
            if op not in USER_FEATURE_NUMERIC_OPS:
                raise _SpecError(f"op {op!r} is not a numeric op")
            for col, role in [(col_a, "col_a"), (col_b, "col_b")]:
                if not pd.api.types.is_numeric_dtype(train_df[col]):
                    raise _SpecError(f"{role}={col!r} is not numeric (op {op!r} needs numbers)")
            if op in ("divide", "ratio") and self.fill_method_ == "median":
                series = self._numeric_series(spec, train_df)
                self.ratio_fill_medians_[name] = float(series.median())

        elif ftype == "datetime_diff":
            if op not in USER_FEATURE_DATETIME_DIFF_OPS:
                raise _SpecError(f"op {op!r} is not a datetime_diff op")
            for col, role in [(col_a, "col_a"), (col_b, "col_b")]:
                parsed = _to_datetime(train_df[col])
                if parsed.notna().sum() == 0:
                    raise _SpecError(f"{role}={col!r} does not parse as datetime")
            unit = spec.get("unit", "days")
            if unit not in USER_FEATURE_DATETIME_UNITS:
                raise _SpecError(f"unknown unit {unit!r}")
            spec["unit"] = unit  # normalise default

        else:  # single
            if op in USER_FEATURE_SINGLE_NUMERIC_OPS:
                if not pd.api.types.is_numeric_dtype(train_df[col_a]):
                    raise _SpecError(f"col_a={col_a!r} is not numeric (op {op!r} needs numbers)")
                if op == "log":
                    col_min = float(pd.to_numeric(train_df[col_a], errors="coerce").min())
                    if not np.isfinite(col_min) or col_min < 0:
                        raise _SpecError(
                            f"log requires non-negative values; col_a={col_a!r} train min is {col_min}"
                        )
                elif op == "bin":
                    edges = self._fit_bin_edges(train_df[col_a])
                    if edges is None:
                        raise _SpecError(
                            f"col_a={col_a!r} has too few distinct values to bin"
                        )
                    self.bin_edges_[name] = edges
            elif op in USER_FEATURE_SINGLE_DATE_OPS:
                parsed = _to_datetime(train_df[col_a])
                if parsed.notna().sum() == 0:
                    raise _SpecError(
                        f"col_a={col_a!r} does not parse as datetime (op {op!r})"
                    )
            else:
                raise _SpecError(f"op {op!r} is not a single-column op")

    @staticmethod
    def _fit_bin_edges(series: pd.Series) -> np.ndarray | None:
        """Compute train-only quantile bin edges (outer edges opened to ±inf), or None."""
        s = pd.to_numeric(series, errors="coerce").dropna()
        if s.nunique() < _N_BINS:
            return None
        _, edges = pd.qcut(s, _N_BINS, retbins=True, labels=False, duplicates="drop")
        if len(edges) < 3:  # collapsed to a single bin
            return None
        edges = edges.astype(float).copy()
        edges[0], edges[-1] = -np.inf, np.inf
        return edges

    # ------------------------------------------------------------ transform --

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fitted plan to ``df`` (train or test) — no refitting.

        Args:
            df: Any frame containing the source columns referenced by the valid specs.
                Never mutated.

        Returns:
            A new DataFrame: the original columns plus the user-feature columns in
            :attr:`created_features_` order. User-feature outputs are NaN-free (numeric
            outputs fill residual NaN with ``0.0``; coded outputs — ``bin`` and date
            parts — use ``-1``) so they are safe to feed straight into balancing/training.

        Raises:
            RuntimeError: If called before :meth:`fit`.
        """
        if not self.fitted_:
            raise RuntimeError("UserFeatureBuilder.transform() called before fit()")
        if not self.plan_:
            return df.copy()

        out = df.copy()
        new_cols: dict[str, pd.Series] = {}
        for spec in self.plan_:
            name = spec["name"]
            # Source columns are validated at fit; stay defensive if a frame lacks one.
            try:
                new_cols[name] = self._compute(spec, df)
            except Exception:  # noqa: BLE001 — a single feature must not abort transform
                logger.exception("UserFeatureBuilder: failed to compute %r at transform", name)

        if new_cols:
            ordered = {n: new_cols[n] for n in self.created_features_ if n in new_cols}
            out = pd.concat([out, pd.DataFrame(ordered, index=df.index)], axis=1)
        return out

    def _compute(self, spec: dict[str, Any], df: pd.DataFrame) -> pd.Series:
        """Compute one user-feature column for ``df`` from a validated spec."""
        ftype, op, name = spec["type"], spec["op"], spec["name"]
        if ftype == "numeric":
            series = self._numeric_series(spec, df)
            if op in ("divide", "ratio"):
                series = self._apply_fill(name, series)
            else:
                series = series.replace([np.inf, -np.inf], np.nan).fillna(0.0)
            return series

        if ftype == "datetime_diff":
            a = _to_datetime(df[spec["col_a"]])
            b = _to_datetime(df[spec["col_b"]])
            seconds = (a - b).dt.total_seconds()
            duration = seconds / _UNIT_SECONDS[spec.get("unit", "days")]
            return duration.fillna(0.0)

        # single-column transform
        if op in USER_FEATURE_SINGLE_NUMERIC_OPS:
            col = pd.to_numeric(df[spec["col_a"]], errors="coerce")
            if op == "log":
                # train min ≥ 0 (validated); clip any out-of-train-range negatives in
                # test to 0 so log1p never produces NaN/complex values.
                return np.log1p(col.clip(lower=0.0)).fillna(0.0)
            if op == "abs":
                return col.abs().fillna(0.0)
            # bin
            edges = self.bin_edges_[name]
            codes = pd.cut(col.astype(float), bins=edges, labels=False, include_lowest=True)
            return pd.Series(codes, index=df.index).fillna(-1).astype(int)

        # date-part extraction (year/month/day/dayofweek/hour)
        parsed = _to_datetime(df[spec["col_a"]])
        part = getattr(parsed.dt, op)
        return pd.Series(part, index=df.index).fillna(-1).astype(int)

    @staticmethod
    def _numeric_series(spec: dict[str, Any], df: pd.DataFrame) -> pd.Series:
        """Compute the raw two-column numeric op (divide/ratio leave NaN at the guard)."""
        a = df[spec["col_a"]].astype(float)
        b = df[spec["col_b"]].astype(float)
        op = spec["op"]
        if op == "add":
            return a + b
        if op == "subtract":
            return a - b
        if op == "multiply":
            return a * b
        # divide / ratio — near-zero denominator → NaN (filled by the caller)
        safe = b.where(b.abs() >= _DENOM_EPS, np.nan)
        return (a / safe).replace([np.inf, -np.inf], np.nan)

    def _apply_fill(self, name: str, series: pd.Series) -> pd.Series:
        """Apply the configured divide/ratio zero-denominator fill (mirrors Section 7B)."""
        if self.fill_method_ == "nan":
            return series
        if self.fill_method_ == "median":
            return series.fillna(self.ratio_fill_medians_.get(name, 0.0))
        return series.fillna(0.0)  # "zero" (default)

    # -------------------------------------------------------- fit_transform --

    def fit_transform(self, train_df: pd.DataFrame, target: str) -> pd.DataFrame:
        """Fit on ``train_df`` then transform and return it."""
        return self.fit(train_df, target).transform(train_df)
