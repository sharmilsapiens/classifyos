# Phase 9b — React frontend: result-rendering pages

> Paste into a fresh Claude Code session in the ClassifyOS repo.
> Second of three frontend slices (9a foundation ✅ → **9b result pages** → 9c remaining + polish).
> 9a is done: design system (Option A "Clarity"), Recharts, typed client against the LOCKED
> contract, app shell + 13-page nav, and a verified Upload→Configure→Run round-trip.

---

## 0. Read first (in this order)

- `CLAUDE.md` — stable contract, hard rules, frontend conventions.
- `PROJECT_STATE.md` — live status (Phase 9a done; what's wired; the decisions log for the
  9a design/chart choices; the "Testing debt / untested paths" section).
- `docs/api_contract.md` — **the LOCKED `/api/v1/run` schema. The source of truth for every
  field these pages render. Re-read it before writing any page.**
- `frontend_short_desc.md` — what the shell, typed client, and round-trip already provide.
- `api_short_desc.md` — the endpoints, especially `/outputs/{name}` for PNGs/CSVs.
- The 9a code: `frontend/src/api/{types,client,parse}.ts`, the app store, and the existing
  Upload/Configure/Pipeline/Overview screens — you are EXTENDING this, not restarting.

The person directing this is **new to frontend/React**. Generated code must teach as it goes:
short comments on what each component, hook, and chart does, in plain terms.

---

## 1. What this slice is

Build the **result-rendering pages** — every screen that visualizes the `result.*` object the
typed client already returns from `/run`. The data binding exists; this slice turns it into
charts and tables. Pages in scope:

1. **Overview** — upgrade the 9a stub to the real summary (KPIs + per-model comparison).
2. **Feature Impact** — `result.feature_impact` (+ the plot4 PNG).
3. **Confusion Matrix** — `result.confusion_matrix` (per model).
4. **Class Report** — `result.class_report` (per class per model).
5. **ROC / PR Curves** — `result.curves` (interactive Recharts).
6. **Predictions Table** — `result.predictions` (sampled) + full-CSV download.
7. **Interaction Features** — the interaction columns in `result.run.active_features` /
   `interaction_cols` (+ the plot6 PNG).

**NOT in this slice (9c):** Explainability (`/explain` stub), Setup Guide, Risk Register, and
the final responsiveness/polish pass. Leave those as the existing stub routes.

---

## 2. Frozen vs scope

- **FROZEN:** the entire backend (`backend/classifyos/` + `backend/api/`). No backend edits.
  The frontend only consumes the LOCKED contract.
- **Contract discipline:** render ONLY fields that exist in `docs/api_contract.md`. If a page
  seems to need something the contract doesn't have, STOP and flag it — do not invent a field,
  do not add a backend endpoint. (The contract is locked; a genuine gap is a 1.1 discussion.)
- **Reuse, don't duplicate:** these pages read the `/run` result already in the app store from
  the round-trip. Do not add new fetch logic for `/run`; read from the store. Only NEW network
  calls allowed in 9b are `GET /outputs/{name}` (for PNGs/CSVs) via the existing client helper.

---

## 3. The interactive-vs-PNG rule (important — encode this in comments)

The contract gives interactive data for SOME visuals and only a PNG for others. Follow this
split exactly; do not try to reconstruct missing data:

- **Render interactively from contract data:**
  - ROC / PR Curves ← `result.curves` (Recharts line charts).
  - Confusion Matrix ← `result.confusion_matrix` (custom heatmap — grid of cells, not a chart lib).
  - Class Report ← `result.class_report` (table + optional grouped bar).
  - Feature Impact ranking ← `result.feature_impact` (Recharts horizontal bar).
  - Per-model metrics ← `result.models[]` (Overview + Class Report header).
- **Fetch the PNG via `/outputs/{name}`** (no interactive data exists in the contract):
  - plot3 feature-importance and plot5 calibration — show the `<img>` from `/outputs/{name}`.
  - plot4 (feature impact) and plot6 (interaction summary) — the interactive versions cover the
    headline, but the PNG is the richer artifact; show it alongside as the downloadable/visual.
- PNGs are ALWAYS fetched on demand via the client's `outputUrl(name)` — never base64-inlined,
  never assumed present (guard for a missing artifact → show a friendly "not generated for this
  run" state, since some plots are placeholders for some problem types).

---

## 4. Binary / multiclass / multilabel handling (do not assume binary)

The contract shapes differ by problem type. Every page must branch on
`result.run.problem_type` and degrade honestly:

- **`curves`:** binary → one ROC + one PR keyed by the positive class. Multiclass → one-vs-rest:
  one ROC line per class; PR may be omitted/placeholder (render "PR not shown for multiclass" if
  absent — do NOT fabricate it). Plot the per-class AUC/AP from the contract in the legend.
- **`confusion_matrix`:** N×N for multiclass; the heatmap must size to the label count and stay
  readable (scroll/auto-cell-size for many classes).
- **`class_report`:** N rows for multiclass; the table is the primary view.
- **Multilabel (Product Recommendation):** this path has **never been run end-to-end** (see the
  testing-debt note). Render defensively — if `curves`/`confusion_matrix` come back in an
  unexpected multilabel shape, show a clear "multilabel view is preliminary" notice rather than
  crashing. Do NOT claim multilabel is verified. (This is a known Week-4 validation target.)
- A model with `status: "failed"` must still render its row everywhere (greyed, with the
  `error` string in a tooltip) — never silently dropped. The contract includes failed rows by
  design; the UI honors that.

---

## 5. Page-by-page contracts

For each: read the named field, render it, handle empty/loading/error/failed states. Keep the
9a design tokens — no new colors outside the token set.

### 5.1 Overview (upgrade the stub)
- KPI band: dataset name/target/problem_type/n_rows/n_train/n_test, models_succeeded, the best
  model by `f1_weighted` (the primary metric — per the metrics stance).
- A per-model comparison bar (Recharts) across the key metrics from `result.models[]`.
- Active config summary (from `result.run`) + the interaction columns count.
- Links to the detail pages.

### 5.2 Feature Impact
- Horizontal bar of `composite_score` per feature (ranked), from `result.feature_impact`.
- A toggle/secondary view for the per-metric columns (anova_f, mutual_info, point_biserial /
  corr_ratio) — null-safe (multiclass has corr_ratio not point_biserial; binary the reverse).
- **Surface the `id_like` flag prominently** (a warning chip on flagged rows — it's the
  leakage-bait signal; the whole feature-impact story depends on showing it).
- Show the plot4 PNG via `/outputs/plot4_feature_impact.png` as the downloadable artifact.

### 5.3 Confusion Matrix
- Custom heatmap (CSS grid of cells, color-scaled by value) per model from
  `result.confusion_matrix[model].matrix` with `labels`.
- A normalise toggle (raw counts ↔ row-normalised) — compute the normalisation client-side
  from the raw matrix (the contract gives raw counts; this is display math, not ML).
- Model selector when multiple models succeeded.

### 5.4 Class Report
- Per-class precision/recall/F1/support table from `result.class_report[model]`, per model.
- Optional grouped bar across classes. Highlight a weak minority class (low recall) — this is
  the imbalanced-data story the metrics stance is built around.

### 5.5 ROC / PR Curves
- Recharts line charts from `result.curves[model]`. ROC: fpr (x) vs tpr (y), diagonal reference
  line, AUC in the legend. PR: recall (x) vs precision (y), AP in the legend.
- Per-class lines for multiclass (one-vs-rest). Per-model selector.
- **Recharts 3.x:** wrap every chart in `ResponsiveContainer`; add `role="img"` + a summary
  `aria-label`; custom tooltips use the 3.x content-prop typing (NOT the 2.x `TooltipProps`);
  manage overlap by JSX render order (z-index is render-order in 3.x), not a z-index prop.

### 5.6 Predictions Table
- Render `result.predictions.sample_rows` (actual, predicted, per-class probabilities,
  confidence, correct_flag). Filter by correct/incorrect; sort by confidence.
- A clear banner: "Showing {rows_returned} of {rows_total} (sampled). Download full table" →
  a download link to `result.predictions.full_csv` via `/outputs/{name}`. Do NOT imply the
  sample is the whole table.

### 5.7 Interaction Features
- List the interaction columns (`result.run.interaction_cols`, or active_features matching
  `_x_` / `_div_` / `_minus_`). Explain each in plain terms (which two columns, which op).
- Show plot6 (`/outputs/plot6_interaction_summary.png`) as the visual.
- Empty state when interactions were disabled for the run.

---

## 6. Tests (vitest + Testing Library; light render-level, full E2E is Phase 10)

Using the committed sample `/run` envelope fixture from 9a (and add a multiclass fixture by
capturing one from a live multiclass run if not present):
- Each page renders without crashing given the fixture result (binary AND multiclass).
- Feature Impact shows the `id_like` warning when a flagged row is present.
- Predictions Table shows the "sampled / download full" banner with correct counts.
- ROC/PR renders one line for binary, multiple (per-class) for multiclass.
- A `status:"failed"` model row renders (greyed) and does not crash the page.
- PNG components call `outputUrl(name)` and handle a missing-artifact case gracefully.
Note clearly: per-page render tests here are smoke-level; true browser E2E across all 7 use
cases (incl. the unverified multilabel path) is Phase 10/11.

---

## 7. Hard rules

- Frontend talks ONLY to `/api/v1/`; no backend edits. Types mirror the LOCKED contract exactly
  — never invent/rename a field; flag gaps instead.
- PNGs fetched on demand via `/outputs/{name}`; never inlined; always guarded for absence.
- Read the `/run` result from the app store; don't re-fetch `/run` in these pages.
- Accessible contrast + keyboard-usable controls + `role="img"`/`aria-label` on charts.
- Keep the 9a design tokens; no off-palette colors. shadcn/ui components for tables/toggles/chips.

---

## 8. WRAP-UP BLOCK (mandatory — do all of it)

1. **Archive this prompt** to `prompts/frontend_phases/phase_09b_result_pages.md` (verbatim),
   committed with the code.
2. **Update `PROJECT_STATE.md`:** 9b sub-entry under Phase 9 (pages built, which fields each
   consumes, binary+multiclass verified against fixtures, multilabel rendered-but-unverified);
   session-log row; set next step to 9c (Explainability stub page, Setup Guide, Risk Register,
   polish). Keep the "Testing debt" section honest (multilabel E2E still open).
3. **Update `frontend_short_desc.md`:** add one-line summaries of the seven pages and the
   interactive-vs-PNG rule.
4. **Update `plan_tweak.md` ONLY if a real deviation occurred** (e.g. a contract field the pages
   needed turned out missing/misshapen, or a multiclass curve shape didn't match the contract).
   Do not pad it. Record any chart/UX decisions in PROJECT_STATE's decisions log instead.
5. **Hallucination check (governance):** verify against the INSTALLED versions —
   **Recharts 3.8.1** (LineChart/Bar/ResponsiveContainer/Tooltip 3.x content-prop typing,
   reference line, legend), Testing Library + vitest, and `import.meta.env`. 3.x ≠ 2.x — do not
   use removed 2.x props (`activeIndex` on chart items, old `TooltipProps` for custom tooltips).
   Record versions in the PROJECT_STATE entry.
6. **Commit message:**
   `Phase 9b: result-rendering pages (Overview, Feature Impact, Confusion, Class Report, ROC/PR, Predictions, Interactions) against the locked contract`

When done, report: pages built, which `result.*` field each renders, whether multiclass was
verified against a fixture (and that multilabel is rendered-but-unverified), any contract gaps
flagged, and the versions hallucination-checked.
