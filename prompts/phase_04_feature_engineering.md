# Phase 4 Generation Prompt — Feature Engineering (Sections 7 + 7B)

> Archive location: prompts/phase_04_feature_engineering.md

---

Read CLAUDE.md, PROJECT_STATE.md, and plan_tweak.md first. This session implements
Phase 4: Section 7 (build_features) and Section 7B (interaction features), plus tests.
Do NOT implement class balancing or models. Phases 1–3 code must not be modified except
where this prompt explicitly sanctions a config.py addition.

Both components follow the same leakage-safe pattern as Phase 3's Preprocessor:
sklearn-style fit/transform classes where ALL learned statistics come from train only.
(The scope wrote these as plain functions and ignored leakage in frequency encoding,
binning edges, and MI auto-discovery — log this as a plan_tweak entry.)

They run AFTER preprocessing in the corrected pipeline order:
split → preprocess → build_features → interactions → balance → train.

## Files to create

1. `backend/classifyos/preprocessing/features.py` — Section 7, class `FeatureBuilder`
2. `backend/classifyos/preprocessing/interactions.py` — Section 7B, class `InteractionFeatureBuilder`
3. `backend/tests/test_features.py`, `backend/tests/test_interactions.py`

## Section 7 — FeatureBuilder (features.py)

```python
class FeatureBuilder:
    def __init__(self, config: dict): ...
    def fit(self, train_df: pd.DataFrame, target: str) -> "FeatureBuilder": ...
    def transform(self, df: pd.DataFrame) -> pd.DataFrame: ...
    def fit_transform(...) -> pd.DataFrame
    created_features_: list[str]
```

Capabilities (each individually toggleable via a new config sub-dict
`feature_engineering` added to DEFAULT_CONFIG — the sanctioned config.py edit:
`{"enabled": True, "polynomial": False, "ratios": True, "binning": True,
"max_poly_features": 8}`):

- **Polynomial (degree 2)**: squared terms for numeric columns only, capped at the
  top `max_poly_features` numeric columns ranked by absolute correlation with target
  computed on TRAIN (cap prevents column explosion; [RISK] comment). Default OFF —
  often redundant with tree models; document this in the docstring.
- **Ratio features**: for numeric column pairs the builder is told about OR a
  heuristic default of (each numeric col ÷ train-median-largest numeric col).
  Denominator guard: |denominator| < 1e-9 → NaN → filled per Section 7B fill rules.
- **Binning for skewed numerics**: columns with train skewness |skew| > 1.5 get a
  5-bin quantile-binned companion column (suffix `_bin`, ordinal ints). Bin edges
  computed on TRAIN ONLY and stored; test values outside the range clip to the
  outer bins. Original column is kept.
- Frequency encoding is NOT duplicated here — Phase 3's Preprocessor already owns
  high-cardinality encoding. Note this in the docstring (scope listed it in both
  places; plan_tweak entry: consolidated in Preprocessor to avoid double-encoding).

Never mutates the input df or the config. Target column untouched. Picklable.

## Section 7B — InteractionFeatureBuilder (interactions.py)

```python
class InteractionFeatureBuilder:
    def __init__(self, config: dict): ...   # reads config["interaction_features"]
    def fit(self, train_df: pd.DataFrame, target: str) -> "InteractionFeatureBuilder": ...
    def transform(self, df: pd.DataFrame) -> pd.DataFrame: ...
    interaction_cols_: list[str]
    pairs_used_: dict[str, list[str]]   # "col_a+col_b" -> ["multiply", ...]
```

Config keys (already in DEFAULT_CONFIG from Phase 1): enabled, interaction_pairs,
default_interactions, drop_original_if_interacted, max_auto_pairs, fill_method.

Behavior:

- **Explicit pairs**: `interaction_pairs` maps "col_a+col_b" → "multiply" | "ratio" |
  "diff" | "auto" | "all". Apply the named operation(s) to numeric column pairs.
- **Naming convention (exact, contract-level)**: `col_a_x_col_b` (multiply),
  `col_a_div_col_b` (ratio), `col_a_minus_col_b` (difference).
- **Auto mode / auto-discovery**: when a pair is "auto", or for discovering up to
  `max_auto_pairs` new pairs: candidate pairs are scored on TRAIN by MI gain =
  MI(interaction_term, target) − max(MI(col_a, target), MI(col_b, target)); keep
  pairs with positive gain, top-N by gain. mutual_info_classif, random_state from
  config. Candidate pool: numeric columns only; cap the pool at the 15 most
  target-correlated numeric columns before pairing ([RISK]: O(n²) pair explosion).
  The discovered pair list and chosen op per pair are FIXED at fit time and stored —
  transform never re-discovers ([RISK]: re-discovery on test = leakage).
- **Ratio guard**: |denominator| < 1e-9 → NaN, then filled per `fill_method`
  ("zero" → 0, "median" → train median of that interaction column, "nan" → leave).
- **drop_original_if_interacted=True**: source columns removed from output frame
  AFTER all interactions are computed.
- Never mutates input df or config (this is the section the scope's _run_config
  isolation note targets — enforce it here at the component level too).
- **plot6_interaction_summary.png**: separate function
  `plot_interaction_summary(df, target, interaction_cols, storage)` — horizontal bar
  chart of |correlation| of each interaction column with the (label-encoded) target,
  Agg backend, dpi=150, white facecolor, closed after save, written via StorageAdapter.

## Tests

Real CSVs from DATA_DIR through the Phase 1–3 pipeline (load → split → preprocess →
features → interactions). Required:

- Naming: a multiply pair on policy_lapse produces exactly `a_x_b` named column;
  ratio → `a_div_b`; diff → `a_minus_b`.
- Leakage — binning: bin edges from a train split are unchanged after transforming a
  poisoned test split (extreme values); poisoned values land in outer bins.
- Leakage — auto-discovery: pairs_used_ identical before/after transforming test data;
  discovery uses train only (poison test, assert same pairs).
- Ratio guard: a constructed zero-denominator row yields the fill_method value, no inf.
- max_auto_pairs respected (set 3, assert ≤3 discovered pairs).
- drop_original_if_interacted removes sources but keeps interaction columns.
- Config object deep-equal before vs after fit+transform (no mutation).
- enabled=False → transform returns the frame unchanged.
- plot6 PNG exists in (tmp) OUTPUT_DIR and is >10 KB after a real run on policy_lapse.
- Skewed-column binning fires on fraud_claims (claim_amount is lognormal → skewed).
- Regression: FULL suite (Phases 1–3) still green.

## Process requirements

- Type hints, docstrings, [RISK] comments as noted. Verify sklearn/scipy/pandas
  signatures against installed versions.
- Full pytest suite green before finishing.
- Save this prompt to prompts/phase_04_feature_engineering.md.
- Update PROJECT_STATE.md (Ph.4 status, session summary, next: Phase 5 class balancing).
- Update short_desc.md (Phase 4 entry) and plan_tweak.md (at minimum: fit/transform
  classes vs scope's plain functions; frequency-encoding consolidation into
  Preprocessor; polynomial default-off; auto-discovery candidate-pool cap).
- Commit as: "Phase 4: feature engineering + interaction layer — sections 7, 7B + tests"

---

## Implementation notes (filled in after the session)

- **Sanctioned config edit**: added the `feature_engineering` sub-dict to
  `DEFAULT_CONFIG` plus a `_validate_feature_engineering` check (bool flags;
  `max_poly_features` positive int). `interaction_features` already existed from Phase 1.
- **FeatureBuilder ratio denominator**: chosen as the numeric column with the largest
  *absolute* train median. Because the frame is post-standard-scaling, medians sit near
  zero, so the heuristic is weakly determined and frequently small — the per-row guard
  (→ 0.0) keeps it safe. Recorded as a plan_tweak entry/[RISK].
- **Auto-discovery scoring** uses the *multiplicative* interaction term as the canonical
  2nd-order term; kept pairs are then materialized with the ops in `default_interactions`
  (default `["multiply"]`). Pool capped at the 15 most target-correlated numeric columns.
- **Binning** requires |skew| > 1.5 AND ≥ 5 distinct values; with the default IQR outlier
  capping the lognormal tail is clipped (skew ≈ 1.0), so the binning test runs with
  `outlier_method="none"` to keep `claim_amount` skewed (≈ 11.3) — a faithful trigger.
- 19 new tests; full suite 60 passed. Hallucination check: `mutual_info_classif`,
  `scipy.stats.skew`, `pandas.qcut` verified against sklearn 1.9.0 / scipy 1.17.1 /
  pandas 2.3.3 in the venv.
