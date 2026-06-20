# ClassifyOS v1.0 — Governance Sign-off Dossier

> **Status: prepared for human review (Phase 11).** This document is the evidence package the
> team lead + stakeholders need to sign off ClassifyOS v1.0. **Claude Code prepared it; it cannot
> sign off, demo, or collect signatures** — those are human acts (Naveen + the stakeholders). The
> checkboxes that remain unticked below are deliberate: they are the human actions that turn
> "engineering complete" into "v1.0 released".
>
> Prepared: 2026-06-21 (end of Phase 11). Repo state: Phase 11 engineering complete.
> Companion docs: `CLAUDE.md` (hard rules), `PROJECT_STATE.md` (live status),
> `plan_tweak.md` (deviation register), `docs/api_contract.md` (locked contract).

---

## 1. Scope §12 governance checklist — status + evidence

| # | Governance requirement | Status | Evidence |
|---|---|---|---|
| 1 | Prompt version control | ✅ Done | Every section/phase prompt is archived verbatim under `prompts/**` — see §2 below for the inventory. |
| 2 | Section-level unit tests on real data | ✅ Done | **202 backend pytest + 72 frontend vitest + 9 Playwright E2E**, all green. Coverage map in §3. |
| 3 | [RISK]-comment review by team lead | ⬜ **HUMAN** | The complete `[RISK]` inventory is tabulated in §4 for the lead to walk + check off. (Code is in place + commented; the *review* is the human act.) |
| 4 | Leakage audit (encoder/scaler/SMOTE train-only) | ⬜ **HUMAN** | The specific tests that *prove* train-only fitting are pointed to in §5, for the auditor to confirm. |
| 5 | Output schema contract locked | ✅ Done | `docs/api_contract.md`, `schema_version` **1.0**, frozen at Phase 8. Multilabel (Phase 11) renders through it **unchanged**. |
| 6 | Hallucination check (library calls vs installed versions) | ✅ Done | Per-phase version verifications recorded in `PROJECT_STATE.md`; Phase 11 additions in §6 below. |
| 7 | Team-lead sign-off per phase (Naveen) | ⬜ **HUMAN** | Per-phase sign-off is Naveen's action — see §7. |
| 8 | Final stakeholder demo | ⬜ **HUMAN** | Demo script in §8 (repeatable click-through). Demo + acceptance is the stakeholders' action — see §7. |

**Engineering is complete; the four ⬜ items are human acts, not code.**

---

## 2. Prompt version control — archived prompts (evidence for #1)

All generation prompts are kept verbatim (governance requirement) under `prompts/`, organised by
surface:

- `prompts/backend_phases/` — `phase_01_skeleton` … `phase_07_runner`, `phase_07B_tuning` (the ML engine).
- `prompts/api_phases/` — `phase_08_fastapi` (the FastAPI layer).
- `prompts/frontend_phases/` — `phase_09a_foundation`, `phase_09b_result_pages`, `phase_09c_remaining_polish` (the dashboard).
- `prompts/testing_phases/` — `phase_10_e2e_testing`, `phase_11_integration_signoff` (this phase).
- `prompts/tooling/` and `prompts/docs/` — dev/tooling + documentation prompts.
- `prompts/README.md` — the filing scheme.

---

## 3. Test coverage (evidence for #2)

**Final counts (all green): 202 backend pytest · 72 frontend vitest · 9 Playwright E2E.**

Backend pytest (by area):

| Area | File(s) | What it covers |
|---|---|---|
| Config / inspect / loader / split | `test_config`, `test_inspect`, `test_loader`, `test_split` | Validation, dtypes, target coercion, stratified + temporal split. |
| Feature impact | `test_feature_impact` | ANOVA/MI/point-biserial/eta, id_like flag, no input mutation. |
| Preprocess (leakage suite) | `test_preprocess` | Train-only encoder/scaler/imputer; poisoned-test-set scaler check. |
| Feature / interaction engineering | `test_features`, `test_interactions` | Train-only poly/ratio/bin edges + MI auto-discovery frozen on test. |
| Class balance | `test_balance` | SMOTE/undersample/class_weight/none, tiny-minority guard, multilabel→class_weight. |
| Models / registry / metrics / classify | `test_models`, `test_registry`, `test_metrics`, `test_classify` | 6 wrappers, proba shape/order, all metrics, predictions table. |
| Runner / plots / CLI | `test_runner`, `test_plots`, `test_cli` | End-to-end orchestration, `_run_config` isolation, per-algo robustness. |
| Tuning (Optuna) | `test_tuning` | CV-in-train leakage-safe scoring, per-model isolation, hard timeout. |
| Curves | `test_curves` | ROC/PR points, multiclass OvR, leakage-safe (test-only). |
| API | `test_api_health/upload/run/outputs/explain` | Locked envelope, 422/400, sampled predictions, full-test curves, stub. |
| **Multilabel (Phase 11)** | **`test_multilabel`** | **True multilabel (label names, not combos); per-label metrics/curves; smote→class_weight fallback; train-only binarizer; label-set predictions.** |
| **7-use-case sweep (Phase 11)** | **`test_use_case_sweep`** | **All 7 insurance use cases run through the API → contract-valid envelope + 11 artifacts each.** |

Frontend vitest (72): typed-client `ApiError` mapping, `buildPayload`/`parseRunResponse`,
render-level smoke of every result page against **binary + multiclass + multilabel** captured
`/run` fixtures, error/empty states, the multilabel honest-state assertions (per-label curves,
"no confusion matrix for multilabel" notice, per-label class report).

Playwright E2E (9): the **7-use-case happy-path sweep** (Upload → Configure → Run → rendered
charts/heatmap/PNG, asserting the LOCKED contract; multilabel asserts the honest states) + 2 real
cross-origin CORS tests (GET + preflight OPTIONS).

---

## 4. `[RISK]` comment inventory (evidence for #3 — team-lead walk-through)

Every `[RISK]` comment in the engine, file + one-line summary. The lead can walk each one against
the code and tick it off.

| File:line | Risk point (one line) |
|---|---|
| `config.py:94` | Runaway tuning — hard 600s/model wall-clock cap so a study can never run unbounded. |
| `config.py:151` | Config mutation — deep-copy defaults so `DEFAULT_CONFIG` is never mutated (root of `_run_config` isolation). |
| `analysis/feature_impact.py:28` | Raw-data screen — pairwise-drops NaNs; a screening signal, not a final selector. |
| `analysis/feature_impact.py:120` | ID-like columns are near-unique leakage bait — flagged, not silently dropped. |
| `multilabel.py:17` | Multilabel delimiter fixed at `\|` for v1.0; labels containing `\|` are out of scope. |
| `models/base.py:21` | Proba shape `(n, n_classes)` + `classes_` column order is an engine-wide assumption. |
| `io/loader.py:76` | Target-NaN rows can't train/evaluate — dropped up front, never imputed; logged. |
| `evaluation/curves.py:16` | Leakage — curve points read held-out TEST predictions only; fit nothing. |
| `models/wrappers.py:120` | Degenerate single-column binary proba guarded to the 2-column contract. |
| `models/wrappers.py:273` | SVM (calibrated) exposes no coefficients → feature importance is `None`. |
| `preprocessing/balance.py:8` | Balancing operates on TRAIN only — the central no-leakage rule of the stage. |
| `preprocessing/balance.py:83` | Works on copies; never sees the test set by construction. |
| `preprocessing/balance.py:96` | Multilabel resampling unsupported → class_weight fallback (documented). |
| `preprocessing/balance.py:147` | Tiny-minority SMOTE → random-oversample fallback (duplicates, no synthetic variety). |
| `preprocessing/balance.py:183` | Undersampling discards majority rows — information loss, logged. |
| `evaluation/metrics.py:10` | Accuracy misleads on imbalance → F1-weighted primary, MCC + PR-AUC emphasised. |
| `evaluation/metrics.py:107` | F1-weighted is the primary metric. |
| `tuning.py:23` | Leakage — every trial scored INSIDE the train split (test never passed in). |
| `tuning.py:306` | Trial train/val both carved from the TRAIN split only. |
| `tuning.py:436` | Per-model isolation — a failed study falls back to defaults, never aborts the run. |
| `runner.py:28` / `runner.py:130` | `_run_config` isolation — deep-copy config once; `self.config` never mutated. |
| `runner.py:160` | **Multilabel binarizer learns its label vocabulary from TRAIN only (leakage boundary).** |
| `runner.py:173` | Tuning scored on PRE-balance train folds; balancing applied only to the final fit. |
| `split.py:45` | Temporal leakage — time-ordered data uses a most-recent holdout, never a random split. |
| `preprocessing/features.py:72` | Fit/transform separation IS the leakage guard (train-only poly/ratio/bin stats). |
| `preprocessing/features.py:123` | Polynomial cap — `max_poly_features` bounds degree-2 column explosion. |
| `preprocessing/features.py:135` | Post-scaling medians near 0 → ratio denominator heuristic weakly determined (guarded). |
| `preprocessing/interactions.py:97` | Re-discovery on test = leakage; pair list + ops frozen at fit. |
| `preprocessing/interactions.py:175` | O(n²) pair explosion — candidate pool capped at the 15 most target-correlated cols. |
| `preprocessing/preprocess.py:90` | Fit/transform separation IS the leakage guard for preprocessing. |
| `preprocessing/preprocess.py:211` | Target encoding is the most leakage-prone encoder (train-only m-estimate means). |
| `preprocessing/preprocess.py:240` | Unseen test categories → all-zeros block (train/serve-skew signal). |
| `preprocessing/preprocess.py:305` | "drop" missing-strategy never drops TEST rows (would corrupt evaluation). |

---

## 5. Leakage audit — the proof (evidence for #4)

The "no data leakage" rule (CLAUDE.md) is enforced **structurally** (fit/transform split, no
test argument) and **proven by dedicated tests**. The auditor can confirm each:

- **Encoder / scaler / imputer train-only** — `tests/test_preprocess.py`: the poisoned-test-set
  scaler check (a 1e9 value injected into TEST does not move the train-fitted scaler), the
  train-only target-encoding mean (vs a full-data mean on a skewed split), unseen-category →
  all-zeros, and "drop never removes test rows".
- **Feature/interaction stats train-only** — `tests/test_features.py` + `tests/test_interactions.py`:
  bin edges survive a poisoned test set; MI auto-discovery pairs are frozen across a
  scrambled/poisoned test transform.
- **Balancing train-only by construction** — `tests/test_balance.py`: `handle_class_imbalance`
  takes **no test argument**; tests assert the test arrays are never touched.
- **Models fit on balanced TRAIN only; eval reads untouched TEST** — `tests/test_runner.py`
  (`_run_config` isolation asserted) + `tests/test_classify.py` / `tests/test_metrics.py`.
- **Tuning leakage-safe** — `tests/test_tuning.py`: every trial is scored with CV *inside the
  train split*; the test set is never passed to `tune_model` (structural); balancing is applied
  only to the final fit, not inside CV folds.
- **Curves leakage-safe** — `tests/test_curves.py`: `compute_curve_points` reads held-out test
  predictions only and fits nothing.
- **Multilabel binarizer train-only (Phase 11)** — `tests/test_multilabel.py::test_multilabel_binarizer_is_train_fitted`:
  a label appearing only in the test split is ignored, not added to the vocabulary.

---

## 6. Hallucination check — Phase 11 additions (evidence for #6)

Phase 11 added no new runtime dependencies. Library calls verified against the installed,
pinned versions (`backend/requirements.lock`, `frontend/package.json`):

- **scikit-learn 1.9.0** — `MultiLabelBinarizer().fit/transform` (train-only vocabulary; unknown
  test labels ignored with a `UserWarning`), `OneVsRestClassifier` on an indicator matrix,
  `roc_auc_score`/`average_precision_score` multilabel averaging, `classification_report` on
  indicator inputs. The pre-existing per-phase verifications (pandas 2.3.3, scipy 1.17.1,
  imbalanced-learn 0.14.2, xgboost 3.2.0, lightgbm 4.6.0, optuna 4.9.0, FastAPI 0.136.3,
  Pydantic 2.13.4) are unchanged.
- **@playwright/test 1.61.0**, **vitest 4.1.9**, **recharts 3.8.1** — re-confirmed; the 7-use-case
  sweep + multilabel render tests use only already-verified APIs.

---

## 7. Human action items (NOT code — these turn "engineering complete" into "v1.0 released")

- [ ] **Per-phase sign-off — Naveen.** Review each phase (engine 1–7B, API 8, frontend 9a–c,
      testing 10–11) against `PROJECT_STATE.md` + the archived prompts.
- [ ] **`[RISK]`-comment review — team lead.** Walk the §4 table against the code; confirm each
      mitigation is acceptable.
- [ ] **Leakage-audit sign-off.** Confirm the §5 tests are sufficient proof of train-only fitting.
- [ ] **Final stakeholder demo + acceptance — Amit Shah, DharaniKiran Kavuri, Matat Rotbaum.**
      Run the §8 demo script end-to-end.
- [ ] **Signatures + tag.** Collect sign-offs; tag the repo **`v1.0`**.

Until all five are done, v1.0 is **"ready for sign-off"**, not "released".

---

## 8. Demo script (repeatable click-through)

A ~5-minute end-to-end demo proving the system works. (Full setup detail: `RUN_FULL_SYSTEM.md`.)

1. **Start both servers.**
   - Backend: from `backend/`, `.venv\Scripts\activate` then
     `uvicorn api.main:app --reload --port 8000`. Wait for `Application startup complete`.
   - Frontend: from `frontend/`, `npm run dev`. Open `http://localhost:5173`.
   - The top bar shows **"API connected"** (green) — the browser reached the backend.
2. **Upload.** Go to **Upload**, drop `backend/data/samples/policy_lapse.csv`. The column table +
   class-distribution chips appear (proves `/upload` + `inspect_file`). Pick target **`will_lapse`**.
3. **Configure.** Continue to **Configuration**: select features, problem type **binary**, a couple
   of algorithms (e.g. LogisticRegression + RandomForest), class balance **class_weight**. Run.
4. **Watch + Overview.** The Overview shows the pipeline-stage checklist while it runs, then the
   **KPI band** (best model, accuracy, ROC-AUC, MCC), the per-model comparison chart, and the
   **model scoreboard**.
5. **Tour the result pages.** Feature Impact (ranked bars + the `id_like` leakage flag) → ROC/PR
   Curves (interactive) → Confusion Matrix (heatmap, raw↔normalised) → Class Report → Predictions
   (sampled banner + full-CSV download) → Interaction Features → Explainability (the honest v2.0
   stub).
6. **Show an artifact.** On ROC/PR Curves, the **plot2 PNG** loads (fetched via `/outputs/{name}`);
   or download `classification_results.csv` from Predictions.
7. **(Optional) Show the multilabel use case.** Re-run with `product_reco.csv` →
   `recommended_products`, problem type **multilabel**. The result pages render the **honest**
   multilabel states: per-label one-vs-rest curves, per-label class report, label-set predictions,
   and the "a single confusion matrix is not defined for multilabel" notice.

---

## 9. Honest v1.0 limitations (what a reviewer MUST know at sign-off)

Consolidated from `plan_tweak.md`:

1. **Synthetic data.** All metrics are on synthetic datasets with constructed signal — **not
   representative of real insurance data**. Real-data revalidation is a documented post-v1.0 item
   (plan_tweak #5).
2. **Multilabel is preliminary** (plan_tweak #34–35). It runs end-to-end and renders honestly, but:
   per-label **thresholds** are out of scope (fixed 0.5 via one-vs-rest); multilabel **imbalance is
   effectively unhandled** (resampling is N/A — the `smote`→`class_weight` fallback fires — and the
   OvR wrapper does not apply class weights); there is **no single confusion matrix** (omitted by
   design). Usable for per-label scoring/ranking; thresholding + imbalance weighting are v1.x.
3. **Synchronous `/run` + gateway timeout** (plan_tweak #28). `/run` blocks until the run finishes;
   a long run (large data, many algorithms, tuning on) can exceed a reverse-proxy/gateway timeout.
   At the measured perf size (12k rows, 13s) this does not bite; a background-job path
   (submit → poll → fetch) is deferred to **v1.5**.
4. **`/explain` is a structured stub** (plan_tweak #29). v1.0 is stateless with no model
   persistence; real SHAP arrives in **v2.0** (the response *shape* is final, so v2.0 fills it in
   without a contract change).
5. **Outputs are overwritten per run** (fixed filenames). A shared `OUTPUT_DIR` keeps only the
   latest run's artifacts; `--output-dir` is the per-run workaround (RUNBOOK.md).
6. **Performance baseline** (plan_tweak #37): 12k rows × 4 algorithms, tuning off = **13.0s** (well
   within the "< 5 min" target); a realistic tuning run (XGBoost, 25 trials) = 65.7s, bounded by the
   per-model cap. Much larger data or tuning-on is where the v1.5 background-job path matters.

---

_Prepared by Claude Code at the end of Phase 11. The unticked items in §1 and §7 are the human
acts that remain before ClassifyOS v1.0 is released._
