# ClassifyOS — Project State

> Living document. Updated at the end of every working session (by Claude Code or manually).
> A copy is uploaded to the ClassifyOS Claude Project knowledge after each update so the
> planning/overseer chat stays in sync with the local repo.

**Last updated:** 2026-06-25
**Updated by:** Claude Code (**TEMPORARY — interaction features unwired**. By request, Section 7B
interaction features were temporarily removed from training and hidden from the UI (NOT deleted —
fully reversible). **Engine:** `ModelRunner._engineer` now force-disables `interaction_features`
on the deep-copied run config regardless of the incoming request, so `InteractionFeatureBuilder`
short-circuits (no pairs, transform returns a copy) and `plot6_interaction_summary.png` is no
longer written; `result.run.interaction_cols` comes back empty — **the LOCKED schema 1.0/1.1 is
unchanged** (the field still exists, just `[]`). **UI:** the Interaction-features config card
(`Configure.tsx`), the sidebar nav entry (`nav.ts`), and the `/interactions` route+import
(`App.tsx`) are commented out; `/interactions` now redirects to `/`. The `Interactions.tsx` page
and `results.ts` decoders are left intact (unreferenced) for trivial restore. **Tests updated**
to match: `test_runner` (no `_x_`/`_minus_` interaction cols; plot6 absent), `test_use_case_sweep`
(plot6 dropped from the expected set, now 10). All 48 affected backend tests green; frontend
`tsc -b` clean. plan_tweak 42. **Caveat:** the API's `interaction_cols` heuristic still matches
the `_div_` marker, which is ALSO used by the Section 7 `FeatureBuilder` ratio features — so when
`feature_engineering.ratios` is on, a ratio column like `a_div_b` can still surface in
`interaction_cols`; this is pre-existing marker imprecision, unchanged by this work, and harmless
now that the Interactions page is hidden. **To re-enable:** delete the force-disable line in
`_engineer`, restore the plot6 call + the three UI comment blocks, and revert the test edits.
**This unwiring is now logged in `unwire.md`** (repo root) — the living registry of
temporarily-disabled features, carrying for each entry a one-line summary, a short description,
and the exact wire-back steps. Add a new section there whenever a feature is unwired; mark
entries **Restored** with a date rather than deleting them.)
**Prior update:** 2026-06-23
**Updated by:** Claude Code (Phase 16 — **UI-only**: a **feature-builder panel** on the
Configuration page where analysts build the `user_features` specs the API accepted in Phase 15 —
entirely from **dropdowns**, never a free-text formula (the engine's no-eval safety contract carried
to the UI). New `UserFeatureSpec`/`UserFeatureType` types + `user_features` on `RunConfig` (mirror the
contract exactly); `user_features` added to `ConfigFormState`/`DEFAULT_FORM_STATE` (`[]`) +
`buildPayload`; new controlled `components/config/FeatureBuilderPanel.tsx` (type selector → numeric
`[col_a][op][col_b]` / single `[transform][col]` / datetime_diff `[end][start][unit]`; typed column
dropdowns filtered by inspect; client-side name validation: non-empty + unique vs existing columns
and added features; removable rows with a readable, formula-free label) wired into
`pages/Configure.tsx`. An invalid spec's **422** surfaces via the existing `ApiError`→Overview path
(no crash). +9 vitest (**91 total**); `npm run build` clean. No plan_tweak deviation — realises the
request field added in Phase 15.)
**Prior update (same day):** Phase 15 — **API-only, request-side**: exposed `user_features` on the
`/api/v1/run` REQUEST so the dashboard can send user-defined feature specs. New `UserFeatureSpec`
Pydantic sub-model + optional `RunConfig.user_features` (default `[]`); a fast-fail 422 allowlist
check (unknown `type`/`op`, or a two-column type missing `col_b`) mirrors the engine's
`USER_FEATURE_*` constants (imported, not duplicated); `to_engine_config` dumps each spec with
`exclude_none` and forwards it to `build_config` (the authoritative validator). **No response
change and NO version bump** — the created columns are real engineered columns that already
surface in `result.run.active_features` (verified end-to-end). +5 API tests (**237 backend
pytest**). plan_tweak 41. UI follow-up is a separate session.)
**Prior update (same day):** Phase 14 — **engine-only**: USER-DEFINED structured features.
New leakage-safe `UserFeatureBuilder` (`preprocessing/user_features.py`) + sanctioned
`user_features` config key (default `[]`, OFF) + sanctioned ModelRunner edit. Users specify
new columns as STRUCTURED specs — `[col_a] + [op from a fixed allowlist] + [col_b]` or a
single-column transform — **NEVER a free-text formula** (no `eval`/`exec`; [RISK]-marked). Ops:
numeric `add/subtract/multiply/divide/ratio`, `datetime_diff` (duration in s/min/h/days), and
single `log/abs/bin` + date-parts `year/month/day/dayofweek/hour`. Same train-only fit/transform
leakage discipline as FeatureBuilder; invalid specs skipped+logged (run never aborts); name
collisions refused. **Design call:** the builder reads source columns from the RAW post-split
frame (outputs still inject after FeatureBuilder, before interactions) because the Preprocessor
scales numerics and encodes/drops datetime columns — so post-preprocessing `datetime_diff` is
impossible. +24 tests (**232 backend pytest**). plan_tweak 40. API/UI = separate follow-ups.)
**Prior update (same day):** Phase 13 — **UI-only**: dedicated **Tuning Results** page consuming
the schema-1.1 `result.tuning` block. New `RunTuning` type + optional `tuning` on `RunResult`
(mirrors the contract exactly), `pages/TuningResults.tsx` (no-run / tuning-OFF / tuning-ON
states, one card per tuned model + "ran on defaults" note + defensive `unknown`-value rendering),
route `/tuning` + sidebar entry (nav 12 → **13**). Zero engine/API change; reads the store, no
new network call. +10 vitest (**82 total**); build clean. No plan_tweak deviation — this realises
the 1.1 field added in Phase 12.)
**Prior update (same day):** Phase 12 — additive API change: surfaced the per-model tuned
hyperparameters on the `/api/v1/run` response as a new optional `result.tuning` block; first
version bump of the locked contract `1.0` → `1.1`, done additively. Zero engine change. plan_tweak 39
**Prior update (same day):** Phase 7B.2 — expanded three Optuna search spaces from the
read-only tuning audit: LightGBM `max_depth`, XGBoost `gamma`, SVM real+conditional `kernel`.
Engine refinement of the existing tuning layer; no scope deviation. 206 backend pytest green

**Prior update:** 2026-06-21 — Phase 11 (FINAL): multilabel wired end-to-end (Product
Recommendation), 7-use-case E2E sweep (engine+API+browser), 12k-row performance baseline,
tuning sanity, governance dossier — **Phase 11 engineering complete; v1.0 ready for
sign-off/demo**
**Repo tag / commit:** 4ef560b (Phase 10) + Phase 11 commit pending. **v1.0 tag pending the
human sign-offs/demo.**

---

## Current status

**🎯 v1.0 READY FOR SIGN-OFF/DEMO (not yet released).** All eleven engineering phases (0–11) are
complete. **Phase 11 (FINAL)** wired the **multilabel** use case (Product Recommendation)
end-to-end for the first time, drove **all 7 insurance use cases** through the engine + API +
browser, measured a **12k-row performance baseline (13.0s, target < 5 min)**, ran a tuning sanity
check, and produced the **governance dossier** (`docs/governance_signoff_v1.0.md`). Suites:
**202 backend pytest · 72 frontend vitest · 9 Playwright E2E — all green.** What remains before
release is purely **human**: Naveen's per-phase sign-off, the `[RISK]` + leakage-audit review, the
stakeholder demo, signatures, and the `v1.0` git tag (see the dossier + "Testing debt" below).
A subsequent audit-driven tuning refinement (**Phase 7B.2**, 2026-06-23) expanded three Optuna
search spaces; backend pytest now **206 green** (was 202). No behaviour change to a non-tuning
run; tuning stays OFF by default.

**Active phase (historical context below):** Phase 8 complete — **FastAPI layer** (`backend/api/`)
wraps the engine over HTTP for the Phase 9 frontend, and the **`/api/v1/run` response schema is
LOCKED** (`docs/api_contract.md`). **The engine is reachable from a browser; the contract is frozen.**
**Sprint day:** Phase 11 done (sprint complete)
**Overall:** 🟢 Six endpoints under `/api/v1/` (`health`, `upload`, `run`, `explain`,
`outputs`, `outputs/{name}`) drive the existing `ModelRunner` / `inspect_file` — no ML logic
added. The synchronous `/run` runs the pipeline on a threadpool and returns the locked
envelope; predictions are sampled for display while curves/confusion are full-test. Full
suite green (184 tests).

Phase 8 one-line summary: the FastAPI layer (`backend/api/`) is a thin HTTP translator over
the engine — `main.py` (load_dotenv, lifespan logging the storage roots, CORS allowlist from
env, routers mounted under `/api/v1`), `models.py` (Pydantic v2 `RunConfig` + locked response
models + `to_engine_config()`), `serialize.py` (numpy→Python + NaN/Inf→None on top of the
engine's `_jsonify`), and `routes/` (health/upload/run/explain/outputs). The single sanctioned
ML touch is `evaluation/curves.py::compute_curve_points` (ROC/PR points; plot2 refactored to
use it). A second additive engine edit — `StorageAdapter.save_input` — was needed so uploads
land in `DATA_DIR` (plan_tweak 31). `/explain` is a v1.0 structured stub (no model persistence).
184 tests passing (148 prior + 36 new).

Engine summary (Phase 7/7B, unchanged): Sections 14–16 implemented. **Section 15 `ModelRunner`** (`runner.py`)
is the orchestrator: it deep-copies the config once at the start of `run()` and never
mutates `self.config` (the `_run_config` isolation rule — asserted by a test), executes
the corrected canonical order (split BEFORE preprocessing — plan_tweak row 4, not the
scope's step diagram), trains each `config["algorithms"]` entry on the balanced TRAIN
matrices, classifies + evaluates on the untouched TEST set, and is robust to a single
failing algorithm (logged, recorded as a `status="failed"` metrics row, run continues).
State attrs: `raw_df_, train_df_, test_df_, feature_impact_, predictions_df_, metrics_df_,
models_, metrics_, X_test_, y_test_, classes_, active_features_, run_profile_`. **Section
14 `plot_results`** (`evaluation/plots.py`) writes plot1 (confusion: raw + row-normalized
per model), plot2 (binary ROC+PR / multiclass one-vs-rest ROC, AUC/AP in legend), plot3
(feature importances per model that exposes them), plot5 (binary calibration) — all via
StorageAdapter, Agg backend, dpi=150, white facecolor, figures always closed; degenerate
cases (no importances, multiclass calibration/PR) fall back to labelled placeholder PNGs
so the artifact set is always complete. plot4/plot6 are written upstream (Sections 5/7B)
and not duplicated. **Section 16 CLI** (`cli.py`): `load_dotenv()` at startup (mandatory —
engine doesn't auto-load `.env`), `--inspect` (profile only) and run modes, default
feature detection (drops id_like/datetime), prints a per-model metrics table + the files
written; `--output-dir` override. Outputs to OUTPUT_DIR: `classification_results.csv`,
`metrics_comparison.csv`, `class_report.csv`, `run_profile.json` (+ plot1/2/3/5, plot4,
plot6). **130 tests passing (117 prior + 13 new).** Real-data milestone: CLI on
`real/iris.csv` (multiclass) with LR/RF/XGB/LGBM → accuracy 0.93–0.97, all 11 artifacts
written. Engine complete; ready for Phase 8 (FastAPI layer).

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
| 7 | Plots + ModelRunner + CLI (Sections 14–16) | ✅ Done | ModelRunner (deep-copy config isolation, corrected order, robust per-algo failures) + plot_results (plot1/2/3/5) + CLI (load_dotenv, inspect/run modes); 13 tests; real-data run on iris done; engine feature-complete |
| 7B | Optuna hyperparameter tuning (Section 8B) | ✅ Done | `tuning.py` (`tune_model`) — OFF by default; one uniform mechanism for all 6 models; CV-in-train trial scoring (leakage-safe); per-model isolation + hard 600s/model timeout; ModelRunner + config + CLI (`--tune…`) sanctioned edits; 17 tests; **AutoML pulled v1.5→v1.0** (plan_tweak 24–25). **7B.2 (2026-06-23):** audit-driven search-space expansion — LGBM `max_depth`, XGB `gamma`, SVM real+conditional `kernel`; +4 tests (206 total); refinement, no scope deviation (plan_tweak 38) |
| 8 | FastAPI layer | ✅ Done | 6 endpoints under `/api/v1/`; `/run` schema LOCKED (docs/api_contract.md); `curves.py` helper + plot2 refactor; `save_input` upload support; `/explain` stub; 36 tests (184 total) |
| 9 | React dashboard (12 pages) | ✅ Done | **9a** (foundation: Option A design + Recharts; shadcn/ui; typed client vs LOCKED contract; app shell + nav; live round-trip; 13 FE tests). **9b** (6 result pages + Overview upgrade; binary+multiclass vs fixtures; 46 FE tests). **9c** (Explainability v2.0-ready stub wired to `/explain`; Setup Guide + Risk Register authored from the real docs; **Overview/Pipeline merged → 12 nav items**, `/pipeline` redirects to `/`; polish pass; 55 FE tests). Build clean. |
| 10 | Testing: browser E2E + real CORS + render gaps + suite audit | ✅ Done | Playwright (1.61.0) two-server webServer; happy-path E2E parametrized (binary+multiclass run live → rendered charts/heatmap/PNG); real cross-origin CORS test (GET + preflight OPTIONS); `/explain` live-path; +7 vitest gap tests. Suites green: **184 backend pytest + 62 frontend vitest + 4 Playwright E2E**. Tests only — no behaviour change, no deviation |
| 11 | Integration: 7-use-case E2E + multilabel + perf + governance (LAST phase) | ✅ Done (engineering) | **Multilabel wired end-to-end** (delimited target → `MultiLabelBinarizer` → OvR; per-label metrics/curves/report/predictions; honest null for confusion/MCC; additive, binary/multiclass untouched). **All 7 use cases** driven through engine+API (`test_use_case_sweep`, 8 tests) AND browser (Playwright 7-case sweep). **Perf baseline 13.0s** on 12k rows/4 algos (target < 5 min). Tuning sanity (XGB, 25 trials) 65.7s, timeout-bounded. **Governance dossier** `docs/governance_signoff_v1.0.md`. Suites: **202 pytest + 72 vitest + 9 E2E**. plan_tweak 34–37. **Human sign-offs/demo + `v1.0` tag remain.** |
| 12 | API: expose tuned hyperparameters on `/run` (additive, schema 1.0→1.1) | ✅ Done | New optional `result.tuning` block (per-model `best_params` + tuning settings); first contract version bump, done additively; **zero engine change**; `tuning` null on a non-tuning run. +2 tuning tests; `/explain` keeps its own 1.0. plan_tweak 39. UI panel = separate session |
| 14 | Engine: USER-DEFINED structured features (`UserFeatureBuilder`) | ✅ Done | **Engine-only.** New leakage-safe `preprocessing/user_features.py` + sanctioned `user_features` config key (default `[]`, OFF → run byte-identical) + sanctioned ModelRunner edit. STRUCTURED specs only (no free-text formula; no `eval`/`exec`, [RISK]-marked): numeric `add/subtract/multiply/divide/ratio`, `datetime_diff` (duration), single `log/abs/bin` + date-parts. Train-only fit/transform (bin edges, divide-fill); invalid specs skipped+logged; name collisions refused; reads RAW post-split frame (so `datetime_diff` works) and injects after FeatureBuilder, before interactions. +24 tests (**232 total**). plan_tweak 40. API/UI separate |
| 15 | API: accept `user_features` on the `/run` REQUEST | ✅ Done | **API-only, request-side.** New `UserFeatureSpec` Pydantic sub-model + optional `RunConfig.user_features` (default `[]`). Fast-fail 422 allowlist check (unknown `type`/`op`, two-column type missing `col_b`) mirrors the engine's `USER_FEATURE_*` constants (imported). `to_engine_config` dumps each spec with `exclude_none` → `build_config` (authoritative validator). **No response change / no version bump** — created columns surface in `result.run.active_features` (verified). +5 tests (**237 total**). plan_tweak 41. UI follow-up separate |
| 16 | UI: feature-builder panel for user-defined structured features | ✅ Done | **UI-only.** New `UserFeatureSpec`/`UserFeatureType` types + `user_features` on `RunConfig` (mirror the contract exactly); `user_features` on `ConfigFormState`/`DEFAULT_FORM_STATE` (`[]`) + `buildPayload`. New controlled `components/config/FeatureBuilderPanel.tsx` (added to Configuration): a `type` selector (numeric `[col_a][op][col_b]` / single `[transform][col]` / datetime_diff `[end][start][unit]`) + a name input — **STRUCTURED specs only, no free-text formula** (the engine's no-eval rule carried to the UI). Column dropdowns populated + filtered from the inspect profile (numeric/datetime cols; single-transform col filtered by op; empty typed list → all cols, API 422 guides). Client-side name validation (non-empty + unique vs existing columns AND added features); added features shown as removable rows with a readable label (`name = a ÷ b`). Invalid-spec **422** surfaces via the existing `ApiError`→Overview path (no crash). +9 vitest (**91 total**); build clean. No plan_tweak deviation — realises the Phase 15 request field |
| 13 | UI: dedicated **Tuning Results** page (consumes schema 1.1) | ✅ Done | **UI-only.** New `RunTuning` type + optional `tuning` on `RunResult` (mirrors the 1.1 contract exactly); `pages/TuningResults.tsx` reads `result.tuning` from the store (no new network call, no `run_profile.json` scrape) with three states — no-run / tuning-OFF (`null`/`enabled:false` → "not enabled" + Configuration hint) / tuning-ON (settings header strip + one card per tuned model's `best_params` key→value table; untuned run models shown "ran on defaults"; `unknown` values stringified defensively, empty `{}` → "no params returned"). Route `/tuning` + sidebar entry (nav 12 → **13**). Zero engine/API change. +10 vitest (**82 total**); build clean. No plan_tweak deviation |

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
| 2026-06-15 | ModelRunner deep-copies config once at the top of `run()` and uses the copy for every stage; `self.config` is the untouched caller object (never mutated) | The `_run_config` isolation rule — re-running the same runner/config must be safe and interaction columns added to the working frames must not leak back into config. Each sub-builder also deep-copies config internally, so isolation holds at every layer |
| 2026-06-15 | A failing algorithm is caught, logged, and recorded as a `status="failed"` row in `metrics_df_` (with the error string); the run continues for the others. Unknown algorithm names (build_model `ValueError`) are caught the same way | Scope robustness requirement: "one bad model must not kill the whole run." Real data + a 6-model registry makes per-model failures a realistic edge case |
| 2026-06-15 | `plot_results` writes plot1/2/3/5 only (plot4/plot6 are written upstream in Sections 5/7B). Degenerate cases emit a labelled placeholder PNG instead of skipping the file: no model exposes importances → plot3 placeholder; multiclass → plot5 placeholder (calibration is binary-only) and plot2 uses one-vs-rest ROC per class (PR omitted) | Keeps the OUTPUT_DIR artifact set stable/complete for the frontend regardless of problem type or model mix; avoids duplicating the two plots earlier sections already own |
| 2026-06-15 | `run_profile.json` records both `features` (configured) and `active_features` (final engineered columns incl. interaction cols), plus class_distribution, class_weight, n_rows/n_train/n_test, models_succeeded, and a UTC `timestamp` | The profile is the run's audit record; the active-vs-configured feature distinction makes the engineering effect visible at sign-off |
| 2026-06-16 | **Phase 7B**: added an Optuna tuning layer (`tuning.py`) as a NEW module — wrappers/registry untouched; ModelRunner/config/CLI got sanctioned edits. AutoML pulled from v1.5 into v1.0 | Sanctioned deviation (plan_tweak 24). One uniform `tune_model(name, X_train, y_train, problem_type, config, …)` for all six models; Optuna/TPE over a grid; OFF by default |
| 2026-06-16 | Tuning trial scoring is **k-fold CV inside the TRAIN split** (default; single train-internal split optional via `cv=False`); the test set is never passed to `tune_model` (structural). Balancing/SMOTE is NOT applied inside the CV folds — tuning runs on the pre-balance train folds, and ModelRunner balances only the final fit (the prompt's documented safe default); `class_weight` is passed through to per-trial `build_model` (mild approximation, [RISK]-noted) | Per-fold balancing would leak synthetic minority rows across folds; the safe default keeps trial scoring leakage-free without the per-fold-SMOTE complexity |
| 2026-06-16 | Best params are read from `study.best_trial.user_attrs["tuned_params"]`, NOT `study.best_params` | A search-space function may transform a suggestion (e.g. the LogisticRegression `"solver|penalty"` categorical splits into two estimator kwargs); reading the stored derived params guarantees the returned dict is exactly what was scored |
| 2026-06-16 | `tuning.timeout_seconds` default is a **hard 600s per model**, NOT `None` (the prompt's literal default) — explicit `None` still accepted as an opt-out | With `models=[]` (tune-all) + `n_trials=30`, an unbounded default would run a 30-trial study for every algorithm incl. the slow calibrated-SVM. A finite ceiling makes a tuning run impossible to leave unbounded; a study stops at the timeout OR the trial cap, whichever first |
| 2026-06-26 | **REVERSES the 2026-06-16 row above (owner request).** `tuning.timeout_seconds` default `600`→**`None`** (no per-model cap) everywhere — `config.py`/`api/models.py`/frontend form/contract examples; **`n_trials` (still 30) is now the SOLE study bound.** The `[RISK] runaway tuning` comment is kept and rewritten (governance: not removed). The frontend also exposes `search_space_overrides` (per-model collapsible editor) which was previously hardcoded `{}` | Owner wants tuning uncapped by default and the per-model search space editable from the browser. No engine ML change, no schema/version change (default-value only — field shapes unchanged). Re-impose a cap by setting `timeout_seconds` for large data / long `n_trials`. plan_tweak #43 |
| 2026-06-16 | Per-model isolation: each model's study runs in its own try/except — a study that errors (or whose every trial fails, e.g. an inverted-bound override) returns `{}` and the model falls back to defaults, never aborting the run (same pattern as the Phase 6/7 per-algo isolation) | "One bad model must not kill the run" extended to tuning; robustness on real data / extreme configs |
| 2026-06-16 | **Phase 7B follow-up**: LogisticRegression tuning space reduced to `C` only (dropped the solver/penalty pairs) | sklearn 1.9 deprecated the `penalty` arg (FutureWarning, removal in 1.10) and `liblinear` rejects multiclass (`n_classes >= 3`) — the pairs warned on every fit and hard-errored on multiclass targets (surfaced by a user tuning LR on 3-class iris). Clean penalty-type tuning needs `saga` + `l1_ratio` (slow / convergence risk) — deferred. plan_tweak row 26 |
| 2026-06-17 | **Phase 8**: sanctioned curve-points helper — new `evaluation/curves.py::compute_curve_points` (ROC/PR points + AUC/AP per class, one-vs-rest for multiclass), and `plot_results` plot2 refactored to draw from it | The frontend needs raw curve coordinates; deriving them in two places (plot + API) would drift. One additive module = one source of truth. Reads held-out test predictions only, fits nothing (leakage-safe). plan_tweak 27 |
| 2026-06-17 | **Phase 8**: `/api/v1/run` is **synchronous** — runs on `run_in_threadpool` and returns the full result in one response | The engine is synchronous CPU-heavy Python; a threadpool keeps the event loop responsive without a job queue. A submit→poll→fetch background path is deferred to v1.5 (a long run can exceed a gateway timeout). plan_tweak 28 |
| 2026-06-17 | **Phase 8**: `/api/v1/run` prefix is `/api/v1/` (mounted via `FastAPI.include_router(prefix=...)`); responses JSON-safe via `api/serialize.safe_jsonify` (numpy→Python, NaN/Inf→None) extending the engine's `_jsonify` | CLAUDE.md mandates `/api/v1/` (supersedes the scope's bare `/api/...` table, plan_tweak 30); NaN/Inf are invalid JSON and would 500 or break the browser parser, so they map to null |
| 2026-06-17 | **Phase 8**: `/explain` ships option **(B)** — a structured "needs a persisted model (v2.0)" stub for ALL models; no training on request | v1.0 is stateless with no model registry, and `shap` is not installed; the prompt's default (A) (re-fit + TreeExplainer) needs a heavy dep + retraining per call. The response shape is final so v2.0 fills it in without a contract change. Owner-confirmed. plan_tweak 29 |
| 2026-06-17 | **Phase 8**: added additive `StorageAdapter.save_input(key, fileobj)` (ABC + `LocalFolderStorage`) writing into the INPUT root | `open_write` targets `OUTPUT_DIR` but inspect/loader read from `DATA_DIR`, so an upload saved via the existing API couldn't be read by `/run`. A second sanctioned engine edit beyond the curve helper, honoring "ALL I/O through StorageAdapter" over "no other engine edits". Additive, traversal-guarded. Owner-confirmed. plan_tweak 31 |
| 2026-06-17 | **Phase 9a**: design direction = **Option A "Clarity"** (light/clean SaaS, indigo `--primary #4f46e5`, Inter + JetBrains Mono) — owner pick from three mockups (`frontend/design-mockups/`) | The dashboard's audience is insurance analysts; a clean, neutral, dense-capable SaaS look reads as professional and keeps strong hierarchy without the contrast risk of the dark option or the lower density of the soft option. A decision, not a deviation |
| 2026-06-17 | **Phase 9a**: chart library = **Recharts** (pinned `3.8.1`) | Owner pick. The result pages are mostly standard chart types (bars, lines, heatmaps); Recharts' declarative React-component model is faster/cleaner to build and maintain than Chart.js' imperative canvas API for this app. Chart.js would only win for very dense curves on dark surfaces (the un-chosen Option B) |
| 2026-06-17 | **Phase 9a**: theming via ONE CSS-variable token block in `src/index.css` (Tailwind v4 `@theme inline`); change `--primary`/`--radius` to re-skin the whole app | Single source of truth for the look; no component file needs editing to re-theme. Stack: **Tailwind v4** (`@tailwindcss/vite`), **shadcn/ui** component pattern, **React Router 7** |
| 2026-06-17 | **Phase 9a**: shadcn/ui Button/Card/Badge/Input/Label are genuine (CVA); **Select/Switch are accessible native HTML** styled to match, not the Radix-based shadcn versions | Avoids a `@radix-ui/*` dependency in 9a; native `<select>`/checkbox are fully accessible and clearest for a frontend-new owner. Token theming is identical; drop-in upgradeable later. plan_tweak 32 |
| 2026-06-17 | **Phase 9b**: ROC/PR curves drawn as **per-`<Line>` data** (each class is a separate Recharts `Line` with its own `{x,y}` array on a numeric `XAxis type="number" dataKey="x"`), the no-skill diagonal via `ReferenceLine segment={[{0,0},{1,1}]}`, and a **custom tooltip via the 3.x `content`-prop** (not the removed 2.x `TooltipProps`) | ROC/PR curves for different classes have different x-grids (different fpr/recall arrays), so a single shared `data` array can't represent them; per-Line data lets the one-vs-rest curves coexist on one chart. Recharts 3.x ≠ 2.x — typing/props deliberately follow 3.8.1 |
| 2026-06-17 | **Phase 9b**: the multiclass `curves` block **does** carry PR per class (ROC and PR both, one-vs-rest) — verified against a captured live multiclass fixture — so the page renders multiclass PR rather than the prompt's defensive "PR not shown for multiclass" fallback (the fallback is still coded for the genuinely-absent case) | The locked contract (not the prompt's hedge) is the source of truth; `compute_curve_points` emits both curves for multiclass. Honoring the contract over the prompt's cautious wording. No deviation — the fallback path remains for robustness |
| 2026-06-17 | **Phase 9b**: a captured **multiclass `/run` envelope** (`run_envelope_multiclass.json`, risk_tier LR+RF) was committed as a second test fixture alongside the 9a binary one | The prompt asked for a multiclass fixture "if not present"; produced via the real FastAPI `TestClient` so the JSON is contract-accurate (same serializer the browser sees). Lets render tests prove binary AND multiclass shapes without a live server |
| 2026-06-17 | **Phase 9b**: plot3 (model feature-importance) placed on **Feature Impact**; plot5 (calibration) placed on **ROC/PR Curves** — both PNG-only artifacts the prompt listed without assigning a page | Topical homes: plot3 is about features, plot5 (probability calibration) sits with the other probability-diagnostic curves. A UX placement decision, not a deviation. PNGs guarded for absence (plot5 is a placeholder for multiclass) |
| 2026-06-17 | **Phase 9b**: confusion matrix is a **custom CSS-grid heatmap** (not a chart lib); raw↔row-normalised toggle computes the normalisation **client-side** from the raw counts | The contract gives raw integer counts; row-normalisation is pure display math (each cell ÷ its row total), not a second ML pass — doing it in the browser keeps the engine the only place that computes anything ML |
| 2026-06-17 | **Phase 9c**: **Overview and Pipeline merged into one page** (`pages/Overview.tsx`); the old Pipeline page is deleted and `/pipeline` redirects to `/` (`<Navigate replace>`). Nav went 13 → 12 items. Overview now renders four states: running (in-progress) → error → no-run → results (KPI band + comparison + scoreboard + artifacts + quick links + raw envelope) | The scope listed Overview and Pipeline separately, but they are the two ends of one flow (Configure → Run → watch → see results). One continuous screen matches the mental model; keeping the redirect means existing links/state never break. Recorded as plan_tweak 33 (page/nav count) |
| 2026-06-17 | **Phase 9c**: the merged Overview "while running" state shows the **canonical pipeline stages as a static checklist** + a spinner, NOT a fake streaming "live log" | `/run` is synchronous — the engine returns everything in one response, so there is no incremental log to stream. Listing the real stages (RUNBOOK order) is honest; a faked live feed would imply streaming the API does not do |
| 2026-06-17 | **Phase 9c**: Explainability is built as a **v2.0-ready stub** — a model + test-row picker that calls the real `/explain` endpoint, then renders the structured `unavailable` response (surfacing the server's own `reason`/`message`) with a clearly-stubbed "SHAP waterfall reserved for v2.0" region | Honours the frozen `/explain` stub (plan_tweak 29) without faking SHAP over null data. Exercising the real client→`/explain` path means v2.0 only fills `shap_values`/`base_value` into an already-designed layout, not rebuilds the page |
| 2026-06-17 | **Phase 9c**: Setup Guide and Risk Register are **static pages authored from the real docs** (RUNBOOK/API_RUNBOOK/api_contract for setup; CLAUDE.md constraints + engine `[RISK]` themes + scope §12 governance for risks) — not from any API response | The setup steps and `[RISK]` notes live in engine source + markdown, not in any endpoint; exposing them as data would be a frozen-backend change. Authoring from the docs is accurate and decoupled. A future live `[RISK]`/setup endpoint is a clean additive v1.1 path (noted, not built) |
| 2026-06-21 | **Phase 11**: a multilabel target is **one `\|`-delimited column** (e.g. `Auto\|Home`), parsed into a multi-hot indicator matrix by a `MultiLabelBinarizer` **fitted on TRAIN only**; the runner restores the real label NAMES as `model.classes_` after fitting OvR-on-indicator | The LOCKED contract has a single `target` field, so the delimited-column representation keeps the contract unchanged; OvR-on-indicator otherwise exposes integer column classes (0..n), losing the product names needed for metrics/curves/report. Train-only fit = the leakage boundary (a test-only label is ignored). New module `classifyos/multilabel.py` |
| 2026-06-23 | **Phase 14**: `UserFeatureBuilder` reads its source columns from the **RAW post-split frame**, not the preprocessed frame, even though its output columns are injected at the prompt's specified position (after FeatureBuilder, before interactions) | The Preprocessor **scales** numerics and **encodes/drops** datetime columns, so post-preprocessing a `datetime_diff` (`end − start`) is impossible (the datetime columns are gone) and numeric ops would run on scaled values. Reading from raw is the only design that makes the prompt's headline use case (`duration = end_time − start_time`) work; outputs are made NaN-free (numeric→0.0, coded→−1) and joined by index so the preprocessing "drop" strategy stays aligned. plan_tweak 40 |
| 2026-06-23 | **Phase 14**: invalid user-feature specs (missing/wrong-type column, target-as-source, unknown op at the builder, name collision) are **skipped + logged**, not raised; the config boundary (`build_config`) **hard-rejects** unknown ops/types/duplicate names | Two layers: the config boundary is the structural allowlist guard (a malformed config fails fast), while fit-time issues that depend on the actual data (column existence/type) must not abort an otherwise-valid run — "one bad spec must not kill the run", mirroring the per-algorithm robustness rule. No free-text formula is ever evaluated ([RISK]) |
| 2026-06-21 | **Phase 11**: multilabel renders through the **unchanged locked envelope** — per-label metrics/curves/class-report populate; the single confusion matrix, MCC and log-loss are `null` (undefined for a multi-hot target), and curves carry per-label one-vs-rest entries | The contract is general enough to express multilabel honestly without a new field — `null`/empty for the genuinely-undefined pieces beats a fabricated number or a contract bump. Scope conclusion: ship "runs + renders honestly with documented limits", not full parity (per-label thresholds + imbalance weighting → v1.x). plan_tweak 34–35 |

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

## Completed this session (Phase 7 — 2026-06-15)

- **Section 15** `backend/classifyos/runner.py`: `ModelRunner(config, storage)` +
  `run() -> self`, the single orchestrator the API and CLI drive (supersedes `dev_run.py`,
  which stays as a dev tool). `run()`:
  - **[RISK] `_run_config` isolation** — `copy.deepcopy(self.config)` once at the top;
    `self.config` is never mutated (asserted by `test_config_not_mutated`). Sub-builders
    also deep-copy config internally, so interaction columns never leak back.
  - Executes the **corrected canonical order** (plan_tweak row 4, NOT the scope diagram):
    `data_loader → analyze_feature_impact (raw, writes plot4 + summary CSV) →
    train_test_split_cls → Preprocessor.fit(train)/transform(both) →
    FeatureBuilder.fit(train)/transform(both) → InteractionFeatureBuilder.fit(train)/
    transform(both) (writes plot6) → handle_class_imbalance (TRAIN ONLY) → per-algorithm
    build_model → fit → classify → evaluate_model → save all`.
  - **Robust per-algorithm loop** (`_run_one_algorithm`): each algorithm runs in a
    try/except; a failure (incl. an unknown name → `build_model` `ValueError`) is logged
    and recorded as a `status="failed"` metrics row with the error string — the run
    continues for the rest. Successful models are kept in `models_` / `metrics_`.
  - State attrs: `raw_df_, feature_impact_, train_df_, test_df_, active_features_,
    predictions_df_, metrics_df_, models_, metrics_, X_test_, y_test_, classes_,
    problem_type_, run_profile_`. Plus a `run_from_args(...)` convenience wrapper.
  - **Outputs** (all via StorageAdapter): `classification_results.csv` (predictions,
    tagged by `model` + `sample_index`), `metrics_comparison.csv` (per-model summary
    rows), `class_report.csv` (per-class per-model, flattened from the classification
    report), `run_profile.json` (input_file, target, problem_type, features,
    active_features, algorithms, class_balance, class_weight, class_distribution,
    n_rows/n_train/n_test, models_succeeded, UTC timestamp).
- **Section 14** `backend/classifyos/evaluation/plots.py`: `plot_results(runner, storage)
  -> list[str]` writes **plot1** (confusion matrix per model — raw counts + row-normalized,
  annotated heatmaps), **plot2** (binary: ROC + PR, one line per model with AUC/AP in the
  legend; multiclass: one subplot per model with one-vs-rest ROC per class, PR omitted),
  **plot3** (top-15 feature importances per model that exposes them; models without →
  skipped), **plot5** (binary calibration vs the perfect diagonal). plot4/plot6 are NOT
  duplicated (written in Sections 5/7B). Agg backend, dpi=150, white facecolor, every
  figure closed after save; each plot guards its own failure (never raises into the run)
  and degenerate cases (no importances / multiclass calibration & PR) emit a labelled
  placeholder PNG so the artifact set is always complete.
- **Section 16** `backend/classifyos/cli.py`: `python -m classifyos.cli`. **`load_dotenv()`
  at startup (mandatory)** — the engine does not auto-load `.env`. argparse: `--file
  --target --features --problem-type --test-size --algos --balance --encoding --scaling
  --inspect --output-dir`. `--inspect` prints the `inspect_file` profile and exits; run
  mode builds the config (default features = all columns except target / datetime /
  ID-like, resolving aliases like LR/RF/XGB), runs `ModelRunner`, and prints a per-model
  metrics table (accuracy / F1-weighted / ROC-AUC / MCC) + the files written. Readable
  per-stage failures with non-zero exit codes (no raw tracebacks).
- **Tests** (13 new): `test_runner.py` (end-to-end binary + multiclass, `_run_config`
  isolation, bad-algo robustness, all-output-files incl. run_profile keys, class_report
  per-model), `test_plots.py` (binary plot1/2/3/5 written as non-trivial PNGs,
  `plot_results` returns the 4 keys, no-importance plot3 placeholder, multiclass plot2 +
  plot5 placeholder), `test_cli.py` (inspect-only, full run via `main()`, missing-file
  readable failure). **130 passed** (117 prior + 13 new) — no regressions.
- **Real-data milestone** (first true end-to-end run): `python -m classifyos.cli --file
  real/iris.csv --target target --algos LR,RF,XGB,LGBM` → multiclass, SMOTE-balanced;
  accuracy LR 0.933 / RF 0.933 / XGB 0.967 / LGBM 0.967; all 11 artifacts written to the
  real OUTPUT_DIR (outside the repo, gitignored — NOT committed).
- **[RISK] comments**: the deep-copy `_run_config` isolation point (runner); per-plot
  failure isolation + placeholder fallbacks (plots).
- Hallucination check ✅ — `sklearn.metrics` `roc_curve` / `precision_recall_curve` /
  `auc` / `average_precision_score` and `sklearn.preprocessing.label_binarize` verified
  against scikit-learn 1.9.0; matplotlib 3.11.0 Agg/savefig; `python-dotenv` `load_dotenv`
  default `override=False` (so the test env's OUTPUT_DIR is preserved).
- Archived this session's prompt to `prompts/phase_07_runner.md`.

## Completed this session (Phase 7B — 2026-06-16)

- **Section 8B** `backend/classifyos/tuning.py` (NEW module): `tune_model(model_name,
  X_train, y_train, problem_type, config, class_weight=None, random_state=42) -> dict` —
  an Optuna tuning layer that wraps *around* the Phase 6 wrappers (wrappers/registry
  **untouched**). One uniform mechanism for all six models:
  - **Per-model studies.** One Optuna `study` per model, TPE sampler seeded from
    `random_state`, `direction="maximize"` the configured metric. `SEARCH_SPACES` holds one
    function per model — **rich** spaces for the tree models XGBoost / LightGBM /
    RandomForest, **thinner** for the rest (LogisticRegression tunes `C` only — see the
    2026-06-16 follow-up; SVM is slow — calibrated CV per trial; NaiveBayes only
    `var_smoothing`, rarely moves). Per-model **bound overrides** via
    `tuning.search_space_overrides`.
  - **[RISK] leakage-safe scoring.** Every trial is scored INSIDE the train split only —
    k-fold CV (default; `cv_folds`) or a single train-internal split (`cv=False`). The test
    set is never passed to the module (structural). Balancing/SMOTE is NOT applied inside the
    CV folds (would leak synthetic rows across folds) — tuning runs on the pre-balance train
    folds; ModelRunner balances only the final fit. `class_weight` is passed through to
    per-trial `build_model` (mild approximation, [RISK]-noted).
  - **Budget + safety.** `n_trials` and a **hard `timeout_seconds` (default 600s/model)**
    bound every study — a study stops at the timeout OR the trial cap, whichever first, so a
    tuning run can never be unbounded. `cv_folds` is auto-clamped to the smallest class size
    (falls back to a single split when CV is infeasible).
  - **Robustness.** Each study runs in try/except: a study that errors or whose every trial
    fails (e.g. an inverted-bound override) returns `{}` and the model falls back to defaults
    — never aborts the run. Best params are read from `study.best_trial.user_attrs` so a
    transformed suggestion (LR `solver|penalty`) round-trips exactly.
- **Sanctioned edits:**
  - `config.py`: added the `tuning` sub-dict to `DEFAULT_CONFIG` + `TUNING_METRICS` tuple +
    `_validate_tuning` (enabled/cv bool, models list-of-str, metric ∈ TUNING_METRICS,
    cv_folds ≥ 2, n_trials ≥ 1, timeout None-or-positive, overrides dict).
  - `runner.py`: a new `_tune(...)` step (stage 7B) runs each requested model's study on the
    PRE-balance TRAIN matrices and feeds the best params into `build_model` for the final
    fit; `_run_one_algorithm` gained a `best_params` arg; `run_profile.json` gained a
    `tuning` audit block (`enabled`, `metric`, `cv`, `cv_folds`, `n_trials`,
    `timeout_seconds`, `tuned_models`, `best_params`). `_run_config` deep-copy isolation
    intact (tuning never mutates `self.config`).
  - `cli.py`: `--tune`, `--tune-models`, `--tune-metric`, `--trials`, `--timeout`,
    `--tune-cv-folds`; prints a tuning line + a `=== tuned hyperparameters ===` block.
- **Tests** `tests/test_tuning.py` (17): XGBoost returns expected keys; tuned CV score ≥
  default on identical seeded folds (LR — model-agnostic, fast); test-set-untouched
  (structural signature); enabled=False is a no-op (unit + runner metrics-identical);
  model-not-in-list → defaults; study-failure → `{}`; n_trials × cv_folds fit count;
  timeout honored (scorer stubbed → bounded, can't hang); single-split alternative;
  config-not-mutated; LR solver/penalty validity; tune-list resolution; all six models have
  a space; default timeout bounded; runner tunes only the requested model + records the
  audit; LR tunes C only + a multiclass no-failed-trials regression guard (2026-06-16
  follow-up). **148 passed** (130 prior + 18 Phase 7B) — no regressions. **Speed:** the tuning file
  runs in ~20s (tests cap search-space bounds + disable interaction auto-discovery; never
  tune SVM/NaiveBayes); full suite 3m29s.
- **Real-data CLI run** (`--output-dir` to a temp dir, not committed): `--file
  policy_lapse.csv --target will_lapse --algos XGB,RF --balance class_weight --tune
  --tune-models XGB --trials 3 --tune-cv-folds 2` → XGB tuned (RF on defaults), tuned params
  printed, `run_profile.json` tuning block populated, all 11 artifacts written.
- **Deps**: `optuna==4.9.0` (+ alembic/colorlog/SQLAlchemy/Mako/greenlet/tqdm/MarkupSafe)
  installed, added to `requirements.txt`, re-pinned in `requirements.lock` (`pip freeze`).
- **Hallucination check ✅** — verified against **Optuna 4.9.0** in the venv: `create_study(*,
  direction, sampler)`, `TPESampler(seed=…)`, `Study.optimize(func, n_trials, timeout,
  catch=…)`, `Trial.suggest_float/int(…, log=…)/suggest_categorical`,
  `study.best_trial.user_attrs`, `optuna.TrialPruned`, `optuna.logging.set_verbosity`.
- Prompt archived to `prompts/backend_phases/phase_07B_tuning.md`; plan_tweak rows 24–25 added.

## Completed this session (Phase 8 — 2026-06-17)

- **FastAPI layer** under `backend/api/` — a thin HTTP translator over the engine, NO ML logic:
  - **`main.py`**: `load_dotenv()` as the first real work (mandatory — engine doesn't auto-load
    `.env`); an `@asynccontextmanager` `lifespan` logging the resolved absolute
    `DATA_DIR`/`OUTPUT_DIR` + CORS allowlist; `CORSMiddleware` reading `CORS_ORIGINS`
    (comma-separated; never `["*"]` unless the `CLASSIFYOS_CORS_DEV` marker is set); routers
    mounted under `/api/v1`. Teaching docstrings throughout (request/response flow, uvicorn,
    endpoints, Pydantic, CORS, lifespan, threadpool).
  - **`deps.py`**: lazily-cached `get_storage()` dependency (built on first request, so the test
    suite's temp-`OUTPUT_DIR` override lands before construction).
  - **`models.py`**: Pydantic v2 `RunConfig` (3 required fields → 422; `extra="forbid"`; nested
    `feature_engineering`/`interaction_features`/`tuning` sub-models) + `to_engine_config()`
    (forwards to `build_config` — the single authoritative validator) + the locked response
    models (`RunResponse`/`RunResult`/`RunMeta`/`ModelMetrics`/`PredictionsBlock`/… ).
  - **`serialize.py`**: `safe_jsonify` — numpy→Python (via the engine's `_jsonify`) + NaN/Inf→None,
    so a degenerate metric can never 500 or emit invalid JSON.
  - **`artifacts.py`**: the canonical 11-artifact key list + `collect_artifacts(storage)` (shared
    by `/run` and `/outputs`).
- **Six endpoints** (`backend/api/routes/`): `GET /health`; `POST /upload` (multipart →
  `save_input` into `DATA_DIR/uploads/` → `inspect_file` → keys + `server_path`); `POST /run`
  (`async`, `run_in_threadpool(runner.run)`, reshape → locked envelope, predictions sampled at
  100/model, curves+confusion full-test); `POST /explain` (v1.0 structured stub); `GET /outputs`
  (list) + `GET /outputs/{name}` (stream CSV/PNG via `FileResponse`, traversal-guarded by the
  adapter).
- **Sanctioned engine edits (2):** (1) NEW `classifyos/evaluation/curves.py::compute_curve_points`
  (ROC/PR points + AUC/AP per class, one-vs-rest for multiclass, ≤500 pts/curve, [RISK]
  leakage-safe — test predictions only) and `plot_results` plot2 refactored to use it
  (filename/appearance/placeholder unchanged); (2) additive `StorageAdapter.save_input` for
  uploads. Both recorded in plan_tweak (27, 31).
- **`/api/v1/run` schema LOCKED** in `docs/api_contract.md` (envelope + `schema_version` 1.0 +
  the notes + the synchronous/gateway-timeout limitation).
- **Tests (36 new → 184 total):** `test_curves.py` (5 — point well-formedness, multiclass OvR,
  single-class omission, structural no-training-data guard, plot2 regression), `test_api_health.py`
  (1), `test_api_upload.py` (5 — each sample's inspect keys + `server_path`, server_path runnable
  by `/run`, unsupported-type 422), `test_api_run.py` (15 — 422 validation incl. bad enum; binary
  locked-schema assertions incl. failed-algo row + sampled predictions + full-test curves +
  artifacts PNGs + strict-JSON round-trip; multiclass OvR; `safe_jsonify` NaN/Inf/numpy unit),
  `test_api_outputs.py` (5 — list, PNG+CSV stream, 404, traversal rejected), `test_api_explain.py`
  (5 — stub shape + all model kinds). Prior 148 still pass.
- **Hallucination check ✅** — verified against the installed venv: **FastAPI 0.136.3**
  (`FastAPI(lifespan=…)`, `CORSMiddleware`, `UploadFile`/`File`/`Form`, `APIRouter`,
  `run_in_threadpool`, `FileResponse`), **Starlette 1.3.0** `TestClient` (httpx-based;
  emits a benign StarletteDeprecationWarning suggesting httpx2 — filtered, still works on
  **httpx 0.28.1**), **Pydantic 2.13.4** (`BaseModel`, `Field`, `field_validator`, `ConfigDict`,
  `model_dump`/`model_validate`), **scikit-learn 1.9.0** (`roc_curve`/`precision_recall_curve`/
  `auc`/`average_precision_score`). **No new deps** added (`shap` deliberately not added — see
  `/explain` decision); the API deps were already pinned in `requirements.lock`.
- Two design forks were surfaced to the owner and resolved to the recommended options: the
  upload storage gap → additive `save_input`; `/explain` → structured stub (B).
- Prompt archived to `prompts/api_phases/phase_08_fastapi.md`; plan_tweak rows 27–31 added.

## Completed this session (Phase 9a — 2026-06-17)

> **First frontend slice.** Backend untouched (frozen). Everything is a pure HTTP client of
> `/api/v1/`. First of three slices: **9a foundation** → 9b result pages → 9c remaining + polish.

- **Design pick (owner):** three full-look mockups of the same Overview screen were generated
  (`frontend/design-mockups/` — `option-a-clarity` / `option-b-telemetry` / `option-c-atlas`
  + an `index.html`). Owner chose **Option A "Clarity"** (light/clean SaaS, indigo accent) and
  **Recharts** as the chart library. Both recorded in the decisions log.
- **Design system** (`frontend/src/index.css`): one CSS-variable token block (Option A
  "Clarity") mapped through Tailwind v4's `@theme inline`, so `bg-card`/`text-muted-foreground`/
  `rounded-lg` etc. and every shadcn component theme from one place — change `--primary` to
  re-skin. shadcn/ui components added in the shadcn idiom (CVA + `cn`): `button`, `card`,
  `badge`, `input`, `label`; `select`/`switch` are accessible **native** elements styled to
  match (no Radix dep in 9a — plan_tweak 32). Fonts: Inter + JetBrains Mono.
- **Typed API client** generated against the **LOCKED** contract:
  - `src/api/types.ts` mirrors `docs/api_contract.md` + `backend/api/models.py` **exactly**
    (RunConfig + nested fe/ix/tuning; envelope with `models` as a LIST, sampled `predictions`
    with `full_csv`, per-model `confusion_matrix`/`class_report`/`curves`, `feature_impact`,
    `artifacts`). Each type commented with the page that consumes it. **No invented fields.**
  - `src/api/client.ts` — one typed fn per endpoint (`health`/`upload`/`run`/`explain`/
    `listOutputs`/`outputUrl`) with a single `ApiError` distinguishing network-offline / 422
    (with field detail) / 400 run-error. `src/api/parse.ts` (`parseRunResponse`) structurally
    validates a `/run` envelope before the UI trusts it. API base from `VITE_API_BASE_URL`
    (default `/api/v1`). `src/lib/buildPayload.ts` (pure) turns flat form state → RunConfig.
- **App shell:** `Sidebar` (canonical **13-page** nav, grouped, active highlight, from one
  `lib/nav.ts`), `Topbar` with the **API health banner** (`checkAPI()` on load → green
  connected / red "offline — start uvicorn on :8000" + retry) and a "New run" button,
  `AppLayout` (`<Outlet/>`). Global store `src/store/AppStore.tsx` (React Context) holds
  serverPath+inspect, the RunConfig form, the last `/run` result, and loading/error flags.
  First-class empty/loading/error states (`components/common/States.tsx`) — no blank screens.
- **Upload → Configure → Run round-trip (real screens):** **Upload** (drag-drop → `/upload` →
  columns/dtypes/missing + class-distribution chips + suggested type; stores `server_path`),
  **Configure** (form binding every RunConfig field; enum option lists mirror `config.py` so a
  run never 422s on a bad enum; client-side required-field mirror), **Pipeline** (in-progress
  state → model scoreboard + artifact downloads + raw envelope; 422 vs 400 shown distinctly),
  and **Overview** (KPI band + per-model F1 Recharts chart + active config). The other 9 pages
  are honest stub routes naming what they'll show.
- **Verified live:** `npm run build` clean (tsc + vite). Backend started (uvicorn :8000) and a
  **real round-trip exercised**: `/health` ok → `/upload policy_lapse.csv` (server_path
  `uploads/policy_lapse.csv`) → `/run` (LR+RF, class_weight) returned `status:"ok"` schema 1.0,
  2/2 models, 11 artifacts, curves for both. The **Vite dev proxy** was confirmed end to end
  (`http://localhost:5173/api/v1/health` → backend). The captured envelope is committed as the
  test fixture (`src/test/fixtures/run_envelope.json`).
- **Tests (13, vitest + Testing Library):** `buildPayload` → contract-valid RunConfig (+ trim +
  required-field mirror); `parseRunResponse` accepts the **real saved envelope** and rejects
  malformed/error-with-result/bad-status; `checkAPI()` offline (mocked rejected fetch) doesn't
  crash + online path. Full page-render + E2E deferred to Phase 10.
- **Hallucination check ✅** — verified against the INSTALLED versions and pinned in
  `frontend/package.json`: **react 19.2.6**, **react-router-dom 7.18.0** (BrowserRouter/Routes/
  Route/NavLink/Outlet/useNavigate), **recharts 3.8.1** (ResponsiveContainer/BarChart/Tooltip),
  **tailwindcss 4.3.1** + **@tailwindcss/vite 4.3.1** (`@theme inline`), **lucide-react 1.20.0**,
  **class-variance-authority 0.7.1** / **clsx 2.1.1** / **tailwind-merge 3.6.0**, **vite 8.0.16**,
  **vitest 4.1.9** / **jsdom 29.1.1** / **@testing-library/react 16.3.2**, **typescript 6.0.x**
  (verbatimModuleSyntax/erasableSyntaxOnly honored; `baseUrl` dropped — deprecated in TS6,
  `paths` resolves via `moduleResolution: bundler`). `import.meta.env` typed in `vite-env.d.ts`.
- **Contract gaps:** **none** — every UI field maps to a contract field. (`PROJECT_WISDOM.md`,
  named in the prompt's read-list, does not exist; its `.env`/CORS rules live in CLAUDE.md +
  `docs/api_contract.md`, which were read — noted in plan_tweak 32.)
- Prompt archived to `prompts/frontend_phases/phase_09a_foundation.md`; plan_tweak row 32 added;
  `frontend_short_desc.md` created (referenced from backend_/api_short_desc.md).

## Completed this session (Phase 9b — 2026-06-17)

> **Second frontend slice.** Backend untouched (frozen). Pure HTTP client of the LOCKED
> contract. 9a foundation → **9b result pages** → 9c remaining + polish.

- **The 6 result pages + an Overview upgrade**, each reading the last `/run` result already in
  the app store (no page re-fetches `/run`); the only new network call is `GET /outputs/{name}`
  for PNGs/CSVs via the existing `outputUrl` helper. Every page branches on
  `result.run.problem_type`, renders `status:"failed"` model rows greyed (never dropped), and
  shows friendly empty/missing states.
  - **Overview** (`pages/Overview.tsx`, upgraded): KPI band (best model by `f1_weighted`,
    accuracy, ROC-AUC, MCC, models-trained) + a per-model grouped bar across the key metrics +
    active-config card (with failed-model error in a tooltip) + quick links to the detail pages.
    Reads `result.run` + `result.models`.
  - **Feature Impact** (`pages/FeatureImpact.tsx`): ranked horizontal bar (composite or any
    single metric, picker) + full per-metric table (anova_f / mutual_info / point_biserial /
    corr_ratio, null-safe) + the **`id_like` leakage flag surfaced prominently** (warning banner
    + per-row chip; flagged bars coloured rose) + the **plot4** PNG. Reads `result.feature_impact`.
  - **Confusion Matrix** (`pages/ConfusionMatrix.tsx`): custom CSS-grid heatmap (auto cell-size +
    scroll for many classes; diagonal outlined), raw↔row-normalised toggle (client-side math),
    model selector. Reads `result.confusion_matrix`.
  - **Class Report** (`pages/ClassReport.tsx`): per-class precision/recall/F1/support table
    (macro/weighted-avg rows split into a footer) + grouped bar; weakest-recall class highlighted
    (the imbalance story). Reads `result.class_report`.
  - **ROC / PR Curves** (`pages/Curves.tsx`): interactive Recharts line charts from
    `result.curves` — ROC (no-skill `ReferenceLine` diagonal, AUC per class in legend) + PR (AP
    per class); one curve for binary (positive class), one-vs-rest per class for multiclass;
    per-model selector; `role="img"` + summary `aria-label` on each chart; custom tooltip via the
    3.x `content`-prop. Shows the **plot2** + **plot5** (calibration, binary-only) PNGs.
  - **Predictions Table** (`pages/Predictions.tsx`): sampled `result.predictions.sample_rows`
    (actual/predicted/per-class probabilities/confidence/correct), filter by model and
    correct/incorrect, sort by confidence; a clear **"showing {rows_returned} of {rows_total}
    (sampled)"** banner + full-CSV download (`full_csv` via `/outputs`). Never implies the sample
    is the whole table.
  - **Interaction Features** (`pages/Interactions.tsx`): lists `result.run.interaction_cols`, each
    decoded into a readable expression (`_x_`→×, `_div_`→÷, `_minus_`→−) with op chips; the
    **plot6** PNG; empty state when interactions were disabled.
- **Shared building blocks** (`components/results/`): `ResultGate` (the common "no run yet"
  empty-state wrapper, render-prop over the non-null result), `ModelSelector` (per-model dropdown,
  hidden for a single model), `PngArtifact` (fetches via `outputUrl`, guards a
  missing/placeholder artifact → friendly "not generated for this run" panel, never a broken
  image). Pure helpers in `lib/results.ts` (chart palette, class-report avg-row split, interaction
  name decoder).
- **Interactive-vs-PNG rule** (encoded in comments): ROC/PR, the confusion heatmap, the class
  report and the feature-impact ranking are drawn live from contract data; the plot PNGs
  (plot2–plot6) are fetched on demand, never inlined, always guarded for absence.
- **Routing/nav:** `App.tsx` now mounts the 6 result pages as real routes; `lib/nav.ts` cleared
  their `stub` flags (Explainability/Setup/Risks remain stubs for 9c).
- **Tests (vitest + Testing Library, render-level):** added a captured **multiclass** fixture
  (`run_envelope_multiclass.json`) next to the 9a binary one (both via the real FastAPI
  `TestClient` → contract-accurate). `resultPages.test.tsx` renders all 7 pages with BOTH fixtures
  + the no-run empty state; asserts the Feature Impact `id_like` warning, the Predictions sampled
  banner/counts, one ROC curve for binary vs three (per-class) for multiclass (via the chart's
  `aria-label`), and a `status:"failed"` row rendering greyed without crashing. `PngArtifact`
  present/absent tests; `lib/results` helper unit tests. **46 FE tests pass** (13 prior + 33 new);
  `npm run build` clean (tsc + vite). A no-op `ResizeObserver` stub was added to the vitest setup
  so Recharts' `ResponsiveContainer` renders in jsdom (chart bodies stay 0×0 — tests assert on the
  surrounding DOM, not chart internals).
- **Binary + multiclass verified against fixtures. Multilabel is rendered-but-UNVERIFIED** — the
  Curves page shows a "multilabel view is preliminary" notice for `problem_type:"multilabel"`; no
  multilabel run has ever executed end-to-end (still a Week-4 / Phase 10–11 target).
- **Contract gaps flagged: none.** Every rendered field maps to a `docs/api_contract.md` field;
  the multiclass `curves` block was confirmed to include PR per class (the page renders it rather
  than the prompt's defensive "PR omitted" fallback, which remains coded for the absent case).
- **Hallucination check ✅** — verified against the INSTALLED, pinned versions: **recharts 3.8.1**
  (`LineChart`/`Line` with per-series `data`, `BarChart`/`Bar`/`Cell`, `ResponsiveContainer`,
  `CartesianGrid`, `XAxis`/`YAxis` `type="number"`, `Legend`, `ReferenceLine` `segment`/
  `ifOverflow`, custom `Tooltip` via the 3.x `content`-prop — NOT the removed 2.x `TooltipProps`/
  `activeIndex`), **vitest 4.1.9** + **@testing-library/react 16.3.2** + **jest-dom 6.9.1**,
  **react-router-dom 7.18.0** (`MemoryRouter`/`Link`), and `import.meta.env`. No new deps.
- Prompt archived to `prompts/frontend_phases/phase_09b_result_pages.md`; `frontend_short_desc.md`
  extended with the seven result pages + the interactive-vs-PNG rule. No `plan_tweak` entry — no
  real deviation (chart/UX choices recorded in the decisions log above).

## Completed this session (Phase 9c — 2026-06-17) — Phase 9 COMPLETE

> **Final frontend slice.** Backend untouched (frozen). Pure HTTP client of the LOCKED contract.
> 9a foundation → 9b result pages → **9c remaining + polish**. All 12 pages are now real.

- **Three new pages built:**
  - **Explainability** (`pages/Explainability.tsx`) — a **v2.0-ready stub** that consumes the
    EXISTING frozen `/explain` response (no fake SHAP). It gates on a completed run (so it can list
    the trained models + features), shows an honest "Explainability is coming in v2.0" framing, and
    lets the user pick a model + a clamped test-row index and hit **Explain** — which calls the real
    `api.explain(...)` client. The structured `unavailable` response renders cleanly (status badge +
    the server's own `reason`/`message`, verbatim), and a clearly-commented **`WaterfallPlaceholder`**
    marks where the SHAP waterfall drops in once `shap_values`/`base_value` are populated (v2.0). The
    null-field branch is the live path; the populated branch is coded so the contract shape is honoured.
  - **Setup Guide** (`pages/SetupGuide.tsx`) — **static, authored from the real docs** (API_RUNBOOK
    start-the-API steps, RUNBOOK engine flow, `docs/api_contract.md`): an architecture
    React→FastAPI→engine diagram, the 5-step run flow (uvicorn :8000 → Upload → Configure → Run →
    explore/download, mirroring the Vite dev proxy + real endpoints), a 6-endpoint API reference
    table, and an **honest v1.0 limitations** section (sync `/run`/gateway timeout, `/explain` stub,
    outputs overwritten, multilabel preliminary, synthetic sample data). A comment records WHY it is
    static (no endpoint exposes setup/risks; a live `[RISK]`/setup endpoint is a future additive v1.1).
  - **Risk Register** (`pages/RiskRegister.tsx`) — **static**, nine risk→mitigation cards authored
    from `CLAUDE.md` "critical constraints" + the engine's actual `[RISK]` themes (leakage,
    imbalance, tiny-minority SMOTE realism, calibration, multicollinearity from interactions,
    threshold sensitivity, temporal leakage, proba shape/order, GenAI governance) — each mitigation
    describing what the code actually does — plus the **governance checklist** (scope §12) showing
    done vs the still-open Week-4 sign-offs.
- **Overview + Pipeline merged** into one continuous page (`pages/Overview.tsx`); `Pipeline.tsx`
  deleted, `/pipeline` redirects to `/` via `<Navigate replace>`, and `lib/nav.ts` dropped the
  Pipeline entry → **13 → 12 nav items** (no `stub` flags left; `StubPage.tsx` deleted). Overview
  now renders four states: **running** (canonical pipeline-stage checklist + spinner — honest, since
  `/run` is synchronous and has no live log to stream), **error** (422 vs 400, as the old Pipeline
  page did), **no-run** (invite), and **results** (the 9b KPI band + per-model comparison + active
  config, plus the old Pipeline content: the full model scoreboard, artifact downloads, and the
  collapsed raw envelope, + quick links). `Configure` now navigates to `/` on run.
- **Polish pass:** sidebar made `shrink-0` + `sticky` so it stays usable when the window narrows
  (content keeps `min-w-0`; every table is in an `overflow-x-auto` wrapper; charts stay inside
  `ResponsiveContainer`). Added `role="img"` + `aria-label` to the Overview comparison chart
  (matching the 9b curve charts). Reused the shared `EmptyState`/`LoadingState`/`ErrorState` on the
  new pages — no blank screens. Bumped two axis tick colours from `#64748b` → `#475569` for stronger
  contrast on chart labels (still within the slate token family). Native `<select>`/`<input>`,
  visible `:focus-visible` rings, and `prefers-reduced-motion` (from 9a) keep keyboard/contrast intact.
- **Tests (vitest + Testing Library, render-level):** new `pages/referencePages.test.tsx` (9 tests):
  nav has exactly **12 items + no Pipeline** entry and includes the 3 new routes; merged Overview
  renders the **in-progress** state and the **results** state from the binary fixture and shows a 422
  distinctly; Explainability invites a run when empty, renders the honest framing, and the **Explain
  action triggers the mocked `/explain` client** then surfaces the `unavailable` status + `reason` +
  the reserved waterfall region without crashing on null fields; Setup Guide + Risk Register render
  their key sections. Updated the 9b failed-model assertion (the merged Overview now shows a model in
  both the chips and the scoreboard). **55 FE tests pass** (46 prior + 9 new); `npm run build` clean
  (tsc + vite). True browser E2E (incl. the unverified multilabel path) remains Phase 10/11.
- **Contract gaps flagged: none.** Explainability renders only the contract's `ExplainResponse`
  fields; the new static pages touch no contract data.
- **Hallucination check ✅** — verified against the INSTALLED, pinned versions: **react-router-dom
  7.18.0** (`Navigate` confirmed a real export, used for the `/pipeline`→`/` redirect; `useNavigate`),
  **recharts 3.8.1** (`BarChart`/`Bar`/`ResponsiveContainer` — unchanged usage), **vitest 4.1.9** +
  **@testing-library/react 16.3.2** (`render`/`screen`/`fireEvent`/`waitFor`/`findByText`) +
  **jest-dom 6.9.1**, **react 19.2.6**, **vite 8.0.x**, **typescript 6.0.x**, and `import.meta.env`
  (existing). No new deps.
- Prompt archived to `prompts/frontend_phases/phase_09c_remaining_polish.md`; `frontend_short_desc.md`
  updated; `plan_tweak.md` row 33 added (the 13→12 page/nav merge).

## Completed this session (Phase 10 — 2026-06-20)

**Browser E2E + real CORS + render-gap coverage + suite audit. Tests ONLY — no backend or
frontend application code was changed; no bug found; no deviation (plan_tweak untouched).**

- **Playwright installed + pinned:** `@playwright/test` **1.61.0** (exact, no caret) in
  `frontend/package.json`; Chromium browser (Chrome for Testing 149) installed. New scripts:
  `npm run e2e` / `e2e:report`. Specs live in `frontend/e2e/`; `frontend/playwright.config.ts`.
- **The two-server webServer (the key machinery).** `playwright.config.ts` declares a `webServer`
  ARRAY: (1) the FastAPI backend via the venv Python (`python -m uvicorn api.main:app --port
  8000`, cwd `backend/`, readiness `…/api/v1/health`, 120s boot budget) and (2) the Vite dev
  server (`npm run dev`, :5173, whose proxy forwards `/api → :8000`). `baseURL` = the Vite URL;
  `reuseExistingServer: !CI`. **Data hygiene:** the backend process gets test-only env —
  `DATA_DIR` → the committed `backend/data/samples`, `OUTPUT_DIR` → a **throwaway**
  `backend/.e2e_output` (gitignored), `CORS_ORIGINS` → the localhost allowlist. These win over
  `backend/.env` because `main.py`'s `load_dotenv()` does not override already-set env vars
  (override=False). No E2E run touches the real output folder.
- **Happy-path E2E (`e2e/happy-path.spec.ts`), parametrized** over a `{file, target,
  problem_type, algorithms, features, expectedClasses}` list (`e2e/flows.ts` `USE_CASES`) so
  **Phase 11 can extend it to all 7 use cases** — Phase 10 runs only the **binary**
  (`policy_lapse` → `will_lapse`) and **multiclass** (`risk_tier`) entries. Each test drives the
  REAL UI: health banner green → upload CSV (file `<input>`) → pick target → Configure (curated
  features, problem type, 2 algorithms, `class_balance=class_weight`, interactions off for speed)
  → Run → wait for results. Then it asserts the **render gaps jsdom can't reach**: the Overview
  KPI band populates; the comparison **bar chart drew real SVG `<path>` geometry** (longest path
  `d` > 30 chars — impossible in a 0×0 jsdom render); the scoreboard lists each trained model; the
  ROC chart drew geometry and has the right curve count (**1 line for binary, N one-vs-rest for
  multiclass** — `path.recharts-curve`); a **PNG artifact** (`plot2`, via `/outputs/{name}`)
  actually loaded (`naturalWidth > 0`); the **confusion heatmap** has n×n `role="cell"` cells; the
  **predictions** sampled banner + rows render. Asserted against the LOCKED contract; honest
  role/label selectors (no brittle CSS).
- **`/explain` live path:** the binary happy-path also navigates to Explainability (in-app nav,
  preserving the store), clicks Explain, and asserts the **structured `unavailable` stub** renders
  cleanly against the **live** endpoint (status + `no_persisted_model` reason + reserved v2.0
  waterfall region). (The existing vitest test mocks the client; this exercises the real
  client → `/explain` → render path in a browser.)
- **Real CORS (`e2e/cors.spec.ts`) — the part the dev proxy normally MASKS.** Two run-free tests:
  the page (origin `:5173`) does a browser `fetch` to the **absolute** cross-origin
  `http://localhost:8000/api/v1/health`, bypassing the proxy → succeeds (proves the env-driven
  allowlist permits the origin); and a cross-origin `POST` to `/explain` with
  `Content-Type: application/json` succeeds — a **non-simple request, so the browser sends an
  OPTIONS preflight first** (server logs confirmed `OPTIONS … 200` then `POST … 200`), proving
  preflight handling. Documented (not automated) that a non-allowlisted origin would be blocked;
  `main.py` guarantees the list is never `["*"]` outside the explicit `CLASSIFYOS_CORS_DEV` marker.
- **Suite audit + gap fill (vitest).** Ran the full suites: **184 backend pytest passed**, **55
  frontend vitest passed** (the pre-Phase-10 baseline, all green). Audited coverage and filled
  genuine gaps (no padding): `src/api/client.test.ts` (5) — the typed client's `ApiError` mapping
  (network → kind `network`/status 0; 422 list + string `detail` → kind `validation` with field
  messages; 400 run-error envelope → kind `http`; ok passthrough), the one error layer the suite
  hadn't touched; `src/pages/errorStates.test.tsx` (2) — Overview's **400 run-error** state
  ("Run failed", distinct from the 422 path) and Upload's **error surface** (a failed `/upload`
  renders the `ApiError` message, no blank screen). The malformed-envelope parser was already
  covered by `parse.test.ts` (noted, not duplicated). Frontend vitest now **62 passed**.
- **One non-app config touch (tooling, not a deviation):** `vite.config.ts` gained a
  `test.include: ['src/**/*.{test,spec}.{ts,tsx}']` so vitest scopes to `src/` and never tries to
  collect a Playwright `*.spec.ts` from `e2e/`. This affects only the vitest runner — zero impact
  on the built app or dev server, so it is test infrastructure, not application behaviour (hence
  no plan_tweak row). `.gitignore` gained the E2E throwaway-artifact paths.
- **Final counts (all green):** **184 backend pytest · 62 frontend vitest · 4 Playwright E2E**
  (2 happy-path + 2 CORS). Frontend `npm run build` clean.
- **Hallucination check ✅** — verified against the INSTALLED versions in `frontend/node_modules`:
  **@playwright/test 1.61.0** (`defineConfig`, `devices`, `webServer` array with `cwd`/`env`/`url`,
  `baseURL`, `expect`/`expect.poll`, `page`/`locator`, `setInputFiles`, `evaluate`,
  `setChecked`/`uncheck({force})` — all exercised by passing tests); re-confirmed **vitest 4.1.9**
  (`vi.mock`/`vi.stubGlobal`), **recharts 3.8.1** (real `<path class="recharts-curve">` / bar
  paths in a browser), **@testing-library/react 16.3.2**, and the backend **FastAPI 0.136.3**
  `TestClient` / **pytest** stack (184 still green). No new runtime deps.
- Prompt archived to `prompts/testing_phases/phase_10_e2e_testing.md` (new subfolder, verbatim).

## Completed this session (Phase 11 — 2026-06-20/21) — FINAL PHASE, v1.0 ready for sign-off

> **Sanctioned editable surface: multilabel ONLY** (per the phase prompt §2). Every multilabel
> change is additive and keyed on `problem_type == "multilabel"`; **binary & multiclass behaviour
> is byte-for-byte unchanged** — the 184 pre-existing pytest stay green throughout. Synthetic data
> only; throwaway OUTPUT_DIR; contract unchanged.

- **Workstream 2 — multilabel end-to-end (the highest-risk item, done first).** Root cause found
  by running it: the leaf-level multilabel branches existed (wrappers' `OneVsRestClassifier`,
  `_evaluate_multilabel`) but **nothing in the orchestrator built the indicator matrix**, so a
  multilabel run silently degenerated into "multiclass over the 63 delimited combos" (classes were
  combo strings, subset-accuracy 0.078). Fixed additively:
  - **New module `classifyos/multilabel.py`** — the delimited-set ↔ indicator bridge
    (`parse_label_sets`, `join_labels`, `MULTILABEL_DELIMITER = "|"`). A multilabel target is ONE
    `|`-delimited column (e.g. `Auto|Home`).
  - **`runner.py`** — fits a `MultiLabelBinarizer` on the TRAIN label sets only ([RISK] leakage
    boundary), builds the `(n, n_labels)` indicator, trains OvR on it, restores the real label
    NAMES as `model.classes_` (OvR-on-indicator otherwise yields integer columns), stores
    `y_test_indicator_`, and reports per-LABEL `class_distribution`.
  - **`predict.py`** — a multilabel `classify` branch: actual/predicted are the delimited label
    SETS, one `probability_<label>` per label, confidence = row-max, `correct_flag` = exact-set
    match (subset accuracy). Same column layout → API/CSV unchanged.
  - **`curves.py`** — multilabel now computes per-label one-vs-rest ROC/PR from the indicator (was
    a no-op stub). **`plots.py`** — plot2 gains a per-label OvR branch; plot1 (confusion) + plot5
    (calibration) already fall back to honest placeholders for multilabel.
  - **`api/routes/run.py`** — passes the indicator to the curve helper for multilabel; everything
    else flows through the **unchanged locked envelope** (confusion `{}`, MCC/log-loss `null`).
  - **Frontend (defensive multilabel rendering):** Curves page subtitle + per-label curves +
    "preliminary" notice; Confusion Matrix shows an honest "not defined for multilabel — see the
    per-label Class Report / Curves" state instead of a blank heatmap.
  - **Outcome:** true multilabel runs — classes are the 6 product names; per-label F1 ≈ 0.58
    (real signal); roc_auc/pr_auc populated; the documented `smote`→`class_weight` fallback warning
    fires; all 11 artifacts written. **Scope conclusion (the §2 judgment call):** shipped as "runs
    + renders honestly with documented limits", NOT full parity — per-label thresholds stay v1.x
    and multilabel imbalance is effectively unhandled (resampling N/A; the OvR wrapper does not
    apply `class_weight`). plan_tweak 34–35.
- **Workstream 1 — 7-use-case sweep.** Extended `scripts/generate_sample_data.py` with the four
  missing datasets (claim_likelihood, customer_segment, claim_severity, product_reco) + a 12k perf
  set. Use-case CSVs are **committed to `backend/data/samples/`** (the portable E2E seed, like the
  existing 3 — a deliberate deviation from the prompt's "out of git", needed for reproducible E2E;
  the perf set is kept out of git). All 7 use cases now run through **engine+API** (new
  `tests/test_use_case_sweep.py`, 8 tests, each → contract-valid envelope + 11 artifacts) AND the
  **browser** (Playwright `happy-path.spec.ts` extended via the one `USE_CASES` list to all 7;
  multilabel asserts the honest states). plan_tweak 36.
- **Workstream 3 — performance baseline.** `ModelRunner.run()` on **12,000 rows × 4 algorithms
  (LR/RF/XGB/LGBM), tuning OFF = 13.0s** (target < 5 min — comfortably within; all 4 models
  succeeded). **Tuning sanity:** XGBoost, 25 trials, cv_folds=3 = 65.7s, bounded by `n_trials`
  before the 600s/model ceiling. The sync-`/run` gateway-timeout risk does not bite at 13s; it
  remains a v1.5 background-job concern for much larger data / tuning-on. plan_tweak 37.
- **Workstream 4 — governance dossier.** Produced `docs/governance_signoff_v1.0.md`: the scope §12
  checklist with status+evidence, the full **`[RISK]` inventory** (35 comments, file + one-line, for
  the lead to walk), **leakage-audit pointers** to the specific tests, the prompt-archive inventory,
  the hallucination-check record, a **repeatable demo script**, the **honest v1.0 limitations list**,
  and the explicit **unticked human action items** (Naveen per-phase sign-off, `[RISK]` + leakage
  review, stakeholder demo, signatures, `v1.0` tag).
- **Tests added (+18 pytest → 202; +10 vitest → 72; +5 E2E → 9):** `test_multilabel.py` (9 —
  delimited-set bridge, true-multilabel-not-combos, per-label metrics, smote→class_weight fallback,
  train-only binarizer, label-set predictions, per-label curves, per-label distribution),
  `test_api_run.py::test_multilabel_run_schema` (1), `test_use_case_sweep.py` (8). Frontend: the
  multilabel `/run` fixture (`run_envelope_multilabel.json`, via the real TestClient) + multilabel
  render tests. Playwright: the 7-use-case sweep (was binary+multiclass only).
- **Final counts (all green): 202 backend pytest · 72 frontend vitest · 9 Playwright E2E.** Frontend
  `npm run build` clean.
- **Hallucination check ✅** — no new runtime deps. Verified vs installed/pinned versions:
  **scikit-learn 1.9.0** (`MultiLabelBinarizer.fit/transform` — train-only vocabulary, unknown test
  labels ignored with `UserWarning`; `OneVsRestClassifier` on an indicator matrix; `roc_auc_score`/
  `average_precision_score` multilabel averaging; `classification_report` on indicator inputs),
  re-confirmed **@playwright/test 1.61.0**, **vitest 4.1.9**, **recharts 3.8.1**.
- **What remains is HUMAN, not code** — see the dossier §7: Naveen per-phase sign-off; `[RISK]`-comment
  review; leakage-audit sign-off; stakeholder demo (Amit Shah, DharaniKiran Kavuri, Matat Rotbaum);
  signatures; repo tag **`v1.0`**.
- Prompt archived to `prompts/testing_phases/phase_11_integration_signoff.md` (verbatim).

## Completed this session (Phase 7B.2 — 2026-06-23) — Optuna search-space expansion

> **Sanctioned editable surface: `tuning.py` `_space_*` functions + `tests/test_tuning.py` ONLY**
> (per the phase prompt). No wrapper/registry/runner/config/API/CLI change. Driven entirely by
> the read-only `docs/tuning_audit.md`. A **refinement of the already-sanctioned Phase 7B tuning
> layer** (itself plan_tweak 24) — **no new scope deviation**; a non-tuning run is byte-for-byte
> unchanged and tuning stays OFF by default.

- **Three audit-ranked additions/fixes** (the audit's items 1–3; the lower-priority items 4–6
  were explicitly deferred this session):
  1. **LightGBM — added `max_depth` (int 3…12, uniform)** to `_space_lightgbm`. [RISK] overfitting:
     LightGBM grows leaf-wise, so with the default `max_depth=-1` (unbounded) and `num_leaves`
     tuned to 255 trees can overfit on smaller datasets; `max_depth` now bounds that growth (the
     standard `num_leaves ≲ 2^max_depth` guard). `num_leaves` left as-is. *(Audit's highest-value
     fix.)*
  2. **XGBoost — added `gamma` / `min_split_loss` (float 0.0…5.0, uniform)** to `_space_xgboost` —
     a complexity regulariser (minimum loss reduction to make a split) distinct from depth and the
     L1/L2 (`reg_alpha`/`reg_lambda`) terms; 0.0 included so the search can stay unregularised on
     this axis.
  3. **SVM — `kernel` is now a real categorical `["rbf", "linear"]`** (was the no-op single-element
     `["rbf"]`). The space is **conditional**: `gamma` is an RBF-only knob (SVC ignores it on a
     linear kernel), so it is suggested only on the `rbf` branch — a linear trial returns no dead
     `gamma`. Linear is cheaper and sometimes wins on scaled data; the slow-calibrated-SVC
     small-`n_trials` guidance still stands.
- **Hallucination check ✅** — verified every parameter against the **installed** versions in the
  venv: **lightgbm 4.6.0** (`max_depth` in `LGBMClassifier.__init__`, default -1), **xgboost 3.2.0**
  (`gamma` accepted via the sklearn-API `**kwargs`, round-trips through `get_params`, fits clean),
  **scikit-learn 1.9.0** (`SVC` accepts `kernel="linear"`; `gamma` default `"scale"`, ignored for
  linear). No new runtime deps.
- **Tests (+4 → `tests/test_tuning.py`):** `test_tune_xgboost_returns_params` extended to assert
  `gamma` ∈ best-params within 0…5; **new** `test_tune_lightgbm_includes_max_depth` (max_depth ∈
  3…12, num_leaves still present); **new** `test_svm_space_kernel_is_a_real_choice` +
  `test_svm_space_gamma_is_conditional` (a recording-stub trial proves gamma present on `rbf`,
  absent on `linear` — fast, deterministic, no slow SVC fit); **new**
  `test_tune_svm_either_kernel_roundtrips` (a real tiny-budget SVM study returns a self-consistent
  space: `gamma` present iff `kernel == "rbf"`). SVM kept to a minimal trial budget per the speed
  contract. **Full suite: 206 passed** (was 202) — no regressions.
- RUNBOOK.md tuning section needed **no change** — it describes the tuning *controls*, not a
  per-model tuned-parameter enumeration, so the additions don't make it inaccurate.
- plan_tweak.md: row 38 added — recorded as a **refinement of existing tuning, no scope deviation**.
- Prompt archived to `prompts/backend_phases/phase_07B2_search_space_expansion.md` (verbatim).

## Completed this session (Phase 12 — 2026-06-23) — tuned hyperparameters on /run (schema 1.0 → 1.1)

> **First version bump of the LOCKED `/api/v1/run` contract, done ADDITIVELY.** API-only —
> **zero engine change** (the runner already produces the data). Driven by the read-only
> `docs/tuned_params_path_audit.md` (Option 1, Section C/D). Prompt 1 of 2; the UI panel that
> consumes the new field is a separate later session.

- **The gap closed:** the engine produces the per-model tuned hyperparameters (in
  `ModelRunner.tuned_params_` and the `run_profile.json` `tuning` block) but the locked `1.0`
  response omitted them, so the dashboard could only see them by downloading the artifact. Now
  they ride the typed, versioned `/run` envelope.
- **`backend/api/models.py`** — added a `RunTuning` response sub-model (`enabled`, `metric`,
  `cv`, `cv_folds`, `n_trials`, `timeout_seconds`, `tuned_models: list[str]`, `best_params:
  dict[str, dict[str, Any]]` — heterogeneous values), added `tuning: RunTuning | None = None`
  to `RunResult`, and bumped `RunResponse.schema_version` default `"1.0"` → `"1.1"`. The block
  is fully optional, so a non-tuning run is unchanged.
- **`backend/api/routes/run.py`** — new `_tuning(runner)` helper copies
  `runner.run_profile_["tuning"]` into the result; returns `None` when tuning was OFF **or**
  produced no `best_params`, so the field is null on a normal run. Wired into `_build_result`;
  no existing reshaper output altered. Pure plumbing — no ML.
- **`docs/api_contract.md`** — added the `result.tuning` block to the response section, a `1.1`
  additive header note + footer line, and a contract note (null when OFF; copied from the engine
  profile). All `1.0` field descriptions left intact.
- **Tests (additive + the necessary `1.1`/key updates):** `test_api_run.py` — new
  `test_tuned_run_exposes_best_params` (tiny budget: XGBoost, `n_trials=3`, `cv_folds=2` →
  `result.tuning.enabled=True`, `XGBoost` in `tuned_models`, non-empty JSON-serializable
  `best_params`) and `test_non_tuning_run_has_null_tuning`; `RESULT_KEYS` gained `"tuning"` and
  the envelope assertion now expects `"1.1"`. `test_use_case_sweep.py` schema_version assertion
  updated `"1.0"` → `"1.1"`. `/explain` keeps its own `1.0` envelope (separate endpoint, out of
  scope). **Touched API + sweep suites green** (`test_api_run` 18, other API files 16, sweep 8).
- **Hallucination check ✅** — Pydantic v2 (`BaseModel` / `Field(default_factory=…)` /
  `dict[str, dict[str, Any]]`) verified against the installed pydantic in the venv; the
  `RunTuning` model validates and serializes the real `run_profile` `tuning` dict.
- **Frontend untouched** (per the prompt) — relied on the parser's version-tolerance
  (`parse.ts` checks `schema_version` is a string and validates only known keys), so `1.1` and
  the extra optional key do not break the current UI.
- plan_tweak.md: row 39 added (first contract version bump, additive). api_short_desc.md updated
  with the `1.1` / `result.tuning` note. Prompt archived to
  `prompts/api_phases/phase_12_tuning_in_response.md` (verbatim).

## Completed this session (Phase 14 — 2026-06-23) — user-defined structured features (engine)

> **New engine capability beyond the original scope: USER-DEFINED feature engineering.**
> Engine-only this session (the API request field + the UI builder panel are separate
> follow-up prompts). OFF by default — a run with no user features is byte-for-byte unchanged.
> The hard safety rule: **no free-text formulas, ever** — the user composes a feature from a
> column + an operation from a fixed allowlist (+ optionally a second column); the engine
> applies only KNOWN operations to KNOWN columns and never `eval`/`exec`s any user input.

- **`backend/classifyos/preprocessing/user_features.py` (NEW)** — `UserFeatureBuilder(config)`,
  an sklearn-style `fit(train_df, target)` / `transform(df)` / `fit_transform` builder mirroring
  the FeatureBuilder leakage discipline, with `created_features_` and `skipped_specs_` attrs.
  Operations (fixed allowlists, in `config.py`):
  - **numeric** (two numeric cols): `add`, `subtract`, `multiply`, `divide`/`ratio` (same
    near-zero-denominator guard as the ratio features, filled per
    `interaction_features.fill_method`).
  - **datetime_diff** (two datetime cols, `op=subtract`) → a numeric duration in `unit`
    (`seconds`/`minutes`/`hours`/`days`, default `days`). Covers `duration = end − start`.
  - **single** (one col): `log` (`log1p`, train min ≥ 0 required), `abs`, `bin` (quantile
    bins, train-only edges), and date-parts `year`/`month`/`day`/`dayofweek`/`hour`.
  - **Leakage-safe:** bin edges and the divide median-fill are learned on TRAIN only and
    applied unchanged ([RISK] noted). **No-eval safety** [RISK]-marked at the module top.
  - **Robust:** an invalid spec (missing column, wrong column type, target-as-source, unknown
    op, **name collision with an existing column**) is skipped + logged with a clear reason —
    the run never aborts; valid specs still build. Outputs are NaN-free (numeric→`0.0`,
    coded `bin`/date-parts→`-1`) so they feed balancing/training directly. Input frame + config
    never mutated; joblib-picklable.
- **`backend/classifyos/config.py` (sanctioned edit)** — added the fixed allowlist tuples
  (`USER_FEATURE_TYPES` / `_NUMERIC_OPS` / `_SINGLE_*_OPS` / `_DATETIME_DIFF_OPS` /
  `_DATETIME_UNITS`), a `user_features: []` key to `DEFAULT_CONFIG`, and `_validate_user_features`
  (the allowlist guard at the config boundary: rejects unknown type/op, non-string columns,
  empty/duplicate names; defers column existence/type to fit time).
- **`backend/classifyos/runner.py` (sanctioned edit)** — `_engineer` now runs
  `UserFeatureBuilder` between FeatureBuilder and the interaction step. **Design call:** it reads
  source columns from the **RAW post-split frame** (`self.train_df_`/`self.test_df_`), not the
  preprocessed frame, then joins the created columns (by index) onto the engineered frame — the
  only way `datetime_diff` and meaningful numeric ops work, since the Preprocessor scales numerics
  and encodes/drops datetime columns. `_run_config` isolation intact; empty list = no-op.
- **Tests** `tests/test_user_features.py` (24): datetime duration (days + seconds, correct known
  values, unparseable row → 0.0 not NaN); numeric divide zero-guard (no inf) under zero + median
  fill; add/subtract/multiply; single log/abs, log-negative-train rejected, **bin edges train-only
  (poisoned test split unchanged + extremes clip to outer bins)**, date-part extraction;
  validation skips (missing column / wrong type / unknown op / target-as-source / name collision)
  + valid-and-invalid coexisting; `build_config` rejects unknown op/type/duplicate name + default
  `[]`; input-df/config immutability + joblib round-trip; **ModelRunner empty-`user_features`
  no-op identity** and a feature run adding the new column to `active_features_` (incl. a date-part
  from a RAW datetime column that is NOT a model feature — proving the raw-frame read).
  **232 passed** total (208 prior + 24) — no regressions.
- **Hallucination check ✅** — `pd.to_datetime(errors="coerce")`, `.dt.total_seconds()`,
  `.dt.year/month/day/dayofweek/hour`, `np.log1p`, `pd.qcut(retbins=True)` verified against the
  installed **pandas 2.3.3** / **numpy** in the venv.
- Archived this session's prompt to `prompts/backend_phases/phase_14_user_features.md`;
  updated `backend_short_desc.md` (UserFeatureBuilder entry) and `plan_tweak.md` (row 40).

## Completed this session (Doc-update enforcement hook — 2026-06-15) — ⚠️ REMOVED 2026-06-16

> This hook was removed in the 2026-06-16 reorg session (see below). Kept here as a record.

- **`scripts/check_docs_updated.py`** (stdlib only, cross-platform): computes the
  session's changed files as the union of `git diff --name-only HEAD`,
  `git diff --name-only --cached HEAD`, and `git ls-files --others --exclude-standard`.
  - ENGINE changed = any path under `backend/classifyos/` → if so, requires BOTH
    `PROJECT_STATE.md` and `backend_short_desc.md` (then `short_desc.md`) in the changed
    set, else exit code 2 with a STDERR message naming the missing doc(s).
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

## Completed this session (RUNBOOK.md — 2026-06-15)

- **`RUNBOOK.md`** (repo root): a plain, command-first operator's manual for running the ML
  engine via the CLI / `ModelRunner` on a local machine — NOT a code-internals doc. Six
  sections: (1) prerequisites & setup (venv activate in PowerShell, `.env` presence + the
  relative-default fallback caveat, run from `backend/`); (2) `--inspect` with real
  `policy_lapse.csv` output + how to read class balance / id_like / missing before choosing
  a target; (3) full-pipeline run with every flag + its default in a table, the algorithm
  alias table (LR/RF/XGB/LGBM/SVM/NB), and worked binary + multiclass + defaults-only
  examples; (4) all 11 output files explained + a "how to read the metrics" note (F1-weighted
  /MCC/PR-AUC over accuracy; perfect score ⇒ check leakage via plot4 / active_features);
  (5) re-run overwrite behavior (fixed filename constants → each run overwrites; `--output-dir`
  is the workaround; `run_profile.json` has a timestamp but no run-id, only the latest survives
  a shared OUTPUT_DIR); (6) a troubleshooting table.
- **Every factual claim derived from the actual code** (cli.py flags/exit codes,
  runner.py output keys + run_profile fields, plots.py placeholders, storage.py fallback
  defaults, config.py enum/default values, registry.py aliases) **and verified with live
  runs**: `--inspect` on `policy_lapse.csv`, a binary run (LR/RF/XGB) and a multiclass run
  (LR/RF/LGBM on `risk_tier.csv`), both to throwaway `--output-dir` temp folders. Example
  outputs in the doc are real (redaction not needed — synthetic sample data only). No data
  or real outputs committed; temp dirs removed after capture.
- Prompt archived to `prompts/doc_runbook.md` (now at `prompts/docs/doc_runbook.md`).

## Completed this session (Repo reorg / housekeeping — 2026-06-16)

> Docs/tooling/layout only — **no `backend/classifyos` pipeline code touched, no behaviour
> changed.** Prompt archived to `prompts/tooling/reorg.md`.

- **Removed the doc-update Stop hook.** Deleted `scripts/check_docs_updated.py` (the
  `scripts/` folder is now empty/gone) and emptied `.claude/settings.json` to `{}` so the
  `Stop` hook no longer fires. Rationale: the hook could detect that files changed but not
  that docs were *meaningfully* updated, and missed cases anyway. Doc-update discipline now
  lives in the phase PROMPTS + CLAUDE.md working-style rules instead.
- **Reorganised `prompts/` into subfolders** (via `git mv`, history preserved):
  `backend_phases/` (`phase_01`…`phase_07`), `api_phases/` + `frontend_phases/` (empty,
  `.gitkeep`), `tooling/` (`tool_dev_run.md`, `tool_doc_hook.md`, `reorg.md`), `docs/`
  (`doc_runbook.md`). Added `prompts/README.md` explaining the scheme. Earlier session-log
  entries above still cite the old flat `prompts/X.md` paths (accurate as of their date) —
  every prompt now lives under one of these subfolders.
- **Renamed `short_desc.md` → `backend_short_desc.md`** (`git mv`) and updated references in
  CLAUDE.md, plan_tweak.md, and the active parts of this file. Noted the future plan:
  `api_short_desc.md` + `frontend_short_desc.md` will join it, each opening with a shared
  short "About ClassifyOS" header then surface-specific summaries.
- **Phase 7 entry in `backend_short_desc.md`: verified present and accurate** (overall +
  ModelRunner + plot_results + CLI + run outputs), checked against `runner.py` / `plots.py` /
  `cli.py`. The reorg prompt assumed it was missing (and that Phase 4 was skipped); in fact
  **both Phase 4 and Phase 7 entries were already present and correct** — no backfill needed,
  nothing silently skipped.
- **CLAUDE.md fixes**: stale CLI example (`data/samples/lapse.csv` → `policy_lapse.csv`);
  working-style now states doc updates are enforced by prompts, not a hook; documented the
  `prompts/` subfolder scheme and the `backend_short_desc.md` rename + future siblings.
- Archived prompt files are left **verbatim** (governance: they are the historical record of
  what was actually asked), so their internal `short_desc.md` references are intentionally
  unchanged — see the note in the wrap-up summary.

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

## Completed this session (Tuning UI — 2026-06-26) — search-space override editor + uncapped timeout

- **Per-model search-space editor (frontend).** The Configuration page now exposes
  `tuning.search_space_overrides` (in the locked contract since `1.0`, but previously hardcoded
  to `{}` by `buildPayload`). New collapsible **"Search space (advanced)"** disclosure containing
  one collapsible block per algorithm; numeric params (e.g. XGBoost `max_depth`, `learning_rate`)
  get **low/high** override fields, categoricals (RandomForest `max_features`, SVM `kernel`) get
  **choice checkboxes**. Blank/unchanged = engine default, so an untouched panel sends `{}` and a
  default-tuning run is unchanged. New `frontend/src/lib/searchSpaces.ts` (read-only mirror of the
  engine `_space_*` bounds — introduces no new tunable knob) + `components/config/TuningOverridesPanel.tsx`;
  wired through `ConfigFormState.tune_search_space_overrides` → `buildPayload`.
- **Removed the default tuning timeout cap (owner request).** `timeout_seconds` now defaults to
  **`None` (no per-model wall-clock cap)** in `config.py`, `api/models.py`, the frontend form, and
  the `docs/api_contract.md` examples — **`n_trials` (still 30) is the SOLE bound** on a study.
  Configure gains a **"No timeout" switch** (default on; unchecking restores a numeric cap field).
  This **reverses the Phase-7B `600`s hardening** (decisions-log 2026-06-16 / plan_tweak #25): an
  enabled tune-all run now runs to completion of every algorithm's `n_trials`. The `[RISK] runaway
  tuning` comment in `config.py` is **kept and rewritten** (governance: not removed) to document
  that `n_trials` is now the only bound.
- **No engine ML change, no schema/version change.** Field shapes are unchanged (default-value
  change only — contract footer notes it; schema stays `1.1`). `test_default_timeout_is_bounded`
  → `test_default_timeout_is_uncapped` + `test_default_n_trials_is_the_bound`; `buildPayload.test.ts`
  expects `timeout_seconds: null`. **Backend tuning + API-run suites green (46); frontend `npm run
  build` clean.** plan_tweak #43; `frontend_short_desc.md` Configure section updated.
- **Tooling:** added `C:/Projects/classifyos_data` to `.claude/settings.local.json`
  `permissions.additionalDirectories` so the external dataset `.csv` files are @-taggable / readable
  in Claude Code (the committed `backend/data/samples/*.csv` were already tracked → already taggable).
- **Known follow-up (pre-existing, not from this work):** `frontend/src/pages/referencePages.test.tsx`
  asserts **13** nav items but the `chore/unwire-interaction-features` branch (commit `7b592f8`)
  commented out the Interactions nav entry → **12**, so that one test is red on this branch
  independently of the tuning work.

## Completed this session (Bugfix — 2026-06-26) — XGBoost/LightGBM special-char feature names

- **Symptom.** Running a real dataset (`real/arizona_buyingpropensity.csv`, JSON-flattened
  insurance quote data with columns like `policyHolder.ownerships[0].type.description`,
  `covers[0].insuranceAmount`) made XGBoost and LightGBM fail at fit while LogisticRegression
  and RandomForest ran fine.
  - XGBoost: `ValueError: feature_names must be string, and may not contain [, ] or <`.
  - LightGBM: `LightGBMError: Do not support special JSON characters in feature name`.
- **Root cause.** Both libraries reject special characters in feature names; the `[0]`
  array-index columns from the flattened source trip the restriction. sklearn models don't care.
- **Fix.** `backend/classifyos/models/wrappers.py` — added `_needs_safe_feature_names` flag +
  `_safe_X()` helper on `_SklearnEstimatorWrapper`. When set, DataFrame columns are renamed to
  safe positional names (`f0..fn-1`) before every `fit`/`predict`/`predict_proba` call;
  importances still map back to the real names via `feature_names_` (captured from the original
  `X` before renaming). Flag enabled on `XGBoostModel` and `LightGBMModel`. Bare-ndarray `X`
  passes through untouched. No public contract change; additive and leakage-safe.
- **Test.** `tests/test_models.py::test_special_chars_in_feature_names` (XGBoost + LightGBM) —
  fits on columns containing `[`, `]`, `<`, asserts predict/predict_proba work and importances
  map back to the special names. **Full suite green: 240 passed.**
- **Also fixed a pre-existing test-isolation bug (surfaced when running the whole suite).**
  `OUTPUT_DIR` is a session-scoped shared temp dir; `test_interactions::test_plot6_written`
  writes `plot6_interaction_summary.png` into it and never cleans up, so on this
  interactions-unwired branch `test_runner::test_all_output_files`'s `assert not exists(plot6)`
  failed (test_interactions sorts before test_runner). Fix: `test_all_output_files` now unlinks
  any stale plot6 before its run so the assertion tests the runner's own behaviour. Marked
  `[TEMP — remove with the interaction unwiring]`. Unrelated to the wrappers bugfix; only
  appeared because the full suite hadn't been run end-to-end since the unwiring.
- **⚠️ Separate observation (not fixed, flagged to user).** On this dataset every model scores
  1.0000 on accuracy/F1/ROC-AUC/MCC — a strong target-leakage signal (likely `status.description`
  and/or `activePolicyNumber` encoding the outcome). Not part of this bugfix; needs a feature
  review with the data owner.

## In progress / partially done

- **Phase 9 (React dashboard) — ✅ COMPLETE (9a + 9b + 9c).** All **12 pages** are real screens:
  Overview (now the merged run page), Upload, Configuration, Feature Impact, Interaction Features,
  Confusion Matrix, Class Report, ROC/PR Curves, Predictions Table, Explainability (v2.0-ready
  stub), Setup Guide, Risk Register. The old Pipeline page was merged into Overview (`/pipeline`
  redirects to `/`). The backend (engine + API) is unchanged/frozen behind it. Binary + multiclass
  result rendering verified against committed fixtures; **multilabel rendered-but-unverified**
  (Phase 10/11). Nothing in Phase 9 remains open — the next work is the Week-4 testing/governance.
- `frontend/design-mockups/` holds the three throwaway design-option HTML mockups (Option A
  chosen) — kept as the provenance of the design pick; not part of the built app.

## Known issues / bugs

| # | Issue | Severity | Found | Status |
|---|---|---|---|---|
| 1 | XGBoost/LightGBM crash on feature names with `[ ] <` (JSON-flattened cols) | High | 2026-06-26 | ✅ Fixed (wrappers `_safe_X`) |
| 2 | Perfect 1.0 metrics on `arizona_buyingpropensity.csv` → suspected target leakage (`status.description`/`activePolicyNumber`) | Medium | 2026-06-26 | Open — needs feature review |

## Blockers

- None. Sample CSVs are in `DATA_DIR`; venv installed; tests green.

---

## Testing debt / untested paths

> **Phase 10 (2026-06-20) closed the browser/render/CORS layer.** ~~Struck~~ items are now
> covered; the remaining bullets are the **Phase 11** agenda (the last phase of the sprint). Do
> not treat the green suites as covering the open items below.

**✅ Closed in Phase 10 (struck through):**

- ~~**Frontend E2E** — true browser → live uvicorn → engine → **rendered** chart.~~ ✅ Done —
  Playwright two-server `webServer`; `e2e/happy-path.spec.ts` drives the real UI through
  upload→configure→run on **binary + multiclass** and asserts the render gaps jsdom could not:
  real SVG `<path>` geometry (Recharts no longer 0×0), the correct curve count (1 binary / N
  multiclass), the confusion heatmap cells, a loaded PNG artifact, the predictions sampled banner.
- ~~**CORS exercised by an actual browser**~~ ✅ Done — `e2e/cors.spec.ts` makes a real
  cross-origin `fetch` (GET) bypassing the Vite proxy and a preflight-triggering cross-origin POST
  (OPTIONS handled); proves the env-driven allowlist is real and never `["*"]`.
- ~~**`/explain` real path**~~ ✅ Done — exercised live in the browser (binary happy-path); the
  structured `unavailable` stub renders cleanly.
- ~~**Error/empty-state + typed-client gaps**~~ ✅ Done — `client.test.ts` (ApiError mapping:
  network/422/400/ok) + `errorStates.test.tsx` (Overview 400 run-error, Upload error surface);
  parser-on-malformed already covered by `parse.test.ts`.

**✅ Closed in Phase 11 (struck through):**

- ~~**Multilabel (Product Recommendation) has NEVER run end-to-end**~~ ✅ Done — wired
  end-to-end via a delimited target + `MultiLabelBinarizer` (train-only) → OvR; per-label
  metrics/curves/report/predictions; the `smote`→`class_weight` fallback verified; honest null for
  the single confusion matrix / MCC. Engine, API and browser all exercised. Regression tests:
  `test_multilabel.py` + the API + sweep + frontend fixture. **Documented limits** (per-label
  thresholds + imbalance weighting → v1.x): plan_tweak 34–35, dossier §9.
- ~~**7-use-case E2E sweep**~~ ✅ Done — all 7 use cases run through engine+API
  (`test_use_case_sweep.py`) AND the browser (Playwright `happy-path.spec.ts`, all 7 via the one
  `USE_CASES` list). New datasets generated + committed as the E2E seed (plan_tweak 36).
- ~~**Tuning at realistic budgets**~~ ✅ Done (sanity) — XGBoost, 25 trials, cv=3 = 65.7s,
  bounded by `n_trials` before the 600s/model ceiling. (A full tuning *sweep* was explicitly out of
  scope; SVM tuning remains the slow, rarely-run path.)
- ~~**Performance baseline on 10k+ rows**~~ ✅ Done — 12k rows × 4 algos, tuning off = **13.0s**
  (target < 5 min). plan_tweak 37.

**⬜ Still open — HUMAN sign-off actions (NOT code; see `docs/governance_signoff_v1.0.md`):**

- **Per-phase sign-off by Naveen.**
- **`[RISK]`-comment review by the team lead** (the full inventory is tabulated in the dossier §4).
- **Leakage-audit sign-off** (the proving tests are pointed to in the dossier §5).
- **Stakeholder demo + acceptance** (Amit Shah, DharaniKiran Kavuri, Matat Rotbaum) — demo script
  in the dossier §8.
- **Signatures + repo tag `v1.0`.**

**⬜ Still open — documented post-v1.0 items (not blockers):**

- **Real (non-synthetic) data** revalidation when it arrives (plan_tweak 5) — all metrics to date
  are on synthetic data.
- **Background-job `/run`** (submit→poll→fetch) to beat gateway timeouts on very large data /
  tuning-on (v1.5, plan_tweak 28). **Real `/explain`/SHAP** once model persistence lands (v2.0,
  plan_tweak 29).

---

## Next steps (priority order)

1. Commit Phase 11 ("Phase 11: 7-use-case E2E sweep + multilabel end-to-end + 10k perf baseline +
   governance dossier — v1.0 ready for sign-off").
2. Upload updated PROJECT_STATE.md to the Claude Project knowledge.
3. **HUMAN sign-off + release (engineering is done).** Per `docs/governance_signoff_v1.0.md`:
   Naveen's per-phase sign-off → the team-lead `[RISK]`-comment review (dossier §4) → leakage-audit
   sign-off (dossier §5) → the stakeholder demo (dossier §8; Amit Shah, DharaniKiran Kavuri, Matat
   Rotbaum) → signatures → **tag the repo `v1.0`**. Only then is v1.0 "released".
4. v1.x backlog: real-data revalidation (plan_tweak 5); per-label thresholds + imbalance weighting
   for multilabel (plan_tweak 35); background-job `/run` (submit→poll→fetch) to beat gateway
   timeouts on very large data / tuning-on (v1.5); real `/explain`/SHAP once model persistence
   (MLflow / a registry) lands (v2.0 — the Explainability page is already wired and shaped for it).

---

## API contract status

`/api/v1/run` response schema: **🔒 LOCKED (Phase 8, schema_version 1.0).**
Contract doc: `docs/api_contract.md` — frozen; changes must be additive and bump the version.

## Governance checklist (from scope §12)

- [x] Prompt version control — prompts/ populated per section (phase_01…phase_07B archived under `prompts/backend_phases/`; Phase 8 archived to `prompts/api_phases/phase_08_fastapi.md`)
- [x] Section-level unit tests passing on real data — **202 backend pytest** (22 Phase 1 + 5 Phase 2 + 14 Phase 3 + 19 Phase 4 + 10 Phase 5 + 47 Phase 6 + 13 Phase 7 + 18 Phase 7B + 36 Phase 8 API/curves + **18 Phase 11: 9 multilabel + 1 API-multilabel + 8 7-use-case sweep**). **Frontend: 72 vitest** (render incl. binary+multiclass+**multilabel** fixtures + typed-client + error/empty states). **Browser E2E: 9 Playwright** (**7-use-case happy-path sweep incl. multilabel** + 2 real-CORS) — true browser → live uvicorn → engine → rendered charts/heatmap/PNG, asserting the LOCKED contract
- [ ] [RISK] comments reviewed by team lead — **full inventory (35 comments) tabulated in `docs/governance_signoff_v1.0.md` §4** (file + one-line summary) for the lead to walk and tick off. (3 Phase 1 + 2 Phase 2 + 4 Phase 3 + Phase 4 poly-cap/ratio-denominator/auto-discovery-pool/re-discovery-leakage + 4 Phase 5 + Phase 6 proba-shape-order/accuracy-misleads/SVM-no-importance + Phase 7B tuning-CV-leakage/per-fold-balancing-deferred/runaway-timeout-cap/per-model-isolation + **Phase 11 multilabel-delimiter + MLB-train-only**, pending review)
- [ ] Leakage audit (encoder/scaler/SMOTE train-only) confirmed — encoder/scaler/imputer (Phase 3), feature-engineering/interaction stats (Phase 4) and balancing (Phase 5) all train-only, enforced by design + dedicated leakage tests (binning edges, MI auto-discovery, test-set-untouched). SMOTE/undersample are train-only by construction (the balancer takes no test argument). Phase 6 models fit on the balanced TRAIN matrices only; evaluate_model/classify only ever read the untouched test set. Phase 7B tuning scores every trial with CV *inside the train split only* (the test set is never passed to `tune_model`), and balancing is applied only to the final fit, not inside the CV folds. **Phase 11: the multilabel `MultiLabelBinarizer` learns its vocabulary from the TRAIN split only** (a test-only label is ignored — `test_multilabel.py::test_multilabel_binarizer_is_train_fitted`); proving tests are listed in `docs/governance_signoff_v1.0.md` §5
- [x] Output schema contract locked — `/api/v1/run` response **LOCKED at Phase 8** (`docs/api_contract.md`, schema_version 1.0). The API contract is frozen; the Phase 9 frontend is generated against it (CLAUDE.md hard rule)
- [x] Hallucination check — library calls verified against installed versions (Phase 1: pandas 2.3.3 / sklearn 1.9.0; Phase 2: scipy 1.17.1 / sklearn 1.9.0 / matplotlib 3.11.0; Phase 3: sklearn 1.9.0 encoders/scalers; Phase 4: mutual_info_classif / scipy.stats.skew / pandas.qcut; Phase 5: imbalanced-learn 0.14.2 SMOTE/RandomUnderSampler/RandomOverSampler, sklearn 1.9.0 compute_class_weight; Phase 6: sklearn 1.9.0 CalibratedClassifierCV/GaussianNB sample_weight/OvR/roc_auc/log_loss/calibration_curve, xgboost 3.2.0 string-label rejection + sample_weight, lightgbm 4.6.0; Phase 7B: optuna 4.9.0 create_study/TPESampler/Study.optimize/Trial.suggest_*/best_trial.user_attrs/TrialPruned/logging.set_verbosity; Phase 8: FastAPI 0.136.3 lifespan/CORSMiddleware/UploadFile/run_in_threadpool/FileResponse, Starlette 1.3.0 TestClient, Pydantic 2.13.4 BaseModel/field_validator/ConfigDict, httpx 0.28.1, sklearn 1.9.0 roc_curve/precision_recall_curve/auc/average_precision_score; **Phase 11: sklearn 1.9.0 MultiLabelBinarizer.fit/transform (train-only vocabulary; unknown test labels ignored with UserWarning), OneVsRestClassifier on an indicator matrix, roc_auc/average_precision multilabel averaging, classification_report on indicator inputs; re-confirmed @playwright/test 1.61.0 / vitest 4.1.9 / recharts 3.8.1 — no new deps**) — all versions pinned in backend/requirements.lock
- [ ] [RISK]-comment review by team lead (HUMAN) — inventory in `docs/governance_signoff_v1.0.md` §4
- [ ] Leakage-audit sign-off (HUMAN) — proving tests in `docs/governance_signoff_v1.0.md` §5
- [ ] Team lead (Naveen) sign-off per phase (HUMAN)
- [ ] Final stakeholder demo + acceptance (HUMAN) — Amit Shah, DharaniKiran Kavuri, Matat Rotbaum; demo script in `docs/governance_signoff_v1.0.md` §8
- [ ] Signatures collected + repo tagged `v1.0` (HUMAN)

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
| 2026-06-15 | Phase 7 — Sections 14–16 (plot_results + ModelRunner + CLI) + tests | 130 tests passing (13 new); ModelRunner deep-copy config isolation + corrected order + robust per-algo failures; plot1/2/3/5 with placeholder fallbacks; CLI inspect/run with load_dotenv; engine feature-complete; real-data run on iris (LR/RF/XGB/LGBM, acc 0.93–0.97); prompt archived; plan_tweak row 23 added |
| 2026-06-15 | Docs — RUNBOOK.md (how to run the engine + interpret outputs) | Command-first operator's manual added (setup/inspect/run/outputs/re-run-overwrite/troubleshooting); all claims derived from code + verified with live --inspect + binary + multiclass runs; prompt archived to prompts/doc_runbook.md |
| 2026-06-16 | Housekeeping — prompts/ reorg, removed doc Stop hook, renamed short_desc.md→backend_short_desc.md | `prompts/` split into backend_phases/api_phases/frontend_phases/tooling/docs (+ README); `scripts/check_docs_updated.py` + Stop hook deleted; CLAUDE.md/plan_tweak/PROJECT_STATE references updated; Phase 7 (and Phase 4) short_desc entries verified already present + accurate; no engine code touched; prompt archived to prompts/tooling/reorg.md |
| 2026-06-16 | Phase 7B — Section 8B Optuna hyperparameter tuning layer (`tuning.py`) + sanctioned config/runner/CLI edits + RUNBOOK section | 147 tests passing (17 new); OFF by default; one uniform per-model study, CV-in-train leakage-safe scoring, hard 600s/model timeout, per-model isolation; AutoML pulled v1.5→v1.0 (plan_tweak 24–25); optuna 4.9.0 added + pinned; real-data CLI `--tune` run verified; prompt archived to prompts/backend_phases/phase_07B_tuning.md |
| 2026-06-16 | Tooling — added `backend/run_tests.ps1` (venv-Python pytest runner; forwards args, no activation needed) + RUNBOOK note | Convenience only; **no engine code touched, no behaviour change** (so backend_short_desc/plan_tweak deliberately not updated). Commit ad44354 |
| 2026-06-16 | Phase 7B follow-up — LogisticRegression tuning space → `C` only | Fixed FutureWarning (`penalty` deprecated, sklearn 1.9) + multiclass `liblinear` errors surfaced by a real LR-on-iris tuning run; +1 multiclass regression test (148 total); decisions log + plan_tweak row 26 + backend_short_desc updated |
| 2026-06-17 | Phase 8 — FastAPI layer (`backend/api/`) + `/api/v1/run` schema LOCKED | 184 tests (36 new); 6 endpoints (health/upload/run/explain/outputs) driving ModelRunner/inspect_file, no ML added; sanctioned `evaluation/curves.py` helper + plot2 refactor; additive `StorageAdapter.save_input` for uploads; `/explain` v1.0 stub; sync `/run` via threadpool (background jobs → v1.5); `docs/api_contract.md` locked; `api_short_desc.md` created; plan_tweak 27–31; prompt archived to `prompts/api_phases/phase_08_fastapi.md` |
| 2026-06-17 | Phase 9a — React frontend foundation (design pick + typed client + Upload→Configure→Run round-trip) | Owner chose **Option A "Clarity"** + **Recharts** from 3 mockups; Tailwind v4 + shadcn/ui design system (one token block); typed client mirrors the LOCKED contract exactly (no invented fields, no contract gaps); 13-page app shell + health banner + global store; Upload/Configure/Pipeline/Overview real, 9 stubs; **live round-trip + Vite proxy verified**; 13 FE tests (vitest); deps pinned + hallucination-checked; `frontend_short_desc.md` created; plan_tweak 32; prompt archived to `prompts/frontend_phases/phase_09a_foundation.md` |
| 2026-06-17 | Phase 9b — React result-rendering pages (Overview upgrade + 6 result pages) against the LOCKED contract | Built Feature Impact / Confusion Matrix / Class Report / ROC-PR Curves / Predictions / Interaction Features + upgraded Overview; shared `ResultGate`/`ModelSelector`/`PngArtifact` + `lib/results` helpers; interactive-vs-PNG rule honored (plot PNGs fetched via `/outputs`, guarded for absence); read from the app store, no backend edits; captured a **multiclass** fixture (real TestClient) alongside the binary one; **46 FE tests** (33 new), build clean; binary+multiclass verified vs fixtures, multilabel rendered-but-unverified; no contract gaps; recharts 3.8.1 hallucination-checked; no plan_tweak (chart/UX in decisions log); prompt archived to `prompts/frontend_phases/phase_09b_result_pages.md` |
| 2026-06-17 | Phase 9c — React remaining pages + polish (Explainability stub, Setup Guide, Risk Register, Overview/Pipeline merge) — **Phase 9 complete** | Built Explainability (v2.0-ready stub wired to the frozen `/explain`), Setup Guide + Risk Register (static, authored from RUNBOOK/API_RUNBOOK/api_contract + CLAUDE.md constraints + engine `[RISK]` themes); **merged Overview + Pipeline → 12 nav items**, `/pipeline` redirects to `/`, deleted `Pipeline.tsx`/`StubPage.tsx`; polish pass (sticky/shrink-0 sidebar, chart `aria-label`, contrast bump, shared empty/loading/error states); **55 FE tests** (9 new), build clean; no contract gaps; react-router-dom 7.18.0 `Navigate` + recharts 3.8.1 + vitest/Testing Library hallucination-checked; plan_tweak row 33 (13→12 page/nav); prompt archived to `prompts/frontend_phases/phase_09c_remaining_polish.md` |
| 2026-06-20 | Phase 10 — browser E2E (Playwright, 2-server) + real CORS + render-gap coverage + suite audit | **Phase 10 complete.** Playwright 1.61.0 (pinned) + Chromium; `playwright.config.ts` two-server `webServer` (venv uvicorn + Vite), test-only env (DATA_DIR→samples, throwaway OUTPUT_DIR `backend/.e2e_output`, CORS allowlist); `e2e/happy-path.spec.ts` parametrized (binary+multiclass run **live** → asserts real SVG geometry, curve count 1/N, n×n heatmap cells, loaded PNG, predictions banner, + `/explain` live path); `e2e/cors.spec.ts` (cross-origin GET + preflight OPTIONS, allowlist real never `*`); +7 vitest gap tests (`client.test.ts` ApiError mapping, `errorStates.test.tsx` 400/upload). **Suites green: 184 pytest · 62 vitest · 4 E2E**; build clean. Tests only — **no app/engine code changed, no bug found, no deviation** (one tooling touch: `vite.config.ts` `test.include` to scope vitest off `e2e/`). Hallucination-checked vs installed versions. Prompt archived to `prompts/testing_phases/phase_10_e2e_testing.md` |
| 2026-06-20/21 | Phase 11 (FINAL) — multilabel end-to-end + 7-use-case sweep + 12k perf baseline + governance dossier | **Engineering complete; v1.0 ready for sign-off/demo.** Multilabel (Product Recommendation) wired end-to-end for the first time — new `classifyos/multilabel.py` (delimited-set ↔ indicator bridge) + additive multilabel branches in runner/predict/curves/plots/api (`MultiLabelBinarizer` train-only → OvR; per-label metrics/curves/report/predictions; honest `null` for confusion/MCC); binary+multiclass untouched. **All 7 use cases** driven through engine+API (`test_use_case_sweep.py`, 8 tests) AND browser (Playwright 7-case sweep, multilabel asserts honest states). 4 new datasets + 12k perf set generated (`generate_sample_data.py`); use-case CSVs committed as the E2E seed. **Perf: 12k×4 algos = 13.0s** (target < 5 min); tuning sanity (XGB, 25 trials) = 65.7s. **Governance dossier** `docs/governance_signoff_v1.0.md` (scope §12 checklist + 35-row [RISK] table + leakage proof + demo script + v1.0 limitations + human action items). **Suites: 202 pytest · 72 vitest · 9 E2E (all green)**; build clean. plan_tweak 34–37. Scope conclusion: multilabel ships "runs+renders honestly with documented limits" (per-label thresholds + imbalance weighting → v1.x). **Human sign-offs/demo + `v1.0` tag remain.** Prompt archived to `prompts/testing_phases/phase_11_integration_signoff.md` |
| 2026-06-22 | Tuning search-space audit (READ-ONLY) — produced `docs/tuning_audit.md` | Read-only investigation; no code/test/config changed. Documented per-model tuned-vs-missing hyperparameters (validated against installed sklearn 1.9.0 / xgboost 3.2.0 / lightgbm 4.6.0 / optuna 4.9.0), trial scoring + leakage boundary, tuning.py→ModelRunner→build_model flow, config/CLI/API configurability, and safe-vs-dangerous user-exposed knobs. Top findings: LightGBM missing `max_depth` (num_leaves≤255 unbounded → overfit risk), XGBoost missing `gamma`, SVM `kernel=["rbf"]` no-op categorical, unvalidated `search_space_overrides`, misleading `--timeout` CLI help. No backend_short_desc change (no engine change); no plan_tweak (investigation only). Prompt archived to `prompts/tooling/audit_search_spaces.md` |
| 2026-06-23 | Read-only audit of tuned-params data path → `docs/tuned_params_path_audit.md` | Read-only investigation; no code/test/config changed. Traced per-model `best_params` engine→API→UI: engine produces it (`ModelRunner.tuned_params_` + `run_profile.json` `tuning.best_params`/`tuned_models`), but `/run` response model/serializer omit it (only reachable as the downloadable `run_profile.json` via `/outputs`), so the typed UI never receives it. Recommended Option 1 (additive `result.tuning` block, `schema_version` 1.0→1.1, zero engine change; Overview panel) over Option 2 (UI scrapes `run_profile.json` — untyped coupling + extra fetch); version bump shown safe (parser is version-tolerant, validates only known keys). Per-layer blast radius listed. No backend_short_desc/plan_tweak change (no code change). Prompt archived to `prompts/tooling/audit_tuned_params_path.md` |
| 2026-06-26 | Tuning UI — per-model search-space override editor + removed default timeout cap | Frontend exposes `tuning.search_space_overrides` (was hardcoded `{}`): collapsible "Search space (advanced)" → per-algorithm collapsibles with low/high numeric overrides + categorical choice checkboxes (`searchSpaces.ts` mirror + `TuningOverridesPanel.tsx`); blank = engine default so an untouched panel sends `{}`. **`timeout_seconds` default `600`→`None` everywhere** (config.py/api models/form/contract examples) per owner request — `n_trials` is now the sole study bound; "No timeout" UI switch (default on). Reverses plan_tweak #25; `[RISK]` comment kept+rewritten. No engine ML / no schema-version change (default-value only). Tests flipped (`test_default_timeout_is_uncapped` + `_n_trials_is_the_bound`; buildPayload expects `null`); backend tuning+API-run green (46), FE build clean. Also added data dir to `.claude` `additionalDirectories` (CSV @-tagging). plan_tweak #43. Pre-existing red: `referencePages.test.tsx` nav count 13≠12 (interaction-unwiring branch, not this work) |
| | | |
