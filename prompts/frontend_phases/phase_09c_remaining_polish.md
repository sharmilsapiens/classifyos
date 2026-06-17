# Phase 9c — React frontend: remaining pages + polish (closes Phase 9)

> Paste into a fresh Claude Code session in the ClassifyOS repo.
> Final frontend slice (9a foundation ✅ → 9b result pages ✅ → **9c remaining + polish**).
> After this, Phase 9 is complete and the project moves to Week 4 (Phases 10–11: testing,
> multilabel/real-data/perf validation, governance sign-off).

---

## 0. Read first (in this order)

- `CLAUDE.md` — stable contract, hard rules, frontend conventions.
- `PROJECT_STATE.md` — live status (9a + 9b done; decisions log; "Testing debt" section).
- `docs/api_contract.md` — the LOCKED contract; note the `/explain` response shape specifically.
- `api_short_desc.md` — the endpoints; read the `/explain` entry (it's a v1.0 structured stub).
- `frontend_short_desc.md` — what the shell + result pages already provide.
- `RUNBOOK.md` + `API_RUNBOOK.md` — the REAL setup/run steps (source for the Setup Guide page).
- `plan_tweak.md` — the real v1.0 limitations to be honest about (`/explain` stub #29, sync
  `/run` #28, multilabel resampling #19, etc.).
- The 9a/9b code under `frontend/src/` — you are EXTENDING it, same design tokens and patterns.

The person directing this is **new to frontend/React**. Code must teach as it goes (short
plain-language comments).

---

## 1. What this slice is

Finish the dashboard:
1. **Explainability** page — render the `/explain` v1.0 **stub** honestly (no fake SHAP).
2. **Setup Guide** page — static, sourced from the real RUNBOOK docs + architecture.
3. **Risk Register** page — static, sourced from the real `[RISK]` points + governance items.
4. **Merge Overview + Pipeline into one page** and retire the separate "Pipeline" nav item
   (13 → 12 nav items).
5. **Polish pass** across all pages — desktop-first, basic narrow-screen safety, consistent
   empty/loading/error states, focus order, contrast.

This is the last slice; no result-rendering pages remain (those were 9b).

---

## 2. Frozen vs scope

- **FROZEN:** the entire backend. No backend edits, no new endpoints, no contract changes.
- The Explainability page consumes the EXISTING `/explain` stub response as-is. Do not add a
  backend route to "make explain work" — real SHAP is a v2.0 item (model persistence/MLflow).
- Render only fields the contract defines. Flag any gap; never invent or patch.

---

## 3. Explainability page (the careful one)

`/explain` in v1.0 returns a **structured "unavailable" stub** (see `docs/api_contract.md` /
`api_short_desc.md`): something like `{status:"unavailable", model, sample_index, method:null,
shap_values:null, base_value:null, reason:"no_persisted_model", message:"...deferred to
v2.0..."}`. The reason: a FastAPI process holds no trained model between requests, and v1.0 has
no model registry.

**Build the page to present this honestly — do NOT fake a SHAP waterfall over empty data:**
- A clear, well-designed **"Explainability is coming in v2.0"** state that surfaces the stub's
  `message`/`reason` in plain language: single-row SHAP needs a persisted model, which arrives
  with the v2.0 model registry. Make it look intentional, not broken or like an error.
- Let the user still trigger the call (pick a model + sample row index, hit "Explain") so the
  wiring is real and exercised — then display the structured stub response cleanly. This proves
  the client→`/explain` path works and means v2.0 only has to fill the fields, not rebuild the
  page.
- Shape the UI so a future real response (`shap_values`, `base_value`, `feature_contributions`)
  drops into an already-designed layout — leave the "this is where the waterfall will go"
  region clearly stubbed. Comment that explicitly for the next developer.
- Be honest about the limitation in the page copy; do not imply explainability partially works.

---

## 4. Setup Guide page (static, sourced from the real docs)

A static, well-structured guide — **author the content FROM the real docs, do not free-write
plausible-sounding steps.** Sources: `API_RUNBOOK.md` (start the API), `RUNBOOK.md` (the engine/
CLI), `docs/api_contract.md` (the flow). Cover:
- The architecture in one diagram/section: React → FastAPI (`/api/v1/`) → Python engine.
- The real run flow: start uvicorn on :8000 → Upload a CSV → Configure → Run → view results →
  download artifacts. Mirror the actual endpoints and the Vite dev proxy.
- A short, accurate API reference (the 6 endpoints, from `api_short_desc.md`).
- **Honest v1.0 limitations** (sourced from plan_tweak): `/run` is synchronous (long/tuning runs
  can approach a gateway timeout; background jobs are v1.5); `/explain` is a v2.0 stub; outputs
  are overwritten each run (fixed filenames); multilabel is preliminary/unverified.
- Why static: the `[RISK]` notes and setup steps live in engine source + markdown docs, not in
  any API response — there's no endpoint exposing them, and adding one is a frozen-backend
  change. Authoring from the real docs gives accuracy without coupling the frontend to engine
  internals. (If we ever want it live, exposing risks/steps as data is a clean v1.1 additive
  endpoint — note that as the future path, don't build it now.)

### Risk Register page (static, sourced from the real risk points)
Author from scope §9 + `CLAUDE.md` "critical constraints" + the engine's actual `[RISK]` themes:
leakage (encoder/scaler/SMOTE train-only), class imbalance (F1/MCC/PR-AUC over accuracy),
probability calibration, multicollinearity from interactions, threshold sensitivity, temporal
leakage, and the GenAI-generated-code governance checks. Present each as: risk → mitigation
(matching what the engine actually does). Tie to the governance checklist from scope §12. Keep
it accurate to the build, not aspirational.

---

## 5. Merge Overview + Pipeline

- Make a single page that shows **run progress + live log while a run is in flight**, and the
  **results summary once the run completes** (the 9b Overview content). One continuous screen
  that matches the Configure → Run → watch → see-results flow.
- Retire the separate "Pipeline" nav item; keep the route/redirect stable so existing links/
  state don't break. Nav goes from 13 to 12 items — update `lib/nav.ts` (or wherever nav is
  defined) and note the merge in the docs.
- Don't lose the in-progress UX: the run-status/log view that was the Pipeline page becomes the
  "while running" state of the merged page.

---

## 6. Polish pass (desktop-first, basic narrow-screen safety)

- **Desktop-first.** Ensure no layout breaks on a narrow/resized window (tables scroll, charts
  stay within `ResponsiveContainer`, sidebar collapses or stays usable) — but NOT a full mobile
  redesign. True mobile is post-v1.0.
- Consistent **empty / loading / error** states on every page (reuse the shared components from
  9a/9b — no page should show a blank white screen or an unhandled error).
- **Focus order + keyboard usability**: every interactive control reachable and operable by
  keyboard; visible focus rings; `role="img"`/`aria-label` on charts (from 9b) intact.
- **Contrast**: verify text/background and data colors meet accessible contrast in the Option A
  "Clarity" palette; fix any low-contrast spots without leaving the token set.
- Consistent spacing/hierarchy across pages so the whole app reads as one product.

---

## 7. Tests (vitest + Testing Library; render-level)

- Explainability: renders the stub response cleanly (mock the `/explain` client returning the
  `unavailable` shape); the "Explain" action triggers the client call; no crash on null fields.
- Setup Guide / Risk Register: render without crashing; key sections present.
- Merged Overview/Pipeline: renders the in-progress state and the results state from a fixture.
- Nav: 12 items, no dangling "Pipeline" entry, old route redirects.
- Note that full browser E2E across all use cases (incl. multilabel) remains Phase 10/11.

---

## 8. Hard rules

- Frontend talks ONLY to `/api/v1/`; no backend edits, no new endpoints, no contract changes.
- Explainability consumes the EXISTING stub; do not fake SHAP or imply it works.
- Setup Guide / Risk Register content is authored from the REAL docs, kept honest about v1.0
  limits — not aspirational or invented.
- Keep the Option A design tokens; no off-palette colors. shadcn/ui for components.
- PNGs (if any referenced) fetched on demand via `/outputs/{name}`, never inlined.

---

## 9. WRAP-UP BLOCK (mandatory — do all of it)

1. **Archive this prompt** to `prompts/frontend_phases/phase_09c_remaining_polish.md` (verbatim),
   committed with the code.
2. **Update `PROJECT_STATE.md`:** mark Phase 9 ✅ complete (all 12 pages real; Explainability
   stub wired; Setup Guide + Risk Register authored from docs; Overview/Pipeline merged; polish
   pass done). Add a 9c session entry + session-log row. Update the phase tracker (Phase 9 → ✅).
   Set next steps to **Phase 10 (full test suite incl. frontend tests + true E2E)** and
   **Phase 11 (7-use-case integration incl. the unverified multilabel path, perf baseline,
   real-data/CORS validation, governance sign-off)** — point at the existing "Testing debt"
   section as the Phase 10/11 agenda.
3. **Update `frontend_short_desc.md`:** add the three pages, the Overview/Pipeline merge (note
   12 nav items now), and the polish pass. Note Explainability is a v2.0-ready stub.
4. **Update `plan_tweak.md` ONLY if a real deviation occurred** (e.g. merging Overview/Pipeline
   changes the scope's 13-page/14-nav count — record the final page/nav count as a small
   deviation/clarification if it matters at sign-off; the scope listed them separately). Don't
   pad. Record pure UX choices in the decisions log instead.
5. **Hallucination check (governance):** verify against INSTALLED versions — React Router (the
   nav merge/redirect), Recharts 3.8.1, Testing Library + vitest, `import.meta.env`. Record
   versions in the PROJECT_STATE entry.
6. **Commit message:**
   `Phase 9c: Explainability stub + Setup Guide + Risk Register + Overview/Pipeline merge + polish — Phase 9 complete`

When done, report: the three pages built, how the Explainability stub is presented, the final
nav/page count after the merge, what the polish pass covered, any plan_tweak entry (or why
none), and the versions hallucination-checked. Note that Phase 9 (the React dashboard) is now
complete and the project is ready for Week 4 testing/governance.
