# Investigation Prompt — Trace the tuned-hyperparameters data path (engine → API → UI) (READ-ONLY)

> Not a phase. Investigation only — produces a report, changes NO code.
> Run this AFTER phase 7B.2 (search-space expansion) has landed, so best_params reflects the
> expanded spaces. Archive at prompts/tooling/audit_tuned_params_path.md.

---

Read CLAUDE.md, PROJECT_WISDOM.md, backend_short_desc.md, api_short_desc.md,
frontend_short_desc.md first. READ-ONLY: do not modify any code, tests, or config — only
write a report.

## Goal

I want to display the chosen (tuned) hyperparameters in the dashboard, so a user can see
which hyperparameters were picked for each model after a tuning run. The engine, API, and
React UI are already built. Before changing anything, I need to know exactly where the tuned
hyperparameter data currently travels and where it stops — across all three layers — so the
change can be made coherently (backend ↔ API ↔ UI) without breaking the locked contract.

## Trace this ONE data path, end to end

1. **Engine** — confirm what tuned-hyperparameter data ModelRunner produces and where:
   `run_profile.json` `best_params` / `tuned_models` (file + field names), and whether any
   tuned-params data is held in memory on the runner (e.g. `self.tuned_params_`) that the API
   could read directly without re-reading the file.
2. **API** — does the `/api/v1/run` RESPONSE currently include the tuned hyperparameters?
   Inspect the response model in `api/models.py` and the run route. State plainly:
   - Is there already a field carrying per-model best_params / tuned info? If yes, name it and
     give its exact shape.
   - If NOT, the locked contract (docs/api_contract.md, schema_version) does not expose it —
     confirm that, and note what an ADDITIVE, version-bumped change would look like (a new
     optional field; never mutate the existing locked fields).
   - Does `/api/v1/outputs` expose run_profile.json for download (an alternative path the UI
     could already use)?
3. **UI** — does the React app already receive/store/display any tuning info? Check the typed
   API client/types, the app store, and the result pages (is there a tuning or
   model-detail page that could host it?). State where a "tuned hyperparameters" panel would
   most naturally live and what data it would need.

## Output → docs/tuned_params_path_audit.md

Structure:
- **Section A — current state**: a 3-row table (Engine / API / UI) — "does the tuned-params
  data exist here? in what shape? what's the exact field/file/type?"
- **Section B — the gap**: the precise point where the data stops (e.g. "engine writes it to
  run_profile.json and holds self.tuned_params_, but the /run response model omits it, so the
  UI never receives it").
- **Section C — change options**, with tradeoffs:
  - Option 1: additive field on the locked /run response (version bump) + UI panel — the clean
    path; specify the exact field shape to add and which files change in each layer.
  - Option 2: UI reads run_profile.json via /api/v1/outputs — no contract change; note
    downsides (extra fetch, parsing a file vs a typed field).
  - A recommendation between them.
- **Section D — blast radius**: list every file that would change per layer for the
  recommended option, and confirm whether the locked contract must bump its schema_version
  (and how that's done additively without breaking the existing frontend).

Keep it factual and sourced from the code. No code changes, no contract changes — report only.

## Wrap-up

- Save this prompt to prompts/tooling/audit_tuned_params_path.md.
- Update PROJECT_STATE.md session log (one line: "read-only audit of tuned-params data path →
  docs/tuned_params_path_audit.md"). No short_desc/plan_tweak change (no code change).
- Commit as: "docs: audit tuned-hyperparameters data path engine→API→UI (read-only)"
