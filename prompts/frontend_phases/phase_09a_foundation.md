# Phase 9a — React frontend: foundation, design pick, and the live round-trip

> Paste into a fresh Claude Code session in the ClassifyOS repo.
> This is the FIRST of three frontend slices (9a foundation → 9b result pages →
> 9c remaining pages + polish). Do NOT build all 13 pages here.

---

## 0. Read first (in this order)

- `CLAUDE.md` — stable contract, hard rules, module map, env/CORS rules.
- `PROJECT_STATE.md` — live status (engine complete; Phase 8 API done; `/api/v1/run` LOCKED).
- `PROJECT_WISDOM.md` — how we work + lessons learned (esp. the `.env`/CORS rules).
- `docs/api_contract.md` — **the LOCKED `/api/v1/run` request/response schema. This is the
  source of truth for every type the frontend uses. Read it carefully before writing code.**
- `api_short_desc.md` — plain-language tour of the six endpoints.
- `backend/api/models.py` — the actual Pydantic request/response models to mirror in TS.

The person directing this is **new to frontend/React as well as web APIs**. Generated code
must teach as it goes: short comments explaining what a component, hook, typed client, and
fetch call each do, in plain terms. Favor clarity over cleverness.

---

## 1. What this slice is

Build the **foundation** of the React dashboard and prove it talks to the live API:

1. Present **three full-look design template options** for the human to pick from (see §3).
2. Once a design is picked (the human will say which), lock it in as the design system.
3. Build the **app shell**: sidebar nav, topbar, routing, global app state, API health banner.
4. Build the **typed API client** generated against the LOCKED contract.
5. Wire the **Upload → Configure → Run** path end-to-end so ONE real round-trip works against
   a running backend (uvicorn on :8000, Vite proxy `/api → :8000`).

Result rendering pages (charts, tables, SHAP) are **9b/9c** — not this slice. Here, "Run"
can dump the raw result to a simple panel; rich rendering comes next.

> NOTE on flow: §3 (templates) ends your first turn — STOP after presenting the three options
> and wait for the human to pick. Then continue with §4 onward in the same session.

---

## 2. Frozen vs scope

- **FROZEN:** the entire backend (`backend/classifyos/` + `backend/api/`). The frontend only
  CALLS the API over HTTP. No backend edits in any frontend slice.
- **Contract:** the frontend is generated against `docs/api_contract.md`. If something the UI
  needs seems missing from the contract, STOP and flag it — do not change the backend, and do
  not invent fields. (The contract is locked; additive changes would bump it to 1.1, a
  separate decision.)
- **Deviation note:** scope/plan said a single-file `classify_ui.html`; we use React (Vite+TS)
  — already recorded (plan_tweak 2). No new deviation for that.

---

## 3. Design template options (do this first, then STOP)

Using the Claude Code frontend tooling, generate **three distinct full-look options** for the
dashboard — each a real, viewable mockup of the SAME representative screen (the Overview page
with the stats band + an active-config panel + the 8-step pipeline diagram placeholder), so
they're comparable. All three must share these **non-negotiable UX goals**: simple, vibrant,
clear, easy to use; strong visual hierarchy; obvious primary actions; readable data tables and
chart areas; accessible color contrast.

The three directions:
- **Option A — Light & clean SaaS:** white/neutral base, vibrant accent color(s) for actions
  and data, crisp borders, modern sans typography.
- **Option B — Dark data dashboard:** dark surface, vivid high-contrast data colors, good for
  charts-heavy screens, careful contrast for text.
- **Option C — Soft & friendly:** light pastel surfaces, rounded corners, gentle shadows, a
  warmer approachable feel while staying clear and uncluttered.

For each option, also state: the proposed **component library** usage (we've chosen
**shadcn/ui** — show how each look themes it via tokens) and a **charting library
recommendation** (Chart.js vs Recharts) with one line of why it suits that look. We will pick
the chart library together with the design.

Present all three so they can be viewed side by side, then **STOP and wait for the human's
pick** (design + chart library). Do not proceed to §4 until they choose.

---

## 4. Foundation (after the design is picked)

Set up under `frontend/` (Vite + React + TypeScript already scaffolded). Use **shadcn/ui**
for components, themed to the chosen design's tokens. Use the chosen chart library (install it,
pin it).

### 4.1 Design system
- Centralize design tokens (colors, spacing, typography, radius, shadows) so the whole app is
  themed from one place. Comment where to change the accent color, etc.
- Set up shadcn/ui and note in `frontend_short_desc.md` that it's used (per CLAUDE.md's
  "mention shadcn if used").

### 4.2 Typed API client (generated against the LOCKED contract)
- `frontend/src/api/types.ts` — TypeScript types mirroring **exactly** the `docs/api_contract.md`
  request (`RunConfig`) and response envelope (`status`, `schema_version`, `result.{run,
  models[], predictions, confusion_matrix, class_report, feature_impact, curves, artifacts[]}`).
  `models` is an **array**. `predictions` is the sampled shape with `full_csv`. Comment each
  type with which page consumes it.
- `frontend/src/api/client.ts` — one typed function per endpoint: `health()`, `upload(file,
  target?)`, `run(cfg)`, `explain(req)`, `listOutputs()`, `outputUrl(name)` (returns the URL
  for `<img>`/download — PNGs are fetched on demand, never inlined). Central error handling:
  surface 422 validation detail and 400 run-errors as typed, readable errors. Teaching
  comments on what `fetch`, a Promise, and async/await are doing.

### 4.3 App shell
- Sidebar nav listing the canonical pages (see §5) with the active route highlighted; topbar
  with the app name + an **API health banner** driven by `health()` (`checkAPI()` on load —
  green "API connected" / red "API offline, start uvicorn on :8000" with the reason). Routing
  via React Router. A single global app-state store (Context or a small store) holding: the
  uploaded file's `server_path` + inspect result, the current `RunConfig`, the last `/run`
  result, and loading/error flags. Comment the state shape.
- Empty/loading/error states are first-class from the start (no blank white screens).

### 4.4 The live round-trip (Upload → Configure → Run)
- **Upload page:** drag-drop / file picker → `upload()` → show returned columns, dtypes, class
  distribution chips, suggested problem type; store `server_path`. Populate the target +
  feature pickers from the inspect result.
- **Configure page:** form binding every `RunConfig` field the contract accepts (problem_type,
  algorithms multi-select with the alias names, class_balance, encoding/scaling/missing,
  test_size, threshold, calibrate toggle, interaction toggle, tuning toggle + dials). A
  `buildPayload()` that assembles a valid `RunConfig`. Client-side mirror of the 3 required
  fields (target/input_file/feature_cols) so the user sees the error before the 422 — but the
  server 422 is still handled gracefully (show the field detail).
- **Run:** a `runPipeline()` that POSTs the config, shows a clear in-progress state (note in a
  comment: `/run` is synchronous and can take a while; long/tuning runs may approach a gateway
  timeout — v1.5 will add background jobs), and on success stores the result and dumps it to a
  simple raw/JSON-ish results panel (rich rendering is 9b). Handle 422 and 400 distinctly.

---

## 5. Canonical page list (settle the 13 vs 14 drift)

Lock the nav to these pages (build only Overview + Upload + Configure as real screens in 9a;
the rest are nav entries + stub routes for now, filled in 9b/9c):

1. Overview · 2. Upload Data · 3. Configuration · 4. Pipeline (run progress/log) ·
5. Feature Impact · 6. Interaction Features · 7. Confusion Matrix · 8. Class Report ·
9. ROC / PR Curves · 10. Predictions Table · 11. Explainability · 12. Setup Guide ·
13. Risk Register.

(That's 13. If a "Pipeline" monitor and an "Overview" feel redundant, keep both as nav stubs
now and we'll merge in 9c if needed — don't drop one silently.)

---

## 6. Tests (light for 9a; the heavy frontend test pass is Week 4 / Phase 10)

- A couple of unit tests for the typed client: `buildPayload()` produces a contract-valid
  `RunConfig` from sample form state; the response parser accepts a real saved `/run` envelope
  (commit a sample JSON captured from the live API) and rejects a malformed one.
- `checkAPI()` handles the offline case (mocked failed fetch) without crashing the app.
- Note clearly that full page-render tests + E2E come in Phase 10.

---

## 7. Hard rules

- Frontend talks ONLY to `/api/v1/` (Vite already proxies `/api → :8000`). No backend edits.
- Types mirror the LOCKED contract exactly; do not invent or rename fields. Flag gaps, don't patch.
- PNGs fetched on demand via `/outputs/{name}`; never base64-inlined.
- Accessible contrast + keyboard-usable controls from the start (part of "good UX").
- No secrets in the frontend; the API base URL comes from a Vite env var (comment it).

---

## 8. WRAP-UP BLOCK (mandatory — do all of it)

1. **Archive this prompt** to `prompts/frontend_phases/phase_09a_foundation.md` (verbatim),
   committed with the code.
2. **Update `PROJECT_STATE.md`:** add Phase 9 as 🔄 In progress with a 9a sub-entry (design
   chosen, chart lib chosen, shell + typed client + Upload/Configure/Run round-trip done,
   canonical 13-page nav locked); session-log row; set next step to 9b (result pages).
3. **Create `frontend_short_desc.md`** (NEW): open with the shared short **"About ClassifyOS"**
   header, then plain-language summaries of the shell, the typed client (bound to the locked
   contract), the chosen design system + component/chart libraries, and the Upload→Configure→Run
   flow. Reference it from the "how to read this project" lists in the other short_desc files.
4. **Update `plan_tweak.md` ONLY if a real deviation occurred** (e.g. the contract turned out to
   be missing a field the UI needs — flagged, not patched). The React-vs-HTML choice and the
   page-count settle are already covered / not deviations — don't pad the register. Record the
   chosen chart library + design direction in PROJECT_STATE's decisions log (that's a decision,
   not a deviation).
5. **Hallucination check (governance):** verify against the INSTALLED versions — React Router,
   the chosen chart library, shadcn/ui setup, Vite env var access (`import.meta.env`) — and pin
   any newly added deps in `frontend/package.json`. Record versions in the PROJECT_STATE entry.
6. **Commit message:**
   `Phase 9a: React foundation — design system + typed API client (locked contract) + Upload/Configure/Run round-trip`

When done, report: the chosen design + chart library, what's wired end-to-end (with a note on
whether a real Upload→Configure→Run round-trip succeeded against a live backend), the canonical
page list, and any contract gaps you had to flag.
