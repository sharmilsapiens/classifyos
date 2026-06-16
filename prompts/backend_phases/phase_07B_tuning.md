# Hyperparameter Tuning Prompt — Optuna tuning layer (new Section 8B / Phase 7B)

> Archive location: prompts/backend_phases/phase_07B_tuning.md
> Scope note: AutoML/hyperparameter search was listed OUT OF SCOPE for v1.0 in the scope doc
> (planned v1.5). Adding it now is a deliberate, sanctioned deviation — record in plan_tweak.md.

---

Read CLAUDE.md, PROJECT_STATE.md, plan_tweak.md, backend_short_desc.md first. This session
adds an Optuna-based hyperparameter tuning layer as a NEW module. It must NOT modify the
model wrappers (Phase 6) or the registry — tuning wraps around them. It integrates into
ModelRunner as an optional step BEFORE each model is fit. Engine code from Phases 1–6 is
otherwise unchanged; ModelRunner (Phase 7) gets a sanctioned edit to call the tuner.

## Design principle

ONE uniform tuning mechanism for all six models, fully controlled by config at RUN TIME.
"Which models to tune", "how hard", and "which metric" are runtime dials, not build-time
choices. Search spaces are defined in code (defaults) but overridable via config. Tuning is
OFF by default. Each model is tuned independently (its own study) — one model tuning poorly
or erroring must not affect the others (same robustness pattern as Phase 6/7 per-algo isolation).

## Leakage rule (non-negotiable)

Every trial is scored INSIDE the training split only — never the test set. Default scoring
is k-fold cross-validation within train; a single train-internal validation split is the
faster alternative. The test set is untouched by tuning. [RISK] comment marking this.
Class balancing (SMOTE etc.) inside CV must be applied per-fold on the fold's train portion
only — do NOT balance before CV (that leaks synthetic rows across folds). If integrating
balancing into the CV loop is too complex this pass, document the chosen approach explicitly
and add a [RISK] note; the safe default is: tune on the pre-balance train folds, balance only
the final fit.

## Files

1. `backend/classifyos/tuning.py` — new module
2. Sanctioned edit: `backend/classifyos/runner.py` — call the tuner before fitting when enabled
3. Sanctioned edit: `backend/classifyos/config.py` — add the `tuning` config sub-dict
4. Tests: `tests/test_tuning.py`
5. Update `RUNBOOK.md` (new tuning section)

## tuning.py

```python
def tune_model(model_name, X_train, y_train, problem_type, config,
               class_weight=None, random_state=42) -> dict:
    """Returns the best hyperparameters found (dict) for model_name, or {} if the
    model has no defined search space or tuning is disabled for it."""
```

- Uses Optuna. One `study` per model. TPE sampler (default), seeded from random_state for
  reproducibility. Direction = maximize the configured metric.
- **Search spaces** — define per model in a `SEARCH_SPACES` dict (a function per model that
  takes an Optuna `trial` and returns params). Provide rich spaces for the models that
  benefit, minimal/default for the rest (be honest about this in comments):
  - XGBoost: learning_rate (log 0.01–0.3), max_depth (3–10), n_estimators (100–800),
    subsample (0.6–1.0), colsample_bytree (0.6–1.0), min_child_weight (1–10),
    reg_alpha (log 1e-3–10), reg_lambda (log 1e-3–10).
  - LightGBM: num_leaves (15–255), learning_rate (log 0.01–0.3), n_estimators (100–800),
    feature_fraction (0.6–1.0), bagging_fraction (0.6–1.0), min_child_samples (5–100),
    reg_alpha, reg_lambda (log).
  - RandomForest: n_estimators (100–600), max_depth (3–30 or None), max_features
    ("sqrt"/"log2"/0.5–1.0), min_samples_leaf (1–10), min_samples_split (2–20).
  - LogisticRegression: C (log 1e-3–1e2), penalty/solver compatible pairs.
  - SVM: C (log 1e-2–1e2), gamma (log 1e-4–1e0), kernel (rbf default). (Note: slow — comment.)
  - NaiveBayes: var_smoothing (log 1e-12–1e-6). (Note: rarely moves — comment honestly.)
- **Scoring per trial**: build the model via build_model(name, ...) with the trial's params,
  evaluate with the configured metric. Default = k-fold CV (config: cv_folds, default 3 or 5)
  within train; alternative = single train-internal validation split (config flag). Use the
  same leakage-safe handling described above.
- **Budget controls (runtime, from config)**: n_trials (per model) and/or timeout_seconds
  (per model). Optuna supports both; pass through. If a model isn't in the tune list, return {}.
- **Robustness**: wrap each study in try/except; on failure log it and return {} (fall back to
  defaults) — never kill the run. A single failed trial is pruned/skipped, not fatal.
- Return the best params dict; the caller passes them into build_model for the final fit.

## config.py — `tuning` sub-dict (sanctioned edit, with validation)

```
"tuning": {
    "enabled": False,                # OFF by default
    "models": [],                    # which models to tune; [] or ["all"] handled explicitly
    "metric": "f1_weighted",         # what to optimize; reuse evaluate_model's metric names
    "cv": True,                      # True = k-fold CV in train; False = single val split
    "cv_folds": 3,
    "n_trials": 30,                  # per model
    "timeout_seconds": None,         # per model; None = no timeout (trials cap applies)
    "search_space_overrides": {},    # optional per-model bound overrides
}
```
Add validation in build_config (enum/type checks; metric must be a known one).

## runner.py — sanctioned integration

In run(), for each algorithm: if config["tuning"]["enabled"] and the model is in the tune
list (or "all"), call tune_model(...) on the (pre-balance) TRAIN data, get best params,
and pass them into build_model for the final fit on the balanced train. If tuning is off or
returns {}, behave exactly as today (defaults). Record in run_profile.json which models were
tuned and the best params found (audit trail). Keep _run_config isolation intact (tuning must
not mutate self.config). [RISK] comment on the deep-copy still holding.

## Tests — test_tuning.py

- test_tune_xgboost_returns_params: tuning XGBoost on policy_lapse with n_trials=5 returns a
  non-empty params dict with expected keys.
- test_tuning_improves_or_matches: a tuned model's CV score >= the default model's CV score
  on the same train folds (allow equality; tuning shouldn't make it worse).
- test_test_set_untouched: tuning never accesses the test split (structural — tune_model
  receives only train; assert no test data is passed).
- test_disabled_is_noop: enabled=False → ModelRunner produces identical results to pre-tuning
  behavior (same metrics within tolerance).
- test_model_not_in_list_uses_defaults: tuning XGB only leaves RF/LR on defaults.
- test_tuning_failure_falls_back: a model whose study errors returns {} and the run completes.
- test_n_trials_respected and test_timeout (small timeout) honored.
- test_config_not_mutated: tuning run leaves the original config unchanged.
- Regression: FULL suite (Phases 1–7) green.

## Process requirements

- Add `optuna` to requirements.txt; pin it in requirements.lock (pip freeze). Verify the
  installed Optuna API (study creation, sampler, trial.suggest_* signatures, timeout param)
  against the installed version — hallucination check.
- Type hints, docstrings, [RISK] comments (leakage in CV, per-fold balancing, deep-copy).
- Full pytest suite green before finishing.
- Update RUNBOOK.md: a new "Hyperparameter tuning" section — how to enable it (config/CLI),
  the runtime dials (models, n_trials, timeout, cv), what gets recorded in run_profile.json,
  the expected cost (tuning multiplies fits; tree models benefit most; NB rarely moves), and
  a worked example command. If the CLI needs a --tune flag (or --trials/--timeout) to expose
  this, add it (sanctioned cli.py edit) and document it.
- Save this prompt to prompts/backend_phases/phase_07B_tuning.md.
- Update PROJECT_STATE.md, backend_short_desc.md (tuning entry), and plan_tweak.md
  (deviation: AutoML/hyperparameter search pulled from v1.5 into v1.0; Optuna over grid
  search; CV-default; uniform-but-honest search spaces).
- Commit as: "Phase 7B: Optuna hyperparameter tuning layer + RUNBOOK update + tests"

---

## Implementation note (added during the session — not part of the original prompt)

Deviations from the prompt's literal spec, all sanctioned and recorded in plan_tweak.md
(rows 24–25):

- **`timeout_seconds` default is `600`, not `None`.** A hard per-model wall-clock cap was
  added on the user's explicit instruction so a tuning run can NEVER be unbounded — with
  `models=[]` (tune-all), enabling tuning would otherwise run a 30-trial study for every
  algorithm including the slow calibrated-SVM. Explicit `None` is still accepted as an opt-out
  for runs scoped with a short `models` list.
- **Best params are read from `study.best_trial.user_attrs`, not `study.best_params`**, so a
  space that transforms a suggestion (e.g. the LogisticRegression `"solver|penalty"`
  categorical split into two kwargs) returns exactly the params that were scored.
- **Balancing is NOT applied inside CV folds** (the prompt's documented safe default):
  tuning scores on the pre-balance train folds; ModelRunner balances only the final fit.
  `class_weight` is passed through to `build_model` during tuning (mild approximation, noted).
- **CLI flags added** (sanctioned `cli.py` edit): `--tune`, `--tune-models`, `--tune-metric`,
  `--trials`, `--timeout`, `--tune-cv-folds`.
