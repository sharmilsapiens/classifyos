# Phase 6 Generation Prompt — Models + Evaluation (Sections 10, 11, 12, 13)

> Archive location: prompts/phase_06_models_eval.md
> This is the largest phase. If context gets tight, split at the marked checkpoint —
> but keep all of it in ONE coherent session if possible so the ABC contract stays consistent.

---

Read CLAUDE.md, PROJECT_STATE.md, plan_tweak.md first. This session implements the model
layer and evaluation: Section 11 (6 model wrappers), Section 12 (MODEL_REGISTRY),
Section 10 (evaluate_model), Section 13 (classify). Do NOT build plot_results, ModelRunner,
or the CLI (that's Phase 7). Phases 1–5 code must not be modified.

These wrappers CONSUME Phase 5 output: SMOTE/undersample give a rebalanced train frame;
class_weight returns a dict that must be passed into the model at construction/fit.

## Files to create

1. `backend/classifyos/models/base.py`        — ModelWrapper ABC
2. `backend/classifyos/models/wrappers.py`     — 6 concrete wrappers (or one file per model)
3. `backend/classifyos/models/registry.py`     — MODEL_REGISTRY
4. `backend/classifyos/evaluation/metrics.py`  — evaluate_model
5. `backend/classifyos/predict.py`             — classify
6. Tests: `tests/test_models.py`, `tests/test_registry.py`, `tests/test_metrics.py`,
   `tests/test_classify.py`

## Section 11 — base.py (ABC) + wrappers.py

`base.py` defines the abstract contract ALL wrappers obey:

```python
class ModelWrapper(ABC):
    def __init__(self, problem_type: str, class_weight: dict | None = None,
                 random_state: int = 42, **params): ...
    @abstractmethod
    def fit(self, X, y) -> "ModelWrapper": ...
    @abstractmethod
    def predict(self, X) -> np.ndarray: ...
    @abstractmethod
    def predict_proba(self, X) -> np.ndarray: ...   # MUST be shape (n, n_classes)
    @abstractmethod
    def feature_importance(self) -> dict[str, float] | None: ...
    name: str            # short key matching the registry
    classes_: np.ndarray # learned class labels, set in fit
```

Wrappers (each subclasses ModelWrapper):
- **LogisticRegressionModel** (sklearn LogisticRegression; accepts class_weight; for
  multilabel use OneVsRestClassifier).
- **RandomForestModel** (sklearn; feature_importance from feature_importances_).
- **XGBoostModel** (xgboost; handle class_weight via sample_weight or
  scale_pos_weight for binary; feature_importance from the booster).
- **LightGBMModel** (lightgbm; class_weight supported; feature_importance from booster).
- **SVMModel** (sklearn SVC with probability=True OR CalibratedClassifierCV for proba;
  feature_importance → None for non-linear kernels; note in docstring).
- **NaiveBayesModel** (sklearn GaussianNB; class_weight not supported → if a class_weight
  dict is passed, translate to sample_weight in fit; feature_importance → None).

Hard requirements for ALL wrappers:
- predict_proba ALWAYS returns (n_samples, n_classes), columns ordered to match
  self.classes_ — for every problem_type, including binary (2 columns, not 1).
  [RISK] comment: downstream metrics/plots assume this exact shape/order.
- For multilabel problem_type, wrap the base estimator in OneVsRestClassifier and
  predict_proba returns (n_samples, n_labels). Document the shape difference.
- class_weight handling is explicit per model (some take the dict directly, some need
  sample_weight translation, GaussianNB needs sample_weight). Never silently ignore it.
- Consistent output schema regardless of underlying library.

### --- CONTEXT CHECKPOINT (optional split point) ---
### If splitting the session: commit wrappers + base + registry + their tests here,
### then continue with metrics + classify in a second session.

## Section 12 — registry.py

```python
MODEL_REGISTRY: dict[str, type[ModelWrapper]] = {
    "LogisticRegression": LogisticRegressionModel,
    "RandomForest": RandomForestModel,
    "XGBoost": XGBoostModel,
    "LightGBM": LightGBMModel,
    "SVM": SVMModel,
    "NaiveBayes": NaiveBayesModel,
}
def build_model(name, problem_type, class_weight=None, random_state=42, **params) -> ModelWrapper
```
- build_model looks up the key, raises ValueError listing valid keys if unknown.
- New models are added HERE ONLY — never by editing existing wrappers (additive rule).
- Accept the scope's short aliases too (LR, RF, XGB, LGBM/LightGBM, SVM, NB) → map to keys.

## Section 10 — metrics.py

`evaluate_model(y_true, y_pred, y_proba, problem_type, classes) -> dict`

Compute (guarding against undefined cases, e.g. ROC-AUC needs ≥2 classes present):
- Accuracy, Precision (weighted+macro), Recall (weighted+macro),
  F1 (weighted PRIMARY, + macro), ROC-AUC (binary: standard; multiclass: ovr weighted;
  multilabel: average), Log Loss, MCC.
- Confusion matrix (as nested list, labels in classes order).
- Per-class classification report (precision/recall/f1/support per class) as a dict.
- Calibration curve data (fraction_of_positives, mean_predicted_value) for binary.
Return a single JSON-serializable dict (plain python types — no numpy scalars).
[RISK] comment: accuracy is misleading on imbalanced data — F1-weighted is primary,
MCC + PR-AUC emphasized for imbalanced binary.

## Section 13 — predict.py

`classify(model, X_test, y_test, classes) -> pd.DataFrame`
- One row per test sample: actual, predicted, probability_<class> per class,
  confidence (max proba), correct_flag (actual==predicted).
- Column names stable and JSON-friendly. Index aligned to X_test.

## Tests

Use real CSVs through the FULL Phase 1–5 pipeline (load → split → preprocess → features →
interactions → balance) to produce train/test matrices, then:

- **test_all_wrappers_fit_predict**: every registry model fits on policy_lapse (binary)
  and risk_tier (multiclass); predict_proba shape == (n, n_classes) for both; columns
  align to classes_.
- **test_class_weight_consumed**: passing a class_weight dict changes predictions/behavior
  vs None (at least runs without error for every model, including GaussianNB via
  sample_weight).
- **test_registry_unknown**: build_model("nope") → ValueError listing valid keys; aliases
  (LR/RF/XGB/LGBM/SVM/NB) resolve correctly.
- **test_feature_importance**: tree models return a non-empty dict; SVM(rbf)/NB return None
  without error.
- **test_evaluate_model_binary**: all 7 metrics present, confusion matrix 2x2, per-class
  report has both classes, calibration data present; dict is JSON-serializable
  (json.dumps succeeds — catches stray numpy types).
- **test_evaluate_model_multiclass**: risk_tier 3-class — macro/weighted metrics present,
  3x3 confusion matrix, ROC-AUC computed via ovr.
- **test_classify_output**: predictions df has actual/predicted/probability_*/confidence/
  correct_flag; row count == test rows; probabilities per row sum ≈ 1 (binary/multiclass).
- **test_imbalanced_metrics**: on fraud (after SMOTE on train, raw test) MCC and ROC-AUC
  are computed and finite.
- Regression: FULL suite (Phases 1–5) green.

## Process requirements

- Type hints, docstrings, [RISK] comments. Verify xgboost/lightgbm/sklearn signatures
  against installed versions (these APIs vary a lot by version — check class_weight /
  sample_weight handling, predict_proba availability, SVC probability calibration).
- Full pytest suite green before finishing.
- Save this prompt to prompts/phase_06_models_eval.md.
- Update PROJECT_STATE.md, short_desc.md (Phase 6 entries), and plan_tweak.md if any
  deviation arose (likely: SVM/NB feature_importance None; multilabel via OneVsRest;
  class_weight→sample_weight translations). If nothing deviated, state so.
- Commit as: "Phase 6: model wrappers + registry + evaluation + classify — sections 10-13 + tests"

---

## Generation outcome (filled in by Claude Code, 2026-06-15)

Implemented base.py (ModelWrapper ABC), wrappers.py (six wrappers via a shared
`_SklearnEstimatorWrapper` template base), registry.py (MODEL_REGISTRY + build_model +
aliases), evaluation/metrics.py (evaluate_model), predict.py (classify). 47 new tests;
117/117 suite green. Hallucination check performed against the installed versions
(scikit-learn 1.9.0, xgboost 3.2.0, lightgbm 4.6.0, numpy 2.4.6, pandas 2.3.3).

Deviations from this prompt (recorded in plan_tweak.md rows 20–22):
1. **class_weight applied uniformly via sample_weight translation** for ALL wrappers, not
   the native `class_weight` dict for LR/RF/SVM/LGBM as the prompt suggested. Reason: the
   loader coerces the target to string dtype, so numeric targets arrive as `"0"/"1"`;
   sklearn's native class_weight-dict path int-coerces those labels and then fails to find
   the string keys (`ValueError: classes [0, 1] are not in class_weight`). Per-sample
   weight translation is mathematically equivalent and library-agnostic.
2. **SVM uses `CalibratedClassifierCV(SVC(), ensemble=False)`** rather than
   `SVC(probability=True)` — the latter is deprecated in scikit-learn 1.9 and removed in
   1.11. Feature importance is `None` (the calibrated wrapper exposes no coef_/importances).
3. **xgboost and lightgbm were not previously installed** nor in requirements.txt; they were
   installed (xgboost 3.2.0, lightgbm 4.6.0) and added to requirements.txt as the prompt
   requires both wrappers. XGBoost rejects string labels, so the XGBoost wrapper
   label-encodes y internally and maps predictions back.
