# Prompt — Expand Optuna search spaces (LightGBM max_depth, XGBoost gamma, SVM kernel)

> Archive at prompts/backend_phases/phase_07B2_search_space_expansion.md

---

Read CLAUDE.md, PROJECT_WISDOM.md, PROJECT_STATE.md, plan_tweak.md, backend_short_desc.md
first. This is a focused engine change: expand the hyperparameter search spaces in
`backend/classifyos/tuning.py` only. Base every change on `docs/tuning_audit.md` (the
read-only audit already in the repo). Do NOT touch the model wrappers, the registry, the
runner flow, the config schema, the API, or the CLI — only the `_space_*` functions in
tuning.py and their tests. Verify all parameter names/validity against the INSTALLED versions
(xgboost 3.2.0, lightgbm 4.6.0, scikit-learn 1.9.0) — hallucination check.

## Changes (exactly these three; do not add others this session)

1. **LightGBM — add `max_depth`** to `_space_lightgbm`. Suggest int `3 … 12` (uniform).
   This is the highest-value fix: `num_leaves` is tuned up to 255 with depth currently
   unbounded (-1), which overfits on smaller datasets. Add a [RISK]/explanatory comment that
   max_depth now bounds the leaf-wise growth (the standard num_leaves ≲ 2^max_depth guard).
   Keep num_leaves as-is.

2. **XGBoost — add `gamma` (min_split_loss)** to `_space_xgboost`. Suggest float `0.0 … 5.0`
   (uniform). It is a complexity regulariser distinct from depth and the L1/L2 terms. Comment
   what it does (minimum loss reduction required to make a split).

3. **SVM — fix the no-op `kernel` choice** in `_space_svm`. Currently `kernel=["rbf"]` tunes
   nothing. Change to a real categorical `["rbf", "linear"]`. IMPORTANT: when `kernel="linear"`,
   `gamma` is ignored by SVC — make the space conditional so `gamma` is only suggested for
   `rbf` (use Optuna's conditional suggestion: suggest kernel first, then suggest gamma only if
   rbf). Add a comment that linear is cheaper and sometimes wins on scaled data, but the
   calibrated SVC is still the slow model — the existing small-n_trials guidance stands.

Leave all other models and all other parameters unchanged. Do NOT change ranges that the
audit judged sound. Do NOT add the lower-priority items (min_split_gain, max_delta_step, RF
max_depth ceiling, LR penalty/solver) — those are deferred.

## Tests — update/extend tests/test_tuning.py

- A LightGBM tuning trial now includes `max_depth` in the returned best-params keys, within
  3…12.
- An XGBoost tuning trial now includes `gamma` in the returned best-params keys, within 0…5.
- An SVM tuning run can select either kernel; when kernel resolves to "linear", the returned
  params do NOT contain a numeric gamma (conditional space works); when "rbf", gamma is present.
- Existing tuning tests still pass; tests keep tiny budgets (n_trials<=5, cv_folds=2, do NOT
  tune SVM with a large budget — keep its trial count minimal to stay fast).
- Full pytest suite green (regression).

## Wrap-up

- Save this prompt to prompts/backend_phases/phase_07B2_search_space_expansion.md.
- Update PROJECT_STATE.md (session log + note the 3 search-space additions) and
  backend_short_desc.md (one line on the expanded tuning spaces).
- plan_tweak.md: add a short row only if you consider this a deviation worth recording
  (expanded tuning coverage beyond the original 07B spaces); otherwise note "refinement of
  existing tuning, no scope deviation". Your call — do not invent.
- Update RUNBOOK.md tuning section IF it enumerates per-model tuned params (so it stays
  accurate); if it only describes the controls, no change needed.
- Commit as: "Phase 7B.2: expand Optuna search spaces (LGBM max_depth, XGB gamma, SVM kernel)"
