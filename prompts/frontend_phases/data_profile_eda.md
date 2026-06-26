# Prompt — Data Profile (EDA) view on upload

> Archived verbatim per the governance requirement (CLAUDE.md → "MANDATORY before
> committing any generated section, save the exact generation prompt"). This feature
> spans engine + API + frontend but is primarily a dashboard view, so it lives under
> `frontend_phases/`.

## User request

> on uploading the data in the dashboard, i want to create some views for the data taken
> as input, for numeric data or continuous data, we could show the data distribution and
> show some values on the data, like mean mode. what are some standard visualisations that
> we could add for this dashboard.. what kind of things we show for categorical data..

(Run with `/plan`; the standard session footer: read PROJECT_STATE.md + the relevant
short_desc files + CLAUDE.md first; respect no-leakage / additive-changes / StorageAdapter /
locked-contract constraints; run the relevant tests; update PROJECT_STATE.md + the appropriate
short_desc file(s); update plan_tweak.md only on a genuine deviation; hallucination-check any
library calls against installed versions.)

## Decisions taken up front (AskUserQuestion)

1. **UI placement** → a new dedicated **"Data Profile"** Workspace page (Upload → Data Profile →
   Configuration).
2. **Visualization scope** (all four) → numeric histogram + stats (mean/median/mode/std/quartiles/
   skew); categorical top-N frequency bars (+ "other" bucket); dataset-level missingness overview;
   numeric correlation heatmap.
3. **Backend approach** → carry the profile on the **extended `/upload` response** (a new optional
   `column_profiles` + `correlation` block), not a separate endpoint.

## Implementation summary (what was built)

- **Engine** — new pure `backend/classifyos/analysis/profile.py::profile_dataframe(df, *, numeric_cols,
  categorical_cols, binary_cols, datetime_cols, max_bins=20, top_k=12, max_rows=50_000,
  max_corr_cols=30)`. Numeric → stats + `numpy.histogram`; categorical/binary → top-K value counts +
  `other_count`/`truncated`; datetime → min/max; dataset → Pearson `correlation` (numeric cols).
  Large files sample for the heavy work; per-column counts use every row. Reads no target, fits
  nothing (no leakage). `inspect_file` gained an **additive** optional `profile: bool = False` param
  that attaches the blocks to the already-loaded frame (no second read); default keeps it
  byte-identical.
- **API** — `routes/upload.py` calls `inspect_file(profile=True)` and wraps the body in
  `safe_jsonify` (NaN/Inf → null). Additive `/upload`/inspect payload (not the locked `/run`
  envelope) → no `schema_version` bump. Documented in `docs/api_contract.md`.
- **Frontend** — `pages/DataProfile.tsx` (reads the store, no new call), `InspectProfile` extended
  with `ColumnProfile`/`NumericStats`/`Histogram`/`TopValue`/`CorrelationMatrix`, nav + route, and an
  "Explore data profile" link on Upload. Recharts for histograms/frequency/missingness; CSS-grid
  correlation heatmap (same pattern as Confusion Matrix).
- **Tests** — backend `tests/test_profile.py` (+10) + `/upload`/inspect asserts → 250 pytest;
  frontend `pages/dataProfile.test.tsx` (+3) → 94 vitest. `tsc -b` + build clean.
- **Hallucination check** ✅ against pandas 2.3.3 / numpy 2.4.6 (`Series.mode/skew/quantile`,
  `numpy.histogram`, `df.corr(numeric_only=True)`).
- **No plan_tweak entry** — additive feature realizing a user request, not a deviation; recorded as
  a Decisions-log row in PROJECT_STATE.md.
