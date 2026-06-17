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

## Phase 4 — Feature engineering & interactions (✅ Done, 2026-06-12)
**In one line:** Added a stage that builds new helper columns from the existing ones — squared terms, ratios, bins for skewed numbers, and combinations of two columns — deciding what to build from the training data only (60 tests passing).
- `FeatureBuilder` (preprocessing/features.py): adds squared terms (off by default), ratio columns, and quantile "bucket" columns for very skewed numbers — each decided on the training data and applied unchanged to the test data.
- `InteractionFeatureBuilder` (preprocessing/interactions.py): combines pairs of columns — multiply (`a_x_b`), divide (`a_div_b`), subtract (`a_minus_b`) — either pairs you name or pairs it auto-discovers on training data, with a guard so dividing by (near-)zero never produces infinities.
- PNG output `plot6_interaction_summary.png`: a bar chart of how strongly each new interaction column relates to the target.
- Dev tool `backend/scripts/dev_run.py`: runs the whole pipeline so far (Phases 1–4) end-to-end on a real CSV and writes the real artifacts (feature_impact_summary.csv, plot4, plot6) to OUTPUT_DIR, failing readably stage-by-stage.

## Phase 5 — Class imbalance handling (✅ Done, 2026-06-15)
**In one line:** Added the stage that evens out lopsided training data (e.g. fraud, where only ~1% of rows are positive) — strictly on the training data, never the test data (70 tests passing).
- `preprocessing/balance.py` (`handle_class_imbalance`): given the training features and labels, it rebalances them one of four ways chosen in the config:
  - **SMOTE** — invents realistic synthetic minority-class rows until the classes are even (with safety guards so it never crashes when the minority is tiny, falling back to simple duplication for a one-of-a-kind class).
  - **Undersample** — randomly drops majority-class rows until the classes are even (and logs how many it threw away).
  - **Class weight** — changes nothing in the data; instead hands the model a "pay more attention to the rare class" instruction. The only option that returns weights.
  - **None** — leaves the data exactly as-is.
- Train-only by design: the function is never even given the test data, so it physically cannot resample or reweight it — the core "no leakage" rule, made structural.
- Multilabel safety: when each row can carry several labels at once (where resampling doesn't make sense), it automatically switches to the class-weight approach and says so.

## Phase 6 — Models & evaluation (✅ Done, 2026-06-15)
**In one line:** Added the part that actually trains models, scores how good they are, and produces a per-customer predictions table — six algorithms, all behind one common interface (117 tests passing).
- Six model wrappers (`models/base.py` + `models/wrappers.py`): Logistic Regression, Random Forest, XGBoost, LightGBM, SVM, and Naive Bayes, all wearing the same "shape" so the rest of the app can use any of them interchangeably — same way of training, predicting, giving class probabilities, and reporting which features mattered.
- Model registry (`models/registry.py`): a lookup table that turns an algorithm name (or a short nickname like "RF" or "XGB") into the right model; new models are added here and nowhere else.
- `evaluate_model` (`evaluation/metrics.py`): given the true answers and the model's predictions, it computes the full scorecard — accuracy, precision/recall/F1, ROC-AUC, PR-AUC, log-loss, MCC, a confusion matrix, a per-class breakdown, and calibration data — all packaged so the web dashboard can read it directly. It deliberately leads with F1 (not accuracy), because accuracy lies on lopsided data like fraud.
- `classify` (`predict.py`): builds the per-row results table — for each test record: the actual label, the predicted label, the probability of each class, the model's confidence, and whether it got it right.
- Rare-class handling carried through: the "pay more attention to the rare class" weights from Phase 5 are fed into every model; SVM uses a calibrated variant so its probabilities are trustworthy; XGBoost's quirk of only accepting numeric labels is handled invisibly.
- Two new libraries (XGBoost, LightGBM) were installed and the exact versions of everything were frozen into a lock file so the setup is reproducible on another machine.

## Phase 7 — Plots, the runner & the command line (✅ Done, 2026-06-15)
**In one line:** Tied every previous stage together so a single command runs the whole thing end-to-end — train every model, score them, draw the charts, and save everything — and added the command-line tool to do it (130 tests passing). **The engine is now feature-complete.**
- `ModelRunner` (runner.py): the conductor. Given a configuration it runs the full pipeline in the correct, leakage-safe order — load the data, rank features, split, clean, engineer features, balance the training data, then train and score every requested algorithm — and writes all the results. It makes a private copy of the configuration so a run never changes the original (you can re-run safely), and if one algorithm trips over a bad edge case it's logged and skipped rather than crashing the whole run.
- `plot_results` (evaluation/plots.py): draws the result charts — confusion matrices (where each model gets right vs wrong), ROC/precision-recall curves (how well each model separates the classes), feature-importance bars (what each model leaned on), and calibration curves (are the probabilities trustworthy). When a chart doesn't apply (e.g. a model with no importances, or calibration for a 3-way problem) it writes a clearly-labelled placeholder so nothing downstream ever finds a missing file.
- The command-line tool (cli.py): `python -m classifyos.cli --file <data> --target <column>`. An `--inspect` mode just profiles the file (columns, missing values, class balance); the normal mode runs everything and prints a tidy per-model scoreboard plus the list of files written. It loads the project's environment settings itself so it always finds the right data and output folders.
- Outputs written for every run: a per-customer predictions table, a model-comparison scoreboard, a per-class breakdown, a JSON "run profile" (an audit record of exactly what was run), and the six charts.
- First real-data run: pointed the tool at a real dataset and trained four algorithms end-to-end — 93–97% accuracy — confirming the whole engine works outside the synthetic samples.

## Phase 7B — Hyperparameter tuning (✅ Done, 2026-06-16)
**In one line:** Added an optional, OFF-by-default Optuna layer that automatically searches for better settings for each model before training it — strictly on the training data, so it never peeks at the test set (147 tests passing).
- `tuning.py` (`tune_model`): for a chosen model, runs a small Optuna "study" that tries different hyperparameter combinations and keeps the best one. One uniform mechanism for all six models; rich search spaces for the tree models that benefit most (XGBoost, LightGBM, RandomForest) and thinner ones for the rest (LogisticRegression tunes its regularisation strength `C`; SVM is slow; NaiveBayes barely changes).
- Runtime dials (all in config / on the CLI): which models to tune, the metric to optimise (default F1-weighted), how many trials, a per-model time cap, and k-fold-vs-single-split scoring. Tuning is OFF unless you ask for it.
- No leakage: every candidate is scored using cross-validation *inside the training split only*; the test set is never touched. Balancing (SMOTE) is applied only to the final fit, never inside the tuning folds.
- Safety: each model is tuned independently — if one model's search errors, it quietly falls back to defaults and the run continues. A **hard default time cap (600s per model)** means a tuning run can never run unbounded.
- The conductor (ModelRunner) calls the tuner before fitting each requested model, feeds the best settings into the final fit, and records what was tuned (and the winning settings) in `run_profile.json`. CLI flags: `--tune`, `--tune-models`, `--tune-metric`, `--trials`, `--timeout`, `--tune-cv-folds`.

## Tooling — Doc-update enforcement hook (✅ Done 2026-06-15, ❌ Removed 2026-06-16)
**In one line:** Briefly added a safety net that wouldn't let a coding session finish if it changed the ML engine but forgot to update the project's living docs — then removed it as ineffective.
- `scripts/check_docs_updated.py`: checked (via git) whether any pipeline code under `backend/classifyos/` changed; if so, it required both PROJECT_STATE.md and backend_short_desc.md to have been updated too.
- Was registered as a Claude Code "Stop" hook in `.claude/settings.json`.
- **Removed 2026-06-16:** the hook could detect that files changed but not that the docs were *meaningfully* updated, and it missed cases anyway. Doc-update discipline now lives in the phase prompts instead (and in CLAUDE.md's working-style rules). The script and the hook entry are gone.

## RUNBOOK.md — operator's manual (✅ Done, 2026-06-15)
**In one line:** RUNBOOK.md added — a plain, command-first guide to running the ML engine from the terminal and reading the results, written against the real CLI and verified with live runs.
- Covers setup (venv + `.env`, the relative-default fallback caveat), `--inspect`, every CLI flag with its default, worked binary/multiclass examples, what each of the 11 output files means, the re-run overwrite limitation (fixed filenames → use `--output-dir` to keep runs), and a troubleshooting table.

---

## How to read this project

- **CLAUDE.md** — the conventions and hard rules (what must never be violated).
- **PROJECT_STATE.md** — the live status: what's done, decisions made, known issues, next steps.
- **plan_tweak.md** — the honest register of where we deviated from the original signed plan and why.
- **backend_short_desc.md** (this file) — the plain-language phase-by-phase summary of the
  ML engine.
- **api_short_desc.md** — the plain-language summary of the API surface (Phase 8 FastAPI layer).
  (Future sibling: `frontend_short_desc.md`.)
- **docs/api_contract.md** — the **locked** `/api/v1/run` request/response schema.
