"""Section 5 — ``analyze_feature_impact``.

Ranks every configured feature by its statistical relationship with the target,
**before any preprocessing** (pipeline step 2 of 8 — it runs on the raw loaded
DataFrame). This makes the analysis a faithful screen of the relationships present
in the raw data, but also means the numbers can shift once encoding/scaling/
imbalance handling are applied downstream.

Metrics computed per feature (NaN where not applicable):

* **ANOVA F-score** (``scipy.stats.f_oneway``): numeric features only, grouping the
  feature's values by target class. NaN for categorical features.
* **Mutual information** (``sklearn.feature_selection.mutual_info_classif``): all
  features. Categorical features are label-encoded internally *only* for this
  computation — the temporary encoding never leaks into the returned frame or any
  artifact. ``discrete_features`` is set per column type.
* **Point-biserial correlation** (``scipy.stats.pointbiserialr``): only when the
  problem is binary and the feature is numeric. NaN otherwise.
* **Correlation ratio (eta)**: the multiclass analogue of point-biserial, in the
  ``corr_ratio`` column. eta = sqrt(SS_between / SS_total), where
  SS_between = Σ_k n_k (mean_k − grand_mean)² over the k target classes and
  SS_total = Σ_i (x_i − grand_mean)². eta ∈ [0, 1]: the fraction of the feature's
  variance explained by the target grouping.
* **Composite importance score**: each available metric column is min-max
  normalized to [0, 1] across features, then averaged (ignoring NaN) per feature.
  The result is sorted descending by this score.

[RISK] This screen sees *raw* data: missing values are pairwise-dropped (not
imputed), categoricals are only crudely label-encoded for MI, and no train/test
boundary exists yet. Results are a screening aid, **not** a final feature-selection
authority — they can and do change after preprocessing. Treat high scores as
candidates to investigate, not decisions.
"""

from __future__ import annotations

import logging
import warnings
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless safety: set the non-interactive backend before pyplot

import matplotlib.pyplot as plt  # noqa: E402  (must follow matplotlib.use)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import f_oneway, pointbiserialr  # noqa: E402
from sklearn.feature_selection import mutual_info_classif  # noqa: E402

from ..io.storage import StorageAdapter  # noqa: E402

logger = logging.getLogger(__name__)

# Logical output keys (these names become part of the future API/output contract).
SUMMARY_CSV_KEY = "feature_impact_summary.csv"
PLOT_PNG_KEY = "plot4_feature_impact.png"

# A feature whose distinct-value fraction reaches this threshold is flagged id_like.
_ID_LIKE_FRACTION = 0.99

# Exact, ordered columns of the returned frame (locked — future API contract).
_RESULT_COLUMNS = [
    "feature",
    "dtype_group",
    "anova_f",
    "anova_p",
    "mutual_info",
    "point_biserial",
    "corr_ratio",
    "composite_score",
    "id_like",
    "rank",
]

# Raw-metric columns that feed the composite score. ``point_biserial`` enters by
# magnitude (a strong negative correlation is as informative as a positive one).
_COMPOSITE_METRICS = ("anova_f", "mutual_info", "point_biserial", "corr_ratio")


def analyze_feature_impact(
    df: pd.DataFrame,
    config: dict[str, Any],
    storage: StorageAdapter,
) -> pd.DataFrame:
    """Rank features by their raw statistical association with the target.

    Args:
        df: The raw, loaded dataframe (Section 4 output). Not mutated.
        config: Run config; uses ``target``, ``feature_cols``, ``problem_type``,
            and ``random_state``.
        storage: Storage adapter — both artifacts are written through it.

    Returns:
        One row per feature, columns exactly :data:`_RESULT_COLUMNS`, sorted
        descending by ``composite_score`` (NaN scores last) with a 1-based ``rank``.

    Side effects:
        Writes ``feature_impact_summary.csv`` and ``plot4_feature_impact.png`` to
        the output root via ``storage``.
    """
    target = config["target"]
    feature_cols = list(config["feature_cols"])
    problem_type = config.get("problem_type", "binary")
    random_state = config.get("random_state", 42)

    # Work on a copy so the caller's frame is never mutated, and guard against
    # NaN-target rows even though the loader already drops them.
    work = df.copy()
    work = work[work[target].notna()]
    y = work[target].astype(str)
    n_rows = len(work)

    rows: list[dict[str, Any]] = []
    for col in feature_cols:
        series = work[col]
        is_numeric = pd.api.types.is_numeric_dtype(series)
        dtype_group = "numeric" if is_numeric else "categorical"

        # [RISK] ID-like columns (e.g. policy_id) are near-unique and produce
        # spuriously high mutual information — classic leakage-bait. We flag them
        # rather than dropping anything silently, so the screen stays transparent.
        distinct_fraction = series.nunique(dropna=True) / n_rows if n_rows else 0.0
        id_like = bool(distinct_fraction >= _ID_LIKE_FRACTION)

        anova_f, anova_p = _anova(series, y) if is_numeric else (np.nan, np.nan)
        mutual_info = _mutual_information(series, y, is_numeric, random_state)

        point_biserial = np.nan
        corr_ratio = np.nan
        if is_numeric:
            if problem_type == "binary":
                point_biserial = _point_biserial(series, y)
            else:
                corr_ratio = _correlation_ratio(series, y)

        rows.append(
            {
                "feature": col,
                "dtype_group": dtype_group,
                "anova_f": anova_f,
                "anova_p": anova_p,
                "mutual_info": mutual_info,
                "point_biserial": point_biserial,
                "corr_ratio": corr_ratio,
                "id_like": id_like,
            }
        )

    result = pd.DataFrame(rows)

    # --- composite score: min-max each available metric, then mean per feature ---
    norm_sources = {
        "anova_f": result["anova_f"],
        "mutual_info": result["mutual_info"],
        # magnitude: direction of a (point-biserial) correlation is irrelevant to
        # "how strongly is this feature associated with the target".
        "point_biserial": result["point_biserial"].abs(),
        "corr_ratio": result["corr_ratio"],
    }
    norm_df = pd.DataFrame({k: _minmax_normalize(v) for k, v in norm_sources.items()})
    # Drop metrics that are inapplicable to *every* feature (e.g. corr_ratio on a
    # binary problem) so they don't dilute the mean with NaN-only columns.
    norm_df = norm_df.dropna(axis=1, how="all")
    result["composite_score"] = norm_df.mean(axis=1, skipna=True)

    # Sort by composite (NaN last) and assign a stable 1-based rank.
    result = result.sort_values(
        "composite_score", ascending=False, na_position="last", kind="stable"
    ).reset_index(drop=True)
    result["rank"] = range(1, len(result) + 1)
    result = result[_RESULT_COLUMNS]

    # Normalized metrics aligned to feature name, for the per-metric plot panel.
    norm_for_plot = norm_df.copy()
    norm_for_plot.index = [r["feature"] for r in rows]

    _write_summary_csv(result, storage)
    _plot_feature_impact(result, norm_for_plot, target, storage)

    return result


# --------------------------------------------------------------------------- #
# Per-metric helpers — each pairwise-drops NaNs in its (feature, target) pair.  #
# --------------------------------------------------------------------------- #


def _anova(series: pd.Series, y: pd.Series) -> tuple[float, float]:
    """One-way ANOVA F-score/p-value of a numeric feature grouped by target class.

    Returns ``(nan, nan)`` when there are fewer than two non-empty groups or the
    feature has no within-group variance (e.g. a constant column).
    """
    pair = pd.DataFrame({"x": pd.to_numeric(series, errors="coerce"), "y": y}).dropna()
    if pair.empty:
        return (np.nan, np.nan)
    groups = [g["x"].to_numpy() for _, g in pair.groupby("y", observed=True)]
    groups = [g for g in groups if g.size > 0]
    if len(groups) < 2:
        return (np.nan, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # constant input -> f_oneway warns + returns nan
        stat, p = f_oneway(*groups)
    f_val = float(stat) if np.isfinite(stat) else np.nan
    p_val = float(p) if np.isfinite(p) else np.nan
    return (f_val, p_val)


def _mutual_information(
    series: pd.Series, y: pd.Series, is_numeric: bool, random_state: int
) -> float:
    """Mutual information between a single feature and the target.

    Categorical features are label-encoded (via ``pd.factorize``) for this call
    only; ``discrete_features`` is set to match the column type. The encoding is
    local and is never written out or returned.
    """
    pair = pd.DataFrame({"x": series, "y": y}).dropna()
    if pair.empty or pair["y"].nunique() < 2:
        return np.nan

    if is_numeric:
        x = pd.to_numeric(pair["x"], errors="coerce").to_numpy(dtype=float)
        discrete = False
    else:
        # Temporary, in-memory label encoding for MI only (no leakage downstream).
        x = pd.factorize(pair["x"])[0].astype(float)
        discrete = True

    y_codes = pd.factorize(pair["y"])[0]
    try:
        mi = mutual_info_classif(
            x.reshape(-1, 1),
            y_codes,
            discrete_features=[discrete],
            random_state=random_state,
        )
    except ValueError:
        return np.nan
    return float(mi[0])


def _point_biserial(series: pd.Series, y: pd.Series) -> float:
    """Point-biserial correlation of a numeric feature with a binary target.

    The two target classes are coded 0/1. Returns NaN if the feature is constant
    or the pair has too few points.
    """
    pair = pd.DataFrame({"x": pd.to_numeric(series, errors="coerce"), "y": y}).dropna()
    classes = sorted(pair["y"].unique())
    if pair.shape[0] < 3 or len(classes) != 2:
        return np.nan
    if pair["x"].nunique() < 2:  # constant feature -> correlation undefined
        return np.nan
    codes = pair["y"].map({classes[0]: 0, classes[1]: 1}).to_numpy(dtype=float)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r, _ = pointbiserialr(pair["x"].to_numpy(dtype=float), codes)
    return float(r) if np.isfinite(r) else np.nan


def _correlation_ratio(series: pd.Series, y: pd.Series) -> float:
    """Correlation ratio (eta) of a numeric feature against a categorical target.

    eta = sqrt(SS_between / SS_total) where
        SS_between = Σ_k n_k (mean_k − grand_mean)²   (over target classes k)
        SS_total   = Σ_i (x_i − grand_mean)²
    eta ∈ [0, 1] is the fraction of the feature's variance explained by the target
    grouping — the multiclass analogue of |point-biserial|. Returns NaN for a
    zero-variance feature.
    """
    pair = pd.DataFrame({"x": pd.to_numeric(series, errors="coerce"), "y": y}).dropna()
    if pair.shape[0] < 2:
        return np.nan
    x = pair["x"].to_numpy(dtype=float)
    grand_mean = x.mean()
    ss_total = float(np.sum((x - grand_mean) ** 2))
    if ss_total == 0.0:  # constant feature -> eta undefined
        return np.nan
    ss_between = 0.0
    for _, g in pair.groupby("y", observed=True):
        gx = g["x"].to_numpy(dtype=float)
        ss_between += gx.size * (gx.mean() - grand_mean) ** 2
    eta = np.sqrt(ss_between / ss_total)
    return float(min(eta, 1.0))


def _minmax_normalize(col: pd.Series) -> pd.Series:
    """Min-max scale a metric column to [0, 1] across features, preserving NaN.

    A column with no spread (all equal, or a single non-NaN value) maps its defined
    entries to 0.0 — it carries no discriminating signal. NaN entries stay NaN so
    they are skipped in the composite mean.
    """
    vals = col.astype(float)
    if not vals.notna().any():
        return vals
    lo = float(np.nanmin(vals))
    hi = float(np.nanmax(vals))
    if hi == lo:
        return vals.where(vals.isna(), 0.0)
    return (vals - lo) / (hi - lo)


# --------------------------------------------------------------------------- #
# Artifact writers                                                             #
# --------------------------------------------------------------------------- #


def _write_summary_csv(result: pd.DataFrame, storage: StorageAdapter) -> None:
    """Write the full result frame to ``feature_impact_summary.csv``."""
    with storage.open_write(SUMMARY_CSV_KEY) as fh:
        result.to_csv(fh, index=False)
    logger.info("Wrote feature-impact summary: %s", SUMMARY_CSV_KEY)


def _plot_feature_impact(
    result: pd.DataFrame,
    norm_for_plot: pd.DataFrame,
    target: str,
    storage: StorageAdapter,
) -> None:
    """Write a 2-panel feature-impact figure to ``plot4_feature_impact.png``.

    Panel (a): horizontal bars of ``composite_score`` (top 20 features).
    Panel (b): grouped bars of the normalized individual metrics (top 10 features).
    Rendered on an explicit white figure with dark text so it stays legible on both
    light and dark UI backgrounds.
    """
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(15, 7), facecolor="white")

    # --- panel (a): composite score, highest at top ---
    top_a = result.dropna(subset=["composite_score"]).head(20).iloc[::-1]
    if top_a.empty:  # degenerate input — keep the panel but say so
        ax_a.text(0.5, 0.5, "no composite scores", ha="center", va="center")
    else:
        ax_a.barh(top_a["feature"], top_a["composite_score"], color="#3b6ea5")
        ax_a.set_xlabel("composite score (0–1)", color="#222222")
        ax_a.set_xlim(0, 1)
    ax_a.set_title(f"Feature impact on '{target}' — composite", color="#222222")
    ax_a.tick_params(colors="#222222")

    # --- panel (b): per-metric normalized contributions for the top features ---
    top_features = result.head(10)["feature"].tolist()
    metric_cols = list(norm_for_plot.columns)
    if not top_features or not metric_cols:
        ax_b.text(0.5, 0.5, "no metrics to plot", ha="center", va="center")
    else:
        sub = norm_for_plot.reindex(top_features)
        positions = np.arange(len(top_features))
        n_metrics = len(metric_cols)
        width = 0.8 / n_metrics
        for i, metric in enumerate(metric_cols):
            offsets = positions - 0.4 + width * (i + 0.5)
            ax_b.bar(offsets, sub[metric].fillna(0.0).to_numpy(), width=width, label=metric)
        ax_b.set_xticks(positions)
        ax_b.set_xticklabels(top_features, rotation=45, ha="right", color="#222222")
        ax_b.set_ylabel("normalized metric (0–1)", color="#222222")
        ax_b.set_ylim(0, 1)
        ax_b.legend(fontsize=8)
    ax_b.set_title("Normalized metrics — top features", color="#222222")
    ax_b.tick_params(colors="#222222")

    fig.tight_layout()
    try:
        with storage.open_write(PLOT_PNG_KEY, binary=True) as fh:
            fig.savefig(fh, format="png", dpi=150, facecolor="white")
    finally:
        # Always release the figure, even if savefig raises, to bound memory growth
        # across repeated runs.
        plt.close(fig)
    logger.info("Wrote feature-impact plot: %s", PLOT_PNG_KEY)
