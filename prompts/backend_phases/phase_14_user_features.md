# Prompt — User-defined features (backend engine layer)

> Archive at prompts/backend_phases/phase_XX_user_features.md
> Backend first. API + UI are separate follow-up prompts (same sequencing as the tuning-display change).

---

Read CLAUDE.md, PROJECT_WISDOM.md, PROJECT_STATE.md, plan_tweak.md, backend_short_desc.md
first. This adds USER-DEFINED feature engineering to the engine: the user specifies new
columns derived from existing columns via STRUCTURED operations (not free-text formulas).
This is the engine layer only — do NOT touch the API or UI this session. Do NOT modify
earlier sections except a sanctioned config addition. Follow the same leakage-safe
fit/transform pattern as the existing FeatureBuilder.

## Critical safety rule

NO arbitrary code/formula evaluation. The user NEVER sends a formula string that the backend
evaluates. Users select [column A] + [operation from a fixed allowlist] + [column B] (or a
single-column transform from a fixed allowlist). The backend applies KNOWN operations to
KNOWN columns only. Never use eval/exec on user input. [RISK] comment marking this.

## Scope of operations (fixed allowlists)

Two-column operations: `add` (a+b), `subtract` (a-b), `multiply` (a*b), `divide` (a/b, with
the same near-zero denominator guard the existing ratio features use → fill per the existing
fill_method), `ratio` (alias of divide). Both columns must be numeric (validate; reject with a
clear error otherwise — datetime handling note below).

Single-column transforms (optional, include if clean to do): `log` (log1p, numeric ≥ 0 only),
`abs`, `bin` (quantile bins, reuse the existing binning approach), and date-part extraction
`year`/`month`/`day`/`dayofweek`/`hour` for datetime columns. If a transform doesn't apply to
the column type, reject with a clear message — never silently produce NaN columns.

Datetime difference: support `subtract` on two DATETIME columns → produces a numeric duration
(in a stated unit, e.g. seconds or days — pick one, document it). This covers the
`duration = end_time - start_time` use case explicitly. Validate both columns parse as datetime.

## Design — a new builder, leakage-safe

New module `backend/classifyos/preprocessing/user_features.py`, class
`UserFeatureBuilder(config)` with sklearn-style `fit(train_df, target)` / `transform(df)` /
`fit_transform`, and `created_features_: list[str]`. It reads a config spec (see below) and:
- Validates every requested feature at fit time (columns exist, types are compatible, op is in
  the allowlist) — fail readably listing the bad spec, do not crash the whole run.
- Any statistic needed (e.g. bin edges, log handling, divide fill value) is computed on TRAIN
  ONLY and applied unchanged to test — same leakage rule as FeatureBuilder. [RISK] comment.
- New column naming: clear and collision-safe (e.g. `userfeat_<name>` or the user-supplied
  name validated to be unique and not clash with existing columns). Never overwrite an existing
  column.
- Never mutates input df or config. Picklable (joblib) — needed for artifact export later.

## Config spec (sanctioned config.py addition)

Add a `user_features` key to DEFAULT_CONFIG: a list of structured specs, default `[]` (feature
off when empty). Each spec is a dict, e.g.:
```python
{"name": "duration_days", "op": "subtract", "type": "datetime_diff",
 "col_a": "end_time", "col_b": "start_time", "unit": "days"}
{"name": "premium_per_sum", "op": "divide", "type": "numeric", "col_a": "annual_premium",
 "col_b": "sum_assured"}
{"name": "log_claim", "op": "log", "type": "single", "col_a": "claim_amount"}
```
Add validation in build_config: each spec has a valid op/type, referenced columns are strings,
name is a non-empty unique identifier. Reject unknown ops/types (this is the allowlist guard at
the config boundary too).

## Pipeline integration (ModelRunner — sanctioned edit)

UserFeatureBuilder runs AFTER preprocessing and the existing FeatureBuilder, and BEFORE the
interaction auto-discovery step (so user features can themselves become interaction candidates,
and so they exist before balancing/training). fit on train, transform both. Keep _run_config
isolation intact (no mutation of self.config). If `user_features` is empty, this step is a
no-op and the run is identical to current behaviour (assert this in a test).

## Tests — tests/test_user_features.py

- duration: two datetime columns + subtract → a numeric duration column with correct values
  (construct a tiny known case).
- numeric divide: produces a/b, the zero-denominator guard fires (no inf), filled per fill_method.
- single-col log/abs/bin produce expected columns; bin edges are train-only (poison test split,
  edges unchanged).
- validation: a spec referencing a missing column / wrong type / unknown op is rejected with a
  clear error, doesn't crash the run.
- name collision with an existing column is rejected.
- empty user_features → no-op (ModelRunner output identical to a run without the key).
- no mutation of input df/config; joblib round-trip.
- Regression: FULL suite green.

## Process

- Type hints, docstrings, [RISK] comments (no-eval safety; train-only stats). Verify pandas
  datetime / numeric ops against the installed pandas version (hallucination check).
- Full pytest suite green before finishing.
- Save this prompt to prompts/backend_phases/phase_XX_user_features.md.
- Update PROJECT_STATE.md, backend_short_desc.md (UserFeatureBuilder entry), and plan_tweak.md
  (new capability beyond scope: user-defined structured features; explicitly NOT free-text
  formulas, for safety).
- Commit as: "feat: user-defined structured features (engine) — UserFeatureBuilder + tests"

## Note for the follow-up API/UI prompts (do NOT do now)

After this lands: the API needs to accept the `user_features` list in the RunConfig request
(additive — it's request-side, likely no response-schema bump), and the UI needs a builder
panel (dropdowns: column A, operation, column B, new-name; a list of added features). The UI
must send STRUCTURED specs, never a formula string. We'll prompt those separately.
