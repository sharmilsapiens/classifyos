# Phase 5 Generation Prompt — Class Imbalance Handling (Section 8)

> Archive location: prompts/phase_05_class_balance.md

---

Read CLAUDE.md, PROJECT_STATE.md, and plan_tweak.md first. This session implements
Phase 5: Section 8 — class imbalance handling — plus tests. Do NOT implement models or
evaluation. Phases 1–4 code must not be modified.

Pipeline position (corrected order): ... preprocess → build_features → interactions →
**handle_class_imbalance (TRAIN ONLY)** → train. The test set is NEVER resampled or
reweighted. This is the single most important rule of this phase.

## File(s)

1. `backend/classifyos/preprocessing/balance.py`
2. `backend/tests/test_balance.py`

## balance.py

`handle_class_imbalance(X_train, y_train, config) -> (X_res, y_res, class_weight)`

- Operates ONLY on training features/labels passed in. It has no access to the test set
  by design. [RISK] comment: resampling or reweighting anything but train inflates
  metrics and is leakage.
- Strategy from config["class_balance"]: "smote" | "undersample" | "class_weight" | "none".
  - **smote**: imbalanced-learn SMOTE. Returns resampled (X_res, y_res), class_weight=None.
    Guard: SMOTE needs n_neighbors (default 5) < smallest class count — if the minority
    class is too small, automatically reduce k_neighbors to (minority_count - 1), and if
    minority_count <= 1, fall back to random oversampling with a logged warning
    ([RISK]: tiny minority classes — fraud at ~1% / extreme ratios). random_state from config.
  - **undersample**: imbalanced-learn RandomUnderSampler. Returns resampled set,
    class_weight=None. [RISK]: discards majority data; note in log how many rows dropped.
  - **class_weight**: NO resampling. Returns (X_train, y_train unchanged) and a
    class_weight dict ("balanced" computed via sklearn compute_class_weight) for the
    model to consume. This is the only strategy that returns a non-None class_weight.
  - **none**: returns inputs unchanged, class_weight=None.
- Multiclass: SMOTE and undersample must work for 3+ classes (imbalanced-learn handles
  this; test on risk_tier). For multilabel targets, SMOTE is not applicable — detect
  multilabel (problem_type) and fall back to class_weight with a logged warning
  ([RISK]: multilabel resampling unsupported in v1.0; plan_tweak entry).
- Returns must always be a 3-tuple with consistent shapes; X_res columns identical to
  X_train columns (order preserved). Never mutates inputs or config.

## Tests — test_balance.py

Use real CSVs through the Phase 1–4 pipeline (the post-interaction train matrix).

- **test_smote_balances_train**: fraud_claims (~1% positive) → after SMOTE the train
  classes are (near) equal; assert minority proportion rises substantially.
- **test_test_set_untouched**: the function never receives test data; additionally
  assert that calling it does not change the caller's test arrays (pass copies, compare).
- **test_smote_tiny_minority**: construct a train set with minority count = 3 →
  k_neighbors auto-reduced, no crash; minority count = 1 → random-oversample fallback,
  warning logged, no crash.
- **test_undersample_reduces_majority**: majority count drops; minority unchanged;
  rows-dropped logged.
- **test_class_weight_no_resample**: row count identical to input; returned class_weight
  is a dict with one entry per class; SMOTE/undersample return None for it.
- **test_none_passthrough**: arrays returned unchanged, class_weight None.
- **test_multiclass_smote**: risk_tier 3-class → all classes balanced after SMOTE.
- **test_column_order_preserved**: X_res columns == X_train columns exactly.
- **test_no_mutation**: inputs and config deep-equal before/after.
- Regression: FULL suite (Phases 1–4) green.

## Process requirements

- Type hints, docstrings, [RISK] comments. Verify imbalanced-learn / sklearn signatures
  against installed versions (imbalanced-learn API differs across versions — check
  SMOTE/RandomUnderSampler import paths and the k_neighbors param name).
- Full pytest suite green before finishing.
- Save this prompt to prompts/phase_05_class_balance.md.
- Update PROJECT_STATE.md (Ph.5 status, next: Phase 6 models + evaluation — the big one).
- Update short_desc.md (Phase 5 entry) and plan_tweak.md (multilabel SMOTE fallback;
  any auto-k_neighbors behavior beyond scope).
- Commit as: "Phase 5: class imbalance handling — section 8 + tests"
