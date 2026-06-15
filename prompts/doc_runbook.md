# Documentation Prompt — RUNBOOK.md (how to run the ML engine)

> Not a phase. A user-facing operational manual. Archive at prompts/doc_runbook.md.

---

Read CLAUDE.md and PROJECT_STATE.md first. Create `RUNBOOK.md` in the repo root: a plain,
practical manual for running the ClassifyOS ML engine (the CLI / ModelRunner) on a local
machine. This is for a human who wants to run the pipeline and understand the results —
NOT a code-internals doc.

IMPORTANT: derive every factual claim from the ACTUAL code (cli.py, runner.py, plots.py,
the StorageAdapter, .env handling) and from a real test run — do NOT guess. Where behavior
depends on config or environment, say so. If something is uncertain, run it and observe.

## Required sections

### 1. Prerequisites & setup
- Activating the venv (Windows PowerShell, since that's the user's environment).
- Confirming .env is present with DATA_DIR / OUTPUT_DIR, and the reminder that the CLI
  loads .env itself (the relative-default fallback caveat).
- Which directory to run commands from (state the exact working directory).

### 2. Inspect a file first (--inspect mode)
- Exact command to profile a CSV (columns, dtypes, class distribution) without a full run.
- Example using a real file in DATA_DIR. Show representative output and how to read it
  (what to check before choosing a target: class balance, id_like columns, missing data).

### 3. Run the full pipeline
- The exact CLI command, run from the correct directory, with every useful flag explained:
  --file (path relative to DATA_DIR), --target, --features (and the default if omitted),
  --problem-type (and inference if omitted), --algos, --balance, --encoding, --scaling,
  --output-dir.
- 2–3 worked examples: a binary run, a multiclass run, and one with explicit algorithms.
- Note the alias forms accepted for algorithms (LR/RF/XGB/LGBM/SVM/NB).

### 4. Where the outputs go and what each one means
- The exact OUTPUT_DIR location (from .env) and the full list of files written.
- For EACH output file, 1–2 lines on what it contains and how to interpret it:
  classification_results.csv, metrics_comparison.csv, class_report.csv, run_profile.json,
  plot1_confusion_matrix, plot2_roc_pr_curves, plot3_feature_importance,
  plot4_feature_impact, plot5_calibration_curve, plot6_interaction_summary.
- A short "how to read the metrics" note: which metric to trust on imbalanced data
  (F1-weighted / MCC / PR-AUC over raw accuracy), and what a suspiciously high score
  might indicate (leakage — check id_like flags / feature_impact).

### 5. Re-running: what gets overwritten
- VERIFY FROM THE CODE: does a second run overwrite the previous run's files in OUTPUT_DIR?
  State the actual behavior plainly (e.g. "fixed filenames — each run overwrites the last;
  copy or rename outputs you want to keep"). If outputs are NOT isolated per run, note this
  as a known limitation and suggest the --output-dir flag as the manual workaround.
- Note whether run_profile.json records enough to tell two runs apart after the fact.

### 6. Troubleshooting
- The common, real failure modes and their fixes: FileNotFoundError (wrong --file path
  relative to DATA_DIR, or .env not loaded), target not found / <2 classes, a single
  algorithm failing (run continues; where the failure is recorded), outputs appearing in
  the wrong folder (relative-default fallback when .env didn't load).

## Method & wrap-up

- Actually RUN --inspect and at least one full run on a real DATA_DIR/real CSV to capture
  accurate example output for the manual (do NOT commit data or real outputs; redact any
  sensitive column names/values in examples if needed).
- Keep it concise and command-first — copy-pasteable blocks, short explanations.
- Save this prompt to prompts/doc_runbook.md.
- Update PROJECT_STATE.md session log + short_desc.md (one line: "RUNBOOK.md added").
- Commit as: "docs: add RUNBOOK.md (how to run the engine + interpret outputs)"
