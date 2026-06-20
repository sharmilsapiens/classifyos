# ClassifyOS — Frontend Surface (Plain-Language Summary)

## About ClassifyOS

ClassifyOS is a GenAI-developed machine-learning framework for the insurance domain: it
predicts categorical outcomes (will a policy lapse? is a claim fraudulent? which risk tier?)
from ordinary tabular data. It is built in three layers — a **React** browser frontend talks
to a **FastAPI** backend, which drives a pure-Python **ML engine**. You set a run up in the
browser, it is sent to the API, the engine executes it, and the results stream back as JSON
to fill charts and tables. This file covers the **frontend surface** (the React dashboard).
For the engine see `backend_short_desc.md`; for the API see `api_short_desc.md`.

---

## What the frontend is (Phase 9a — foundation)

The dashboard is a React (Vite + TypeScript) single-page app. Phase 9a built the **foundation**
and proved it talks to the live API end to end; the rich result pages come in 9b/9c. It is a
pure HTTP client of the API — it contains **no machine-learning logic** and never touches the
backend code; it only calls `/api/v1/…` (proxied to the backend on port 8000 in development).

## The design system

- **Look chosen:** **Option A "Clarity"** — a light, clean SaaS style: white/neutral canvas, a
  confident **indigo** primary accent, sky/emerald data accents, crisp hairline borders, and
  the Inter typeface (JetBrains Mono for numbers).
- **Components:** **shadcn/ui** style — Button/Card/Badge/Input/Label are built with the shadcn
  pattern (class-variance-authority + Tailwind), and Select/Switch are accessible native HTML
  elements styled to match (no extra Radix dependency in 9a; can upgrade later).
- **One place to theme:** every colour, radius and font is a CSS variable in
  `src/index.css`. Change `--primary` there and the whole app re-skins — no component edits.
- **Charts:** **Recharts** (declarative React chart components) — validated on the Overview page
  and used for all result charts from 9b on.
- **Quality floor from day one:** visible keyboard focus rings, accessible contrast,
  reduced-motion respected, and first-class empty / loading / error states (never a blank screen).

## The typed API client (bound to the locked contract)

- `src/api/types.ts` mirrors the **locked** `/api/v1/run` contract (`docs/api_contract.md`)
  and the Pydantic models **exactly** — same field names, `models` as a list, `predictions`
  sampled with a `full_csv` link, `curves`/`confusion_matrix` per model. We never invent or
  rename a field; a genuine gap would be flagged, not patched.
- `src/api/client.ts` has one typed function per endpoint — `health`, `upload`, `run`,
  `explain`, `listOutputs`, `outputUrl` — with one readable `ApiError` type that distinguishes
  a network failure (server down), a 422 validation error (with the offending field), and a
  400 run error. `src/api/parse.ts` structurally validates a `/run` envelope before the UI
  trusts it.
- The API base URL comes from a Vite env var (`VITE_API_BASE_URL`, default `/api/v1`).

## The app shell

A fixed sidebar (the canonical **13-page** navigation, grouped Workspace / Results / Reference,
with the active page highlighted), a sticky topbar with the **API health banner** (green
"API connected" / red "API offline — start uvicorn on :8000", checked on load) and a "New run"
button, and the routed page in the middle. One small global store (React Context,
`src/store/AppStore.tsx`) holds the shared state: the uploaded file's profile + `server_path`,
the current run configuration, the last `/run` result, and the loading/error flags.

## The Upload → Configure → Run flow (the live round-trip)

- **Upload** — drag-drop a CSV/Excel/Parquet file → `/upload` saves and inspects it → the page
  shows the columns, types, missing counts, suggested problem type, and (once a target is
  chosen) its class distribution. The returned `server_path` is stored for the run.
- **Configure** — a form binding **every** field the `RunConfig` contract accepts (target +
  feature pickers, problem type, algorithms, balancing, encoding/scaling/missing, test size,
  threshold, calibration, feature-engineering, interactions, and the Optuna tuning dials). It
  mirrors the three required fields client-side so you see a problem before the server's 422.
- **Run** — posts the config to `/run` (which is **synchronous** — long/tuning runs can take a
  while), shows an in-progress state on the **Pipeline** page, then a model scoreboard, the
  artifact downloads, and the raw result envelope. (Rich charts/tables are 9b.) A real
  Upload→Configure→Run round-trip was verified against a live backend.

## The 12 canonical pages (Phase 9 complete)

Overview · Upload Data · Configuration · Feature Impact · Interaction Features · Confusion
Matrix · Class Report · ROC / PR Curves · Predictions Table · Explainability · Setup Guide ·
Risk Register. **All 12 are real screens.** 9a built Overview/Upload/Configuration; 9b built the
six result pages; 9c built the last three (Explainability, Setup Guide, Risk Register). The
**separate "Pipeline" page was merged into Overview in 9c** — so the nav went from 13 → 12 items
and `/pipeline` now redirects to `/` (old links keep working).

## The result pages (Phase 9b)

These read the **last `/run` result already in the app store** (no page re-fetches `/run`) and
turn it into charts and tables. The one new network call any of them makes is fetching a plot
PNG on demand via `/outputs/{name}`. Each branches on the problem type (binary / multiclass)
and shows failed-model rows greyed (never dropped), with friendly empty/missing states.

- **Overview** — the run summary: a KPI band (best model by F1-weighted, accuracy, ROC-AUC, MCC,
  models-trained), a per-model bar across the key metrics, the active configuration, and quick
  links to the detail pages. Reads `result.run` + `result.models`.
- **Feature Impact** — a ranked horizontal bar (composite score, or any single metric you pick)
  + a full per-metric table, with the **`id_like` leakage flag surfaced prominently** as a
  warning. Reads `result.feature_impact`; shows the plot4 PNG alongside.
- **Confusion Matrix** — a custom CSS-grid heatmap (sizes/scrolls to the class count) with a
  raw↔row-normalised toggle (normalisation computed client-side) and a model selector. Reads
  `result.confusion_matrix`.
- **Class Report** — the per-class precision/recall/F1/support table (macro/weighted averages
  split into a footer) + a grouped bar, with the weakest-recall class highlighted. Reads
  `result.class_report`.
- **ROC / PR Curves** — interactive Recharts line charts from `result.curves`: ROC (with the
  no-skill diagonal, AUC per class in the legend) and PR (AP per class); one curve for binary,
  one-vs-rest per class for multiclass; per-model selector. Shows the plot2 and plot5
  (calibration, binary-only) PNGs.
- **Predictions Table** — the sampled `result.predictions.sample_rows` (actual/predicted/
  per-class probabilities/confidence/correct), filterable by model and correct/incorrect and
  sortable by confidence, with a clear "showing N of M (sampled)" banner and a full-CSV download.
- **Interaction Features** — the `result.run.interaction_cols`, each decoded into a readable
  expression (`_x_`→×, `_div_`→÷, `_minus_`→−), with the plot6 PNG and an empty state when
  interactions were disabled.

**The interactive-vs-PNG rule:** ROC/PR, the confusion heatmap, the class report, and the
feature-impact ranking are drawn live from the contract data. The plot PNGs (plot2–plot6) are
fetched on demand via `outputUrl(name)`, never base64-inlined, and always guarded — a missing
or placeholder artifact shows a friendly "not generated for this run" panel rather than a broken
image.

## The remaining pages + polish (Phase 9c — Phase 9 complete)

The final slice finished the dashboard and merged two pages into one.

- **Overview is now the merged run page.** The old separate "Pipeline" page is gone; its
  behaviour lives in Overview, which shows four states in one continuous screen: **while running**
  it lists the pipeline stages with a spinner (honest — `/run` is synchronous, so there is no live
  log to stream); on **error** it distinguishes a 422 (invalid config) from a 400 (run error); with
  **no run** it invites you to start; and once a run **completes** it shows the KPI band, the
  per-model comparison, the active configuration, the full model scoreboard, the artifact
  downloads, quick links, and the raw result envelope. The nav dropped to **12 items** and
  `/pipeline` redirects to Overview so old links never break.
- **Explainability** is an honest **v2.0-ready stub**. A SHAP explanation needs a model kept in
  memory, and the API is stateless with no model registry — so `/explain` returns a structured
  "unavailable" response. The page says so plainly, but still lets you pick a trained model and a
  test-row index and hit **Explain**, which calls the real endpoint and renders its structured
  reply (status + the server's own reason/message). The region where the SHAP waterfall will go is
  clearly reserved so v2.0 only has to fill in the values, not rebuild the page.
- **Setup Guide** is a static getting-started reference authored from the real docs (API_RUNBOOK,
  RUNBOOK, the locked contract): an architecture diagram (React → FastAPI → engine), the run flow
  (start uvicorn → upload → configure → run → explore/download), a 6-endpoint API reference, and an
  honest list of v1.0 limitations.
- **Risk Register** is a static page of risk → mitigation cards drawn from the engine's real
  `[RISK]` points (leakage, imbalance, calibration, multicollinearity, threshold/temporal leakage,
  probability-shape, GenAI governance) plus the governance checklist — each mitigation describing
  what the code actually does. (Both static pages are authored from the docs because no API
  endpoint exposes setup steps or risk notes; a live one would be a future additive v1.1 path.)
- **Polish pass:** the sidebar stays usable when the window narrows (sticky, fixed-width, never
  crushed; content scrolls, tables have horizontal scroll, charts stay inside their containers); the
  Overview comparison chart gained an accessible `role="img"` label; chart tick contrast was nudged
  up within the palette; and every page reuses the shared empty/loading/error states so none ever
  shows a blank screen. Keyboard focus rings and reduced-motion (from 9a) are intact.

## Testing the frontend (Phase 10 — browser E2E)

The dashboard now has two test layers:

- **Unit / render tests (vitest, jsdom)** — `npm test` in `frontend/`. **62 tests** covering the
  typed API client's error mapping, the `/run` envelope parser, per-page render against captured
  fixtures, and the empty/error states. These run in jsdom, where Recharts charts render 0×0 — so
  they verify the *data binding* around a chart, not the painted pixels.
- **Browser E2E (Playwright)** — `npm run e2e` in `frontend/`. **The layer jsdom can't reach:** a
  real Chromium loads the live app, which talks to live uvicorn, which runs the real engine, and
  we assert the charts/tables actually RENDER (real SVG geometry, the confusion heatmap cells, a
  loaded PNG). It needs **both servers up** — Playwright's `webServer` config starts them for you:
  the **FastAPI backend** (uvicorn :8000) and the **Vite frontend** (:5173, whose proxy forwards
  `/api → :8000`). The backend is launched with a test-only env (sample CSVs in, a throwaway
  output folder out — never your real data). Two specs:
  - `e2e/happy-path.spec.ts` — drives the full **Upload → Configure → Run** flow on the **binary**
    and **multiclass** sample datasets and checks the rendered Overview KPIs, the ROC/PR curves
    (one line for binary, N for multiclass), the confusion heatmap, the predictions sampled banner,
    a downloaded plot PNG, and the live `/explain` stub. It is parametrized so **Phase 11** can add
    all seven use cases (incl. multilabel) by extending one list.
  - `e2e/cors.spec.ts` — the **real CORS** test. In dev the Vite proxy makes API calls look
    same-origin, so it hides CORS; this spec has the browser call the API **directly cross-origin**
    (bypassing the proxy) to prove the env-driven allowlist actually works, including a preflight
    (OPTIONS) for a non-simple request.

(See `RUN_FULL_SYSTEM.md` for starting the two servers by hand.)

---

## How to read this project

- **CLAUDE.md** — the conventions and hard rules.
- **PROJECT_STATE.md** — the live status (done, decisions, issues, next steps).
- **plan_tweak.md** — the honest register of deviations from the signed plan.
- **docs/api_contract.md** — the **locked** `/run` request/response schema (the frozen contract).
- **backend_short_desc.md** — plain-language summary of the ML engine.
- **api_short_desc.md** — plain-language summary of the API surface.
- **frontend_short_desc.md** (this file) — plain-language summary of the React dashboard.
