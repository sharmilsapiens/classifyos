# Prompt 1 of 2 — API: expose tuned hyperparameters on /run (additive, schema 1.0 → 1.1)

> Archive at prompts/api_phases/phase_XX_tuning_in_response.md (use the next api phase number).
> RUN THIS FIRST. The UI prompt (prompt 2) depends on this being committed.

---

Read CLAUDE.md, PROJECT_WISDOM.md, PROJECT_STATE.md, plan_tweak.md, backend_short_desc.md,
api_short_desc.md first. Also read docs/tuned_params_path_audit.md — it is the source of truth
for this change (Option 1, Section C/D). This is an ADDITIVE API change only. Do NOT modify any
engine code (backend/classifyos/**) — the runner already produces the data. Do NOT change the
UI in this session (separate prompt).

## Goal

Surface the per-model tuned hyperparameters on the `/api/v1/run` response so the dashboard can
display them. The engine already holds them (`ModelRunner.tuned_params_`) and writes them
(`run_profile.json` → `tuning` block). The locked response currently omits them. Add an
ADDITIVE optional `result.tuning` block and bump `schema_version` 1.0 → 1.1. Never mutate or
rename any existing 1.0 field.

## Exact change (per the audit, Section C Option 1 + Section D)

1. **docs/api_contract.md** — add the new optional `result.tuning` block to the response
   section; add a "1.1 (additive)" note explaining the new field; leave all existing 1.0 field
   descriptions intact. Document that `tuning` is null/absent when tuning was OFF.

   Shape:
   ```jsonc
   "tuning": {                      // NEW in 1.1; null when tuning was OFF
     "enabled": true,
     "metric": "f1_weighted",
     "cv": true,
     "cv_folds": 3,
     "n_trials": 30,
     "timeout_seconds": 600,
     "tuned_models": ["XGBoost"],
     "best_params": { "XGBoost": { "learning_rate": 0.07, "max_depth": 6, "gamma": 1.2 } }
   }
   ```

2. **backend/api/models.py** — add a `RunTuning` Pydantic response sub-model; add
   `tuning: RunTuning | None = None` to `RunResult`; bump `RunResponse.schema_version` default
   "1.0" → "1.1". `best_params` is heterogeneous → type it `dict[str, dict[str, Any]]`. The
   block must be fully optional so a non-tuning run is unchanged.

3. **backend/api/routes/run.py** — add a `_tuning(runner)` helper that returns
   `runner.run_profile_.get("tuning")` (or assembles from `runner.tuned_params_` + the tuning
   config), and include it in `_build_result`. When tuning was off / produced nothing, return
   None so the field is null. Do not alter any existing reshaper output.

4. **api_short_desc.md** — note the new `result.tuning` field and the 1.1 bump.

## Tests (additive — do not weaken existing ones)

- A tuned run (small budget: n_trials<=5, cv_folds=2, tune ONE fast model e.g. XGBoost) returns
  `result.tuning` with `enabled=True`, the model in `tuned_models`, and `best_params[model]`
  non-empty and JSON-serializable.
- A non-tuning run returns `result.tuning` as null (or omitted) and is otherwise byte-identical
  to current 1.0 behaviour for the existing fields.
- `schema_version` in the response is now "1.1".
- Full existing API + engine suite still green (regression — the additive field must break nothing).

## Process

- Verify Pydantic v2 signatures against the installed version (hallucination check).
- Confirm the frontend parser tolerance noted in the audit is real (parse.ts validates only known
  keys + checks schema_version is a string) — but DO NOT touch the frontend this session; just
  rely on it being version-tolerant so 1.1 won't break the current UI.
- Save this prompt to prompts/api_phases/phase_XX_tuning_in_response.md.
- Update PROJECT_STATE.md, api_short_desc.md. plan_tweak.md: add a row (additive contract bump
  1.0→1.1 to expose tuned params; the first version bump of the locked contract — note it was
  done additively, existing fields untouched).
- Commit as: "api: expose tuned hyperparameters on /run response (additive, schema 1.0→1.1)"
