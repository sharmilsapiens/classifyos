# ClassifyOS — Plan Deviation & Assumption Register

> Honest record of every place the build deviated from the signed scope document / 4-week
> plan, or made an assumption the plan didn't cover. A register, not an essay — one line
> per cell. "Impact" = what a reviewer (Naveen / stakeholders) needs to know at sign-off.
>
> Covers Phases 0–3. From Phase 4 onward, this file is updated at the end of every phase.

| # | Phase | What the plan said | What we did instead / assumed | Why | Impact |
|---|---|---|---|---|---|
| 1 | 0 | Single `classification_framework.py` holding all 16 sections | Split into modules/packages under `backend/classifyos/` | Maintainability; module boundaries enforce the "additive sections" rule; easier for GenAI iteration | Structural only; section-to-file map is in CLAUDE.md. No behaviour change |
| 2 | 0 | Single-file HTML dashboard (`classify_ui.html`) | React (Vite + TypeScript) frontend, 13 pages | 13 pages too large for one file; intended for future Sapiens website integration | Scope's UI deliverable is superseded; frontend not yet built (Phase 9) |
| 3 | 0 | No storage abstraction in scope | Added `StorageAdapter` + env-configured `DATA_DIR`/`OUTPUT_DIR` | Clean local→Databricks (Unity Catalog volumes) swap later; no hardcoded paths | New abstraction reviewers should know about; all I/O routes through it |
| 4 | 1/3 | Step order: preprocess = step 3, split = step 6 | Split runs BEFORE preprocessing | Scope's own leakage rule ("scaler fitted on train only") contradicts its step order | **Scope doc §4 order diagram is outdated** — canonical order is in PROJECT_STATE decisions log |
| 5 | 1 | Real insurance CSVs to validate against | Synthetic datasets with constructed signal (`generate_sample_data.py`) | Real data unavailable at build time | **Metrics on synthetic data are not representative; real-data revalidation pending** |
| 6 | 1/3 | Fixed RunConfig key table | Added `random_state`, `time_split_col`, `outlier_method`, `high_cardinality_threshold` | Reproducibility, temporal splits, and Section 6 tunables not covered by scope | Config contract is wider than scope's table; documented in DEFAULT_CONFIG |
| 7 | 3 | A plain `preprocess()` function | `Preprocessor` as a picklable fit/transform class | Needed for train-only fitting and later `/api/explain` reuse | API shape differs from scope; behaviour matches intent |
| 8 | 2/3 | Scope addressed binary framing | Multiclass adaptations: correlation ratio (eta) replaces point-biserial; frequency encoding replaces target encoding for high-cardinality multiclass | Point-biserial and target-mean encoding are ill-defined for 3+ classes | Methodology choice reviewers should confirm is acceptable for multiclass use cases |
| 9 | 2 | (Not specified) | Test outputs isolated to pytest temp dirs, not real `OUTPUT_DIR` | Tests must never pollute real output artifacts | Test-hygiene assumption; no production impact |
| 10 | 1/2 | Output schema contract locks at Phase 8 | `inspect_file()` return keys + feature_impact output columns locked early | Frontend/contract stability needed before later code depends on them | Early lock; reviewers should treat these keys as fixed ahead of the Phase 8 lock |
| 11 | 2 | (Not in scope) | `id_like` flag for ≥99%-unique columns in feature impact | Leakage guard — identifier columns flagged, not silently dropped | Extra safety signal; columns flagged not removed (human decides) |

---

## How to read this register

- A row exists wherever reality differs from the signed scope, or fills a gap the scope
  left open. Most are deliberate, recorded decisions (see PROJECT_STATE.md decisions log).
- The two rows a reviewer should weigh most at sign-off: **#4** (pipeline-order correction
  vs. the scope diagram) and **#5** (synthetic data — metrics not yet representative).
- See `short_desc.md` for plain-language phase summaries, CLAUDE.md for the hard rules.
