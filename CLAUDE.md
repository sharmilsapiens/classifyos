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
frontend/   React (Vite + TS) — 13 pages, charts, typed API client
backend/
  classifyos/   ML engine (the "16 sections", split into modules)
  api/          FastAPI layer — routes, RunConfig (Pydantic), serializers
  tests/        pytest — one test file per section + API tests
prompts/    Archived generation prompts (governance requirement)
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
- **API contract is locked after Phase 8.** The /api/run response schema lives in
  docs/api_contract.md. Frontend code is generated against it; do not change it silently.

## Conventions

- Interaction feature naming: `col_a_x_col_b` (multiply), `col_a_div_col_b` (ratio),
  `col_a_minus_col_b` (difference).
- Model wrapper interface (ABC in models/base.py): `__init__, fit, predict, predict_proba,
  feature_importance`. predict_proba returns shape (n, n_classes) for every problem type.
- All routes under `/api/v1/`. CORS uses an env-configured allowlist — never `["*"]` outside
  local dev.
- Type hints + docstrings on every public function. Pydantic v2 style validators.
- Default metrics stance: F1-weighted is primary; MCC and PR-AUC alongside Accuracy on
  imbalanced problems.
- Every generated section gets a unit test on real sample data before integration.
- Generation prompts are archived in prompts/section_NN_name.md (governance requirement).

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

# ML engine standalone
python -m classifyos.cli --file data/samples/lapse.csv --target will_lapse --inspect
```

Env vars (backend/.env): `DATA_DIR`, `OUTPUT_DIR`, `CORS_ORIGINS`.

## Insurance use cases (validation targets)

Policy Lapse (binary, will_lapse) · Claim Likelihood (binary, will_claim) ·
Fraud Detection (binary, is_fraud, ~99:1 imbalance) · Risk Tier (multiclass) ·
Customer Segment (multiclass) · Claim Severity (multiclass) ·
Product Recommendation (multilabel).

## Working style

- One section/phase per session where possible. Generate → unit test on real CSV → integrate.
- After completing work, UPDATE PROJECT_STATE.md: what was completed, decisions made,
  known issues, next steps. This file is synced to the planning Claude Project.
- If a library API call is uncertain, verify against the installed version (hallucination
  check is a governance requirement) — run a quick import/dir check rather than guessing.
