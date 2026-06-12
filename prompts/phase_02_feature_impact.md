# Phase 2 Generation Prompt — Feature Impact Analysis (Section 5)

> Archive location: prompts/phase_02_feature_impact.md (governance: prompt committed with the code)

---

Read CLAUDE.md and PROJECT_STATE.md first. This session implements Phase 2 of ClassifyOS:
Section 5 — `analyze_feature_impact()` — plus its outputs and tests. Do NOT implement
preprocessing, feature engineering, or models. Build only on the Phase 1 modules
(config.py, io/inspect.py, io/loader.py, split.py) without modifying them.

## Files to create

1. `backend/classifyos/analysis/feature_impact.py`
2. `backend/tests/test_feature_impact.py`

## Section 5 — analysis/feature_impact.py

`analyze_feature_impact(df: pd.DataFrame, config: dict, storage: StorageAdapter) -> pd.DataFrame`

Purpose: rank every feature column by its statistical relationship with the target,
BEFORE any preprocessing — this reflects real relationships in the raw data
(pipeline step 2 of 8; it runs on the raw loaded DataFrame).

Per feature, compute what is applicable and leave NaN where not:

- **ANOVA F-score** (scipy.stats.f_oneway or sklearn f_classif): numeric features only,
  grouped by target class. Skip (NaN) for categorical features.
- **Mutual Information** (sklearn.feature_selection.mutual_info_classif): all features.
  Categorical features are label-encoded internally for the MI computation only —
  this temporary encoding must NOT leak into the returned df or be saved anywhere.
  Set discrete_features correctly per column type. random_state from config.
- **Point-Biserial correlation** (scipy.stats.pointbiserialr): only when problem_type
  is binary AND feature is numeric. NaN otherwise. For multiclass targets compute the
  **correlation ratio (eta)** instead, in a separate column `corr_ratio` — document
  the formula in the docstring.
- **Composite importance score**: min-max normalize each available metric column to
  [0,1] across features, then take the mean of available (non-NaN) normalized metrics
  per feature. Column name: `composite_score`. Sort the result descending by it.

Implementation requirements:

- Handle missing values inside the function by pairwise dropping rows with NaN in the
  (feature, target) pair being measured — do NOT impute here, and do NOT mutate the
  input df. [RISK] comment: this analysis sees raw data; results can shift after
  preprocessing — it is a screening tool, not a final feature-selection authority.
- Rows with NaN target are excluded (loader already drops them, but guard anyway).
- ID-like columns: if a feature has unique values in ≥99% of rows (e.g. policy_id),
  still compute but add a boolean `id_like` column and a [RISK] comment — high MI on
  ID columns is leakage-bait. Do not silently drop anything.
- Returned DataFrame columns (exact names — future API contract):
  `feature`, `dtype_group` ("numeric"|"categorical"), `anova_f`, `anova_p`,
  `mutual_info`, `point_biserial`, `corr_ratio`, `composite_score`, `id_like`, `rank`.

Outputs (both written via StorageAdapter to OUTPUT_DIR):

- `feature_impact_summary.csv` — the full returned DataFrame.
- `plot4_feature_impact.png` — matplotlib figure, `Agg` backend (set
  `matplotlib.use("Agg")` before pyplot import — headless safety), 2-panel:
  (a) horizontal bar chart of composite_score, features sorted, top 20 max;
  (b) grouped bars of the normalized individual metrics for the top 10 features.
  Clear axis labels, title includes the target name, tight_layout, dpi=150.
  Legible on both light and dark backgrounds (no pure-white or pure-black text;
  use explicit facecolor="white" on the figure).

## Tests (pytest) — test_feature_impact.py

Use the real sample CSVs from DATA_DIR via the Phase 1 loader.

- policy_lapse.csv (binary): returns one row per feature; num_late_payments has
  composite_score above the median (it drives the target by construction);
  point_biserial is non-NaN for numeric features and NaN for occupation;
  occupation gets a mutual_info value (categorical handled); policy_id flagged id_like.
- risk_tier.csv (multiclass): point_biserial is all-NaN, corr_ratio populated for
  numeric features; is_smoker ranks in the top 5 by composite_score.
- Outputs: feature_impact_summary.csv and plot4_feature_impact.png exist in OUTPUT_DIR
  after the run, and the PNG is non-empty (>10 KB).
- Input df is not mutated (compare df.copy() before/after).
- Edge case: a zero-variance feature (constant column added in the test) gets
  composite_score 0 or NaN handled gracefully — no exception.

## Process requirements

- Type hints + docstrings everywhere. Embed the [RISK] comments noted above.
- All file writes via StorageAdapter. matplotlib figures closed after saving
  (plt.close) to avoid memory growth over repeated runs.
- Verify scipy/sklearn call signatures against installed versions (hallucination check).
- Run the FULL pytest suite (Phase 1 tests must still pass — regression guard).
- Save this prompt to prompts/phase_02_feature_impact.md.
- Update PROJECT_STATE.md (Ph.2 status, session summary, next steps: Phase 3 preprocess).
- Commit as: "Phase 2: feature impact analysis — section 5 + tests"
