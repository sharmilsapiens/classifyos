# Prompt — Imputation controls only where there's something to impute (frontend-only)

> Archived verbatim per the governance requirement (CLAUDE.md → "MANDATORY before
> committing any generated section, save the exact generation prompt"). This is a
> pure dashboard refinement (no engine, API, or contract change), so it lives under
> `frontend_phases/`.

## Task (verbatim)

> where there are no missing values, we still see option for impudation in per coumn impudation..
> i want to remove that, show only coums where impudation is req,in Missing values · per column thing
>
> also in preporcessing no missing columns are in for a category(numerical/carte..)
> don't let users pick the overall categoru thign in preprocessing, when clicked show mo missing
> values for this category but show the available options..

(Standard session footer: read PROJECT_STATE.md + the relevant short_desc files + CLAUDE.md first;
respect no-leakage / additive-changes / StorageAdapter / locked-contract constraints; run the
relevant tests and add tests for new behaviour; verify end-to-end where it makes sense; update
PROJECT_STATE.md + the appropriate short_desc file(s) + docs/api_contract.md if the API changed;
update plan_tweak.md only on a genuine deviation; hallucination-check any library calls against
installed versions; archive this generation prompt under prompts/ in the same commit as the code;
don't commit/push unless asked.)

## Interpretation

Two requests, both on the Configuration page's imputation UI, both pure display logic over the
`n_missing`/`missing_pct` the upload profile already returns:

1. **"Missing values · per column" card** — only list columns that actually have missing values
   (`n_missing > 0`). A complete column has nothing to impute, so drop it from the list entirely.
2. **Per-type selectors (*Missing values · numeric* / *· categorical*)** — when the selected
   feature columns of that kind have **no** missing values, don't let the user pick a strategy that
   would never run: disable that selector and state "no missing values for this category", while
   still keeping the options listed (the "show the available options" clause → keep the `<option>`s
   in the DOM; a `disabled` native `<select>` shows its current value and keeps its options).

## Implementation summary (what was built)

- **`components/config/MissingByColumnPanel.tsx`** — the listed columns are now
  `profiled.filter(n_missing > 0)`. Two-way empty state: "None of the selected feature columns have
  missing values — there is nothing to impute per column." when profiled features exist but all are
  complete, vs the pre-existing "Select feature columns above…" when there's no profile / nothing
  picked. The per-column badge simplifies to the amber "N missing (X%)" count (the "no gaps" branch
  is dead now that complete columns are filtered out). Intro copy updated ("Only columns with
  missing values are shown…").
- **`pages/Configure.tsx`** — `missingSummary(...)` became `missingState(...)` returning
  `{ summary, disableSelector }`. `disableSelector` is true **only** when there ARE profiled selected
  columns of that kind and NONE have gaps. In that state the per-type `<Select>` is `disabled`, the
  summary is emerald "No missing values in the N selected {kind} column — nothing to impute for this
  category.", and the per-strategy hint is suppressed. Options stay in the DOM. Both per-type selects
  gained an `aria-label` (accessibility + testability). Unknown missingness (no profile / no column of
  that kind selected) → `summary` null, selector stays enabled (unchanged).
- **Tests** (`pages/configure.test.tsx`) — added a shared `PROFILE_WITH_GAPS` + `renderConfigureGaps`
  helper; the two per-column tests now use it (a complete column no longer renders a selector); +2 new
  (per-column card lists only gap columns / omits a complete one; "nothing to impute per column"
  message when all clean); the reassure test became "locks the per-type selector" (asserts `disabled`
  + options still present); the numeric-summary test also asserts the selector stays editable with
  gaps. **153 vitest green (+2 net, was 151) · `tsc -b` + `vite build` clean.**
- **Hallucination check** — N/A: no new library calls (existing `@/api/types` fields +
  `fmtInt`/`fmtPct`; native `<select disabled>`). Confirmed.
- **No engine/API/contract change, no `schema_version` bump** — the engine still applies per-type and
  per-column strategies exactly as before; this only hides controls that would have no effect.
- **No plan_tweak entry** — additive UI refinement over data the profile already returns, realizing
  user feedback; recorded as a Decisions-log row in PROJECT_STATE.md.
