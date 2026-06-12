"""Section 7 — ``FeatureBuilder`` (polynomial, ratio, and binning features).

An sklearn-style fit/transform feature engineer that mirrors the Phase 3
:class:`~classifyos.preprocessing.preprocess.Preprocessor` leakage discipline: every
statistic that drives or selects a derived feature — the polynomial-column ranking,
the ratio denominator, and the quantile bin edges — is computed in :meth:`fit` from
the TRAINING data only and merely *applied* in :meth:`transform`.

Pipeline position (corrected canonical order): ``split → preprocess → build_features
→ interactions → balance → train``. ``FeatureBuilder`` therefore receives the
*preprocessed* frame, in which every feature column is already numeric (scaled
numerics, one-hot 0/1 indicators, ordinal codes, target/frequency means) and the
target is appended last, untouched.

Capabilities (each individually toggleable via the ``feature_engineering`` config
sub-dict — keys ``enabled``, ``polynomial``, ``ratios``, ``binning``,
``max_poly_features``):

* **Polynomial (degree 2)** — squared companion (`{col}_sq`) for the top
  ``max_poly_features`` numeric columns ranked by |correlation with target| on TRAIN.
  Default OFF: squared terms are usually redundant with tree models and risk a column
  explosion.
* **Ratio features** — each numeric column divided by the single numeric column with
  the largest absolute TRAIN median (`{num}_div_{denom}`). A near-zero denominator is
  guarded (see :data:`_DENOM_EPS`).
* **Binning** — a 5-bin quantile companion (`{col}_bin`, ordinal ints) for numeric
  columns whose |TRAIN skew| exceeds :data:`_SKEW_THRESHOLD`. Bin edges are computed on
  TRAIN only; the original column is kept.

High-cardinality / frequency encoding is **not** duplicated here — Phase 3's
:class:`Preprocessor` already owns categorical and high-cardinality encoding. (The
scope listed frequency encoding in both Section 6 and Section 7; it is consolidated in
the Preprocessor to avoid double-encoding — see plan_tweak.md.)

The input frame and the config are never mutated. Instances are picklable via
``joblib`` so a fitted builder can be persisted and reused alongside the Preprocessor.
"""

from __future__ import annotations

import copy
import logging
import warnings
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

#: |skew| above which a numeric column gets a quantile-binned companion.
_SKEW_THRESHOLD = 1.5

#: Number of quantile bins for skewed columns (fewer if edges collapse on ties).
_N_BINS = 5

#: Denominators with magnitude below this are treated as zero (ratio → NaN → 0.0).
_DENOM_EPS = 1e-9


class FeatureBuilder:
    """Train-only-fitted derived-feature engineering (Section 7).

    Configuration is read from ``config["feature_engineering"]``. When that sub-dict
    is absent the builder is a no-op passthrough. When ``enabled`` is ``False`` the
    builder fits nothing and :meth:`transform` returns the input frame unchanged.

    Attributes:
        created_features_: Names of the columns added by :meth:`transform`, in output
            order. Empty until :meth:`fit` runs (or when the builder is disabled).

    [RISK] leakage guard — like the Preprocessor, the fit/transform separation IS the
    leakage guard: the polynomial ranking, ratio denominator, and bin edges all come
    from the training rows passed to fit(). Never fit() on data containing test rows.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Store an independent deep copy of ``config`` (never mutated)."""
        self.config = copy.deepcopy(config)
        fe = self.config.get("feature_engineering", {}) or {}
        self.enabled_ = bool(fe.get("enabled", True))
        self.do_polynomial_ = bool(fe.get("polynomial", False))
        self.do_ratios_ = bool(fe.get("ratios", True))
        self.do_binning_ = bool(fe.get("binning", True))
        self.max_poly_features_ = int(fe.get("max_poly_features", 8))
        self.created_features_: list[str] = []
        self.fitted_ = False

    # ------------------------------------------------------------------ fit --

    def fit(self, train_df: pd.DataFrame, target: str) -> "FeatureBuilder":
        """Learn the derived-feature plan from ``train_df`` ONLY.

        Args:
            train_df: The TRAIN partition (already preprocessed — all-numeric
                features plus the target column).
            target: Name of the target column. Excluded from feature engineering;
                used only to rank polynomial candidates by correlation.

        Returns:
            ``self`` (fitted), for chaining.
        """
        self.target_ = target
        self.poly_cols_: list[str] = []
        self.ratio_numerators_: list[str] = []
        self.ratio_denominator_: str | None = None
        self.bin_edges_: dict[str, np.ndarray] = {}
        self.created_features_ = []

        if not self.enabled_:
            self.fitted_ = True
            return self

        numeric_cols = [
            c
            for c in train_df.columns
            if c != target and pd.api.types.is_numeric_dtype(train_df[c])
        ]
        self.numeric_cols_ = numeric_cols

        # -- polynomial: rank by |corr with target|, cap at max_poly_features -----
        if self.do_polynomial_ and numeric_cols:
            # [RISK] cap — without the max_poly_features ceiling, degree-2 expansion
            # over many numeric columns explodes width and multicollinearity. Rank by
            # absolute train correlation with the (label-encoded) target and keep only
            # the strongest few.
            corr = self._abs_target_corr(train_df, numeric_cols, target)
            ranked = sorted(numeric_cols, key=lambda c: corr.get(c, 0.0), reverse=True)
            self.poly_cols_ = ranked[: self.max_poly_features_]
            self.created_features_.extend(f"{c}_sq" for c in self.poly_cols_)

        # -- ratios: denominator = numeric col with largest |train median| --------
        if self.do_ratios_ and len(numeric_cols) >= 2:
            medians = {c: float(train_df[c].median()) for c in numeric_cols}
            # [RISK] after standard scaling most medians sit near 0, so the
            # "largest-median" denominator is weakly determined and frequently small
            # (triggering the zero-guard). Documented in plan_tweak.md; the per-row
            # guard keeps it safe, never producing inf.
            self.ratio_denominator_ = max(medians, key=lambda c: abs(medians[c]))
            self.ratio_numerators_ = [
                c for c in numeric_cols if c != self.ratio_denominator_
            ]
            self.created_features_.extend(
                f"{num}_div_{self.ratio_denominator_}" for num in self.ratio_numerators_
            )

        # -- binning: quantile bins for skewed numerics (train edges) -------------
        if self.do_binning_:
            for col in numeric_cols:
                series = train_df[col].dropna()
                if series.nunique() < _N_BINS:
                    continue  # too few distinct values to bin meaningfully
                skew = float(series.skew())
                if not np.isfinite(skew) or abs(skew) <= _SKEW_THRESHOLD:
                    continue
                _, edges = pd.qcut(
                    series, _N_BINS, retbins=True, labels=False, duplicates="drop"
                )
                if len(edges) < 3:  # collapsed to a single bin → nothing to bin
                    continue
                # Open the outer edges so test values beyond the train range clip
                # into the lowest/highest bin rather than becoming NaN.
                edges = edges.astype(float).copy()
                edges[0], edges[-1] = -np.inf, np.inf
                self.bin_edges_[col] = edges
                self.created_features_.append(f"{col}_bin")

        self.fitted_ = True
        return self

    # ------------------------------------------------------------ transform --

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fitted feature plan to ``df`` (train or test) — no refitting.

        Args:
            df: Any frame containing the columns seen at fit time. Never mutated.

        Returns:
            A new DataFrame: the original columns (unchanged, target included) plus
            the engineered companions in :attr:`created_features_` order.

        Raises:
            RuntimeError: If called before :meth:`fit`.
        """
        if not self.fitted_:
            raise RuntimeError("FeatureBuilder.transform() called before fit()")
        if not self.enabled_:
            return df.copy()

        out = df.copy()
        new_cols: dict[str, pd.Series] = {}

        for col in self.poly_cols_:
            if col in df.columns:
                new_cols[f"{col}_sq"] = df[col].astype(float) ** 2

        if self.ratio_denominator_ is not None and self.ratio_denominator_ in df.columns:
            denom = df[self.ratio_denominator_].astype(float)
            safe_denom = denom.where(denom.abs() >= _DENOM_EPS, np.nan)
            for num in self.ratio_numerators_:
                if num not in df.columns:
                    continue
                ratio = df[num].astype(float) / safe_denom
                # Guard: zero/near-zero denominator → NaN → 0.0 (no inf). Mirrors the
                # Section 7B "zero" fill rule.
                ratio = ratio.replace([np.inf, -np.inf], np.nan).fillna(0.0)
                new_cols[f"{num}_div_{self.ratio_denominator_}"] = ratio

        for col, edges in self.bin_edges_.items():
            if col not in df.columns:
                continue
            codes = pd.cut(
                df[col].astype(float), bins=edges, labels=False, include_lowest=True
            )
            # No NaN expected (outer edges are ±inf), but stay defensive.
            new_cols[f"{col}_bin"] = pd.Series(codes, index=df.index).fillna(-1).astype(int)

        if new_cols:
            # Preserve created_features_ order; index aligns with the input frame.
            ordered = {name: new_cols[name] for name in self.created_features_ if name in new_cols}
            out = pd.concat([out, pd.DataFrame(ordered, index=df.index)], axis=1)
        return out

    # -------------------------------------------------------- fit_transform --

    def fit_transform(self, train_df: pd.DataFrame, target: str) -> pd.DataFrame:
        """Fit on ``train_df`` then transform and return it."""
        return self.fit(train_df, target).transform(train_df)

    # -------------------------------------------------------------- helpers --

    @staticmethod
    def _abs_target_corr(
        df: pd.DataFrame, cols: list[str], target: str
    ) -> dict[str, float]:
        """Absolute Pearson correlation of each column with the label-encoded target.

        The target is factorized to integer codes (binary 0/1 or multiclass 0..k-1);
        a constant column or undefined correlation yields 0.0 so it ranks lowest.
        """
        if target not in df.columns:
            return {c: 0.0 for c in cols}
        y = pd.Series(pd.factorize(df[target].astype(str))[0], index=df.index).astype(float)
        out: dict[str, float] = {}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # constant column → undefined corr → NaN → 0
            for c in cols:
                r = df[c].astype(float).corr(y)
                out[c] = abs(float(r)) if pd.notna(r) else 0.0
        return out
