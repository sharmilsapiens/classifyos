# ClassifyOS — Plain-Language Build Summary

What got built, phase by phase, in everyday language. For someone non-technical, or for
anyone returning after a break who wants the gist without reading code.

---

## Phase 0 — Project scaffold & environment setup (✅ Done, 2026-06-12)
**In one line:** Laid the empty skeleton of the whole project — folders, plumbing, and tooling — so later work has a place to live.
- Repo structure: created the backend (Python), frontend (React), and supporting folders matching the planned module map, with empty packages ready to fill in.
- StorageAdapter: a single "file gateway" so the app reads/writes through one place (local folders now, cloud storage later) instead of touching files directly.
- Environment & templates: requirements list, an `.env.example` template, `.gitignore`, and a stubbed API contract doc — everything needed to set up a fresh machine.
- Sample data: scaffolded the place for sample datasets and a React (Vite + TypeScript) frontend shell with a dev proxy to the backend.

## Phase 1 — Framework skeleton (✅ Done, 2026-06-12)
**In one line:** Built the first working pieces of the data pipeline — reading a file, understanding it, loading it, and splitting it for training.
- config.py: defines the settings for a run and validates them (catches bad inputs before anything runs).
- io/inspect.py: peeks at a data file and reports its columns, types, missing values, and a guess at the problem type — without fully loading it.
- io/loader.py: actually loads the data (CSV/Excel/Parquet), checks the target and features are valid, and standardises the target column.
- split.py: divides data into training and test sets — keeping class balance, or splitting by time when asked.
- Tests: 22 automated checks passing on real sample data; synthetic sample datasets (policy lapse, fraud, risk tier) generated.

## Phase 2 — Feature impact analysis (✅ Done, 2026-06-12)
**In one line:** Added a tool that ranks which input columns most strongly relate to the thing we're predicting, with a chart to show it.
- analysis/feature_impact.py: scores every feature against the target using several statistical measures and combines them into one ranked list.
- CSV output: writes `feature_impact_summary.csv` — the ranked table of features and their scores.
- PNG output: writes `plot4_feature_impact.png` — a two-panel chart (top features by combined score, plus a metric comparison).
- ID-column guard: flags columns that look like identifiers (almost all unique values) as leakage-bait — marked, not silently used.

## Phase 2 follow-up — Environment hardening (✅ Done, 2026-06-12)
**In one line:** Tidied up how the project finds its data folders and made sure tests never make a mess in real output folders.
- Data folders moved outside the repo so datasets and results never get committed by accident.
- dotenv notes: documented that only the test suite auto-loads `.env`; the engine, CLI, and API must load it themselves (otherwise they fall back to default local folders).
- Test isolation: tests now write their outputs to a temporary folder instead of the real output directory.

## Phase 3 — Preprocessing (✅ Done, 2026-06-12)
**In one line:** Built the data-cleaning stage — and made its central rule "learn only from training data" enforceable and tested.
- preprocessing/preprocess.py: a `Preprocessor` that fills missing values, caps outliers, encodes categories, and scales numbers.
- Leakage guard: every statistic it uses is learned from the training data only and merely applied to the test data — the core "no data leakage" rule, baked into the design.
- Smart encoding: switches encoding strategy automatically for high-cardinality columns, and handles multiclass problems where target-based encoding doesn't apply.
- Tests: 14 new automated checks (41 total), including dedicated tests that would fail if any leakage crept in.

---

## How to read this project

- **CLAUDE.md** — the conventions and hard rules (what must never be violated).
- **PROJECT_STATE.md** — the live status: what's done, decisions made, known issues, next steps.
- **plan_tweak.md** — the honest register of where we deviated from the original signed plan and why.
- **short_desc.md** (this file) — the plain-language phase-by-phase summary.
