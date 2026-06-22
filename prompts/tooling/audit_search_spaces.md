# Investigation Prompt — Audit current hyperparameter search spaces (READ-ONLY)

> Not a phase. Investigation only — produces a report, changes NO code.
> Archive at prompts/tooling/audit_search_spaces.md.

---

Read CLAUDE.md, PROJECT_WISDOM.md, backend_short_desc.md first. This is a READ-ONLY audit.
Do NOT modify any code, tests, or config in this session — only produce a report document.

## Goal

I want to understand the current state of hyperparameter tuning before improving it:
which hyperparameters are tuned for each model, the range/distribution each is sampled from,
and which important hyperparameters are MISSING. Output a clear report I can review.

## What to inspect (source of truth = the actual code)

Read `backend/classifyos/tuning.py` (the SEARCH_SPACES and the per-model space functions),
plus the model wrappers in `backend/classifyos/models/` and the `tuning` config sub-dict in
`config.py`. For EACH of the six models (LogisticRegression, RandomForest, XGBoost, LightGBM,
SVM, NaiveBayes), report in a table:

| Hyperparameter | Currently tuned? | Type | Range / choices | Distribution (uniform/log/categorical) |

Then, for each model, a second short list: **important hyperparameters NOT currently tuned**
— with a one-line note on what each controls and whether it's typically worth tuning. Base
this on the actual installed library versions (check them — xgboost, lightgbm, scikit-learn
versions in the venv) so the parameter names and validity are correct for OUR versions, not
a generic guess. Flag any currently-tuned parameter whose range looks questionable
(too narrow, too wide, or a suspicious default).

## Also report

- How a trial is currently scored (CV vs single split; which metric; how the leakage-safe
  boundary is implemented — confirm tuning never sees the test set).
- How the chosen best params flow into the final fit (tuning.py → ModelRunner → build_model).
- Where tuning is currently configurable from (config keys today; whether the CLI exposes any
  tuning flags; whether anything is user-facing yet).
- Which parameters, if exposed to a user, would be safe vs dangerous (e.g. an unbounded
  n_estimators or a huge n_trials could blow runtime — note these).

## Output

Write the report to `docs/tuning_audit.md` (this is a doc, not engine code — safe to create).
Structure: one section per model (the two tables above), then a "scoring & flow" section,
then a "configurability today" section, then a "recommendations" section listing the
highest-value additions per model and any ranges worth fixing. Keep it factual and
sourced from the code — no code changes.

## Wrap-up

- Save this prompt to prompts/tooling/audit_search_spaces.md.
- Update PROJECT_STATE.md session log (one line: "tuning search-space audit produced
  docs/tuning_audit.md, read-only"). No backend_short_desc change (no engine change).
  No plan_tweak entry (no deviation — investigation only).
- Commit as: "docs: audit current hyperparameter search spaces (read-only)"
