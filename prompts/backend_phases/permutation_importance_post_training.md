# Prompt — Permutation feature importance (model-agnostic, per-model)

> Archived generation prompt (governance). Cross-surface feature (engine → API → UI) but
> engine-originated, so filed under `backend_phases/`. Verbatim record of what was asked plus
> the clarified scope it resolved to. Follow-up to `feature_importance_post_training.md`
> (the native counterpart).

## Original request (verbatim, conversational)

> why is it that i see feature impact post training only for 4 models but not all 6
> i dont see feature importance listed for svm and naive bayes
> why is that
>
> [after the explanation] i first want to understand how feature importance is measured for
> these four models — what measuring natively mean — and also what does permutation based
> feature imp mean? how is feature imp calculated natively and in perm based
>
> [then] add permutation importance along with this native
> i'll remove any of them later

## Clarified scope (resolved with the user)

- The user noticed native importance is blank for **2 of 6 models** (RBF-SVM, GaussianNB expose
  none). After explaining native vs. permutation, they asked to **add permutation importance
  alongside** the existing native block, intending to compare the two and drop one later.
- **Method = PERMUTATION importance** (the model-agnostic measure): shuffle one feature column on
  the held-out test split, measure the drop in F1-weighted (the engine's primary metric), repeat
  and average. Works for **all six** models because it only needs `predict` — the whole point,
  filling the SVM/NaiveBayes gap.
- **Scope = full stack** (engine → API → UI), keeping the native `result.feature_importance` (1.3)
  intact and adding a parallel `result.permutation_importance` block.

## Key design decisions

- **Manual implementation**, not `sklearn.inspection.permutation_importance`. Our `ModelWrapper`s
  aren't sklearn estimators (no `score`/`get_params`), and XGBoost/LightGBM rely on the wrapper's
  `_safe_X` DataFrame-column-rename path — a numpy round-trip through sklearn would break
  feature-name matching. The manual version drives `ModelWrapper.predict` directly on a DataFrame.
- **Scored on F1-weighted, on the TEST split** — same metric the dashboard leads with, and genuine
  generalisation reliance consistent with the reported metrics.
- **Leakage-safe:** reads held-out test predictions only — fits nothing, refits nothing, shuffles a
  private copy (the test matrix is never mutated). Seeded `np.random.default_rng` → reproducible.
- **[RISK]** noted in the module: correlated features can both look unimportant (the model leans on
  the untouched twin); cost scales with `n_features × n_repeats` predict passes per model.

## What was built

**Engine**
- New pure module `backend/classifyos/analysis/permutation_importance.py::permutation_importance(
  model, X, y_true, problem_type, *, n_repeats=5, random_state=42)` → `{feature: drop} | None`.
- `ModelRunner`: new `permutation_importances_` attr, collected post-training on the test split via
  `_compute_permutation_importances` (per-model try/except — report-only, never aborts the run; for
  multilabel uses the indicator matrix). `_build_permutation_importance_df()` → ranked
  `permutation_importance_summary.csv` (`model, feature, importance, rank`; all models contribute,
  header-only when none). Written via `StorageAdapter` in `_save_all`.

**API (`backend/api/`, `docs/api_contract.md`)**
- `permutation_importance_summary.csv` added to the artifacts allowlist.
- New `PermutationImportanceRow` Pydantic model; optional
  `RunResult.permutation_importance: dict[str, list[PermutationImportanceRow]] | None`.
- `_permutation_importance(runner)` builder in `routes/run.py` (every model with a computed measure
  appears — incl. SVM/NaiveBayes; whole block `None` when none could be computed).
- `schema_version` bumped `1.3 → 1.4` (fourth additive bump; same pattern as
  `tuning`/`train`/`feature_importance`). Contract doc updated additively: header note, response
  example, notes bullet, footer line.

**Frontend (`frontend/src/`)**
- `PermutationImportanceRow` type + optional `permutation_importance` on `RunResult`.
- Feature Impact page: new "Permutation importance · per model" card — model selector → ranked
  Recharts bar (top 20), covering **all** models — below the native-importance card, with the
  correlated-feature caveat and a graceful "not computed" state. Backwards-safe when 1.4 absent.

**Tests**
- Backend: `test_permutation_importance_captured_for_all_models` (NaiveBayes native→None but gets a
  permutation dict; CSV ranked desc; both models present); API
  `test_binary_run_permutation_importance_block` (ranked; superset of `feature_importance` keys);
  `RESULT_KEYS` and the three `schema_version` asserts bumped to `1.4`; `test_use_case_sweep`
  artifact set gains `permutation_importance_summary.csv`.
- Frontend: +2 vitest (1.4 block present → card + SVM option; block absent → "not computed").
- Green: 295 backend pytest · 99 frontend vitest · `tsc -b` + `vite build` clean.

## Constraints honored

Additive sections (new module/attr/method/field; nothing earlier rewritten) · locked contract
changed only additively with a version bump · all I/O via `StorageAdapter` · no leakage (held-out
test predictions only, no refit, no mutation) · hallucination check ✅ (sklearn 1.9.0 `f1_score`
`average`/`zero_division`; numpy 2.4.6 `random.default_rng().permutation`). Additive feature realizing
a user request, not a plan deviation — **no plan_tweak entry** (logged as a Decisions-log row).
