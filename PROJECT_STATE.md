# ClassifyOS — Project State

> Living document. Updated at the end of every working session (by Claude Code or manually).
> A copy is uploaded to the ClassifyOS Claude Project knowledge after each update so the
> planning/overseer chat stays in sync with the local repo.

**Last updated:** 2026-06-12
**Updated by:** Claude Code (Phase 3 session)
**Repo tag / commit:** dd514a0 (Phase 2 follow-up) + Phase 3 commit pending

---

## Current status

**Active phase:** Phase 3 complete — Preprocessing (Section 6)
**Sprint day:** Phase 3 done
**Overall:** 🟢 Leakage boundary is live — Preprocessor fits on train only, all tests green

One-line summary: Section 6 `Preprocessor` (fit/transform) implemented — missing-value
imputation, train-fitted outlier capping, onehot/ordinal/target/frequency encoding with
high-cardinality auto-switch, and scaling, all statistics computed on the TRAIN split
only. 41 tests passing (27 prior + 14 new, incl. dedicated leakage tests). Ready for
Phase 4 (build_features + interactions).

---

## Phase tracker

| Ph. | Milestone | Status | Notes |
|---|---|---|---|
| 0 | Repo + env setup, CLAUDE.md, sample CSVs in DATA_DIR | ✅ Done | Scaffold, StorageAdapter, venv+install, sample CSVs all in place |
| 1 | Framework skeleton (Sections 1–4, 9) | ✅ Done | config, inspect, loader, split + 22 tests passing on real samples |
| 2 | Feature analysis (Section 5) | ✅ Done | analyze_feature_impact + 5 tests on real samples; CSV + 2-panel PNG outputs |
| 3 | Preprocessing (Section 6) | ✅ Done | Preprocessor (fit/transform, train-only stats) + 14 tests incl. leakage suite |
| 4 | Feature engineering (Sections 7, 7B) | ⬜ Not started | |
| 5 | Class balancing (Section 8) | ⬜ Not started | |
| 6 | Models + evaluation (Sections 10–13) | ⬜ Not started | |
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

- Nothing in flight. Phase 3 closed; Phase 4 (Sections 7 + 7B — build_features,
  interactions) not yet started.

## Known issues / bugs

| # | Issue | Severity | Found | Status |
|---|---|---|---|---|
| | none | | | |

## Blockers

- None. Sample CSVs are in `DATA_DIR`; venv installed; tests green.

---

## Next steps (priority order)

1. Commit Phase 3 ("Phase 3: preprocessing with leakage guards — section 6 + tests").
2. Upload updated PROJECT_STATE.md to the Claude Project knowledge.
3. Pin exact versions via `pip freeze > requirements.lock` (governance: reproducible env) — still pending.
4. Phase 4 generation session: Sections 7 + 7B — `build_features`
   (`backend/classifyos/preprocessing/features.py`) and `build_interaction_features`
   (`backend/classifyos/preprocessing/interactions.py`) + tests. Both MUST follow the
   same fit/transform pattern as the Preprocessor: any statistic used to derive or
   select features (e.g. interaction-pair auto-selection, fill values) is computed on
   the TRAIN split only and merely applied to test. Interaction naming convention:
   `col_a_x_col_b` / `col_a_div_col_b` / `col_a_minus_col_b`.

---

## API contract status

`/api/v1/run` response schema: **NOT LOCKED** (locks after Phase 8).
Contract doc: docs/api_contract.md — stub only.

## Governance checklist (from scope §12)

- [x] Prompt version control — prompts/ populated per section (phase_01_skeleton.md, phase_02_feature_impact.md, phase_03_preprocess.md archived)
- [x] Section-level unit tests passing on real data (41 passing: 22 Phase 1 + 5 Phase 2 + 14 Phase 3)
- [ ] [RISK] comments reviewed by team lead (3 Phase 1 + 2 Phase 2 + 4 Phase 3, pending review)
- [ ] Leakage audit (encoder/scaler/SMOTE train-only) confirmed — encoder/scaler/imputer train-only now enforced by Preprocessor design + dedicated leakage tests (Phase 3); SMOTE pending Phase 5
- [ ] Output schema contract locked (post Phase 8)
- [x] Hallucination check — library calls verified against installed versions (Phase 1: pandas 2.3.3 / sklearn 1.9.0; Phase 2: scipy 1.17.1 / sklearn 1.9.0 / matplotlib 3.11.0; Phase 3: sklearn 1.9.0 encoders/scalers)
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
| | | |
