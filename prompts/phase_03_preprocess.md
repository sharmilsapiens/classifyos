# Phase 3 Generation Prompt — Preprocessing (Section 6)

> Archive location: prompts/phase_03_preprocess.md (governance: prompt committed with the code)

---

Read CLAUDE.md and PROJECT_STATE.md first. This session implements Phase 3 of ClassifyOS:
Section 6 — preprocessing — plus tests. Do NOT implement feature engineering, class
balancing, or models. Phase 1–2 modules must not be modified, with ONE sanctioned
exception noted below (decisions-log update).

## ⚠ Pipeline-order correction (record this in PROJECT_STATE.md decisions log)

The scope document's 8-step order (preprocess at step 3, split at step 6) contradicts
its own leakage rule ("scaler fitted on train split only"). The corrected canonical
order, which ModelRunner (Phase 7) will implement, is:

1. data_loader → 2. analyze_feature_impact (raw data) → 3. train_test_split_cls →
4. preprocess (FIT on train, TRANSFORM both) → 5. build_features → 5B. interactions →
6. handle_class_imbalance (train only) → 7. train/evaluate → 8. save/plots

Decisions log entry: "Pipeline order corrected: split moved before preprocessing so
encoder/scaler/imputer can be fitted on the training split only, as the scope's own
leakage rule requires."

## Files to create

1. `backend/classifyos/preprocessing/preprocess.py`
2. `backend/tests/test_preprocess.py` (includes the dedicated leakage tests)

## Design — Preprocessor class (sklearn-style fit/transform)

```python
class Preprocessor:
    def __init__(self, config: dict): ...
    def fit(self, train_df: pd.DataFrame) -> "Preprocessor": ...
    def transform(self, df: pd.DataFrame) -> pd.DataFrame: ...
    def fit_transform(self, train_df: pd.DataFrame) -> pd.DataFrame: ...
    feature_names_out_: list[str]   # post-encoding column names
```

ALL statistics (imputation values, outlier caps, encoder categories, target-encoding
means, scaler parameters) are computed in fit() from the training data ONLY and stored
on the instance. transform() applies them to any DataFrame — train or test — without
recomputing anything. [RISK] comment at the top of the class: this fit/transform
separation IS the leakage guard; never call fit on data containing test rows.

The target column passes through untouched (never imputed, encoded, or scaled here).
The instance must be picklable (joblib) — needed later for /api/explain and reuse.

## Processing steps inside fit/transform (in this order)

1. **Missing values** — per config["missing_strategy"]:
   median / mean (numeric; mode for categorical in both cases), mode, ffill
   (fit stores fallback values for test rows where ffill has no prior row), drop
   (drop applies to TRAIN only in fit_transform; transform on test imputes with
   train medians/modes instead — never silently drop test rows; [RISK] comment why).
2. **Outlier capping** — numeric only. IQR method (1.5×IQR fences) computed on train;
   transform clips to the stored fences. Config key: `outlier_method`
   ("iqr" | "zscore" | "none", default "iqr"; zscore caps at ±3σ). ADD this key to
   DEFAULT_CONFIG in config.py with default "iqr" — this is the single sanctioned
   Phase 1 file edit; update build_config validation accordingly.
3. **Categorical encoding** — per config["encoding_method"]:
   - onehot: pd.get_dummies semantics via sklearn OneHotEncoder
     (handle_unknown="ignore" — unseen test categories become all-zeros;
     [RISK] comment on unseen categories).
   - label / ordinal: sklearn OrdinalEncoder with
     handle_unknown="use_encoded_value", unknown_value=-1.
   - target: mean-target encoding computed on TRAIN ONLY, with smoothing
     (m-estimate, m=10) to stabilize rare categories; unseen categories map to the
     global train target mean. [RISK]: target encoding is the most leakage-prone
     encoder — never compute on full data.
   - High-cardinality auto-switch: any categorical column with >20 unique values in
     train is target-encoded regardless of encoding_method (config key
     `high_cardinality_threshold`, default 20 — also add to DEFAULT_CONFIG).
     For multiclass targets, fall back to frequency encoding for these columns
     (target-mean is ill-defined across 3+ classes; document in docstring).
4. **Scaling** — per config["scaling_method"]: StandardScaler / MinMaxScaler /
   RobustScaler / none. Numeric columns only (post-encoding onehot 0/1 columns are
   NOT scaled). Fitted on train only.

Non-feature columns (IDs, the time_split_col): excluded from all processing and
dropped from the returned frame unless they are the target. feature_cols from config
defines what gets processed.

## Tests — test_preprocess.py (leakage tests are the heart of this phase)

Real CSVs from DATA_DIR. Required cases:

- **test_no_leakage_scaler**: fit on train split of policy_lapse; assert the stored
  scaler mean/scale equals values computed manually from train only — then poison the
  test split (multiply a numeric column ×1000), transform it, and assert the stored
  scaler parameters are unchanged.
- **test_no_leakage_target_encoding**: with encoding_method="target", assert encoded
  values for a category equal the smoothed TRAIN-only target mean, not the full-data
  mean (construct splits where the two differ).
- **test_unseen_category**: remove one occupation value from train, keep it in test;
  transform(test) succeeds; onehot → all-zeros row block; target → global train mean.
- **test_missing_strategies**: each of the 5 strategies runs on policy_lapse without
  error; "drop" never removes test rows.
- **test_outlier_capping**: an injected extreme value in test is clipped to the
  train-derived fence.
- **test_target_untouched**: will_lapse values identical before/after transform.
- **test_multiclass_high_cardinality**: risk_tier.csv with a synthetic 30-category
  column → frequency encoding applied, no exception.
- **test_picklable**: joblib.dump/load round-trip; transforms identically after load.
- Regression: FULL existing suite still passes.

## Process requirements

- Type hints + docstrings; [RISK] comments as specified.
- Verify sklearn encoder/scaler signatures against the installed version.
- Run full pytest suite; all green before finishing.
- Save this prompt to prompts/phase_03_preprocess.md.
- Update PROJECT_STATE.md: Ph.3 status, the pipeline-order decision, next steps
  (Phase 4: build_features + interactions — note they must follow the same
  fit/transform pattern).
- Commit as: "Phase 3: preprocessing with leakage guards — section 6 + tests"
