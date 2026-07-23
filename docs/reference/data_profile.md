# Data Profile — logic notes

Concise reference for how the Data Profile (EDA on upload) works end to end.

- **Engine (type detection):** `backend/classifyos/io/inspect.py` (`inspect_file` reads the frame, then delegates to `inspect_dataframe` — the shared profiling core)
- **Engine (per-column metrics):** `backend/classifyos/analysis/profile.py`
- **Frontend (rendering):** `frontend/src/pages/DataProfile.tsx`
- Attached to the `/upload` response (NOT the locked `/run` contract), so changes here need **no `schema_version` bump**. Read-only, fits nothing → **no leakage surface**.
- **Same profile, three data sources.** A CSV `/upload`, a Postgres `/input-sources/select` (materializes then profiles), and a Databricks `/databricks/table-profile` all return the identical `InspectProfile` (same `column_profiles`/`correlation`), so the Data Profile page + the Configure feature picker render identically with **no frontend branching**. The Databricks path profiles a **bounded sample** of the table's real rows read over the SQL warehouse (`fetch_table_sample`, capped at `CLASSIFYOS_DBRICKS_PROFILE_SAMPLE_ROWS`, default 10000) — so its `n_rows` is the *sample* size; if no warehouse is reachable it degrades to a schema-only profile (no blocks). Display-only — the run still reads the full table on the cluster.

---

## 1. Column-type detection (`inspect_file`)

Runs in order of precedence per column:

1. **Datetime** (`_looks_datetime`) — true if dtype is already `datetime64`, OR it's an object column where **(**name matches `date|time|dob|timestamp|_dt$|^dt_` **OR** ≥90% of a 50-row sample contains date separators `- / :`**)** **AND** ≥90% of that sample parses as a date. The separator guard stops IDs like `POL100000` being read as dates.
2. **Binary** — exactly **2 distinct non-null values** → `binary_cols`, regardless of dtype (a numeric `0/1` column counts as binary).
3. **Numeric** — `pandas.is_numeric_dtype` → `numeric_cols`.
4. **Categorical** — everything else → `categorical_cols`.

**Overlap:** `binary_cols` intersects `numeric_cols`/`categorical_cols` (a `0/1` column is in both). Intentional — the UI uses the binary flag for special handling without losing the dtype.

## 2. Display group (`profile_dataframe` → `dtype_group`)

Collapses the overlapping lists into ONE group per column, precedence:

| Order | In list | `dtype_group` |
|---|---|---|
| 1 | datetime | `datetime` |
| 2 | binary | `categorical` (2-value reads best as frequency bars) |
| 3 | numeric | `numeric` |
| 4 | else | `categorical` |

Frontend only ever sees **`numeric` / `categorical` / `datetime`**. Binary is folded into categorical for display.

## 3. Flags (`_quality_flags`, any column type)

From `n_unique` (distinct non-null) and `n_rows` (total, incl. missing):

- **`constant`** — `n_unique <= 1` (single value / all-missing → zero variance, no signal). Checked first.
- **`identifier`** — `n_unique / n_rows >= 0.99` (`ID_LIKE_FRACTION`). Near-unique = ID / free-text key = leakage-bait.

Mutually exclusive. Mirrors `feature_impact._ID_LIKE_FRACTION` (same 0.99) so the two screens agree. Display advisory only — nothing is dropped. Caveat: a genuinely high-cardinality continuous column can also trip `identifier`.

**Badge annotations (frontend `ColumnFlags`, shared by both screens):** the badge shows the concrete detail —
- **`constant`** → the single value (`Single value: 2024`), derived from `stats.mode`/`min` (numeric), `min` (datetime), or `top_values[0].value` (categorical); long strings truncated.
- **`identifier`** → the distinct-of-total count (`Identifier-like · 9,950 of 10,000 unique`), i.e. `n_unique` of `n_rows`.

Every column also carries: `name`, `dtype_group`, `n_missing`, `missing_pct`, `n_unique`, `flags`.

## 4. Metrics & graphs per type

**Numeric** (`_numeric_profile` → `NumericCard`)
- Stats: count, mean, std, min, p25, median, p75, max, mode, skew (non-finite → `null` → em-dash).
- Histogram: 20 bins via `numpy.histogram` (constant col → one widened bin).
- Graph: **smooth density curve** — Recharts `AreaChart`, natural-spline `Area` over bin **midpoints** on a numeric x-axis (updated 2026-07-01; was a bar histogram — a curve reads continuous, many-distinct-value data better). Single-bin column → an honest "only one distinct value" note. **Identifier-like numeric column → no curve** (a distribution over near-unique values is meaningless — shows a short note instead; same in the Configure picker, where the numeric block is dropped entirely).

**Categorical (incl. binary)** (`_categorical_profile` → `CategoricalCard`)
- Metrics: top-**12** value frequencies (`value`, `count`, `pct`) + an `other_count` bucket + `truncated` flag.
- Graph: horizontal frequency bar chart (top values + grey "(other)"), most-frequent value + %, truncation + missing notes.

**Datetime** (`_datetime_profile` → `DatetimeCard`)
- Metrics: `min` / `max` (ISO strings). No chart — Earliest / Latest / Missing card.

**Dataset-level**
- **Missingness** — horizontal bar of missing-% per column (columns with gaps only), colour-graded indigo → amber → rose.
- **Correlation** — Pearson over up to **30** numeric cols (needs ≥2), CSS-grid heatmap diverging indigo (+) ↔ rose (−); undefined cells → "—".

## 5. Large-file sampling

Above **50,000 rows**: heavy work (histograms + correlation) runs on a seeded 50k random sample (`random_state=42`); cheap per-column counts (missing, unique, value frequencies) always use the **full** frame. Payload reports `profile_sampled` + `n_rows_profiled`; UI shows a note.

## 6. Second consumer — Configure feature picker

The Configuration feature-selection list reuses these same `column_profiles`: `dtype_group === "numeric"` → density curve (inline SVG) + avg / IQR (`p75 − p25`) / variance (`std²`); `dtype_group === "categorical"` (non-constant, non-identifier) → its category values as chips (`CategoryChips`); `flags` → the annotated identifier / single-value badges. No new computation — same data, second consumer. Binary numeric columns (grouped `categorical`) list their two values.

**Category-chip scaling.** `top_values` is already capped at the top **12** by the engine, and the picker shows only the first **6** chips + a `+N more` tail (`CATEGORY_CHIP_LIMIT = 6`), so a high-cardinality column never floods the row. Identifier-like columns skip the chip list entirely (their values are near-unique — the badge shows the count instead), and an empty `top_values` falls back to `"{n_unique} categories"`.

## Key constants

| Constant | Value | File |
|---|---|---|
| `ID_LIKE_FRACTION` | 0.99 | `profile.py` |
| `DEFAULT_MAX_BINS` | 20 | `profile.py` |
| `DEFAULT_TOP_K` | 12 | `profile.py` |
| `DEFAULT_MAX_ROWS` (sample threshold) | 50,000 | `profile.py` |
| `DEFAULT_MAX_CORR_COLS` | 30 | `profile.py` |
