# Prompt — Decision policy: real probability calibration + binary decision threshold

> Archived generation prompt (governance). Cross-surface feature (engine → API; frontend is a
> sanctioned follow-up), engine-originated, so filed under `backend_phases/`. Verbatim record of
> the question that started it plus the scope it resolved to.

## Original request (verbatim, conversational)

> in problem framing part of configuration
> i see Decision threshold as a configurable parameter
>
> is that how it is suppoed to be
> i heard that decision threshold is something, that the model needs to decide to get the best abswers..
> are we handling that with calibrate probabilities
> should we let model use diff decision thresholds or using calibrate probabilities enough

## What the investigation found (the reason this became work)

Both `threshold` (0.5) and `calibrate_probs` (True) were exposed end-to-end (UI → API → config)
but **inert** — the engine never read either. `classify()`/`predict()` used sklearn's built-in
0.5 argmax; the only calibration anywhere was the SVM wrapper's intrinsic
`CalibratedClassifierCV` (forced because `SVC(probability=True)` is deprecated), independent of
the flag. So the "Decision threshold" control did nothing, and the RiskRegister page's claim that
"threshold is an explicit config field" was misleading.

Conceptually clarified for the user: calibration (trustworthy probabilities) and the decision
threshold (where to cut) are **orthogonal** — calibration makes a threshold meaningful but does
not choose one; the threshold is a post-hoc operating-point decision (analyst-set or tuned on
held-out data), not something learned during fitting. For imbalanced insurance problems (fraud
99:1, lapse) the 0.5 default is rarely optimal, so calibration alone is not enough.

## Clarified scope (resolved with the user via two decisions)

1. **Threshold** → *auto-tune + manual override*: `threshold_mode ∈ {default, fixed, tuned}`.
   `fixed` applies the analyst `threshold`; `tuned` maximises `threshold_metric` on internal CV
   folds of TRAIN (leakage-safe). Binary only — multiclass/multilabel keep argmax.
2. **Calibration** → *make `calibrate_probs` real*, default kept **True** (a deliberate behaviour
   change: every binary/multiclass run now calibrates; slower but better probabilities, which the
   domain wants). SVM skipped (already calibrated); multilabel out of scope.
3. **Landing** → *engine + API this session* (additive contract bump); frontend controls + result
   badges are a separate follow-up session.

## Implementation contract

- **No new ML re-implemented.** Compose sklearn-native meta-estimators around the built
  estimator: `CalibratedClassifierCV(cv=k, ensemble=False)`, `FixedThresholdClassifier`,
  `TunedThresholdClassifierCV`. New pure module `models/decision.py` (`fit_policy`,
  `effective_threshold`, `unwrap_base_estimator`, `DecisionInfo`).
- **Leakage-safe.** Every wrapper fits via internal CV on TRAIN only; the tuned threshold is
  selected on TRAIN CV folds, never the held-out test set. The test set still only sees
  `predict`/`predict_proba`.
- **Additive seam, no model edits.** `_SklearnEstimatorWrapper` gains `set_decision_policy` + a
  fit branch that delegates to `fit_policy` for binary/multiclass; the six concrete model classes
  are untouched (the "models via registry only" rule is about adding models, not capabilities).
  Multilabel path unchanged.
- **Importance must survive calibration.** The calibration/threshold wrappers hide
  `coef_`/`feature_importances_`, so `feature_importance()` unwraps to the base estimator —
  otherwise native importance would silently vanish the moment calibration (now default) is on.
- **class_weight routing.** When a threshold wrapper is outermost, `sample_weight` only reaches
  the inner fit under scoped `config_context(enable_metadata_routing=True)` with explicit
  `set_fit_request`/`set_score_request` (scorer must NOT consume sample_weight — tune on the
  natural distribution). The positive class follows the engine convention (lexicographically-last
  label) so the string-typed targets don't trip the default integer `pos_label=1`.
- **API additive bump `1.4 → 1.5`.** Request gains `threshold_mode`/`threshold_metric` (forwarded
  to `build_config`, the authoritative validator); response `models[]` gains
  `decision_threshold` (effective binary operating point; null for multiclass/multilabel/failed)
  and `calibrated`. `docs/api_contract.md` updated additively.

## Hallucination check (scikit-learn 1.9.0, verified live)

`TunedThresholdClassifierCV` (`best_threshold_`, `scoring`, `cv`, `refit`), `FixedThresholdClassifier`
(`threshold`, `pos_label`, `response_method`), `CalibratedClassifierCV` (`cv`, `ensemble`),
`make_scorer`/`get_scorer`, `set_fit_request`/`set_score_request`, `config_context(enable_metadata_routing=True)`,
and the unwrap attribute chain (`.estimator_` → `.calibrated_classifiers_[0].estimator`) all
confirmed against the installed version before coding.
