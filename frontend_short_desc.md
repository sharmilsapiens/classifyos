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
  threshold, calibration, feature-engineering, interactions, the Optuna tuning dials, and the
  **user-defined feature builder** below). It mirrors the three required fields client-side so you
  see a problem before the server's 422. **Tuning (when enabled)** now defaults to **no per-model
  timeout** (a "No timeout" switch; `n_trials` is the only bound, with a number field to re-impose a
  cap) and includes a **per-model search-space editor** — a collapsible "Search space (advanced)"
  disclosure containing one collapsible block per algorithm (XGBoost, LightGBM, RandomForest, …)
  where you can override each parameter's low/high bound (or, for categoricals like RandomForest
  `max_features` / SVM `kernel`, the allowed choices). A blank field uses the engine default
  (shown as the placeholder), so an untouched panel sends `{}` and changes nothing; the edits ride
  along in the `/run` request as `tuning.search_space_overrides`.
- **Run** — posts the config to `/run` (which is **synchronous** — long/tuning runs can take a
  while), shows an in-progress state on the **Pipeline** page, then a model scoreboard, the
  artifact downloads, and the raw result envelope. (Rich charts/tables are 9b.) A real
  Upload→Configure→Run round-trip was verified against a live backend.

## The 13 canonical pages

Overview · Upload Data · Configuration · Feature Impact · Interaction Features · Confusion
Matrix · Class Report · ROC / PR Curves · Predictions Table · **Tuning Results** · Explainability ·
Setup Guide · Risk Register. **All 13 are real screens.** 9a built Overview/Upload/Configuration;
9b built the six result pages; 9c built the last three (Explainability, Setup Guide, Risk
Register). The **separate "Pipeline" page was merged into Overview in 9c** — so the nav went 13 →
12 and `/pipeline` now redirects to `/` (old links keep working). **Phase 13** then added the
**Tuning Results** page (below), bringing the nav back to **13 items**.

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

## The feature-builder panel (Phase 16 — user-defined features)

The Configuration page has a **User-defined features** panel where an analyst builds new columns
from existing ones — entirely from **dropdowns**. There is deliberately **no formula box**: the
engine never evaluates code, and that safety contract is carried to the UI, so a user picks a known
operation on known column(s) rather than typing an expression. You add one feature at a time:

- a **type** selector — *numeric* (`[col_a] [op: add/subtract/multiply/divide/ratio] [col_b]`),
  *single-column transform* (`[transform: log/abs/bin | year/month/day/dayofweek/hour] [column]`), or
  *datetime difference* (`[end column] [start column] [unit: days/hours/minutes/seconds]`);
- the column dropdowns are populated from the uploaded file's inspect profile and **filtered by
  type** where it helps (numeric ops list numeric columns; datetime-diff lists datetime columns; a
  single transform lists numeric *or* date columns depending on the chosen op). If a typed list is
  empty it falls back to all columns and lets the API's 422 guide;
- a **name** input for the new column, validated client-side (non-empty, and unique among the
  existing columns *and* the already-added features) with a clear inline message on a collision.

Added features appear as **removable rows** with a readable, formula-free label (e.g.
`duration_days = end_date − start_date`). The assembled specs ride along in the `/run` request as
`user_features` (the same `buildPayload` that assembles the rest of the config). If the server
rejects an invalid spec it returns a precise **422**, which surfaces through the existing error
path on Overview — the page never crashes. This is **request-side only** (Phase 15 added the API
field; the response schema is unchanged): the created columns simply show up in the run's
`active_features`.

## The Tuning Results page (Phase 13 — consumes schema 1.1)

A dedicated **Tuning Results** page (Results group) shows which models the Optuna tuner picked
hyperparameters for, and the exact values it chose. It reads the **`result.tuning`** block that
the API added in **schema 1.1** (additive) — straight from the last `/run` result already in the
store, with **no extra network call** and without scraping the `run_profile.json` artifact. Three
honest states: **no run yet** (an invitation to run), **tuning was OFF** (`tuning` null or
`enabled:false` → a clear "tuning was not enabled for this run" message pointing at Configuration,
since tuning is off by default), and **tuning ON** (a settings header strip — metric, CV folds,
trials/model, timeout — then one card per tuned model listing its chosen hyperparameters as a
key → value table, values in the mono font like the other metric displays). Models that were in
the run but **not** tuned are listed as "ran on defaults" so the picture is complete, and each
`best_params` value is rendered defensively (numbers/bools/strings stringified; an empty
`best_params` shows "no params returned — used defaults") because the contract types them as
`unknown`.

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
  **⚠ TEMPORARILY HIDDEN (2026-06-28, unwire.md #3):** because the backend explanation is not yet
  implemented, this page is hidden from the nav and `/explainability` redirects to Overview. The
  page component, the `explain` client, and the `/api/v1/explain` stub endpoint are all left intact
  — UI-only change, trivially reversible. So the live nav is currently **11 visible items** (the
  hidden Interaction Features entry already dropped it from 12).
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

- **Unit / render tests (vitest, jsdom)** — `npm test` in `frontend/`. **82 tests** covering the
  typed API client's error mapping, the `/run` envelope parser, per-page render against captured
  fixtures (including the Phase 13 Tuning Results page's on/off/no-run states), and the
  empty/error states. These run in jsdom, where Recharts charts render 0×0 — so
  they verify the *data binding* around a chart, not the painted pixels.
- **Browser E2E (Playwright)** — `npm run e2e` in `frontend/`. **The layer jsdom can't reach:** a
  real Chromium loads the live app, which talks to live uvicorn, which runs the real engine, and
  we assert the charts/tables actually RENDER (real SVG geometry, the confusion heatmap cells, a
  loaded PNG). It needs **both servers up** — Playwright's `webServer` config starts them for you:
  the **FastAPI backend** (uvicorn :8000) and the **Vite frontend** (:5173, whose proxy forwards
  `/api → :8000`). The backend is launched with a test-only env (sample CSVs in, a throwaway
  output folder out — never your real data). Two specs:
  - `e2e/happy-path.spec.ts` — drives the full **Upload → Configure → Run** flow and checks the
    rendered Overview KPIs, the ROC/PR curves (one line for binary, N for multiclass/multilabel),
    the confusion heatmap, the predictions sampled banner, a downloaded plot PNG, and the live
    `/explain` stub. **Phase 11 extended it to all seven insurance use cases** (3 binary, 3
    multiclass, 1 multilabel) via the one parametrized `USE_CASES` list. The **multilabel** case
    (Product Recommendation) asserts the honest states: per-label one-vs-rest curves, and the "no
    single confusion matrix for multilabel" notice instead of a heatmap.
  - `e2e/cors.spec.ts` — the **real CORS** test. In dev the Vite proxy makes API calls look
    same-origin, so it hides CORS; this spec has the browser call the API **directly cross-origin**
    (bypassing the proxy) to prove the env-driven allowlist actually works, including a preflight
    (OPTIONS) for a non-simple request.

### Multilabel rendering (Phase 11)

The result pages now render a **multilabel** run honestly (the first end-to-end multilabel runs
happened in Phase 11). The ROC/PR Curves page shows one-vs-rest curves **per label** with a
"multilabel view is preliminary" notice; the Confusion Matrix page shows an honest "a single
confusion matrix is not defined for multilabel runs — see the per-label Class Report / Curves"
message instead of a blank or broken heatmap; the Class Report and Predictions pages render the
per-label rows and the predicted product SET. A captured multilabel `/run` envelope
(`run_envelope_multilabel.json`) backs the render tests, so future work needs no live multilabel run.

(See `RUN_FULL_SYSTEM.md` for starting the two servers by hand.)

## Data Profile page — explore your data after upload (✅ Done, 2026-06-26)
**In one line:** A new "Data Profile" screen (between Upload and Configuration) that shows what's
in your uploaded file at a glance — distributions for number columns, common values for category
columns, a missing-data scan, and how the number columns correlate.
- **For number columns:** a smooth **distribution (density) curve** showing the shape of the data —
  which may come out as a bell curve, a skewed hump, or any smooth shape — plus a stats card: mean,
  median, mode, standard deviation, min/max, the 25th/75th percentiles, and skew. *(Updated 2026-07-01:
  this was a bar histogram; a smooth curve reads continuous data with many distinct values far better.
  A column with only one distinct value shows a short note instead of a curve.)*
- **For category columns (and yes/no columns):** a bar chart of the most common values, with an
  "other" bucket and a note of how many distinct values there are and the most frequent one.
- **Column advisories (both here and in the Configure feature picker):** a **single-value** column
  shows the value it holds ("Single value: 2024"); an **identifier-like** column shows how many
  distinct values it has out of the total rows ("9,950 of 10,000 unique"). *(Added 2026-07-01.)*
- **For date columns:** the earliest and latest dates.
- **Across the whole file:** a "missing values" chart (which columns have gaps, and how big) and a
  colour-coded **correlation heatmap** over the number columns (a quick way to spot redundant or
  suspiciously-related columns before configuring a run).
- **How it works:** the page reads the profile the upload already returned (no extra server call),
  so it loads instantly. Charts use Recharts; the correlation grid is a lightweight coloured table
  (the same technique as the Confusion Matrix). 3 new render tests.

## Post-training importance on the Feature Impact page (✅ Done, 2026-06-26)
**In one line:** The Feature Impact page now has a second section showing, **per model**, which
features the *trained* model actually leaned on — separate from the existing top section, which
ranks raw features *before* any model is trained.
- **Two clearly-separated stories on one page.** The top (unchanged) section is the pre-training
  screen: how each raw column relates to the target, with the ID-like leakage warning. The new
  bottom section is the post-training, per-model native importance.
- **Pick a model, see its ranking.** A model dropdown drives a ranked horizontal bar of that
  model's importances (top 20), shown next to the `plot3` chart (all models in one figure).
- **Honest about gaps.** A short note explains that SVM and Naive Bayes expose no native importance
  (so they're omitted) and that the values aren't comparable across models. If no model in the run
  exposes any, the section shows a friendly explanation instead of an empty chart.
- **Backwards-safe.** The block reads the optional `result.feature_importance` (schema 1.3); an
  older run without it simply shows the "no native importance" state — no crash. New render tests
  cover the present and absent cases.

## Missing-value controls split by feature type on Configuration (✅ Done, 2026-06-27)
**In one line:** The single "Missing values" dropdown on the Configuration page became **two** —
one for number columns and one for category columns — so you can fill blanks differently for each,
and number columns get smarter new options.
- **Two selectors.** *Missing values · numeric* offers median, mean, most-common, forward-fill,
  **backward-fill**, **k-nearest-neighbours**, **iterative/model-based**, and drop. *Missing
  values · categorical* offers most-common, forward-fill, **backward-fill**, and drop — the
  number-only statistics aren't shown there because they don't apply to text.
- **Helpful hints.** Each selector shows a one-line note explaining what the chosen strategy does
  (e.g. KNN "estimates values from the most similar rows"; drop "only ever drops training rows").
- **Sends both to the API.** The form now carries `missing_strategy_numeric` (default median) and
  `missing_strategy_categorical` (default mode) and includes them in the run request; the old global
  field stays as a hidden back-compat default. A new build-payload test covers the split.

## Per-column missing-value overrides on Configuration (✅ Done, 2026-07-01)
**In one line:** A new "Missing values · per column" card lets you override the blank-filling
method for an **individual column**, on top of the by-type defaults — leave any column on "Type
default" and it keeps the type setting.
- **What it shows.** The card lists the columns you've chosen as features (it needs the upload's
  Data-Profile to know each column's kind). Each row has the column name, a numeric/categorical
  tag, and a dropdown that defaults to **"Default (…)"** — showing the current per-type
  choice — plus the strategies valid for that column's kind: number columns get the full set
  (median/mean/most-common/forward-fill/backward-fill/KNN/iterative/drop), category columns get
  most-common/forward-fill/backward-fill/drop. A small count shows how many columns you've
  overridden.
- **Sends a map to the API.** The form carries a new `missing_strategy_by_column` map (default
  `{}`); picking a non-default strategy adds `{column: strategy}`, switching back to "Default"
  removes it — so an untouched card sends `{}` and changes nothing. It rides the existing run
  request; **no engine/API/contract change** beyond the additive request field.
- **Graceful fallback.** With no data profile (an older upload) or no features chosen yet, the card
  shows a short "select feature columns above" note instead of an empty table. New build-payload +
  Configure render tests cover the map default, the override write, and the numeric option set.

## Missingness shown where you choose imputation (✅ Done, 2026-07-08)
**In one line:** The Configuration page now shows **how much data is missing** right where you pick the
fill method — both a running summary above each per-type selector and a per-column badge — so the choice
isn't made blind (previously missingness only appeared on the Data Profile page and the Upload table).
- **Per-type summary.** Above *Missing values · numeric* and *Missing values · categorical*, a one-line
  note summarises the selected feature columns of that kind: amber "K of N numeric columns with gaps
  (T missing cells)" when there are gaps, or a reassuring emerald "No missing values in the N selected
  numeric columns" when clean. It splits numeric vs everything-else exactly like the two selectors do.
- **Per-column badge.** In the "Missing values · per column" card, each column now carries a badge beside
  its strategy dropdown — amber "N missing (X%)" when it has gaps, a muted "no gaps" when it's complete —
  so you can see at a glance which columns even need a strategy.
- **No new data, no waiting.** It reads the `n_missing`/`missing_pct` the upload profile already returns
  (the same numbers the Data Profile missingness scan uses) — **no extra server call and no engine/API/
  contract change**. The `fmtPct` percentage formatter was moved into a shared helper so the missing share
  reads identically on Data Profile and Configuration. New render tests cover the badge, the per-type
  summary, and the clean state. **131 vitest green · tsc + build clean.**
- **The no-missing case is stated on Data Profile too (follow-up).** The Data Profile page already showed a
  dataset-level "No missing values in any column. 🎉" when the whole file is clean (and its missingness bar
  chart when there are gaps). Now each **numeric and categorical column card** also states it per column —
  "N missing (X%)" when it has gaps, "No missing values" when complete — matching the per-column badge on
  Configuration and the datetime card (which always showed a Missing row). So the missing / no-missing
  status is now explicit on both surfaces, at both the dataset and the per-column level. **132 vitest green.**

## Feature picker enrichment on Configuration (✅ Done, 2026-07-01)
**In one line:** The feature-selection list on the Configuration page — previously just a checkbox
and a column name — now shows, for each column, a smooth distribution curve and key numbers for
number columns, and flags identifier / single-value columns right beside the name so you can spot
(and exclude) them at a glance.
- **What each row now shows.** A type tag (numeric/categorical/datetime); any advisory flags —
  **"Identifier-like"** (nearly every value distinct — an ID/reference that won't generalise and can
  leak the answer) and **"Single value"** (the same value in every row — no signal) — shown as small
  badges next to the column name (a single-value column names its value, an identifier-like column
  shows its distinct-of-total count); for **number columns**, a compact **distribution curve** (a
  smooth, bell-/gaussian-style density curve of the column's shape) plus **avg · IQR · variance**
  (average, the middle-50% spread, and the variance); and for **category columns**, the **available
  category values** as small chips. *(Category chips scale: the most-frequent 6 are shown with a
  "+N more" tail, so a column with many categories never floods the list; identifier-like columns
  show the count instead of listing near-unique values.)*
- **No new data, no waiting.** It reads the profile the upload already returned (the same
  `column_profiles` the Data Profile page uses) — so there is **no extra server call** and nothing in
  the engine, API, or the locked contract changed. An older upload without a profile simply shows the
  plain checkbox + name as before.
- **Consistent with Data Profile.** The identifier/single-value wording and the number formatting were
  moved into shared helpers so the picker and the Data Profile page describe and format things
  **identically** (one source of truth). The curve is a lightweight hand-drawn SVG spline (no chart
  library) so it stays fast even with many columns. New render tests cover the numeric stats, the
  distribution curve, and the identifier tag appearing in the picker.

## Decision-threshold policy + calibration on Configuration (✅ Done, 2026-07-01)
**In one line:** The old "Decision threshold" number box (which actually did nothing) is now a
**mode selector** — *Auto-tune* (let the engine find the best cut), *Fixed value*, or *Default
(0.5)* — and each model's effective cut-off + whether its probabilities are calibrated now show on
the scoreboard.
- **Why it changed.** The threshold field used to send a number the engine ignored. Now that the
  backend actually applies calibration and a decision threshold (engine + API done 2026-06-30),
  the UI exposes it properly.
- **The control.** In the **Problem framing** card, "Decision threshold" is a dropdown that
  **defaults to Auto-tune** (the engine picks the probability cut that maximises a metric on
  train-only CV folds — the "the model should decide it" answer). Choosing **Auto-tune** reveals a
  **metric** selector (F1, balanced accuracy, precision, recall, …); choosing **Fixed value**
  reveals the number box; **Default (0.5)** shows a disabled 0.5. A one-line hint explains each
  mode and notes it is **binary-only** (multiclass/multilabel use argmax and ignore it). The
  existing "Calibrate probabilities" switch is unchanged — but now it actually calibrates.
- **Sent to the API.** The form carries `threshold_mode` (default `tuned`) and `threshold_metric`
  (default `f1`) alongside the existing `threshold`; a build-payload test covers them.
- **Seen on results.** The **Model scoreboard** (Overview) gained a **Threshold** column showing
  the effective cut each model used (tuned best / fixed / 0.5; blank for multiclass/multilabel),
  with a green ● when that model's probabilities are calibrated — reading the additive
  `models[].decision_threshold` + `.calibrated` fields (schema 1.5). The Risk Register's threshold
  and calibration cards were updated to describe the now-real behaviour.
- **Backwards-safe.** The new response fields are optional; an older run without them shows "—".
  **113 vitest green · tsc + build clean.**

## Explainability — LLM reason-code narrative on the waterfall (2026-07-03)
- The Configuration page's "Per-row explainability (SHAP)" toggle now reveals a second, nested
  toggle — **"LLM reason-code narrative (Azure OpenAI)"** — shown only once SHAP is enabled (a
  narrative is meaningless without the SHAP numbers it summarises). `buildPayload` carries a new
  `explain_llm` form field into `explainability.llm_narratives`, force-off unless SHAP is also on.
- The **Explainability** page now renders, above the SHAP waterfall, the LLM-authored paragraph
  for the selected row when the response carries one (`result.explanations[model].rows[].narrative`,
  schema 1.7) — an indigo reason-code panel. When a row has no narrative (SHAP-only run, or LLM was
  off/unconfigured) the panel is simply omitted, so the page degrades cleanly. The `ExplanationRow`
  type gained an optional `narrative` and `ExplainabilityConfig` gained `llm_narratives`.
  **124 vitest green · tsc + build clean.**

## Explainability — dataset-context controls for the narrator (2026-07-03)
- When the "LLM reason-code narrative" toggle is on, a new **"LLM narrative context"** card appears
  on Configuration with a **Context mode** selector (Given / Derived / Both), a **Dataset context**
  textarea (what the data/target mean), and a **per-column notes** panel (new
  `components/config/ExplainContextPanel.tsx`, mirroring the per-column imputation panel). In
  *Derived* mode the manual inputs are hidden (the model infers context from the data). These map
  to `explainability.context_mode` / `dataset_context` / `column_context`; `ConfigFormState` gained
  `explain_context_mode` / `explain_dataset_context` / `explain_column_context`, carried by
  `buildPayload` only when the narrative toggle is on. This is what makes narratives cite real
  values and business meaning. **128 vitest green · tsc + build clean.**

---

## How to read this project

- **CLAUDE.md** — the conventions and hard rules.
- **PROJECT_STATE.md** — the live status (done, decisions, issues, next steps).
- **plan_tweak.md** — the honest register of deviations from the signed plan.
- **docs/api_contract.md** — the **locked** `/run` request/response schema (the frozen contract).
- **backend_short_desc.md** — plain-language summary of the ML engine.
- **api_short_desc.md** — plain-language summary of the API surface.
- **frontend_short_desc.md** (this file) — plain-language summary of the React dashboard.
