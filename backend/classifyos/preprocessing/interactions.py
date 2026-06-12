"""Section 7B — ``InteractionFeatureBuilder`` (pairwise interaction features).

An sklearn-style fit/transform builder for second-order interaction features. It
follows the same leakage discipline as the Phase 3 Preprocessor and the Section 7
FeatureBuilder: the auto-discovered pair list and the chosen operation per pair are
decided in :meth:`fit` on the TRAINING data only, then *fixed* — :meth:`transform`
never re-discovers (re-discovering on test data would leak the test target into
feature selection).

Pipeline position: ``split → preprocess → build_features → interactions → balance →
train``. The input frame is therefore already preprocessed (all-numeric features plus
the untouched target appended last).

Operations and the contract-level naming convention (see CLAUDE.md):

* ``multiply`` → ``col_a_x_col_b``  (``a * b``)
* ``ratio``    → ``col_a_div_col_b`` (``a / b``)
* ``diff``     → ``col_a_minus_col_b`` (``a - b``)

Config (``config["interaction_features"]``): ``enabled``, ``interaction_pairs``
(map ``"col_a+col_b" -> "multiply"|"ratio"|"diff"|"auto"|"all"``),
``default_interactions``, ``drop_original_if_interacted``, ``max_auto_pairs``,
``fill_method`` (``"zero"``|``"median"``|``"nan"`` — the ratio zero-denominator fill).

Neither the input frame nor the config is ever mutated.
"""

from __future__ import annotations

import copy
import itertools
import logging
import warnings
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless safety: set the non-interactive backend before pyplot

import matplotlib.pyplot as plt  # noqa: E402  (must follow matplotlib.use)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.feature_selection import mutual_info_classif  # noqa: E402

from ..io.storage import StorageAdapter  # noqa: E402

logger = logging.getLogger(__name__)

#: Logical output key for the interaction-summary figure (future output contract).
PLOT_PNG_KEY = "plot6_interaction_summary.png"

#: Denominators with magnitude below this are treated as zero (ratio guard).
_DENOM_EPS = 1e-9

#: Candidate numeric columns are capped to this many (most target-correlated) before
#: pairing, to bound the O(n²) auto-discovery pair count.
_AUTO_POOL_CAP = 15

#: Supported single operations and the op a pair-key resolves to.
_SINGLE_OPS = ("multiply", "ratio", "diff")

# Naming templates, keyed by op (contract-level — do not change silently).
_OP_NAMES = {
    "multiply": "{a}_x_{b}",
    "ratio": "{a}_div_{b}",
    "diff": "{a}_minus_{b}",
}


def _interaction_series(a: pd.Series, b: pd.Series, op: str) -> pd.Series:
    """Compute one interaction series for ``op`` (ratio leaves NaN at the guard).

    The ratio guard maps a near-zero denominator to NaN (and drops any residual
    ±inf) so the caller can apply its configured fill rule; multiply/diff are exact.
    """
    a = a.astype(float)
    b = b.astype(float)
    if op == "multiply":
        return a * b
    if op == "diff":
        return a - b
    if op == "ratio":
        safe = b.where(b.abs() >= _DENOM_EPS, np.nan)
        return (a / safe).replace([np.inf, -np.inf], np.nan)
    raise ValueError(f"unknown interaction op {op!r}")


class InteractionFeatureBuilder:
    """Train-only-fitted pairwise interaction features (Section 7B).

    Attributes:
        interaction_cols_: Names of the interaction columns produced by
            :meth:`transform`, in output order.
        pairs_used_: Map of ``"col_a+col_b" -> [ops]`` actually applied (explicit and
            auto-discovered), fixed at fit time.

    [RISK] re-discovery on test = leakage — the pair list and per-pair ops are frozen
    in fit(); transform() only applies them. Re-running MI discovery on test rows
    would let the test target influence feature selection.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Store an independent deep copy of ``config`` (never mutated)."""
        self.config = copy.deepcopy(config)
        fe = self.config.get("interaction_features", {}) or {}
        self.enabled_ = bool(fe.get("enabled", True))
        self.interaction_pairs_cfg_ = dict(fe.get("interaction_pairs", {}) or {})
        self.default_interactions_ = list(fe.get("default_interactions", ["multiply"]))
        self.drop_original_ = bool(fe.get("drop_original_if_interacted", False))
        self.max_auto_pairs_ = int(fe.get("max_auto_pairs", 10))
        # Ops materialized for auto-discovered / explicit-"auto" pairs. MI scoring
        # always uses the multiplicative term (the canonical 2nd-order interaction);
        # these are the operation(s) actually emitted for kept pairs.
        self.auto_ops_ = [op for op in self.default_interactions_ if op in _SINGLE_OPS] or ["multiply"]
        self.fill_method_ = fe.get("fill_method", "zero")
        self.random_state_ = self.config.get("random_state", 42)
        self.interaction_cols_: list[str] = []
        self.pairs_used_: dict[str, list[str]] = {}
        self.fitted_ = False

    # ------------------------------------------------------------------ fit --

    def fit(self, train_df: pd.DataFrame, target: str) -> "InteractionFeatureBuilder":
        """Decide and FIX the interaction plan from ``train_df`` ONLY.

        Args:
            train_df: The TRAIN partition (preprocessed; all-numeric features plus
                the target column).
            target: Name of the target column (excluded from interactions; used as
                the supervision signal for auto-discovery).

        Returns:
            ``self`` (fitted), for chaining.
        """
        self.target_ = target
        self.pairs_used_ = {}
        self.interaction_cols_ = []
        self.ratio_medians_: dict[str, float] = {}
        self.sources_used_: list[str] = []

        if not self.enabled_:
            self.fitted_ = True
            return self

        numeric_cols = [
            c
            for c in train_df.columns
            if c != target and pd.api.types.is_numeric_dtype(train_df[c])
        ]
        numeric_set = set(numeric_cols)
        y_codes = pd.factorize(train_df[target].astype(str))[0] if target in train_df else None

        # -- explicit pairs ------------------------------------------------------
        auto_explicit: list[tuple[str, str]] = []
        for key, op in self.interaction_pairs_cfg_.items():
            pair = self._parse_pair_key(key)
            if pair is None or pair[0] not in numeric_set or pair[1] not in numeric_set:
                logger.warning("Skipping interaction pair %r (not two numeric cols)", key)
                continue
            a, b = pair
            if op == "all":
                ops = list(_SINGLE_OPS)
            elif op == "auto":
                auto_explicit.append((a, b))
                continue
            elif op in _SINGLE_OPS:
                ops = [op]
            else:
                logger.warning("Skipping interaction pair %r: unknown op %r", key, op)
                continue
            self._record_pair(a, b, ops)

        # -- auto-discovery (MI gain on TRAIN) -----------------------------------
        # Pool = the _AUTO_POOL_CAP most target-correlated numeric columns, then all
        # unordered pairs of the pool. [RISK] O(n²) pair explosion — the pool cap is
        # what bounds it.
        already = {frozenset(self._parse_pair_key(k)) for k in self.pairs_used_}
        if y_codes is not None and (self.max_auto_pairs_ > 0 or auto_explicit):
            corr = self._abs_target_corr(train_df, numeric_cols, y_codes)
            pool = sorted(numeric_cols, key=lambda c: corr.get(c, 0.0), reverse=True)
            pool = pool[:_AUTO_POOL_CAP]
            base_mi = {c: self._mi(train_df[c], y_codes) for c in pool}

            scored: list[tuple[float, str, str]] = []
            for a, b in itertools.combinations(pool, 2):
                if frozenset((a, b)) in already:
                    continue
                term = _interaction_series(train_df[a], train_df[b], "multiply").fillna(0.0)
                gain = self._mi(term, y_codes) - max(base_mi[a], base_mi[b])
                if gain > 0:
                    scored.append((gain, a, b))
            scored.sort(key=lambda t: t[0], reverse=True)

            discovered = scored[: self.max_auto_pairs_]
            for _, a, b in discovered:
                # Scored on the product; materialized with the configured default ops.
                self._record_pair(a, b, list(self.auto_ops_))
                already.add(frozenset((a, b)))

            # Explicit "auto" pairs the user named: score the product, keep if it adds
            # information (positive MI gain), regardless of the discovery cap.
            for a, b in auto_explicit:
                if frozenset((a, b)) in already:
                    continue
                term = _interaction_series(train_df[a], train_df[b], "multiply").fillna(0.0)
                gain = self._mi(term, y_codes) - max(
                    base_mi.get(a, self._mi(train_df[a], y_codes)),
                    base_mi.get(b, self._mi(train_df[b], y_codes)),
                )
                if gain > 0:
                    self._record_pair(a, b, list(self.auto_ops_))
                    already.add(frozenset((a, b)))

        # -- store ratio train medians (for fill_method="median") ----------------
        if self.fill_method_ == "median":
            for key, ops in self.pairs_used_.items():
                if "ratio" not in ops:
                    continue
                a, b = self._parse_pair_key(key)
                col = _OP_NAMES["ratio"].format(a=a, b=b)
                series = _interaction_series(train_df[a], train_df[b], "ratio")
                self.ratio_medians_[col] = float(series.median())

        self.fitted_ = True
        return self

    # ------------------------------------------------------------ transform --

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fixed interaction plan to ``df`` (train or test) — no refitting.

        Args:
            df: Any frame containing the source columns. Never mutated.

        Returns:
            A new DataFrame: original columns plus the interaction columns. When
            ``drop_original_if_interacted`` is set, source columns that participated
            in an interaction are dropped AFTER all interactions are computed (the
            target is never dropped).

        Raises:
            RuntimeError: If called before :meth:`fit`.
        """
        if not self.fitted_:
            raise RuntimeError("InteractionFeatureBuilder.transform() called before fit()")
        if not self.enabled_ or not self.pairs_used_:
            return df.copy()

        out = df.copy()
        new_cols: dict[str, pd.Series] = {}
        for key, ops in self.pairs_used_.items():
            a, b = self._parse_pair_key(key)
            if a not in df.columns or b not in df.columns:
                continue
            for op in ops:
                name = _OP_NAMES[op].format(a=a, b=b)
                series = _interaction_series(df[a], df[b], op)
                if op == "ratio":
                    series = self._apply_fill(name, series)
                new_cols[name] = series

        if new_cols:
            ordered = {n: new_cols[n] for n in self.interaction_cols_ if n in new_cols}
            out = pd.concat([out, pd.DataFrame(ordered, index=df.index)], axis=1)

        if self.drop_original_:
            drop = [c for c in self.sources_used_ if c in out.columns and c != self.target_]
            out = out.drop(columns=drop)
        return out

    # -------------------------------------------------------- fit_transform --

    def fit_transform(self, train_df: pd.DataFrame, target: str) -> pd.DataFrame:
        """Fit on ``train_df`` then transform and return it."""
        return self.fit(train_df, target).transform(train_df)

    # -------------------------------------------------------------- helpers --

    def _record_pair(self, a: str, b: str, ops: list[str]) -> None:
        """Register ``ops`` for pair ``a+b``, extending output-column bookkeeping."""
        key = f"{a}+{b}"
        existing = self.pairs_used_.setdefault(key, [])
        for op in ops:
            if op not in existing:
                existing.append(op)
                self.interaction_cols_.append(_OP_NAMES[op].format(a=a, b=b))
        for col in (a, b):
            if col not in self.sources_used_:
                self.sources_used_.append(col)

    def _apply_fill(self, name: str, series: pd.Series) -> pd.Series:
        """Apply the configured ratio zero-denominator fill to ``series``."""
        if self.fill_method_ == "nan":
            return series
        if self.fill_method_ == "median":
            return series.fillna(self.ratio_medians_.get(name, 0.0))
        return series.fillna(0.0)  # "zero" (default)

    @staticmethod
    def _parse_pair_key(key: str) -> tuple[str, str] | None:
        """Split a ``"col_a+col_b"`` key into ``(col_a, col_b)`` or ``None``."""
        parts = key.split("+")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return None
        return parts[0], parts[1]

    def _mi(self, x: pd.Series, y_codes: np.ndarray) -> float:
        """Mutual information between a continuous feature column and the target."""
        arr = pd.to_numeric(x, errors="coerce").fillna(0.0).to_numpy(dtype=float)
        mi = mutual_info_classif(
            arr.reshape(-1, 1),
            y_codes,
            discrete_features=False,
            random_state=self.random_state_,
        )
        return float(mi[0])

    @staticmethod
    def _abs_target_corr(
        df: pd.DataFrame, cols: list[str], y_codes: np.ndarray
    ) -> dict[str, float]:
        """Absolute Pearson correlation of each column with the label-encoded target."""
        y = pd.Series(y_codes, index=df.index).astype(float)
        out: dict[str, float] = {}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # constant column → undefined corr → NaN → 0
            for c in cols:
                r = df[c].astype(float).corr(y)
                out[c] = abs(float(r)) if pd.notna(r) else 0.0
        return out


def plot_interaction_summary(
    df: pd.DataFrame,
    target: str,
    interaction_cols: list[str],
    storage: StorageAdapter,
) -> None:
    """Write ``plot6_interaction_summary.png`` — |corr| of each interaction with target.

    Horizontal bar chart of the absolute Pearson correlation between every interaction
    column and the label-encoded target, sorted strongest-first. Rendered on an
    explicit white figure (Agg backend, dpi=150) and written through ``storage``; the
    figure is always closed after save.

    Args:
        df: A frame containing ``interaction_cols`` and ``target`` (typically the
            transformed TRAIN frame).
        target: Target column name (label-encoded for the correlation).
        interaction_cols: The interaction columns to chart.
        storage: Storage adapter — the PNG is written through it.
    """
    present = [c for c in interaction_cols if c in df.columns]
    y = pd.Series(pd.factorize(df[target].astype(str))[0], index=df.index).astype(float)

    corrs: list[tuple[str, float]] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # constant interaction column → corr is NaN
        for c in present:
            r = df[c].astype(float).corr(y)
            corrs.append((c, abs(float(r)) if pd.notna(r) else 0.0))
    corrs.sort(key=lambda t: t[1])  # ascending → strongest ends up at the top of barh

    height = max(3.0, 0.4 * len(corrs) + 1.0)
    fig, ax = plt.subplots(figsize=(9, height), facecolor="white")
    if corrs:
        names = [c for c, _ in corrs]
        values = [v for _, v in corrs]
        ax.barh(names, values, color="#3b6ea5")
        ax.set_xlabel("|correlation| with target", color="#222222")
        ax.set_xlim(0, max(0.05, max(values) * 1.1))
    else:
        ax.text(0.5, 0.5, "no interaction features", ha="center", va="center")
    ax.set_title(f"Interaction features vs '{target}'", color="#222222")
    ax.tick_params(colors="#222222")

    fig.tight_layout()
    try:
        with storage.open_write(PLOT_PNG_KEY, binary=True) as fh:
            fig.savefig(fh, format="png", dpi=150, facecolor="white")
    finally:
        plt.close(fig)
    logger.info("Wrote interaction summary plot: %s", PLOT_PNG_KEY)
