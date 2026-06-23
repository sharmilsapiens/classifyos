# Prompt 2 of 2 — UI: feature-builder panel for user-defined features

> Archive at prompts/frontend_phases/phase_XX_user_features_ui.md
> RUN ONLY AFTER the API prompt is committed and green.

---

Read CLAUDE.md, PROJECT_WISDOM.md, PROJECT_STATE.md, plan_tweak.md, frontend_short_desc.md,
api_short_desc.md first. The /run request now accepts a `user_features` list of structured specs
(see docs/api_contract.md). This session adds a dashboard panel where users build those features
from dropdowns. UI only — do NOT modify engine or API.

## Critical rule (carry the engine's safety contract to the UI)

The panel sends STRUCTURED specs only — {name, op, type, col_a, col_b?, unit?}. There is NO
free-text formula input anywhere. Users choose from dropdowns; the UI never lets a user type an
expression the backend would evaluate.

## Before writing — inspect current state

Read the typed request types (frontend/src/api/types.ts — the RunConfig/TuningConfig shape and
how Configure.tsx + buildPayload.ts assemble the request) so the new field is added the same way
the existing config fields are. The available column list + their types come from the uploaded
file's inspect result already in the store (the same source the target/feature pickers use).

## Change

1. **frontend/src/api/types.ts** — add a `UserFeatureSpec` interface mirroring the API contract
   exactly (name, op, type, col_a, col_b?, unit?) and add `user_features: UserFeatureSpec[]` to
   the request type. No invented fields.
2. **Feature-builder panel** — add to the Configuration page (or a clearly-linked sub-section).
   It lets the user add one feature at a time via dropdowns:
   - `type` selector: numeric (two columns) | single-column transform | datetime difference.
   - based on type, show the right controls:
     - numeric: [col_a ▾] [op ▾ add/subtract/multiply/divide/ratio] [col_b ▾]
     - single: [col_a ▾] [transform ▾ log/abs/bin/year/month/day/dayofweek/hour]
     - datetime_diff: [col_a (end) ▾] [col_b (start) ▾] [unit ▾ days/seconds]
   - a `name` input for the new column (validate client-side: non-empty, unique among existing
     columns + already-added user features; no collision).
   - column dropdowns are populated from the inspected columns; where possible filter by type
     (numeric ops show numeric columns; datetime_diff shows datetime columns) — if type info is
     available from inspect, use it; otherwise show all and let the API 422 guide.
   - an "Add feature" action appends to a list; show the added features as removable chips/rows
     (readable, e.g. "duration_days = end_time − start_time"); allow remove.
3. **buildPayload** — include the assembled `user_features` array in the /run request.
4. Handle the API's 422 for an invalid spec gracefully (surface the message; don't crash).

## Tests (render-level, vitest + Testing Library)

- Adding a numeric feature via the controls appends a spec with the right shape to the payload.
- A datetime_diff feature builds the expected spec (with unit).
- Duplicate / empty name is blocked client-side with a clear message.
- Removing an added feature drops it from the payload.
- No free-text formula input exists in the panel (assert the controls are selects/inputs for
  name only).
- Full FE suite green; `npm run build` clean.

## Process

- Reuse existing design tokens / shadcn components / the established form patterns — match the
  rest of Configuration. Verify against installed versions (react-router, etc.) — hallucination check.
- Save this prompt to prompts/frontend_phases/phase_XX_user_features_ui.md.
- Update PROJECT_STATE.md, frontend_short_desc.md. plan_tweak.md: only if a real deviation;
  otherwise note none (this realises the request field added in the API prompt).
- Commit as: "ui: feature-builder panel for user-defined structured features"

---

## Build notes (Claude Code, 2026-06-23 — archived after implementation)

Implemented as **phase 16** (the UI follow-up to phase 14 engine + phase 15 API). UI-only —
no engine/API touched. Files: `api/types.ts` (`UserFeatureSpec` + `UserFeatureType` + the
`user_features` field on `RunConfig`, mirroring `backend/api/models.py` + the engine's
`USER_FEATURE_*` allowlists exactly), `lib/buildPayload.ts` (`user_features` on
`ConfigFormState`/`DEFAULT_FORM_STATE`=`[]`/`buildPayload`), the new controlled
`components/config/FeatureBuilderPanel.tsx`, and its wiring into `pages/Configure.tsx`.
Tests: `components/config/featureBuilder.test.tsx` (7) + 2 `buildPayload.test.ts` cases →
**91 vitest green** (was 82); `npm run build` clean. 422 surfacing reuses the existing
`ApiError.fieldErrors` → store `runError`/`runFieldErrors` → Overview error path (an invalid
spec returns a precise 422 that already renders there — no crash).

Minor UI choices (not plan deviations): the datetime_diff **unit** dropdown offers all four
engine units (`days`/`hours`/`minutes`/`seconds`), a superset of the prompt's "days/seconds"
example; the single-column **column** dropdown filters numeric- vs date-cols by the chosen
transform (date-parts → datetime cols, log/abs/bin → numeric cols); a typed column list that
comes back empty falls back to all columns (then the API 422 guides). No `plan_tweak` row —
this realises the request field added in phase 15.
