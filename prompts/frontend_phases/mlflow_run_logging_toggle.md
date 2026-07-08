# Prompt — Configuration toggle to log a run to MLflow (frontend-only)

> Archived verbatim per the governance requirement (CLAUDE.md → "MANDATORY before
> committing any generated section, save the exact generation prompt"). This is a
> pure dashboard addition (no engine, API, or contract change), so it lives under
> `frontend_phases/`.

## Task (verbatim)

> Add a frontend-only control to turn MLflow run-logging on/off from the Configuration page.
> Context: MLflow logging (Phases A/2a) already exists at the engine + API layer via the
> `mlflow.enabled` config flag and is surfaced in the API's `RunConfig.mlflow` block (schema 1.9),
> but there is no UI control for it today, so users can only enable it by hand-crafting an API
> request. This is purely a dashboard addition — no engine, API, or contract change.
>
> - Add a toggle on the Configuration page (the "Post-training analysis" card is the natural home,
>   or a small dedicated "Run tracking" control), labelled something like "Log this run to MLflow
>   (run history + saved models)", with a short hint that it records the run to the server's MLflow
>   store and is silently skipped if that store isn't configured/reachable.
> - Wire it through the existing form plumbing: add the field to `ConfigFormState` +
>   `DEFAULT_FORM_STATE`, and have `buildPayload` emit `mlflow.enabled`. Default it ON in the UI
>   (send `true` by default) — this deliberately differs from the engine/API default (OFF), exactly
>   like the existing `threshold_mode` UI-default-vs-engine-default pattern; leave a code comment
>   noting that so it isn't "corrected" later. The `RunConfig`/`mlflow` TS types already exist from
>   1.9 (add the field if missing).
> - Keep it minimal: only the `enabled` toggle. Do not add experiment/run_name inputs (those stay at
>   their defaults; run_name has a separate pending follow-up).
> - Additive only. No `schema_version` bump (the mlflow block already shipped in 1.9). Do not touch
>   the deferred Databricks phases.
>
> When done: run the relevant frontend tests and make sure they pass (add a `buildPayload` test
> asserting `mlflow.enabled` is true by default and false when toggled off, plus a Configure render
> test that the toggle appears and flips the form field), then update PROJECT_STATE.md and
> frontend_short_desc.md. Update plan_tweak.md only if this genuinely deviated — this is additive UI,
> so most likely no entry. Hallucination check is N/A here (no new library calls — pure React +
> existing types), but confirm that. Archive this session's generation prompt under prompts/ (per
> CLAUDE.md — frontend_phases/) in the same commit as the code.

(Standard session footer: read PROJECT_STATE.md + the relevant short_desc files + CLAUDE.md first;
respect no-leakage / additive-changes / StorageAdapter / locked-contract constraints; run the
relevant tests; update PROJECT_STATE.md + the appropriate short_desc file(s); update plan_tweak.md
only on a genuine deviation; hallucination-check any library calls against installed versions.)

## Implementation summary (what was built)

- **Types** (`frontend/src/api/types.ts`) — added the request-side `MlflowConfig` interface
  (`enabled: boolean`, optional `experiment?`/`run_name?`, mirroring `backend/api/models.py`
  `MlflowConfig`) and a `mlflow: MlflowConfig` field on `RunConfig`. The response-side `MlflowInfo`
  already existed from 1.9; this adds the missing request-side type.
- **Form plumbing** (`frontend/src/lib/buildPayload.ts`) — added `mlflow_enabled: boolean` to
  `ConfigFormState`, defaulted it **`true`** in `DEFAULT_FORM_STATE` with a code comment recording
  the deliberate UI-default-vs-engine-default divergence (same pattern as `threshold_mode`), and
  emit `mlflow: { enabled: form.mlflow_enabled }` from `buildPayload`. Only `enabled` is sent;
  `experiment`/`run_name` stay at their server defaults.
- **UI** (`frontend/src/pages/Configure.tsx`) — a small dedicated **"Run tracking"** card after the
  Post-training analysis card with one `Switch` ("Log this run to MLflow (run history + saved
  models)") + a hint that it records to the server's MLflow store and is silently skipped if that
  store isn't configured/reachable.
- **Tests** — `buildPayload.test.ts` +1 (`mlflow.enabled` true by default; false when toggled off);
  `configure.test.tsx` +2 (the toggle renders checked-by-default; toggling calls
  `updateForm({ mlflow_enabled: false })`). **142 vitest green (+3, was 139) · `tsc -b` + `vite
  build` clean.**
- **Hallucination check** — N/A: no new library calls (pure React + existing `@/api/types`); the
  `mlflow.enabled` field maps to the already-shipped schema-1.9 request block. Confirmed.
- **No `schema_version` bump** — the `mlflow` request block shipped in 1.9; this only surfaces it.
- **No plan_tweak entry** — additive UI over an existing request-side field, realizing the task;
  recorded as a Decisions-log row in PROJECT_STATE.md.
