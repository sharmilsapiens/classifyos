# Phase 7 Generation Prompt — Plots + ModelRunner + CLI (Sections 14, 15, 16)

> Archive location: prompts/phase_07_runner.md

---

Read CLAUDE.md, PROJECT_STATE.md, plan_tweak.md first. This session completes the ML engine:
Section 14 (plot_results — all 6 plots), Section 15 (ModelRunner — orchestrator),
Section 16 (CLI). After this phase a single call runs the whole pipeline end to end and
writes all outputs. Phases 1–6 code must not be modified. NO FastAPI yet (Phase 8).

This phase supersedes dev_run.py — ModelRunner is the real orchestrator. Leave dev_run.py
in place (it's a dev tool) but ModelRunner is what the API and CLI will use.

## Files to create

1. `backend/classifyos/evaluation/plots.py`  — Section 14
2. `backend/classifyos/runner.py`            — Section 15, ModelRunner
3. `backend/classifyos/cli.py`               — Section 16
4. Tests: `tests/test_plots.py`, `tests/test_runner.py`, `tests/test_cli.py`

## Section 15 — runner.py (ModelRunner) — the heart of this phase

```python
class ModelRunner:
    def __init__(self, config: dict, storage: StorageAdapter): ...
    def run(self) -> "ModelRunner": ...
    # state attributes set during run():
    raw_df_, train_df_, test_df_, predictions_df_, metrics_df_,
    feature_impact_, models_   # dict name->fitted wrapper
```

run() executes the CORRECTED canonical order (NOT the scope's outdated step diagram):

1. data_loader → self.raw_df_
2. analyze_feature_impact (on raw_df_, before preprocessing) → self.feature_impact_
   (+ writes feature_impact_summary.csv, plot4)
3. train_test_split_cls → self.train_df_, self.test_df_
4. Preprocessor.fit(train) → transform train AND test
5. FeatureBuilder.fit(train) → transform both
6. InteractionFeatureBuilder.fit(train) → transform both (+ plot6)
7. handle_class_imbalance(train only) → balanced train matrices + class_weight
8. For each algorithm in config["algorithms"]:
   build_model → fit on balanced train → classify on test → evaluate_model
   Collect per-model metrics into self.metrics_df_ and predictions into
   self.predictions_df_ (tagged by model). Keep fitted models in self.models_.
9. Save everything (Section 14 plots + CSVs + run_profile.json) to OUTPUT_DIR.

CRITICAL — **_run_config isolation**: run() must deep-copy config at the start and use the
copy internally; self.config is NEVER mutated during a run (so the same ModelRunner /
config can be re-run, and interaction-feature additions don't leak back into config).
[RISK] comment marking the deep-copy. This is the scope's central correctness rule.

Robustness: if one algorithm fails (e.g. a library edge case), log it, record the failure
in metrics, and continue with the others — one bad model must not kill the whole run.

## Section 14 — plots.py

`plot_results(runner, storage)` producing 6 PNGs (Agg backend, dpi=150, white facecolor,
figures closed after save, all via StorageAdapter):
- plot1_confusion_matrix.png  (per algorithm; normalized + raw — subplots or per-model)
- plot2_roc_pr_curves.png     (ROC + PR per class/algorithm; AUC in legend)
- plot3_feature_importance.png (from tree models / available importances)
- plot4 already written in step 2 (feature impact) — don't duplicate
- plot5_calibration_curve.png (per algorithm vs perfect diagonal; binary)
- plot6 already written in step 6 (interactions) — don't duplicate
So plots.py creates plot1, plot2, plot3, plot5. Guard gracefully when a model lacks
importances (skip in plot3) or when multiclass makes PR ill-defined (handle or skip).

## Output files (to OUTPUT_DIR via StorageAdapter)

classification_results.csv (predictions_df_), metrics_comparison.csv (metrics_df_),
class_report.csv (per-class per-model), run_profile.json (input_file, target, features,
active_features incl. interaction cols, problem_type, class_distribution, algorithms,
timestamp), plus plot1/2/3/5 (+ plot4/plot6 from earlier steps).

## Section 16 — cli.py

- `load_dotenv()` at startup (MANDATORY — engine does not auto-load .env; without it
  LocalFolderStorage falls back to relative defaults). Build storage from env.
- argparse: --file, --target, --features, --problem-type, --test-size, --algos
  (comma list), --balance, --encoding, --scaling, --inspect (inspect-only mode: run
  inspect_file and print, no full run), --output-dir (optional override).
- Default features = all columns except target and id_like/datetime (use inspect_file).
- Run mode: build_config → ModelRunner(config, storage).run() → print a metrics summary
  table (per model: accuracy, F1-weighted, ROC-AUC, MCC) and the list of files written.
- Fail readably per stage (real data is messy).

## Tests

Real CSVs from DATA_DIR (tests redirect OUTPUT_DIR to tmp). Required:

- **test_runner_end_to_end_binary**: ModelRunner on policy_lapse with 2–3 algos →
  run() completes; predictions_df_, metrics_df_, feature_impact_ populated; all expected
  output files exist in (tmp) OUTPUT_DIR.
- **test_runner_multiclass**: risk_tier 3-class end-to-end; metrics computed per model.
- **test_config_not_mutated**: deep-copy a config, run(), assert the original config dict
  is unchanged (the _run_config isolation guarantee).
- **test_runner_handles_bad_algo**: an algorithm that errors is recorded as failed and the
  run still completes for the others.
- **test_all_output_files**: classification_results.csv, metrics_comparison.csv,
  class_report.csv, run_profile.json, plot1/2/3/5 present after a binary run.
- **test_cli_inspect**: --inspect mode prints columns/class distribution, no full run.
- **test_cli_run** (subprocess or main() call): a small run produces outputs and a
  summary without error.
- Regression: FULL suite (Phases 1–6) green.

## Process requirements

- Type hints, docstrings, [RISK] comments (esp. the deep-copy isolation point).
- All file I/O via StorageAdapter; matplotlib Agg + close after save.
- Verify library signatures against installed versions.
- Full pytest suite green before finishing.
- Save this prompt to prompts/phase_07_runner.md.
- Update PROJECT_STATE.md, short_desc.md (Phase 7 entries), plan_tweak.md if any deviation
  (note: ModelRunner implements the corrected order, not the scope's step diagram —
  cross-reference the Phase 3 decision). If nothing new deviated, state so.
- Commit as: "Phase 7: plots + ModelRunner + CLI — sections 14-16 + tests"

## After this phase — real-data milestone

This is the first point a single command runs everything. In this session, after tests pass,
also run the CLI on a REAL CSV from DATA_DIR/real and report the metrics summary + the files
written to the real OUTPUT_DIR (do NOT commit data or real outputs). This is the first true
end-to-end look at ClassifyOS on real insurance data.

---

## Generation notes (post-build addendum)

- ModelRunner implements the **corrected canonical order** (split before preprocessing),
  cross-referencing the Phase 3 pipeline-order decision (plan_tweak row 4) — NOT the
  scope's 8-step diagram.
- `_run_config` isolation realised by a single `copy.deepcopy(self.config)` at the top of
  `run()`; `self.config` is the untouched object the caller passed (asserted in
  `test_config_not_mutated`). The sub-builders each deep-copy config internally too, so
  interaction columns added to the working frames never leak back.
- Robustness: each algorithm runs inside a try/except in `_run_one_algorithm`; a failure
  (including an unknown algorithm name → `build_model` ValueError) is logged and recorded
  as a `status="failed"` row with the error string; the run continues.
- plots.py renders plot1/2/3/5 only (plot4/plot6 written upstream). Degenerate cases fall
  back to labelled placeholder PNGs (no feature importances → plot3 placeholder; multiclass
  → plot5 placeholder, since calibration/PR are binary views), so the artifact set is always
  complete. Multiclass plot2 uses one-vs-rest ROC per class (PR skipped).
- 13 new tests; full suite **130 passed**. Real-data run: `real/iris.csv` (multiclass) with
  LR/RF/XGB/LGBM, accuracy 0.93–0.97, all 11 artifacts written to the real OUTPUT_DIR.
