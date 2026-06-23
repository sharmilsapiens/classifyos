# Prompt 2 of 2 — UI: dedicated "Tuning Results" page showing chosen hyperparameters

> Archive at prompts/frontend_phases/phase_XX_tuning_page.md (use the next frontend phase number).
> RUN THIS ONLY AFTER prompt 1 (API schema 1.1) is committed and its tests are green.

---

Read CLAUDE.md, PROJECT_WISDOM.md, PROJECT_STATE.md, plan_tweak.md, frontend_short_desc.md,
api_short_desc.md first. Also read docs/tuned_params_path_audit.md (Section D, UI layer) and
docs/api_contract.md (the new 1.1 `result.tuning` block). This is a UI-only change. Do NOT
modify engine or API code. The `/api/v1/run` response now carries `result.tuning` (schema 1.1).

## Goal

Add a DEDICATED dashboard page (with a sidebar nav entry) that displays the tuned
hyperparameters for the last run — so a user can see which models were tuned and the exact
hyperparameter values chosen for each. Read it from the `result.tuning` field already in the
store (no new network call; do NOT scrape run_profile.json).

## Changes (per the audit Section D, UI layer, adapted for a dedicated page)

1. **frontend/src/api/types.ts** — add a `RunTuning` interface mirroring the 1.1 contract block
   exactly (enabled, metric, cv, cv_folds, n_trials, timeout_seconds, tuned_models: string[],
   best_params: Record<string, Record<string, unknown>>) and add `tuning?: RunTuning | null` to
   `RunResult`. No invented fields — mirror the contract.

2. **New page** `frontend/src/pages/TuningResults.tsx` — reads the last run's `result.tuning`
   from the app store. States to handle (reuse the shared Empty/Loading/Error components — no
   blank screens):
   - No run yet → empty state inviting a run.
   - Run exists but tuning was OFF (`tuning` null/`enabled:false`) → a clear "Tuning was not
     enabled for this run" message, with a hint that it's toggled in Configuration.
   - Tuning ON → a header strip showing the tuning settings (metric, cv/cv_folds, n_trials,
     timeout), then ONE card or table PER tuned model (from `tuned_models`), each listing its
     `best_params` as a readable key → value table. Use the existing design tokens / shadcn
     components / table styling already used elsewhere; keep numbers in the mono font like other
     metric displays. Models that were NOT tuned (in the run but absent from tuned_models) get a
     small "ran on defaults" note so the picture is complete.

3. **Routing + nav** — register the page in `frontend/src/App.tsx` and add a sidebar entry in the
   nav source (lib/nav.ts or equivalent). Pick a clear label ("Tuning Results") and group it with
   the other result pages. Active-state highlight like the others.

4. **Guarding** — every `best_params` value is `unknown`; render defensively (stringify
   numbers/bools/strings; never crash on an unexpected type). Handle a tuned model whose
   best_params is empty (`{}` → "no params returned, used defaults").

## Tests (vitest + Testing Library, render-level)

- Add a `tuning` block to a captured run fixture (or a new fixture) and assert the page renders
  one section per tuned model with the right param values, plus the settings header.
- A fixture with `tuning: null` (tuning off) renders the "not enabled" state, not a crash.
- The no-run empty state renders.
- Nav has the new entry; route resolves. Full existing FE suite still green; `npm run build` clean.

## Process

- Verify against installed versions (react-router, recharts if used, vitest/Testing Library) —
  hallucination check. No new runtime deps expected.
- Save this prompt to prompts/frontend_phases/phase_XX_tuning_page.md.
- Update PROJECT_STATE.md and frontend_short_desc.md (new page + the 1.1 field it consumes).
  plan_tweak.md: only if a real deviation arises (otherwise note none — this realises the 1.1
  field added in the API prompt).
- Commit as: "ui: dedicated Tuning Results page showing chosen hyperparameters (consumes schema 1.1)"
