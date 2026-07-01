# Prompt — Explainability rewired: real per-row SHAP (opt-in)

> Archived generation prompt (governance). Cross-surface feature (engine → API → UI) but
> engine-originated, so filed under `backend_phases/`. Verbatim record of what was asked plus
> the clarified scope it resolved to. Restores `unwire.md` entry #3 (the previously-hidden
> Explainability page) — this time backed by a real backend implementation.

## Original request (verbatim, conversational, via `/plan`)

> you could see that explainability is unwired
> i now want to rewire it
> /plan
> how could we employ explainability here
> and what could we do with that
> at the end when explainbility is rewired, we should remove that from unwire.md
> and update appropriate docs
>
> [after an explainer on global vs local explainability + SHAP] i dont know anything about
> explainability — first help me understand what it is, then make me understand / suggest what
> we could do in our case
>
> [after the concepts + insurance framing] let us use shap library for those available but for
> those not available, can we [do] something — is shap available for all 6? if yes, let's
> implement it. And make this explainability configurable, meaning we choose to turn on the
> toggle for explainability to work.

## Clarified scope (resolved with the user)

- **Local (per-row) explainability** was the missing piece — the two existing importance screens
  (`feature_importance` 1.3, `permutation_importance` 1.4) are **global**. The hidden page was a
  stateless `/explain` stub deferred to a v2.0 "model persistence / MLflow" item.
- **The unlock:** compute explanations **during the run** (models still fitted in memory) and ship
  them in the `/run` response — the same compute-during-run pattern as the two importance blocks —
  so no model persistence is needed and the v2.0 blocker is dissolved.
- **Method — SHAP, all six models.** `shap.TreeExplainer(model_output="probability")` on the
  unwrapped base estimator for the tree models (RF/XGB/LGBM); model-agnostic `shap.KernelExplainer`
  over `predict_proba` for LogisticRegression/SVM/NaiveBayes. Contributions are additive:
  `base_value + Σ contributions == prediction`.
- **Configurable, opt-in.** A default-OFF `explainability` config block (mirrors `tuning`), because
  the KernelExplainer path has real cost; bounded to a small row sample.
- **Delivery.** Read from the store on the rewired Explainability page (no `/explain` call), draw a
  real SHAP waterfall. Binary explains the positive class, multiclass the predicted class;
  multilabel unsupported in v1.

## What to build

- **Engine:** `analysis/explain.py::explain_rows` (explainer selection via `unwrap_base_estimator`,
  robust 2-D/3-D shape normalization, leakage-safe TRAIN-background). `config.py` `explainability`
  block + `_validate_explainability`. `ModelRunner.explanations_` collected during the run (lazy
  `shap` import, per-model try/except, report-only) + `explanations_summary.csv` (only when enabled).
- **API:** `RunConfig.explainability` → `build_config`; `ExplanationRow`/`ModelExplanation` +
  `result.explanations`; `schema_version 1.5 → 1.6` (additive); artifacts allowlist; `_explanations`
  reshape helper; `/explain` message points to `/run`; `docs/api_contract.md` updated.
- **Frontend:** `explainability`/`explanation` TS types; `explain_enabled` toggle in Configure +
  `buildPayload`; `Explainability.tsx` rewritten with a real cumulative waterfall reading the store;
  nav entry + route re-enabled (undo unwire #3).
- **Governance:** hallucination-check the `shap` API against the installed version (0.51.0) before
  coding; run all suites; update PROJECT_STATE.md, backend_short_desc.md, `unwire.md` (#3 Restored),
  and add `shap` to requirements.txt. No plan_tweak entry (additive feature + unwire restore).

## Outcome

337 backend pytest green (+22) · 122 frontend vitest green · `tsc -b` + `vite build` clean.
`shap>=0.46,<1` added. unwire.md #3 marked Restored (2026-07-01).
