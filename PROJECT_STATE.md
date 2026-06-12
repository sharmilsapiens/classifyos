# ClassifyOS — Project State

> Living document. Updated at the end of every working session (by Claude Code or manually).
> A copy is uploaded to the ClassifyOS Claude Project knowledge after each update so the
> planning/overseer chat stays in sync with the local repo.

**Last updated:** 2026-06-12
**Updated by:** Claude Code (scaffold session)
**Repo tag / commit:** — (initial commit pending)

---

## Current status

**Active phase:** Phase 0 — Project setup (pre-sprint)
**Sprint day:** not started (planned: 4 weeks / 20 days)
**Overall:** 🟡 Setup in progress

One-line summary: Repo structure, environment, and templates being set up. No pipeline
sections generated yet.

---

## Phase tracker

| Ph. | Milestone | Status | Notes |
|---|---|---|---|
| 0 | Repo + env setup, CLAUDE.md, sample CSVs in DATA_DIR | 🔄 In progress | Scaffold + StorageAdapter done; venv/install + sample CSVs pending |
| 1 | Framework skeleton (Sections 1–4, 9) | ⬜ Not started | |
| 2 | Feature analysis (Section 5) | ⬜ Not started | |
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
| | | |

---

## Completed this session

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

- Phase 0: scaffold complete. Still pending: `git init` + initial commit; create
  `backend/.venv` and `pip install -r requirements.txt`; `npm install` in `frontend/`;
  copy `.env.example` → `.env`; place sample CSVs in `DATA_DIR`.

## Known issues / bugs

| # | Issue | Severity | Found | Status |
|---|---|---|---|---|
| | | | | |

## Blockers

- Sample insurance CSVs (lapse, fraud, risk_tier) needed in DATA_DIR before Phase 1
  validation can run on real data.

---

## Next steps (priority order)

1. `git init` (if needed); first commit of the scaffold.
2. Copy `backend/.env.example` → `backend/.env` and point `DATA_DIR`/`OUTPUT_DIR` at
   local folders.
3. Create `backend/.venv`, `pip install -r requirements.txt`; `npm install` in `frontend/`.
4. Place sample CSVs (lapse, fraud, risk_tier) into `DATA_DIR`.
5. Upload updated PROJECT_STATE.md to the Claude Project knowledge.
6. Then: Phase 1 generation session (Sections 1–4, 9).

---

## API contract status

`/api/v1/run` response schema: **NOT LOCKED** (locks after Phase 8).
Contract doc: docs/api_contract.md — stub only.

## Governance checklist (from scope §12)

- [ ] Prompt version control — prompts/ populated per section
- [ ] Section-level unit tests passing on real data
- [ ] [RISK] comments reviewed by team lead
- [ ] Leakage audit (encoder/scaler/SMOTE train-only) confirmed
- [ ] Output schema contract locked (post Phase 8)
- [ ] Hallucination check — library calls verified against installed versions
- [ ] Team lead sign-off per phase (Naveen)

---

## Session log

| Date | Session focus | Outcome |
|---|---|---|
| 2026-06-12 | Project setup, structure decisions, templates created | CLAUDE.md + PROJECT_STATE.md created |
| 2026-06-12 | Repo scaffold (dirs, StorageAdapter, requirements, env, gitignore, Vite frontend) | Structure ready; no pipeline sections yet |
| | | |
