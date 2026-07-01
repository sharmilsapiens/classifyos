"""Section 6 — ``Preprocessor`` (missing values, outlier capping, encoding, scaling).

An sklearn-style fit/transform preprocessor. ALL statistics — imputation values,
outlier fences, encoder categories, target-encoding means, scaler parameters — are
computed in :meth:`Preprocessor.fit` from the TRAINING data only and stored on the
instance; :meth:`Preprocessor.transform` applies the stored statistics to any
DataFrame (train or test) without recomputing anything.

The target column passes through untouched (never imputed, encoded, or scaled here),
and non-feature columns (IDs, the ``time_split_col``) are excluded from processing
and dropped from the returned frame. Instances are picklable via ``joblib`` so a
fitted preprocessor can be persisted and reused (e.g. by ``/api/explain``).

Pipeline position (corrected canonical order): the train/test split happens BEFORE
preprocessing, so this class is always fitted on the train partition only.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

import numpy as np
import pandas as pd

# IterativeImputer is still experimental in scikit-learn 1.9 — importing the enabler flag is
# mandatory before ``sklearn.impute.IterativeImputer`` becomes importable.
from sklearn.experimental import enable_iterative_imputer  # noqa: F401
from sklearn.impute import IterativeImputer, KNNImputer
from sklearn.preprocessing import (
    MinMaxScaler,
    OneHotEncoder,
    OrdinalEncoder,
    RobustScaler,
    StandardScaler,
)

from classifyos.config import MISSING_STRATEGIES_CATEGORICAL

logger = logging.getLogger(__name__)

#: Default neighbour count for the numeric ``knn`` imputer (sklearn ``KNNImputer`` default).
KNN_IMPUTER_NEIGHBORS = 5

#: m-estimate smoothing weight for target encoding (pseudo-observations of the
#: global mean blended into each category mean; stabilises rare categories).
TARGET_SMOOTHING_M = 10.0

#: z-score outlier fences are placed at mean ± this many standard deviations.
ZSCORE_CAP = 3.0

_SCALERS = {
    "standard": StandardScaler,
    "minmax": MinMaxScaler,
    "robust": RobustScaler,
}


def _mode_value(series: pd.Series) -> Any:
    """Return the most frequent non-NaN value of ``series`` (ties → smallest).

    Falls back to ``0.0`` for an all-NaN numeric column and ``"missing"`` for an
    all-NaN non-numeric column so imputation never reintroduces NaN.
    """
    modes = series.mode(dropna=True)
    if len(modes):
        return modes.iloc[0]
    return 0.0 if pd.api.types.is_numeric_dtype(series) else "missing"


def _resolve_strategies(cfg: dict[str, Any]) -> tuple[str, str]:
    """Resolve the (numeric, categorical) missing-value strategies from ``cfg``.

    The per-type keys take precedence when set; otherwise the legacy global
    ``missing_strategy`` applies. A numeric-only global (e.g. ``mean``/``median``)
    is undefined for categorical columns, so categorical falls back to ``mode`` —
    exactly the original single-setting behaviour.
    """
    global_strategy = cfg.get("missing_strategy", "median")
    numeric = cfg.get("missing_strategy_numeric") or global_strategy
    categorical = cfg.get("missing_strategy_categorical")
    if not categorical:
        categorical = (
            global_strategy
            if global_strategy in MISSING_STRATEGIES_CATEGORICAL
            else "mode"
        )
    return numeric, categorical


def _resolve_col_strategies(
    cfg: dict[str, Any],
    numeric_cols: list[str],
    categorical_cols: list[str],
    numeric_default: str,
    categorical_default: str,
) -> dict[str, str]:
    """Resolve the imputation strategy for EACH feature column.

    Starts from the per-type default (``numeric_default`` / ``categorical_default``)
    and applies the optional ``missing_strategy_by_column`` override map on top. A
    numeric-only strategy (e.g. ``mean``/``knn``) named on a categorical column is
    coerced back to ``categorical_default`` — the same fallback the per-type resolver
    applies to a numeric-only global — so an ill-typed override never crashes the run.
    Every numeric strategy is valid for a numeric column, so a numeric override always
    applies. Columns absent from the map keep their per-type default.
    """
    by_col = cfg.get("missing_strategy_by_column") or {}
    strategies: dict[str, str] = {}
    for col in numeric_cols:
        override = by_col.get(col)
        strategies[col] = override if override is not None else numeric_default
    for col in categorical_cols:
        override = by_col.get(col)
        strategies[col] = (
            override
            if override in MISSING_STRATEGIES_CATEGORICAL
            else categorical_default
        )
    return strategies


class Preprocessor:
    """Train-only-fitted preprocessing for the ClassifyOS pipeline.

    Steps applied in order: missing-value imputation → outlier capping (numeric)
    → categorical encoding → scaling (numeric). Configuration keys consumed:
    ``feature_cols``, ``target``, ``time_split_col``, ``missing_strategy``,
    ``missing_strategy_numeric``, ``missing_strategy_categorical``,
    ``missing_strategy_by_column``, ``outlier_method``, ``encoding_method``,
    ``high_cardinality_threshold``, ``scaling_method``, ``problem_type``.

    Missing-value notes:
        * The strategy is resolved PER COLUMN. The base is a per-type default:
          ``missing_strategy_numeric`` / ``missing_strategy_categorical`` override
          per type when set; otherwise the legacy global ``missing_strategy`` is
          used (a numeric-only global like ``mean``/``median`` falls back to mode
          for categorical columns, preserving the original behaviour). The optional
          ``missing_strategy_by_column`` map then overrides that default for named
          columns only — an unlisted column keeps its per-type default, so an empty
          map is byte-identical to the per-type-only behaviour. A numeric-only
          strategy named on a categorical column is coerced back to the categorical
          default (same fallback as a numeric-only global).
        * Numeric strategies: ``median``/``mean``/``mode`` (per-column statistic),
          ``ffill``/``bfill`` (directional fill + statistic fallback for the
          leading/trailing edge), ``knn``/``iterative`` (sklearn ``KNNImputer`` /
          ``IterativeImputer`` fitted on the TRAIN numeric block), or ``drop``.
        * Categorical strategies: ``mode``, ``ffill``/``bfill``, or ``drop``.
        * ``drop`` is row-level: TRAIN rows with a missing value in any column whose
          resolved strategy is ``drop`` are dropped in fit/fit_transform only.
          :meth:`transform` NEVER drops rows — it imputes with the stored TRAIN
          statistic instead.

    Encoding notes:
        * Any categorical column with more than ``high_cardinality_threshold``
          unique values in TRAIN is target-encoded regardless of
          ``encoding_method`` — one-hot would explode the width and ordinal codes
          would impose a fake order on many levels.
        * For non-binary targets (multiclass/multilabel), target-mean encoding is
          ill-defined across 3+ classes, so those columns fall back to FREQUENCY
          encoding (category → its train relative frequency; unseen → 0.0). This
          fallback also applies when ``encoding_method="target"`` is requested
          globally on a non-binary problem.
        * Only ORIGINAL numeric feature columns are scaled. Encoder outputs
          (one-hot 0/1 indicators, ordinal codes, target/frequency means) are
          never scaled — scaling indicators destroys their interpretation.

    Attributes:
        feature_names_out_: Post-encoding output column names, in the order
            produced by :meth:`transform` (target excluded; it is appended last,
            untouched, when present in the input frame).

    [RISK] leakage guard — this fit/transform separation IS the leakage guard for
    the whole pipeline: every statistic is computed in fit() from training rows
    only and merely *applied* in transform(). Never call fit() (or fit_transform())
    on data containing test rows; doing so silently invalidates every downstream
    evaluation metric.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Store an independent deep copy of ``config`` (never mutated)."""
        self.config = copy.deepcopy(config)
        self.fitted_ = False

    # ------------------------------------------------------------------ fit --

    def fit(self, train_df: pd.DataFrame) -> "Preprocessor":
        """Compute all preprocessing statistics from ``train_df`` ONLY.

        Args:
            train_df: The TRAIN partition. Must contain every configured feature
                column; must also contain the target column when target encoding
                is in play (``encoding_method="target"`` on a binary problem, or
                any high-cardinality column on a binary problem).

        Returns:
            ``self`` (fitted), for chaining.

        Raises:
            ValueError: If configured feature columns are missing from
                ``train_df``, or target encoding is required but the target
                column is absent.
        """
        cfg = self.config
        target = cfg["target"]
        time_col = cfg.get("time_split_col")
        cols = [c for c in cfg["feature_cols"] if c not in (target, time_col)]
        missing = [c for c in cols if c not in train_df.columns]
        if missing:
            raise ValueError(f"feature columns missing from training frame: {missing}")

        self.cols_ = cols
        self.target_ = target

        work = train_df[cols].copy()
        y = train_df[target] if target in train_df.columns else None

        self.numeric_cols_ = [
            c for c in cols if pd.api.types.is_numeric_dtype(work[c])
        ]
        self.categorical_cols_ = [c for c in cols if c not in self.numeric_cols_]

        # Resolve the missing-value strategy SEPARATELY per feature type, then apply
        # the optional per-column override map on top. The per-type keys override the
        # legacy global when set; a numeric-only global (mean/median/knn/iterative)
        # falls back to mode for categorical columns, preserving the original
        # single-setting behaviour. ``col_strategies_`` holds the final per-column
        # strategy actually applied (an empty override map leaves it == the per-type
        # default for every column).
        self.numeric_strategy_, self.categorical_strategy_ = _resolve_strategies(cfg)
        self.col_strategies_ = _resolve_col_strategies(
            cfg,
            self.numeric_cols_,
            self.categorical_cols_,
            self.numeric_strategy_,
            self.categorical_strategy_,
        )

        # -- step 1: missing values ---------------------------------------
        # "drop" is row-level: any column whose RESOLVED strategy is "drop" forces
        # complete-case training here. The retained rows feed every downstream
        # statistic (fences, encoder categories, scaler params, imputer fit).
        self.drop_cols_: list[str] = [
            c for c in cols if self.col_strategies_[c] == "drop"
        ]
        # Directional-fill groups + model-imputer groups, resolved per column so a
        # run can now MIX strategies across columns of the same type.
        self.ffill_cols_ = [c for c in cols if self.col_strategies_[c] == "ffill"]
        self.bfill_cols_ = [c for c in cols if self.col_strategies_[c] == "bfill"]
        self.knn_cols_ = [
            c for c in self.numeric_cols_ if self.col_strategies_[c] == "knn"
        ]
        self.iterative_cols_ = [
            c for c in self.numeric_cols_ if self.col_strategies_[c] == "iterative"
        ]
        if self.drop_cols_:
            keep = work[self.drop_cols_].notna().all(axis=1)
            work = work.loc[keep]
            if y is not None:
                y = y.loc[keep]

        # Per-column baseline fill values. These ARE the imputed value for the
        # simple statistic strategies (median/mean/mode), and double as the fallback
        # for ffill/bfill edge rows, the knn/iterative residual, and the "drop"
        # columns at transform time (transform never drops — see transform()).
        self.impute_values_: dict[str, Any] = {}
        for col in self.numeric_cols_:
            strat = self.col_strategies_[col]
            if strat == "mean":
                self.impute_values_[col] = float(work[col].mean())
            elif strat == "mode":
                self.impute_values_[col] = _mode_value(work[col])
            else:  # median / ffill / bfill / knn / iterative / drop → median baseline
                self.impute_values_[col] = float(work[col].median())
        for col in self.categorical_cols_:  # mode / ffill / bfill / drop → mode baseline
            self.impute_values_[col] = _mode_value(work[col])

        # Model-based numeric imputers (knn/iterative) are FITTED on the whole TRAIN
        # numeric block (with its NaNs) here, then applied via _impute. Each learns from
        # every numeric column as a predictor but only writes back the columns whose
        # resolved strategy is that imputer's — so per-column overrides can select knn
        # for one column and iterative (or a statistic) for another in the same run.
        # keep_empty_features=True so an all-NaN column never silently changes the output
        # column count. [RISK] leakage — these learn from train rows only; transform
        # merely applies them. ``numeric_imputers_`` is keyed by strategy name.
        self.numeric_imputers_: dict[str, KNNImputer | IterativeImputer] = {}
        if self.numeric_cols_:
            numeric_train = work[self.numeric_cols_].astype(float)
            if self.knn_cols_:
                self.numeric_imputers_["knn"] = KNNImputer(
                    n_neighbors=KNN_IMPUTER_NEIGHBORS, keep_empty_features=True
                ).fit(numeric_train)
            if self.iterative_cols_:
                self.numeric_imputers_["iterative"] = IterativeImputer(
                    random_state=int(cfg.get("random_state", 42)),
                    keep_empty_features=True,
                ).fit(numeric_train)

        work = self._impute(work)

        # -- step 2: outlier capping (numeric only) ------------------------
        outlier_method = cfg.get("outlier_method", "iqr")
        self.outlier_bounds_: dict[str, tuple[float, float]] = {}
        if outlier_method == "iqr":
            for col in self.numeric_cols_:
                q1, q3 = work[col].quantile([0.25, 0.75])
                iqr = q3 - q1
                self.outlier_bounds_[col] = (
                    float(q1 - 1.5 * iqr),
                    float(q3 + 1.5 * iqr),
                )
        elif outlier_method == "zscore":
            for col in self.numeric_cols_:
                mu, sd = float(work[col].mean()), float(work[col].std())
                self.outlier_bounds_[col] = (mu - ZSCORE_CAP * sd, mu + ZSCORE_CAP * sd)
        for col, (lo, hi) in self.outlier_bounds_.items():
            work[col] = work[col].clip(lo, hi)

        # -- step 3: categorical encoding ----------------------------------
        encoding_method = cfg.get("encoding_method", "onehot")
        problem_type = cfg.get("problem_type", "binary")
        threshold = int(cfg.get("high_cardinality_threshold", 20))

        self.high_card_cols_ = [
            c
            for c in self.categorical_cols_
            if work[c].astype(str).nunique() > threshold
        ]

        target_cols: list[str] = []
        freq_cols: list[str] = []
        self.ohe_cols_: list[str] = []
        self.ordinal_cols_: list[str] = []
        for col in self.categorical_cols_:
            if col in self.high_card_cols_ or encoding_method == "target":
                # Frequency fallback for non-binary problems — see class docstring.
                (target_cols if problem_type == "binary" else freq_cols).append(col)
            elif encoding_method == "onehot":
                self.ohe_cols_.append(col)
            else:  # label / ordinal
                self.ordinal_cols_.append(col)

        # [RISK] target encoding is the most leakage-prone encoder: a category's
        # encoded value embeds the target mean, so computing it on data that
        # includes test rows hands the model its own answers. These maps are
        # computed strictly from the train partition passed to fit().
        self.target_maps_: dict[str, dict[str, float]] = {}
        self.target_global_mean_: float | None = None
        if target_cols:
            if y is None:
                raise ValueError(
                    "target encoding requires the target column "
                    f"{target!r} to be present in the training frame"
                )
            classes = sorted(y.astype(str).unique())
            # Positive class = lexicographically last label ("1" for 0/1 targets).
            y_num = (y.astype(str) == classes[-1]).astype(float)
            self.target_global_mean_ = float(y_num.mean())
            for col in target_cols:
                grouped = y_num.groupby(work[col].astype(str))
                counts, means = grouped.count(), grouped.mean()
                smoothed = (
                    counts * means + TARGET_SMOOTHING_M * self.target_global_mean_
                ) / (counts + TARGET_SMOOTHING_M)
                self.target_maps_[col] = {str(k): float(v) for k, v in smoothed.items()}

        self.freq_maps_: dict[str, dict[str, float]] = {}
        for col in freq_cols:
            freqs = work[col].astype(str).value_counts(normalize=True)
            self.freq_maps_[col] = {str(k): float(v) for k, v in freqs.items()}

        # [RISK] unseen categories — handle_unknown="ignore" maps a test-time
        # category never seen in train to an all-zeros indicator block. The model
        # then treats such rows as "none of the known levels"; a flood of unseen
        # categories at scoring time signals train/serve skew and should be
        # monitored, not silently accepted.
        self.ohe_: OneHotEncoder | None = None
        if self.ohe_cols_:
            self.ohe_ = OneHotEncoder(
                handle_unknown="ignore", sparse_output=False, dtype=np.float64
            ).fit(work[self.ohe_cols_].astype(str))

        self.ordinal_: OrdinalEncoder | None = None
        if self.ordinal_cols_:
            self.ordinal_ = OrdinalEncoder(
                handle_unknown="use_encoded_value", unknown_value=-1
            ).fit(work[self.ordinal_cols_].astype(str))

        # -- step 4: scaling (original numeric columns only) ----------------
        scaling_method = cfg.get("scaling_method", "standard")
        self.scaler_ = None
        if scaling_method != "none" and self.numeric_cols_:
            self.scaler_ = _SCALERS[scaling_method]().fit(
                work[self.numeric_cols_].astype(float)
            )

        # -- output column contract -----------------------------------------
        ohe_names: dict[str, list[str]] = {}
        if self.ohe_ is not None:
            for col, cats in zip(self.ohe_cols_, self.ohe_.categories_):
                ohe_names[col] = [f"{col}_{cat}" for cat in cats]
        names = list(self.numeric_cols_)
        for col in self.categorical_cols_:
            names.extend(ohe_names.get(col, [col]))
        self.feature_names_out_: list[str] = names

        self.fitted_ = True
        return self

    # -------------------------------------------------------------- impute --

    def _impute(self, work: pd.DataFrame) -> pd.DataFrame:
        """Apply the resolved per-column imputation to ``work`` (mutates and returns it).

        Shared by :meth:`fit` and :meth:`transform` so train and test are imputed by
        exactly the same fitted statistics. Order: directional fill (ffill/bfill) on the
        columns resolved to those strategies → model-based numeric imputer (knn/iterative,
        each writing back only its own columns) → per-column statistic fallback (catches
        the simple strategies, fill-edge residuals, and "drop" columns). No rows are
        dropped here.
        """
        # Directional fill is per column (a run may mix ffill/bfill/other across
        # columns of the same type), so fill each group's columns independently.
        if self.ffill_cols_:
            work[self.ffill_cols_] = work[self.ffill_cols_].ffill()
        if self.bfill_cols_:
            work[self.bfill_cols_] = work[self.bfill_cols_].bfill()

        # Each model imputer is fitted on the full numeric block but only its own
        # columns take the imputed values (the rest fall through to the statistic step).
        for strategy, cols in (("knn", self.knn_cols_), ("iterative", self.iterative_cols_)):
            imputer = self.numeric_imputers_.get(strategy)
            if imputer is not None:
                imputed = imputer.transform(work[self.numeric_cols_].astype(float))
                imputed_df = pd.DataFrame(
                    imputed, columns=self.numeric_cols_, index=work.index
                )
                work[cols] = imputed_df[cols]

        # Statistic fallback: fills the simple median/mean/mode columns and any
        # residual NaN left by a directional fill at the leading/trailing edge.
        return work.fillna(self.impute_values_)

    # ------------------------------------------------------------ transform --

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fitted statistics to ``df`` (train or test) — no refitting.

        Args:
            df: Any frame containing the configured feature columns. The target
                column is optional; when present it is appended to the output
                untouched. Extra columns (IDs, ``time_split_col``) are dropped.

        Returns:
            A new DataFrame with columns ``feature_names_out_`` (plus the target,
            last, if present in ``df``), original row index preserved. The input
            frame is never mutated and no rows are ever dropped.

        Raises:
            RuntimeError: If called before :meth:`fit`.
            ValueError: If configured feature columns are missing from ``df``.
        """
        if not self.fitted_:
            raise RuntimeError("Preprocessor.transform() called before fit()")
        missing = [c for c in self.cols_ if c not in df.columns]
        if missing:
            raise ValueError(f"feature columns missing from frame: {missing}")

        work = df[self.cols_].copy()

        # [RISK] "drop" never drops here — silently removing test rows would
        # corrupt evaluation (metrics computed on a cherry-picked subset) and is
        # impossible at prediction time (every row needs a prediction). Rows with
        # missing values are imputed with the stored TRAIN statistics instead.
        work = self._impute(work)

        for col, (lo, hi) in self.outlier_bounds_.items():
            work[col] = work[col].clip(lo, hi)

        blocks: dict[str, pd.DataFrame] = {}

        if self.numeric_cols_:
            num = work[self.numeric_cols_].astype(float)
            if self.scaler_ is not None:
                num = pd.DataFrame(
                    self.scaler_.transform(num),
                    columns=self.numeric_cols_,
                    index=work.index,
                )
            blocks["__numeric__"] = num

        if self.ohe_ is not None:
            flat_names = [
                f"{col}_{cat}"
                for col, cats in zip(self.ohe_cols_, self.ohe_.categories_)
                for cat in cats
            ]
            blocks["__onehot__"] = pd.DataFrame(
                self.ohe_.transform(work[self.ohe_cols_].astype(str)),
                columns=flat_names,
                index=work.index,
            )

        if self.ordinal_ is not None:
            blocks["__ordinal__"] = pd.DataFrame(
                self.ordinal_.transform(work[self.ordinal_cols_].astype(str)),
                columns=self.ordinal_cols_,
                index=work.index,
            )

        mapped: dict[str, pd.Series] = {}
        for col, mapping in self.target_maps_.items():
            # Unseen categories → global TRAIN target mean (no information).
            mapped[col] = (
                work[col].astype(str).map(mapping).fillna(self.target_global_mean_)
            )
        for col, mapping in self.freq_maps_.items():
            mapped[col] = work[col].astype(str).map(mapping).fillna(0.0)
        if mapped:
            blocks["__mapped__"] = pd.DataFrame(mapped, index=work.index)

        out = pd.concat(blocks.values(), axis=1)[self.feature_names_out_]
        if self.target_ in df.columns:
            out[self.target_] = df[self.target_]
        return out

    # -------------------------------------------------------- fit_transform --

    def fit_transform(self, train_df: pd.DataFrame) -> pd.DataFrame:
        """Fit on ``train_df`` and return its transformed frame.

        When a column type uses the ``drop`` strategy, the TRAIN rows with a missing
        value in those columns are dropped here (complete-case training); this is the
        only place rows are ever removed — :meth:`transform` never drops.
        """
        self.fit(train_df)
        if self.drop_cols_:
            return self.transform(train_df.dropna(subset=self.drop_cols_))
        return self.transform(train_df)
