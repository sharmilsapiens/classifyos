# ClassifyOS — Project State

> Living document. Updated at the end of every working session (by Claude Code or manually).
> A copy is uploaded to the ClassifyOS Claude Project knowledge after each update so the
> planning/overseer chat stays in sync with the local repo.

**Last updated:** 2026-06-12
**Updated by:** Claude Code (Phase 2 session)
**Repo tag / commit:** fc93002 (Phase 1 + test runner) + Phase 2 commit pending

---

## Current status

**Active phase:** Phase 2 complete — Feature impact analysis (Section 5)
**Sprint day:** Phase 2 done
**Overall:** 🟢 Pipeline skeleton + feature screen in place, all tests green

One-line summary: Section 5 `analyze_feature_impact` implemented on top of the Phase 1
loader — ranks raw features by ANOVA F, mutual information, point-biserial / correlation
ratio, and a composite score; writes summary CSV + 2-panel plot. 27 tests passing
(22 Phase 1 + 5 new). Ready for Phase 3 (preprocess).

---

## Phase tracker

| Ph. | Milestone | Status | Notes |
|---|---|---|---|
| 0 | Repo + env setup, CLAUDE.md, sample CSVs in DATA_DIR | ✅ Done | Scaffold, StorageAdapter, venv+install, sample CSVs all in place |
| 1 | Framework skeleton (Sections 1–4, 9) | ✅ Done | config, inspect, loader, split + 22 tests passing on real samples |
| 2 | Feature analysis (Section 5) | ✅ Done | analyze_feature_impact + 5 tests on real samples; CSV + 2-panel PNG outputs |
| 3 | Preprocessing (Section 6) | ⬜ Not started | |
| 4 | Feature engineering (Sections 7, 7B) | ⬜ Not started | |
| 5 | Class balancing (Section 8) | ⬜ Not started | |
| 6 | Models + evaluation (Sections 10–13) | ⬜ Not started | |
| 7 | Plots + ModelRunner + CLI (Sections 14–16) | ⬜ Not started | |
| 8 | FastAPI layer | ⬜ Not started | |
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

- Nothing in flight. Phase 2 closed; Phase 3 (Section 6 — preprocess) not yet started.

## Known issues / bugs

| # | Issue | Severity | Found | Status |
|---|---|---|---|---|
| | none | | | |

## Blockers

- None. Sample CSVs are in `DATA_DIR`; venv installed; tests green.

---

## Next steps (priority order)

1. Commit Phase 2 ("Phase 2: feature impact analysis — section 5 + tests").
2. Upload updated PROJECT_STATE.md to the Claude Project knowledge.
3. Pin exact versions via `pip freeze > requirements.lock` (governance: reproducible env) — still pending.
4. Phase 3 generation session: Section 6 — `preprocess`
   (`backend/classifyos/preprocessing/preprocess.py`) + tests. First section that fits/applies
   transforms (missing-value imputation, encoding, scaling) — the leakage boundary becomes live:
   everything must be fitted on the TRAINING split only. Feature-impact (Section 5) stays a raw
   screen and is not part of the fitted pipeline.

---

## API contract status

`/api/v1/run` response schema: **NOT LOCKED** (locks after Phase 8).
Contract doc: docs/api_contract.md — stub only.

## Governance checklist (from scope §12)

- [x] Prompt version control — prompts/ populated per section (phase_01_skeleton.md, phase_02_feature_impact.md archived)
- [x] Section-level unit tests passing on real data (27 passing: 22 Phase 1 + 5 Phase 2)
- [ ] [RISK] comments reviewed by team lead (3 in Phase 1 + 2 in Phase 2, pending review)
- [ ] Leakage audit (encoder/scaler/SMOTE train-only) confirmed (N/A until Phase 3+; split boundary established. Section 5 is a raw screen — intentionally pre-split, not part of the fitted pipeline)
- [ ] Output schema contract locked (post Phase 8)
- [x] Hallucination check — library calls verified against installed versions (Phase 1: pandas 2.3.3 / sklearn 1.9.0; Phase 2: scipy 1.17.1 / sklearn 1.9.0 / matplotlib 3.11.0)
- [ ] Team lead sign-off per phase (Naveen)

---

## Session log

| Date | Session focus | Outcome |
|---|---|---|
| 2026-06-12 | Project setup, structure decisions, templates created | CLAUDE.md + PROJECT_STATE.md created |
| 2026-06-12 | Repo scaffold (dirs, StorageAdapter, requirements, env, gitignore, Vite frontend) | Structure ready; no pipeline sections yet |
| 2026-06-12 | Phase 1 — Sections 1–4, 9 (config, inspect, loader, split) + tests | 22 tests passing on real samples; sample data generated; prompt archived |
| 2026-06-12 | Phase 2 — Section 5 (analyze_feature_impact) + tests | 27 tests passing; CSV + 2-panel PNG outputs; prompt archived |
| | | |
