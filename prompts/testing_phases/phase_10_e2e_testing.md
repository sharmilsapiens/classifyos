# Phase 10 — Testing: browser E2E, real CORS, render gaps, and a suite audit

> Paste into a fresh Claude Code session in the ClassifyOS repo.
> Week 4, part 1 of 2. Phase 11 (7-use-case integration, multilabel, performance baseline,
> governance sign-off, demo) is SEPARATE and comes after this. The sprint finishes at Phase 11.

---

## 0. Read first (in this order)

- `CLAUDE.md` — stable contract, hard rules.
- `PROJECT_STATE.md` — live status: Phase 9 complete (12 pages); **184 backend tests + 55
  frontend tests already passing**; read the **"Testing debt / untested paths"** section —
  that is this phase's agenda.
- `PROJECT_WISDOM.md` — lessons learned; the testing-debt list; the "real data is messy" note.
- `docs/api_contract.md` — the LOCKED contract the E2E assertions check against.
- `API_RUNBOOK.md` / `RUNBOOK.md` — how to start the API + engine (the E2E webServer commands).
- `frontend_short_desc.md` / `api_short_desc.md` — what the UI + endpoints do.

The person directing this is **new to web testing**. New test code must teach as it goes:
short comments on what Playwright, a fixture, a webServer, and a CORS preflight each are.

---

## 1. What this phase IS — and IS NOT

**The plan's literal Day 16–17 ("GenAI generates the full pytest suite") is already satisfied
by continuous testing.** Do NOT regenerate the 184 backend + 55 frontend tests — they pass and
re-generating risks churning working tests. Phase 10 adds the test layers that continuous
testing **structurally could not reach**, and audits what exists.

**IN scope for Phase 10:**
1. **True browser E2E** — real browser → live Vite frontend → live uvicorn API → real engine →
   rendered charts/tables. (Current "integration" only hits the engine directly or the API via
   `TestClient`/jsdom — never a real browser.)
2. **Real CORS** — exercised by an actual cross-origin browser request (configured in Phase 8,
   never actually triggered; curl/TestClient don't enforce CORS).
3. **Frontend render gaps** — the vitest suite runs in jsdom where Recharts renders 0×0, so
   chart *pixels* aren't verified. E2E covers the real render.
4. **Suite audit** — confirm the existing 184+55 actually cover what they claim; fill thin
   spots (notably the `/explain` real-path call, error/empty states, the typed-client parsing).

**OUT of scope — these are PHASE 11, do not do them here:**
- The 7-use-case end-to-end sweep, the **multilabel** (Product Recommendation) path, the
  **10k-row performance baseline**, realistic **tuning** budgets, real (non-synthetic) data
  revalidation, and the **governance sign-offs / demo**. Phase 10 builds the E2E *machinery* and
  proves it on the already-verified binary + multiclass paths; Phase 11 drives all 7 use cases
  through it. (You MAY write the E2E tests so Phase 11 can parametrize them across use cases —
  but only run binary + multiclass here.)

---

## 2. Frozen vs scope

- **FROZEN:** all backend (`backend/classifyos/` + `backend/api/`) and all frontend application
  code. Phase 10 ADDS TESTS ONLY. If a test reveals a real bug, STOP and report it with a
  proposed fix — do not silently change frozen code; a fix is a named, sanctioned edit recorded
  in plan_tweak, decided explicitly.
- No contract changes. E2E asserts against the LOCKED `docs/api_contract.md`.

---

## 3. E2E setup (Playwright)

Install **Playwright** (`@playwright/test`) in `frontend/`. Pin the version; record it.

### 3.1 The two-server problem (important — comment this clearly)
A real E2E run needs BOTH servers up:
- the **FastAPI backend** (uvicorn on :8000), and
- the **Vite frontend** (:5173), whose dev proxy forwards `/api → :8000`.

Configure Playwright's `webServer` as an ARRAY of two entries (backend + frontend), each with a
readiness `url`, `reuseExistingServer: !process.env.CI`, and a generous `timeout` (the backend
imports the ML engine + libraries — slow to boot; allow ~120s). Set `baseURL` to the Vite URL so
tests use relative paths. The backend must start with the test `.env` pointing `DATA_DIR` at the
sample CSVs and `OUTPUT_DIR` at a throwaway folder (NEVER the real output dir — same hygiene as
the pytest suite). Comment why each piece exists for a first-time reader.

### 3.2 The happy-path E2E (binary + multiclass only this phase)
One spec that drives the REAL UI through the full flow, asserting against the contract:
- Load the app → the **API health banner** shows connected (proves the browser reaches :8000).
- **Upload** a sample CSV (`policy_lapse.csv` binary; `risk_tier.csv` multiclass) → columns +
  class-distribution chips appear (proves `/upload` round-trips through the browser).
- **Configure** → pick target, features, a couple of algorithms, class_balance.
- **Run** → the merged Overview/Pipeline page shows the in-progress state, then results.
- **Assert the result pages actually render** (this is the gap jsdom couldn't cover): the
  Overview KPI band populates; the ROC/PR chart draws non-trivial SVG (Recharts renders real
  geometry in a real browser, not 0×0); the confusion-matrix heatmap has cells; the predictions
  table shows the "sampled / download full" banner; a PNG artifact (`/outputs/{name}`) loads.
- Write it parametrized over a `{file, target, problem_type, algorithms}` list so **Phase 11**
  can extend the same spec to all 7 use cases — but this phase only includes the binary +
  multiclass entries.
- Keep selectors honest (roles/labels/test-ids), not brittle CSS. Add `data-testid` hooks to
  frontend components ONLY if needed — and if so, that's the one sanctioned frontend touch
  (test attributes, no behavior change); note it in plan_tweak.

### 3.3 Real CORS test (the part the proxy normally hides)
The Vite proxy makes `/api` calls same-origin, so it MASKS CORS. To actually exercise CORS:
- Add a spec where the browser calls the API **directly cross-origin** (absolute
  `http://localhost:8000/api/v1/health`, bypassing the proxy) and assert it succeeds when the
  frontend origin is in `CORS_ORIGINS`, and that a preflight (OPTIONS) is handled. Comment what
  a CORS preflight is and why same-origin (proxied) calls never trigger it.
- Confirm the allowlist behavior: an allowed origin works; document (don't necessarily automate)
  that a non-allowlisted origin would be blocked — the point is to prove the env-driven
  allowlist is real, never `["*"]`.

---

## 4. Frontend render gaps + suite audit

- **Render internals not covered by jsdom:** in the E2E browser, assert the things jsdom can't —
  charts produce real SVG path geometry, the confusion heatmap colors scale, the curves show the
  per-class lines (one for binary, N for multiclass). This closes the "data binds but pixels
  unverified" gap noted in the testing debt.
- **`/explain` real path:** add a frontend test (vitest or E2E) that actually calls `/explain`
  and asserts the page renders the structured `unavailable` stub cleanly (status + reason +
  message), with the reserved waterfall region present. (The 9c page wired this; verify it
  against the live endpoint.)
- **Audit the existing suites:** run the full backend pytest + frontend vitest suites; report the
  real counts and that everything is green. Identify and fill any THIN spots in coverage of
  already-built code — error states (422/400 surfaced in the UI), empty states (no-run pages),
  the typed-client parser on a malformed envelope. Do not pad with trivial tests; target genuine
  gaps. A coverage summary (not a hard threshold) is welcome if cheap to produce.

---

## 5. Tests must not pollute real data

- Backend under test reads sample CSVs from `DATA_DIR` and writes to a THROWAWAY `OUTPUT_DIR`
  (the E2E webServer `.env` and the pytest conftest both enforce this). Confirm no test run
  writes to the real output folder. Synthetic sample data only — no real/PII data in E2E.

---

## 6. Hard rules

- **Tests only.** No backend or frontend behavior changes. A real bug → STOP, report, propose a
  named fix; don't silently edit frozen code. Test-only `data-testid` attributes are the sole
  allowed frontend touch, if necessary, recorded in plan_tweak.
- E2E asserts against the LOCKED contract; no invented fields.
- Throwaway `OUTPUT_DIR`; synthetic data only; never `["*"]` for CORS.
- Keep Phase 11's content (multilabel, 7-use-case sweep, perf, tuning-at-budget, real data,
  governance) OUT — build the machinery to support it, run only binary + multiclass here.

---

## 7. WRAP-UP BLOCK (mandatory — do all of it)

1. **Archive this prompt** to `prompts/testing_phases/phase_10_e2e_testing.md` (create the
   subfolder; verbatim), committed with the tests.
2. **Update `PROJECT_STATE.md`:** flip Phase 10 → ✅; add a "Completed this session (Phase 10)"
   entry (Playwright set up, two-server webServer, happy-path E2E on binary+multiclass, real
   CORS test, render-gap coverage, `/explain` real-path test, suite audit + final counts);
   update the "Testing debt" section to strike the items now covered and clearly leave the
   Phase 11 items (multilabel E2E, 7-use-case sweep, perf baseline, tuning-at-budget, real-data,
   governance) outstanding; session-log row; set next step to Phase 11.
3. **Update `frontend_short_desc.md`** (and `api_short_desc.md` if the CORS test taught something
   about the API surface): note the E2E layer + how to run it (`npx playwright test`), the
   two-server requirement, and the real-CORS test.
4. **Update `plan_tweak.md` ONLY for a real deviation** — e.g. a test-only `data-testid` touch on
   frozen frontend code, or a genuine bug found + the sanctioned fix. Do not pad. A clean "tests
   added, no behavior change, no deviation" is the expected outcome.
5. **Hallucination check (governance):** verify against the INSTALLED versions — `@playwright/
   test` (`defineConfig`, `webServer` array, `baseURL`, `expect`/`locator` API), and re-confirm
   the existing vitest/Recharts/pytest/FastAPI TestClient versions still match. Pin Playwright in
   `frontend/package.json`. Record versions in the PROJECT_STATE entry.
6. **Commit message:**
   `Phase 10: browser E2E (Playwright, 2-server) + real CORS test + render-gap coverage + suite audit`

When done, report: the E2E machinery built, what the binary+multiclass E2E asserts, the CORS
test result, any render gaps closed, the final backend+frontend test counts (all green), any bug
found (with proposed fix) or test-only frontend touch, and confirm the Phase 11 items are
deliberately still open. State clearly that Phase 11 (integration + governance + demo) is the
last phase of the sprint.
