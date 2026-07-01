# Per-column missing-value imputation (engine + API + frontend)

Archived verbatim (governance requirement). This is the generation prompt for the
2026-07-01 "per-column imputation override" work — an additive, request-side extension of
the per-type missing-value split (see `phase_03_preprocess.md` and the 2026-06-27 entry).

---

for impudation
we let all the numeric columns imputed by a single method and all categorical by a..

let us improvise this by giving the option for each column to choose impudation method

---

Standing session instructions applied to the above:

Before doing anything, read PROJECT_STATE.md and the relevant short_desc file(s) for the
surface being touched (backend_short_desc.md / api_short_desc.md / frontend_short_desc.md),
plus CLAUDE.md for the hard rules. Respect the project's constraints: no data leakage (fit
on train only), additive changes (don't rewrite earlier sections), StorageAdapter for all
I/O, and the locked API contract.

When done: run the relevant tests and make sure they pass, then update PROJECT_STATE.md and
the appropriate short_desc file(s) to reflect what changed. Update plan_tweak.md only if this
genuinely deviated from the plan — don't invent an entry. Do a hallucination check on any
library calls against the installed versions.
