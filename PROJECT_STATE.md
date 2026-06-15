# ClassifyOS — Project State

> Living document. Updated at the end of every working session (by Claude Code or manually).
> A copy is uploaded to the ClassifyOS Claude Project knowledge after each update so the
> planning/overseer chat stays in sync with the local repo.

**Last updated:** 2026-06-15
**Updated by:** Claude Code (Phase 6 — model wrappers + registry + evaluation + classify)
**Repo tag / commit:** 33dc292 (Phase 5) + Phase 6 commit pending

---

## Current status

**Active phase:** Phase 6 complete — Models + evaluation (Sections 10–13)
**Sprint day:** Phase 6 done
**Overall:** 🟢 The engine can now train, score, and explain models end-to-end on the
balanced TRAIN matrices and evaluate on the untouched TEST set; full suite green

One-line summary: Sections 10–13 implemented. Section 11 — six model wrappers
(LogisticRegression, RandomForest, XGBoost, LightGBM, SVM, NaiveBayes) behind a single
`ModelWrapper` ABC, all sharing one `_SklearnEstimatorWrapper` template so the public
contract is identical regardless of library: `predict_proba` always returns
`(n, n_classes)` aligned to `classes_` (2 columns for binary), `predict` returns
original-space labels, `feature_importance` returns a dict or `None`. Section 12 —
`MODEL_REGISTRY` + `build_model` (canonical keys + short aliases LR/RF/XGB/LGBM/SVM/NB;
additive rule: new models added here only). Section 10 — `evaluate_model` returns one
JSON-serializable metrics dict (accuracy, weighted+macro precision/recall/F1 with
F1-weighted primary, ROC-AUC, PR-AUC, log-loss, MCC, confusion matrix, per-class report,
binary calibration curve), guarding undefined cases as `None`. Section 13 — `classify`
builds the per-sample predictions table (actual/predicted/probability_*/confidence/
correct_flag). class_weight is consumed uniformly via sample_weight translation (numeric-
string labels break sklearn's native class_weight-dict path); SVM uses
`CalibratedClassifierCV` (SVC probability= deprecated in 1.9); XGBoost label-encodes
internally. 117 tests passing (70 prior + 47 new). Ready for Phase 7 (plots + ModelRunner
+ CLI).

---

## Phase tracker

| Ph. | Milestone | Status | Notes |
|---|---|---|---|
| 0 | Repo + env setup, CLAUDE.md, sample CSVs in DATA_DIR | ✅ Done | Scaffold, StorageAdapter, venv+install, sample CSVs all in place |
| 1 | Framework skeleton (Sections 1–4, 9) | ✅ Done | config, inspect, loader, split + 22 tests passing on real samples |
| 2 | Feature analysis (Section 5) | ✅ Done | analyze_feature_impact + 5 tests on real samples; CSV + 2-panel PNG outputs |
| 3 | Preprocessing (Section 6) | ✅ Done | Preprocessor (fit/transform, train-only stats) + 14 tests incl. leakage suite |
| 4 | Feature engineering (Sections 7, 7B) | ✅ Done | FeatureBuilder + InteractionFeatureBuilder (fit/transform, train-only stats) + 19 tests incl. binning/auto-discovery leakage suite |
| 5 | Class balancing (Section 8) | ✅ Done | handle_class_imbalance (smote/undersample/class_weight/none, train-only) + 10 tests; SMOTE k_neighbors auto-guard + tiny-minority fallback; multilabel→class_weight |
| 6 | Models + evaluation (Sections 10–13) | ✅ Done | 6 wrappers via 1 ABC + MODEL_REGISTRY + evaluate_model + classify; 47 tests; xgboost/lightgbm added to deps |
| 7 | Plots + ModelRunner + CLI (Sections 14–16) | ⬜ Not started | ⚠️ CLI (Sec 16) must `load_dotenv()` at startup — engine code does NOT auto-load `.env`; without it `LocalFolderStorage` falls back to relative `data`/`classification_output` |
| 8 | FastAPI layer | ⬜ Not started | ⚠️ API startup must `load_dotenv()` (or rely on exported env) so DATA_DIR/OUTPUT_DIR/CORS_ORIGINS resolve — same fallback caveat as the CLI |
| 9 | React dashboard (13 pages) | ⬜ Not started | Deviation from scope: React replaces single-file HTML |
| 10 | Unit tests (full pytest suite) | ⬜ Not started | |
| 11 | Integration: 7 use cases E2E + governance sign-off | ⬜ Not started | |

Status legend: ⬜ Not started · 🔄 In progress · ✅ Done · ⚠️ Blocked

---

## Decisions log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-12 | Split classification_framework.py into modules instead of one 16-section file | Maintainability; enforces "additive sections" via module boundaries; better for GenAI iteration |
| 2026-06-12 | React (Vite + TS) frontend instead of single-file classify_ui.html | 13 pages too large for one file; future integration into Sapiens website |
| 2026-06-12 | StorageAdapter abstraction for all file I/O | Local DATA_DIR/OUTPUT_DIR folders now → Databricks (Unity Catalog volumes) later, drop-in swap |
| 2026-06-12 | CORS allowlist via env var, /api/v1/ route prefix, auth middleware stub | Gateway/SSO readiness for Sapiens website integration |
| 2026-06-12 | `binary_cols` overlaps `numeric_cols`/`categorical_cols` in inspect_file | A 0/1 col (e.g. has_agent) is both numeric and binary; UI uses the binary flag for special handling without losing the dtype categorization |
| 2026-06-12 | Loader coerces target to string dtype | Guarantees the target is never treated as a continuous float by sklearn; stratify/value_counts work uniformly across binary/multiclass |
| 2026-06-12 | DATA_DIR set to `./data/samples`; added openpyxl+pyarrow | Sample CSVs live there; loader supports .xlsx/.parquet so the optional readers are now required deps |
| 2026-06-12 | Datetime detection guarded by separator check | Prevents ID columns (POL100000) from being misread as dates while still catching policy_start_date |
| 2026-06-12 | DATA_DIR/OUTPUT_DIR moved outside the repo (`C:/Projects/classifyos_data/{input,output}`) | Keep datasets + artifacts out of git; `.env` is gitignored so paths are machine-local. Committed `backend/data/samples/` stays as the portable seed |
| 2026-06-12 | Test suite redirects OUTPUT_DIR to a pytest temp dir (`tmp_path_factory`); reads still use the real DATA_DIR | Tests must never pollute the real output folder with artifacts. `conftest.storage` depends on the temp-`output_dir` fixture so the override lands before `LocalFolderStorage` reads the env var |
| 2026-06-12 | **Pipeline order corrected: split moved before preprocessing** so encoder/scaler/imputer can be fitted on the training split only, as the scope's own leakage rule requires. Canonical order (ModelRunner, Phase 7): loader → feature impact (raw) → split → preprocess (fit train / transform both) → build_features → interactions → balance (train only) → train/evaluate → save/plots | The scope document's 8-step order (preprocess at step 3, split at step 6) contradicts its own leakage rule ("scaler fitted on train split only") |
| 2026-06-12 | Added `outlier_method` ("iqr" default) and `high_cardinality_threshold` (20) to DEFAULT_CONFIG — the single sanctioned Phase 1 edit of Phase 3 | Outlier capping and the high-cardinality encoder auto-switch are Section 6 tunables; defaults must live in the one config contract |
| 2026-06-12 | Preprocessor scales ORIGINAL numeric feature columns only; encoder outputs (onehot 0/1, ordinal codes, target/frequency means) are never scaled. High-cardinality (and `encoding_method="target"`) columns on non-binary targets fall back to frequency encoding | Scaling indicators destroys their interpretation; target-mean encoding is ill-defined across 3+ classes |
| 2026-06-12 | `missing_strategy="drop"` drops rows in `fit_transform` (train) only; `transform` always imputes with train medians/modes and never drops rows | Dropping test rows would corrupt evaluation and is impossible at prediction time — every row needs a prediction |
| 2026-06-12 | Sections 7/7B built as picklable fit/transform classes (`FeatureBuilder`, `InteractionFeatureBuilder`), not the scope's plain functions | Train-only fitting of the poly ranking, ratio denominator, bin edges, and MI auto-discovery requires a fit/transform split (same rationale as the Preprocessor); also enables `/api/explain` reuse |
| 2026-06-12 | Section 7 does NOT do categorical/frequency encoding — consolidated in the Preprocessor (Section 6) | Scope listed frequency encoding in both sections; double-encoding is wrong. Section 7 builds poly/ratio/bin features only |
| 2026-06-12 | Polynomial features default **OFF**, capped at `max_poly_features` (ranked by \|train corr\| with target) | Squared terms are usually redundant with tree models and explode width/multicollinearity; cap prevents column explosion |
| 2026-06-12 | Interaction auto-discovery: candidate pool capped at the 15 most target-correlated numeric cols; MI-gain scored on the multiplicative term; kept pairs materialized with `default_interactions` ops; pair list + ops FIXED at fit time | Bounds O(n²) pair explosion; re-discovery on test would be leakage. Trade-off: a strong pair outside the top-15 pool can be missed |
| 2026-06-12 | `feature_engineering` sub-dict added to `DEFAULT_CONFIG` (`enabled`/`polynomial`/`ratios`/`binning`/`max_poly_features`) — the single sanctioned Phase 4 config edit | Section 7 toggles must live in the one config contract; validated alongside the existing keys |
| 2026-06-12 | FeatureBuilder heuristic ratio denominator = numeric col with largest \|train median\|; near-zero denominator → 0.0 (guard) | After standard scaling medians sit near 0, so the heuristic is weakly determined; the per-row guard prevents inf. Explicit interaction_pairs (7B) are the reliable path |
| 2026-06-15 | Section 8 `handle_class_imbalance` is a pure function (not a fit/transform class) taking `(X_train, y_train, config)` and returning `(X_res, y_res, class_weight)` — no test argument exists | Balancing has nothing to apply to the test set (test is never resampled/reweighted); the train-only contract is enforced structurally by the signature, so a stateful transform would be misleading |
| 2026-06-15 | SMOTE `k_neighbors` auto-reduced to `min(5, minority_count-1)`; `minority_count<=1` → `RandomOverSampler` fallback (logged) | SMOTE errors when `k_neighbors >= minority_count` and cannot interpolate from a single point; fraud (~99:1) routinely hits small minorities. Auto-guard keeps the pipeline from crashing on extreme ratios |
| 2026-06-15 | Multilabel + smote/undersample → fall back to `class_weight` with a warning | A multilabel row carries several labels at once, so there is no single class to over/undersample on; imbalanced-learn's samplers expect a 1-D label. v1.0 defers multilabel resampling (plan_tweak) |
| 2026-06-15 | Six model wrappers share ONE `_SklearnEstimatorWrapper` template base (provides fit/predict/predict_proba/feature_importance); concrete wrappers only declare `name` + `_build_estimator` | DRY — the contract (proba shape/order, original-label predict, importance dict-or-None) is implemented once and cannot drift between models; new models are a class + a registry entry (additive rule) |
| 2026-06-15 | `class_weight` consumed UNIFORMLY via sample_weight translation for every wrapper (not the native `class_weight` dict for LR/RF/SVM/LGBM) | The loader coerces targets to string dtype, so numeric labels arrive as `"0"/"1"`; sklearn's native class_weight-dict path int-coerces them and fails to find the string keys (`ValueError: classes [0,1] are not in class_weight`). A per-sample weight vector is equivalent and library-agnostic |
| 2026-06-15 | SVM wrapper uses `CalibratedClassifierCV(SVC(), ensemble=False)` for probabilities; `feature_importance` → `None` | `SVC(probability=True)` is deprecated in scikit-learn 1.9 and removed in 1.11; the calibrated wrapper is the sanctioned replacement and exposes no coefficients (None is correct for the default RBF kernel anyway) |
| 2026-06-15 | XGBoost wrapper label-encodes `y` to `0..n-1` internally and maps predictions back | `XGBClassifier` 3.2.0 rejects non-consecutive/string labels (`Invalid classes inferred from unique values of y`); the engine's targets are strings, so encoding is mandatory |
| 2026-06-15 | Added `xgboost` (3.2.0) + `lightgbm` (4.6.0) to deps; pinned all versions in `backend/requirements.lock` (`pip freeze`) | The two boosting wrappers require these libraries (not previously installed/listed); the lock file is the governance reproducible-env record |

---

## Completed this session (Phase 1 — 2026-06-12)

- **Section 1–2** `backend/classifyos/config.py`: `DEFAULT_CONFIG` + `build_config()`
  with full validation (required fields, feature_cols ≥1, target∉features, test_size in
  (0,0.5], enum checks, unknown-key rejection). Deep-copies defaults; `[RISK]` comment on
  config mutation (root of the `_run_config` isolation pattern).
- **Section 3** `backend/classifyos/io/inspect.py`: `inspect_file()` returning the locked
  contract keys (columns, dtypes, numeric/categorical/binary/datetime cols, n_rows,
  n_missing, NaN→None sample, optional class_distribution + suggested_problem_type).
  Datetime detection by dtype/name-pattern/separator heuristic.
- **Section 4** `backend/classifyos/io/loader.py`: `data_loader()` — CSV/xlsx/parquet via
  StorageAdapter, validates file/target/features/≥2 classes, parses time_split_col,
  coerces target to str. `[RISK]` comment + warning on dropping target-NaN rows.
- **Section 9** `backend/classifyos/split.py`: `train_test_split_cls()` — stratified random
  split (default) or temporal last-fraction split when time_split_col set; non-stratified
  fallback for singleton classes. `[RISK]` comment on temporal leakage.
- **Tests**: `tests/conftest.py` (loads .env, normalizes DATA_DIR, storage fixtures) +
  test_config/test_inspect/test_loader/test_split. **22 passed** on the real sample CSVs.
- Generated sample CSVs into `DATA_DIR` via `scripts/generate_sample_data.py`
  (policy_lapse 3000, fraud_claims 8000 @ ~1%, risk_tier 3000 multiclass).
- Created `backend/.env`, `backend/pytest.ini`; added openpyxl+pyarrow to requirements.
- Archived this session's prompt to `prompts/phase_01_skeleton.md`.
- Hallucination check ✅ — verified against pandas 2.3.3 / scikit-learn 1.9.0 in the venv.

## Completed this session (Phase 2 — 2026-06-12)

- **Section 5** `backend/classifyos/analysis/feature_impact.py`:
  `analyze_feature_impact(df, config, storage)` — ranks every configured feature by its
  raw association with the target (runs on the raw loaded DataFrame, before preprocessing):
  - **ANOVA F-score/p** (`scipy.stats.f_oneway`, numeric only, grouped by class).
  - **Mutual information** (`sklearn.feature_selection.mutual_info_classif`, all features;
    categoricals label-encoded in-memory for MI only — encoding never leaks out;
    `discrete_features` set per column type; `random_state` from config).
  - **Point-biserial** (binary + numeric) / **correlation ratio eta** (multiclass + numeric,
    `corr_ratio` column, formula documented in docstring).
  - **Composite score**: min-max normalize each available metric across features (point-biserial
    by magnitude), mean of available normalized metrics; result sorted desc + 1-based `rank`.
  - Pairwise NaN dropping per (feature, target) — no imputation, input df never mutated.
  - `id_like` boolean flag for ≥99%-unique columns (e.g. policy_id) — leakage-bait, flagged not dropped.
  - Returned columns locked to the contract: `feature, dtype_group, anova_f, anova_p,
    mutual_info, point_biserial, corr_ratio, composite_score, id_like, rank`.
- **Outputs** (both via StorageAdapter to OUTPUT_DIR): `feature_impact_summary.csv` and
  `plot4_feature_impact.png` (Agg backend set before pyplot; 2-panel — composite barh top-20 +
  grouped normalized metrics top-10; white facecolor, dark text, dpi=150, figure closed after save).
- **Tests** `tests/test_feature_impact.py` (5): binary lapse metric applicability + id_like;
  multiclass risk (point-biserial all-NaN, corr_ratio populated, is_smoker top-5); outputs exist
  & PNG >10 KB; input-not-mutated; zero-variance feature handled. **27 passed** total (no regressions).
- **[RISK] comments** added: raw-data screening caveat (not a final selection authority) and
  ID-column MI leakage-bait. Hallucination check ✅ — verified `f_oneway`/`pointbiserialr`/
  `mutual_info_classif` signatures against scipy 1.17.1 / sklearn 1.9.0 / matplotlib 3.11.0 in venv.
- Archived this session's prompt to `prompts/phase_02_feature_impact.md`.

## Completed this session (Phase 3 — 2026-06-12)

- **Section 6** `backend/classifyos/preprocessing/preprocess.py`: `Preprocessor` class,
  sklearn-style `fit` / `transform` / `fit_transform` + `feature_names_out_`:
  - ALL statistics (imputation values, outlier fences, encoder categories,
    target-encoding means, scaler parameters) computed in `fit()` from TRAIN only,
    stored on the instance; `transform()` only applies, never recomputes.
  - **Missing values**: median / mean (categoricals → mode in both) / mode / ffill
    (stored train fallbacks for rows with no prior row) / drop (train-only in
    `fit_transform`; `transform` imputes instead — test rows are never dropped).
  - **Outlier capping**: IQR 1.5× fences (default) or z-score ±3σ, computed on the
    imputed train, applied as `clip` in transform.
  - **Encoding**: OneHotEncoder(`handle_unknown="ignore"`, unseen → all-zeros block) /
    OrdinalEncoder(`unknown_value=-1`) / smoothed target encoding (m-estimate, m=10;
    unseen → global train mean; positive class = lexicographically last label).
    High-cardinality auto-switch (>20 train uniques → target encoding); non-binary
    problems fall back to frequency encoding (target-mean ill-defined for 3+ classes).
  - **Scaling**: standard / minmax / robust / none; original numeric columns only,
    encoder outputs never scaled.
  - Target passes through untouched (appended last when present); non-feature columns
    (IDs, `time_split_col`) dropped; input frames never mutated; index preserved;
    instance picklable via joblib (for `/api/explain` reuse).
- **Sanctioned config edit**: `outlier_method` ("iqr") + `high_cardinality_threshold`
  (20) added to `DEFAULT_CONFIG` with validation (enum check; positive-int check).
- **Tests** `tests/test_preprocess.py` (14): poisoned-test-set scaler leakage check,
  train-only target-encoding mean (vs full-data mean on a deliberately skewed split),
  unseen category (onehot all-zeros + target global-mean), all 5 missing strategies
  (drop never removes test rows; ffill leading-NaN fallback), train-fence outlier
  clipping on a 1e9 injection, target untouched, multiclass 30-level frequency
  fallback, joblib round-trip, new config-key validation, input-frame immutability.
  **41 passed** total — no regressions.
- **[RISK] comments** (4): fit/transform separation as THE leakage guard (class
  docstring); target encoding most leakage-prone; onehot unseen categories =
  train/serve-skew signal; transform-never-drops rationale.
- Hallucination check ✅ — `OneHotEncoder(sparse_output=...)`,
  `OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)` and scaler
  signatures verified against sklearn 1.9.0 in the venv.
- Archived this session's prompt to `prompts/phase_03_preprocess.md`.

## Completed this session (Phase 4 — 2026-06-12)

- **Section 7** `backend/classifyos/preprocessing/features.py`: `FeatureBuilder` class,
  sklearn-style `fit(train_df, target)` / `transform` / `fit_transform` +
  `created_features_`:
  - **Polynomial** (default OFF): squared companion `{col}_sq` for the top
    `max_poly_features` numeric columns ranked by |train correlation| with the
    label-encoded target. `[RISK]` cap comment on column explosion.
  - **Ratios** (default ON): each numeric col ÷ the numeric col with the largest
    |train median| → `{num}_div_{denom}`; near-zero denominator guarded → 0.0 (no inf).
  - **Binning** (default ON): numeric cols with |train skew| > 1.5 (and ≥5 distinct
    values) get a 5-bin quantile companion `{col}_bin` (ordinal ints); bin edges
    computed on TRAIN only, outer edges opened to ±inf so test extremes clip into the
    outer bins. Original column kept.
  - No categorical/frequency encoding here (consolidated in the Preprocessor).
    Input frame and config never mutated; picklable.
- **Section 7B** `backend/classifyos/preprocessing/interactions.py`:
  `InteractionFeatureBuilder` (fit/transform) + `interaction_cols_` / `pairs_used_`:
  - **Explicit pairs** via `interaction_pairs` ("a+b" → multiply|ratio|diff|auto|all);
    contract-level naming `a_x_b` / `a_div_b` / `a_minus_b`.
  - **Auto-discovery**: candidate pool = 15 most target-correlated numeric cols, all
    unordered pairs scored by MI gain = MI(product, target) − max(MI(a), MI(b)) on
    TRAIN; positive-gain pairs kept, top `max_auto_pairs`; pair list + ops FIXED at
    fit. `[RISK]` comments on O(n²) pool cap and on re-discovery-as-leakage.
  - **Ratio guard**: |denom| < 1e-9 → NaN → filled per `fill_method`
    (zero → 0.0 / median → stored train median / nan → left).
  - `drop_original_if_interacted` drops interacted source cols AFTER all interactions
    (target never dropped). Input frame + config never mutated.
  - **`plot_interaction_summary(df, target, interaction_cols, storage)`** writes
    `plot6_interaction_summary.png` (Agg, dpi=150, white facecolor, figure closed
    after save, via StorageAdapter) — horizontal |corr|-with-target bars.
- **Sanctioned config edit**: `feature_engineering` sub-dict added to `DEFAULT_CONFIG`
  with a `_validate_feature_engineering` check (bool flags; positive-int
  `max_poly_features`). `interaction_features` already existed from Phase 1.
- **Tests** `tests/test_features.py` (9) + `tests/test_interactions.py` (10): naming
  conventions, "all"-op expansion, binning fires on fraud `claim_amount` (skew ≈ 11.3
  with capping off), binning edges survive a poisoned test set (extremes → outer bins),
  auto-discovery pairs frozen across a poisoned/scrambled test transform,
  `max_auto_pairs` respected, ratio zero-guard under zero + median fill, drop-original,
  polynomial off-by-default + capped, enabled=False passthrough, config + input-frame
  immutability, plot6 PNG > 10 KB. **60 passed** total — no regressions.
- Hallucination check ✅ — `mutual_info_classif`, `scipy.stats.skew`, `pandas.qcut`
  signatures verified against sklearn 1.9.0 / scipy 1.17.1 / pandas 2.3.3 in the venv.
- Archived this session's prompt to `prompts/phase_04_feature_engineering.md`.

## Completed this session (Phase 5 — 2026-06-15)

- **Section 8** `backend/classifyos/preprocessing/balance.py`:
  `handle_class_imbalance(X_train, y_train, config) -> (X_res, y_res, class_weight)` —
  a pure function (no test argument by design; train-only is structural):
  - **smote**: imbalanced-learn `SMOTE`. `k_neighbors` auto-reduced to
    `min(5, minority_count - 1)` when the minority is small (logged); `minority_count <= 1`
    → `RandomOverSampler` fallback (logged — duplicates, no synthetic variety). Returns
    `class_weight=None`.
  - **undersample**: `RandomUnderSampler`; returns `class_weight=None`; logs how many
    majority rows were dropped.
  - **class_weight**: NO resampling — returns the inputs plus a `"balanced"` dict
    (`sklearn.utils.class_weight.compute_class_weight`, one entry per class). The ONLY
    strategy returning a non-`None` weight; the model applies it during training so the
    test set is never altered.
  - **none**: inputs returned unchanged, `class_weight=None`.
  - **Multilabel** (`problem_type="multilabel"`) + smote/undersample → falls back to
    `class_weight` with a logged warning (resampling unsupported in v1.0).
  - Always a 3-tuple; `X_res` columns identical to `X_train` (order re-imposed defensively
    in `_coerce`); inputs and config never mutated (works on copies). Unknown
    `class_balance` raises `ValueError`.
- **[RISK] comments** (4): module-level + per-strategy — train-only-by-design as THE
  leakage guard; tiny-minority synthetic realism (random-oversample fallback);
  undersampling discards majority data; multilabel resampling unsupported.
- **Tests** `tests/test_balance.py` (10): SMOTE lifts fraud's ~1% minority to parity;
  test arrays untouched (and never passed in); tiny-minority guards (count=3 →
  k_neighbors reduced; count=1 → random-oversample fallback, warnings asserted via
  caplog); undersample drops majority / keeps minority / logs dropped count; class_weight
  no-resample + one-entry-per-class (+ smote/undersample give `None`); none passthrough;
  multiclass risk_tier SMOTE balances all 3 classes; column-order preserved;
  config+input immutability across all 4 strategies; invalid-strategy `ValueError`.
  **70 passed** total (60 prior + 10 new) — no regressions.
- Hallucination check ✅ — verified against **imbalanced-learn 0.14.2** / **sklearn 1.9.0**
  in the venv: `SMOTE(*, sampling_strategy, random_state, k_neighbors=5)`,
  `RandomUnderSampler(*, sampling_strategy, random_state, replacement)`,
  `RandomOverSampler(...)`, `compute_class_weight(class_weight, *, classes, y)`.
- Archived this session's prompt to `prompts/phase_05_class_balance.md`.

## Completed this session (Phase 6 — 2026-06-15)

- **Section 11** `backend/classifyos/models/base.py` + `wrappers.py`: the `ModelWrapper`
  ABC (fit/predict/predict_proba/feature_importance, `name`, `classes_`) and six concrete
  wrappers — `LogisticRegressionModel`, `RandomForestModel`, `XGBoostModel`,
  `LightGBMModel`, `SVMModel`, `NaiveBayesModel` — all sharing one
  `_SklearnEstimatorWrapper` template base. Contract held by every wrapper:
  - `predict_proba` ALWAYS returns `(n_samples, n_classes)` aligned to `classes_`
    (2 columns for binary, never 1; `(n, n_labels)` for multilabel via
    `OneVsRestClassifier`). `[RISK]` comment: the engine indexes proba columns by
    `classes_` everywhere downstream.
  - `predict` returns labels in the ORIGINAL string label space (XGBoost label-encodes
    internally and maps back).
  - `feature_importance` → `{feature: importance}` for trees (gain/split) and LR (mean
    |coef|); `None` for SVM (calibrated, no coef) and GaussianNB.
  - `class_weight` consumed uniformly as `sample_weight` (single-label) — never silently
    ignored.
- **Section 12** `backend/classifyos/models/registry.py`: `MODEL_REGISTRY` (6 canonical
  keys) + `build_model(name, problem_type, class_weight=None, random_state=42, **params)`;
  case-insensitive aliases (LR, RF, XGB, LGBM, SVM, NB, …); unknown name → `ValueError`
  listing every valid key. Additive rule enforced (new models added here only).
- **Section 10** `backend/classifyos/evaluation/metrics.py`: `evaluate_model(y_true,
  y_pred, y_proba, problem_type, classes)` → one JSON-serializable dict — accuracy,
  precision/recall/F1 (weighted **primary** + macro), ROC-AUC (binary standard /
  multiclass ovr-weighted / multilabel avg), PR-AUC (binary), log-loss, MCC, confusion
  matrix (nested list in `classes` order), per-class `classification_report`, and binary
  calibration-curve data. Undefined cases (single class present, non-binary calibration)
  guarded → `None`. `_jsonify` strips every numpy scalar (`json.dumps` always succeeds).
  `[RISK]` comment: accuracy misleads on imbalanced data → F1-weighted primary, MCC+PR-AUC
  emphasized.
- **Section 13** `backend/classifyos/predict.py`: `classify(model, X_test, y_test,
  classes)` → per-sample DataFrame with `actual`, `predicted`, `probability_<class>`
  (one per class), `confidence` (row-max proba), `correct_flag`; index aligned to
  `X_test`; binary/multiclass row probabilities sum to ~1.
- **Tests** (47 new): `test_models.py` (all-wrappers fit/predict on binary + multiclass,
  proba shape/alignment, class_weight consumed + actually shifts ≥1 model, tree
  feature-importance non-empty, SVM/NB importance None, bad problem_type raises),
  `test_registry.py` (six models, aliases resolve, unknown → ValueError listing keys,
  params forwarded), `test_metrics.py` (binary all-metrics + 2×2 + calibration + JSON,
  multiclass ovr-AUC + 3×3, fraud imbalanced MCC/AUC finite, single-class guards →
  None), `test_classify.py` (locked columns, row count, probs sum ~1, confidence bounds).
  Shared `conftest.build_matrices` runs the full Phase 1–5 pipeline (load → split →
  preprocess → features → interactions → balance) on the real CSVs; matrices subsampled
  for SVM-calibration speed. **117 passed** (70 prior + 47 new) — no regressions.
- **[RISK] comments**: proba shape/order engine-wide assumption (base + wrappers);
  accuracy-misleads-on-imbalance (metrics); SVM no-importance.
- Hallucination check ✅ — verified against the installed venv: **scikit-learn 1.9.0**
  (CalibratedClassifierCV+sample_weight, GaussianNB sample_weight, OvR.classes_,
  roc_auc/log_loss/calibration_curve signatures), **xgboost 3.2.0** (rejects string
  labels → internal LabelEncoder; fit sample_weight; feature_importances_),
  **lightgbm 4.6.0** (string labels OK; feature_importances_). `SVC(probability=True)`
  confirmed deprecated → switched to `CalibratedClassifierCV`.
- **Deps**: installed `xgboost==3.2.0` + `lightgbm==4.6.0`, added to `requirements.txt`,
  and pinned the full env in `backend/requirements.lock` (`pip freeze`).
- Archived this session's prompt to `prompts/phase_06_models_eval.md`.

## Completed this session (Doc-update enforcement hook — 2026-06-15)

- **`scripts/check_docs_updated.py`** (stdlib only, cross-platform): computes the
  session's changed files as the union of `git diff --name-only HEAD`,
  `git diff --name-only --cached HEAD`, and `git ls-files --others --exclude-standard`.
  - ENGINE changed = any path under `backend/classifyos/` → if so, requires BOTH
    `PROJECT_STATE.md` and `short_desc.md` in the changed set, else exit code 2 with a
    STDERR message naming the missing doc(s).
  - plan_tweak.md is a **non-blocking reminder** only (printed to STDERR, still exit 0)
    when the engine changed but the tweak register wasn't touched — it can't be judged
    mechanically, so forcing it would produce fake entries.
  - Fails open: not-a-git-repo / git errors / no HEAD → exit 0 (never block on tooling).
- **`.claude/settings.json`** (project scope, committed): registers a `Stop` hook
  running `python scripts/check_docs_updated.py`. Verified against Claude Code **2.1.177**
  hooks reference — `Stop` fires on turn end, takes no matcher, exit 2 prevents stopping
  and feeds STDERR back to Claude, exit 0 allows. Windows-safe (invoked via `python` + a
  repo-relative path; no bash-isms). CLAUDE.md is deliberately NOT in the check (it is the
  stable contract, not a per-session doc).
- **Verified behavior**: (A) engine edit + no doc update → BLOCKS (exit 2, names both
  docs); (B) engine edit + both docs updated → PASSES (exit 0, plan_tweak reminder shown);
  (C) doc-only change → PASSES (exit 0, no block). Throwaway engine edit reverted after.
- Prompt archived to `prompts/tool_doc_hook.md`.

## Completed earlier (scaffold session)

- Scaffolded full repo structure from the CLAUDE.md module map:
  - `backend/classifyos/` with subpackages `io/`, `analysis/`, `preprocessing/`,
    `evaluation/`, `models/` — all with empty `__init__.py`. No pipeline sections
    generated yet (intentional — packages only).
  - `backend/api/` + `backend/api/routes/`, `backend/tests/` (with `__init__.py`).
  - `prompts/`, `docs/`, `data/samples/`.
- `backend/classifyos/io/storage.py`: `StorageAdapter` ABC + `LocalFolderStorage`
  implementation reading `DATA_DIR`/`OUTPUT_DIR` from env. Reads resolve under the
  data root, writes under the output root; path-traversal escapes are rejected.
  Smoke-tested against installed Python 3.11 (read/write/list/exists/traversal-block
  all pass) — hallucination check ✅ (stdlib only).
- `backend/requirements.txt` (FastAPI, uvicorn, pydantic v2 + settings, pandas, numpy,
  scikit-learn, imbalanced-learn, matplotlib, joblib, pytest, httpx; loose bounds,
  to be pinned via `pip freeze`).
- `backend/.env.example` (`DATA_DIR`, `OUTPUT_DIR`, `CORS_ORIGINS`).
- `.gitignore` (.venv, node_modules, classification_output, .env, __pycache__, etc.).
- `docs/api_contract.md` stub (clearly marked NOT LOCKED until Phase 8).
- `frontend/` scaffolded with Vite + React + TypeScript (`react-ts` template);
  `vite.config.ts` extended with `/api → http://localhost:8000` dev proxy.

## In progress / partially done

- Nothing in flight. Phase 6 closed; Phase 7 (Sections 14–16 — plots + ModelRunner + CLI) not yet started.

## Known issues / bugs

| # | Issue | Severity | Found | Status |
|---|---|---|---|---|
| | none | | | |

## Blockers

- None. Sample CSVs are in `DATA_DIR`; venv installed; tests green.

---

## Next steps (priority order)

1. Commit Phase 6 ("Phase 6: model wrappers + registry + evaluation + classify — sections 10-13 + tests").
2. Upload updated PROJECT_STATE.md to the Claude Project knowledge.
3. Phase 7 generation session: Sections 14–16 — `plot_results` (`evaluation/plots.py`:
   confusion-matrix / ROC / PR / calibration / feature-importance PNGs via the Agg
   backend + StorageAdapter), `ModelRunner` (`runner.py`: orchestrates the canonical
   order load → impact → split → preprocess → features → interactions → balance → train
   each algorithm → evaluate → classify → plots; deep-copies config per run, never
   mutates `self.config`), and the CLI (`cli.py`: `--inspect`/run modes; **must
   `load_dotenv()` at startup** — engine code does not auto-load `.env`).
4. Wire the model layer into the runner: `build_model` for each `config["algorithms"]`
   entry, pass the Phase 5 `class_weight` through, evaluate on the untouched test set.

---

## API contract status

`/api/v1/run` response schema: **NOT LOCKED** (locks after Phase 8).
Contract doc: docs/api_contract.md — stub only.

## Governance checklist (from scope §12)

- [x] Prompt version control — prompts/ populated per section (phase_01_skeleton.md, phase_02_feature_impact.md, phase_03_preprocess.md, phase_04_feature_engineering.md, phase_05_class_balance.md, phase_06_models_eval.md archived)
- [x] Section-level unit tests passing on real data (117 passing: 22 Phase 1 + 5 Phase 2 + 14 Phase 3 + 19 Phase 4 + 10 Phase 5 + 47 Phase 6)
- [ ] [RISK] comments reviewed by team lead (3 Phase 1 + 2 Phase 2 + 4 Phase 3 + Phase 4 poly-cap/ratio-denominator/auto-discovery-pool/re-discovery-leakage + 4 Phase 5 train-only/tiny-minority/undersample-discards/multilabel + Phase 6 proba-shape-order/accuracy-misleads/SVM-no-importance, pending review)
- [ ] Leakage audit (encoder/scaler/SMOTE train-only) confirmed — encoder/scaler/imputer (Phase 3), feature-engineering/interaction stats (Phase 4) and balancing (Phase 5) all train-only, enforced by design + dedicated leakage tests (binning edges, MI auto-discovery, test-set-untouched). SMOTE/undersample are train-only by construction (the balancer takes no test argument). Phase 6 models fit on the balanced TRAIN matrices only; evaluate_model/classify only ever read the untouched test set
- [ ] Output schema contract locked (post Phase 8)
- [x] Hallucination check — library calls verified against installed versions (Phase 1: pandas 2.3.3 / sklearn 1.9.0; Phase 2: scipy 1.17.1 / sklearn 1.9.0 / matplotlib 3.11.0; Phase 3: sklearn 1.9.0 encoders/scalers; Phase 4: mutual_info_classif / scipy.stats.skew / pandas.qcut; Phase 5: imbalanced-learn 0.14.2 SMOTE/RandomUnderSampler/RandomOverSampler, sklearn 1.9.0 compute_class_weight; Phase 6: sklearn 1.9.0 CalibratedClassifierCV/GaussianNB sample_weight/OvR/roc_auc/log_loss/calibration_curve, xgboost 3.2.0 string-label rejection + sample_weight, lightgbm 4.6.0) — all versions pinned in backend/requirements.lock
- [ ] Team lead sign-off per phase (Naveen)

---

## Session log

| Date | Session focus | Outcome |
|---|---|---|
| 2026-06-12 | Project setup, structure decisions, templates created | CLAUDE.md + PROJECT_STATE.md created |
| 2026-06-12 | Repo scaffold (dirs, StorageAdapter, requirements, env, gitignore, Vite frontend) | Structure ready; no pipeline sections yet |
| 2026-06-12 | Phase 1 — Sections 1–4, 9 (config, inspect, loader, split) + tests | 22 tests passing on real samples; sample data generated; prompt archived |
| 2026-06-12 | Phase 2 — Section 5 (analyze_feature_impact) + tests | 27 tests passing; CSV + 2-panel PNG outputs; prompt archived |
| 2026-06-12 | Phase 2 follow-up — env docs, dotenv notes, test output isolation | DATA_DIR/OUTPUT_DIR moved outside repo; conftest writes to temp OUTPUT_DIR; CLAUDE.md + .env.example updated; 27 tests still green |
| 2026-06-12 | Phase 3 — Section 6 (Preprocessor) + leakage test suite | 41 tests passing; pipeline-order correction recorded; config gains outlier_method + high_cardinality_threshold; prompt archived |
| 2026-06-12 | Docs backfill — created short_desc.md + plan_tweak.md (Phases 0–3) | Plain-language phase summaries + deviation register added; CLAUDE.md working-style updated to maintain both per phase going forward |
| 2026-06-12 | Phase 4 — Sections 7 + 7B (FeatureBuilder, InteractionFeatureBuilder) + tests | 60 tests passing; feature_engineering config sub-dict added; binning/auto-discovery leakage tests + plot6 artifact; prompt archived; plan_tweak rows 12–17 added |
| 2026-06-15 | Tooling — Stop hook enforcing PROJECT_STATE + short_desc updates on engine changes | `scripts/check_docs_updated.py` + `.claude/settings.json` Stop hook; verified block/pass/doc-only cases against v2.1.177; prompt archived |
| 2026-06-15 | Phase 5 — Section 8 (`handle_class_imbalance`) + tests | 70 tests passing; smote/undersample/class_weight/none train-only; SMOTE k_neighbors auto-guard + tiny-minority fallback; multilabel→class_weight; prompt archived; plan_tweak rows 18–19 added |
| 2026-06-15 | Phase 6 — Sections 10–13 (6 wrappers + registry + evaluate_model + classify) + tests | 117 tests passing (47 new); ModelWrapper ABC + shared template base; class_weight→sample_weight uniform; SVM via CalibratedClassifierCV; XGBoost internal label-encode; xgboost/lightgbm added + requirements.lock pinned; prompt archived; plan_tweak rows 20–22 added |
| | | |
