# Dev Tool Prompt — dev_run.py (standalone pipeline runner)

> Not a phase. A development/smoke-test utility. Archive at prompts/tool_dev_run.md.

---

Read CLAUDE.md first. Create a standalone script that runs the pipeline built so far
(Phases 1–4) end-to-end on a real CSV and writes real artifacts to OUTPUT_DIR, so the
pipeline can be exercised before the ModelRunner (Phase 7) exists. Do NOT modify any
pipeline code or tests. Do NOT commit any data files — confirm DATA_DIR is outside the
repo / gitignored.

## File: backend/scripts/dev_run.py

- `load_dotenv()` at the very top (before importing anything that reads env), so it uses
  the real DATA_DIR / OUTPUT_DIR from backend/.env — NOT the LocalFolderStorage defaults.
- Build a LocalFolderStorage from env, same as the app will.
- CLI args (argparse):
  `--file` (required, path relative to DATA_DIR, e.g. real/claim_behaviour.csv)
  `--target` (required)
  `--features` (optional, comma-separated; default = all columns except target and any
   detected ID-like / datetime columns)
  `--problem-type` (optional; if omitted, infer from inspect_file's suggested_problem_type)
  `--encoding`, `--scaling`, `--balance` (optional overrides, pass through to build_config)
- Flow, printing a clear banner before each step and a one-line result after:
  1. inspect_file() → print columns, dtypes split, class_distribution of target;
     STOP with a helpful message if target not found or has <2 classes.
  2. build_config() from the args + inspection.
  3. data_loader().
  4. analyze_feature_impact() → writes feature_impact_summary.csv + plot4 to OUTPUT_DIR;
     print top 5 features by composite_score and flag any id_like=True columns.
  5. train_test_split_cls() → print train/test row counts and class balance each side.
  6. Preprocessor.fit_transform(train) + transform(test) → print feature count in/out.
  7. FeatureBuilder + InteractionFeatureBuilder → print created + interaction columns,
     write plot6 to OUTPUT_DIR.
- End with a summary block: input rows, raw feature count, final feature count,
  interaction columns created, and the list of files written to OUTPUT_DIR.
- Wrap each stage in try/except that prints which stage failed and the exception
  message (real data is messier than synthetic — fail readably, not with a raw trace).
- This script is allowed to print freely; it is a human tool, not pipeline code.

## After building

- Do a dry self-check: run it against a SYNTHETIC file
  (`python scripts/dev_run.py --file policy_lapse.csv --target will_lapse`) and confirm
  it completes and writes plot4 + plot6 + the CSV to OUTPUT_DIR. Report what it printed.
- Do NOT run it on the real data yourself (the user will do that and inspect outputs).
- Add a usage note to short_desc.md ("dev_run.py — manual smoke test, real outputs to
  OUTPUT_DIR; usage: python scripts/dev_run.py --file <rel> --target <col>").
- Save this prompt to prompts/tool_dev_run.md.
- Commit as: "dev: standalone pipeline runner (dev_run.py) for real-data smoke tests"

---

## Build notes / deviations (2026-06-15)

- **Import bootstrap.** Running `python scripts/dev_run.py` puts `scripts/` (not the
  backend root) on `sys.path[0]`, so `import classifyos` would fail. The script inserts
  `BACKEND_DIR` (parent of `scripts/`) onto `sys.path` before importing the engine, and
  calls `load_dotenv(BACKEND_DIR / ".env")` explicitly (the same `.env` the test suite
  loads) so it never depends on cwd.
- **Default-feature ID detection refinement.** Default features exclude the target,
  detected datetime columns (from `inspect_file`), and ID-like columns. "ID-like" uses
  the same ≥0.99 distinct-fraction threshold as `analyze_feature_impact`, but is
  restricted to NON-float columns — a continuous float (e.g. `sum_assured`) is naturally
  near-unique yet a legitimate feature; excluding it by default would gut the smoke test.
  Object/string codes (`policy_id`) and integer row-IDs are still excluded. Step 4 still
  surfaces the framework's own `id_like=True` flag for any such column that remains in
  the feature set (transparent warning, separate from default-exclusion).
- **Self-check result** (`--file policy_lapse.csv --target will_lapse`): completed exit 0;
  3000 rows → 12 raw features → 57 final features, 10 interaction columns; wrote
  `feature_impact_summary.csv`, `plot4_feature_impact.png` (~105 KB),
  `plot6_interaction_summary.png` (~88 KB) to OUTPUT_DIR.
