# Prompt — Post-training (native, per-model) feature importance

> Archived generation prompt (governance). Cross-surface feature (engine → API → UI) but
> engine-originated, so filed under `backend_phases/`. Verbatim record of what was asked plus
> the clarified scope it resolved to.

## Original request (verbatim, conversational)

> at the moment feature impact is measured before pre processing right
> is that what it is
> i was considering to add feature impact after training aswell, does that make sense
>
> [clarifying] like the metric importance we get to know post training
> [clarifying] i was talking about the feature importance for each model post training
> like how much the parameters effected the output — u get some insights post training right —
> and it depends on model too right

## Clarified scope (resolved with the user before building)

- **Method = NATIVE per-model importance**, NOT permutation. The user specifically wanted the
  model's own built-in importance you "get to know post-training" — tree impurity/gain
  (RF/XGBoost/LightGBM), coefficient magnitude (LogisticRegression). RBF-SVM and GaussianNB
  expose none. This already existed in the engine (`ModelWrapper.feature_importance()`, drawn as
  `plot3_feature_importance.png`); the gap was that the numbers lived only in the PNG, not the
  API JSON, and were not on an interactive page.
- **Scope = full stack** (engine → API → UI), owner-approved ("go").
- **Naming:** new field is `result.feature_importance` (post-training, model-derived), kept
  distinct from the existing `result.feature_impact` (pre-training raw-data screen) — following
  the codebase's own impact/importance split.

## What was built

**Engine (`backend/classifyos/runner.py`)**
- `feature_importances_: dict[str, dict[str, float] | None]` collected post-training from each
  fitted model's `feature_importance()` (None for models with no native importance).
- `_build_feature_importance_df()` → ranked long-form `feature_importance_summary.csv`
  (`model, feature, importance, rank`; only models exposing importances contribute rows;
  header-only frame when none do). Written via `StorageAdapter` in `_save_all`.
- Reuses the existing wrapper method + existing `plot3` PNG — **no new ML, no new library calls.**
  Leakage-safe: reads fitted-model internals only (no test data, no refit).

**API (`backend/api/`, `docs/api_contract.md`)**
- `feature_importance_summary.csv` added to the artifacts allowlist (`artifacts.py`).
- New `FeatureImportanceRow` Pydantic model; optional
  `RunResult.feature_importance: dict[str, list[FeatureImportanceRow]] | None`.
- `_feature_importance(runner)` builder in `routes/run.py` (omit models with no importance;
  whole block `None` when none qualify → SVM/NB-only run byte-identical to earlier schemas).
- `schema_version` bumped `1.2 → 1.3` (third additive bump; same pattern as `tuning`/`train`).
  Contract doc updated additively: header note, response example, notes bullet, footer line.

**Frontend (`frontend/src/`)**
- `FeatureImportanceRow` type + optional `feature_importance` on `RunResult` (mirrors contract).
- Feature Impact page: new "Post-training importance · per model" card — model selector → ranked
  Recharts bar (top 20) + the `plot3` PNG — below the pre-training screen, with an SVM/NB-omission
  note and a graceful "no native importance" state. Backwards-safe when the 1.3 block is absent.

**Tests**
- Backend: `test_native_feature_importance_captured` (per-model dict; NaiveBayes→None; CSV ranked
  desc with contiguous ranks); API `test_binary_run_feature_importance_block`; `RESULT_KEYS` and the
  three `schema_version` asserts bumped to `1.3`; `test_use_case_sweep` artifact set gains
  `feature_importance_summary.csv`.
- Frontend: +2 vitest (1.3 block present → section + model option + SVM/NB note; block absent →
  "no native importance" state).
- Green: 253 backend pytest · 96 frontend vitest · `tsc -b` + `vite build` clean.

## Constraints honored

Additive sections (new attr/method/field; nothing earlier rewritten) · locked contract changed only
additively with a version bump · all I/O via `StorageAdapter` · no leakage (fitted-model internals
only) · hallucination check trivial (no new library calls). Additive feature, not a plan deviation —
**no plan_tweak entry.**
