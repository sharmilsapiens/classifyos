# ClassifyOS — Claude Code Context

GenAI-developed ML classification framework for the insurance domain (Sapiens · AI/ML Data).
Predicts categorical outcomes from structured tabular data: binary, multiclass, multilabel.
Read PROJECT_STATE.md for current progress before starting any work.

## Architecture

React frontend → FastAPI backend → Python ML engine.
Config is set in the browser, POSTed to FastAPI, executed by the ML engine, JSON results
stream back and populate charts/tables. The ML engine has NO web dependencies — pure Python,
importable and runnable standalone via CLI.

```
frontend/   React (Vite + TS) — 13 pages, shadcn/ui, charts, typed API client (Phase 9, in progress)
backend/
  classifyos/   ML engine (the "16 sections" + 8B tuning + curves helper, split into modules)
  api/          FastAPI layer (Phase 8, done) — routes, RunConfig (Pydantic), serializers
  tests/        pytest — one test file per section + API tests
prompts/    Archived generation prompts (governance requirement)
docs/       api_contract.md — the LOCKED /api/v1/run schema (schema_version 1.0)
```

## Directory & module map (logical section → physical file)

| Section | Module |
|---|---|
| 1–2 CONFIG, build_config | backend/classifyos/config.py |
| 3 inspect_file | backend/classifyos/io/inspect.py |
| 4 data_loader | backend/classifyos/io/loader.py |
| 5 analyze_feature_impact | backend/classifyos/analysis/feature_impact.py |
| 6 preprocess | backend/classifyos/preprocessing/preprocess.py |
| 7 build_features | backend/classifyos/preprocessing/features.py |
| 7B build_interaction_features | backend/classifyos/preprocessing/interactions.py |
| 8 handle_class_imbalance | backend/classifyos/preprocessing/balance.py |
| 9 train_test_split_cls | backend/classifyos/split.py |
| 10 evaluate_model | backend/classifyos/evaluation/metrics.py |
| 11 model wrappers (×6) | backend/classifyos/models/ (base.py defines the ABC) |
| 12 MODEL_REGISTRY | backend/classifyos/models/registry.py |
| 13 classify | backend/classifyos/predict.py |
| 14 plot_results | backend/classifyos/evaluation/plots.py |
| 15 ModelRunner | backend/classifyos/runner.py |
| 16 CLI | backend/classifyos/cli.py |
| 8B tune_model (Optuna) | backend/classifyos/tuning.py |
| — curve points (ROC/PR) | backend/classifyos/evaluation/curves.py (Phase 8, shared by plot2 + API) |

## Critical constraints — NEVER violate

- **No data leakage.** Encoder, scaler, and SMOTE are fitted/applied on the TRAINING split only.
  The test set is never modified by preprocessing, balancing, or feature selection statistics.
- **Sections are additive.** A later section never modifies an earlier one. New models are added
  via MODEL_REGISTRY only — never by editing existing wrapper code.
- **_run_config isolation.** ModelRunner deep-copies config before any mutation. self.config is
  never mutated during a run.
- **Storage abstraction.** ALL file I/O goes through StorageAdapter
  (backend/classifyos/io/storage.py). Local folders now (DATA_DIR / OUTPUT_DIR env vars);
  Databricks (Unity Catalog volumes) later. Never hardcode paths; never call open() directly
  in pipeline code.
- **[RISK] comments.** Embed inline [RISK] comments at known risk points (leakage, imbalance,
  calibration, multicollinearity, threshold sensitivity). Never remove an existing [RISK]
  comment without documented rationale.
- **API contract is LOCKED (Phase 8).** The `/api/v1/run` request/response schema lives in
  `docs/api_contract.md` (schema_version 1.0, frozen). Frontend code is generated against it;
  never change it silently — additive changes only, bumping the version.
- **Single source of curve points.** `evaluation/curves.py` (`compute_curve_points`) computes
  all ROC/PR curve points, shared by `plot_results` (plot2) and the API so the PNG and the JSON
  can never drift. It reads held-out test predictions only — fits nothing.
- **API is stateless.** A FastAPI process holds no model between requests. No feature may assume
  a previous request's state persists in v1.0 (this is why `/explain` is a stub until v2.0 model
  persistence). The API WRAPS the engine — it never reimplements ML logic.

## Conventions

- Interaction feature naming: `col_a_x_col_b` (multiply), `col_a_div_col_b` (ratio),
  `col_a_minus_col_b` (difference).
- Model wrapper interface (ABC in models/base.py): `__init__, fit, predict, predict_proba,
  feature_importance`. predict_proba returns shape (n, n_classes) for every problem type.
- All routes under `/api/v1/`. CORS uses an env-configured allowlist — never `["*"]` outside
  local dev.
- **Frontend (Phase 9+):** React (Vite + TypeScript), built in slices (9a foundation → 9b
  result pages → 9c remaining + polish). Uses **shadcn/ui** for components. Design language:
  simple, vibrant, clear, easy to use — strong hierarchy, obvious primary actions, accessible
  contrast. The typed API client mirrors `docs/api_contract.md` exactly (never invent/rename
  fields — flag gaps instead). PNGs are fetched on demand via `/outputs/{name}`, never inlined.
  Chart library + concrete design tokens are fixed in 9a (record the choice in PROJECT_STATE).
- Type hints + docstrings on every public function. Pydantic v2 style validators.
- Default metrics stance: F1-weighted is primary; MCC and PR-AUC alongside Accuracy on
  imbalanced problems.
- Every generated section gets a unit test on real sample data before integration.
- Generation prompts are archived under `prompts/` (governance requirement), organised into
  subfolders by surface: `backend_phases/` (engine, `phase_NN_*.md`), `api_phases/`,
  `frontend_phases/`, `tooling/` (dev/tooling/housekeeping prompts), `docs/` (documentation
  prompts). See `prompts/README.md` for where a new prompt lands. Archived prompts are kept
  verbatim as the historical record.

## Environment record (installed versions — for machine migration)

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11.0 | venv per project (backend/.venv) |
| Node.js | 24.16.0 (LTS) | needed for Claude Code + React frontend |
| Git | 2.54.0 | global user configured |
| OS | Windows | PowerShell as default shell |

If setting up a new machine: install these (or newer within the same major version),
clone the repo, recreate backend/.venv from requirements.txt, run npm install in frontend/.
Exact Python package versions are pinned in backend/requirements.txt after first install
(`pip freeze`). Git identity: re-run `git config --global user.name / user.email`.
Copy `backend/.env.example` → `backend/.env` and set `DATA_DIR`/`OUTPUT_DIR` to local
data folders outside the repo (`.env` is gitignored and does not travel — see the
data-dir convention below); seed `DATA_DIR` from the committed `backend/data/samples/`.

## Environment & commands

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000
pytest tests/ -v

# frontend
cd frontend
npm install
npm run dev          # Vite dev server, proxies /api → :8000

# ML engine standalone (--file is a key relative to DATA_DIR)
python -m classifyos.cli --file policy_lapse.csv --target will_lapse --inspect
```

Env vars (backend/.env): `DATA_DIR`, `OUTPUT_DIR`, `CORS_ORIGINS`.

**Data-dir convention.** `DATA_DIR`/`OUTPUT_DIR` point at folders *outside* the repo
(e.g. `C:/Projects/classifyos_data/input` and `.../output`) so datasets and artifacts
never get committed. `backend/.env` is gitignored, so these absolute paths are
**machine-local and do not travel with the repo** — set them per machine. The portable
pieces are `backend/.env.example` (template) and the committed `backend/data/samples/`
CSVs (used to seed a fresh `DATA_DIR`). Forward slashes work in `.env` on Windows
(`pathlib` normalises them). The test suite reads the real `DATA_DIR` but redirects
`OUTPUT_DIR` to a pytest temp dir, so running tests never writes to the real output folder.

**`.env` loading.** Only the test suite (`conftest.py`) auto-loads `.env`. The engine,
CLI, and API do **not** load it implicitly — a standalone process must call
`load_dotenv()` (or have the env vars exported) or `LocalFolderStorage` falls back to its
relative `data`/`classification_output` defaults. The CLI (Section 16) and FastAPI layer
(Phase 8) must load `.env` at startup.

## Insurance use cases (validation targets)

Policy Lapse (binary, will_lapse) · Claim Likelihood (binary, will_claim) ·
Fraud Detection (binary, is_fraud, ~99:1 imbalance) · Risk Tier (multiclass) ·
Customer Segment (multiclass) · Claim Severity (multiclass) ·
Product Recommendation (multilabel).

## Working style

- One section/phase per session where possible. Generate → unit test on real CSV → integrate.
- **Doc updates are enforced via the phase prompts, not a hook.** At the end of EVERY session
  that changes engine code, update PROJECT_STATE.md and backend_short_desc.md; update
  plan_tweak.md only if a real deviation/assumption occurred (do not invent entries).
- PROJECT_STATE.md is the live status (what was completed, decisions, known issues, next
  steps); it is synced to the planning Claude Project after each update.
- `backend_short_desc.md` holds the plain-language one-line phase summaries for the engine.
  (Future: `api_short_desc.md` and `frontend_short_desc.md` when those surfaces are built;
  each will open with a shared short "About ClassifyOS" header, then its own surface-specific
  summaries.)
- If a library API call is uncertain, verify against the installed version (hallucination
  check is a governance requirement) — run a quick import/dir check rather than guessing.
- MANDATORY before committing any generated section: save the exact generation prompt
  used to prompts/section_NN_name.md and include it in the same commit as the code.
  Never commit generated section code without its prompt file.