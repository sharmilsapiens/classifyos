# ClassifyOS — Known Bugs

Deferred bugs to fix later. Each entry: symptom, root cause, reproduction, a verified fix
direction, and scope. Newest first.

---

## BUG-1 — Tuned threshold + an averaged threshold_metric fails on string labels

**Status:** OPEN — deferred (to be fixed after Databricks integration).
**Logged:** 2026-07-09. **Severity:** medium (breaks a valid, user-selectable configuration;
default UI path is unaffected).
**Area:** ML engine — `backend/classifyos/models/decision.py`, `_build_threshold_scorer`.
**Not** related to the MLflow/Postgres work; this predates it (from the 2026-06-30 decision-policy
phase).

### Symptom
Binary training fails for **every** model with:
```
ValueError: pos_label=1 is not a valid label: It should be one of ['0' '1']
```
Observed on the `arizona_impl` dataset (target `converted`, labels `'0'/'1'`) with
`threshold_mode="tuned"` and `threshold_metric="f1_weighted"`. Seen in a real run
(`run_profile.json` → `decision_policy: {threshold_mode: tuned, threshold_metric: f1_weighted,
calibrate_probs: true}`; `metrics_comparison.csv` → LogisticRegression & RandomForest both
`failed` with the above).

### Trigger conditions (all must hold)
- `problem_type == "binary"`, and
- `threshold_mode == "tuned"`, and
- `threshold_metric` is an **averaged/global** metric: `f1_weighted`, `f1_macro`,
  `balanced_accuracy`, or `accuracy`.

The positive-class metrics (`f1`, `precision`, `recall`) are **unaffected**, and the dashboard's
default `threshold_metric` is `"f1"` — which is why this hadn't surfaced before. Multiclass/
multilabel are unaffected (they ignore the threshold).

### Root cause
sklearn's `TunedThresholdClassifierCV` (scikit-learn 1.9.0) has **no `pos_label` parameter**. It
derives the positive class for its internal score→label conversion from the *scorer*, via
`_CurveScorer._get_pos_label()`:
1. use an explicit `pos_label` in the scorer's kwargs if present, else
2. fall back to the metric function's **signature default** — which for `f1_score`/
   `precision_score`/`recall_score` is the integer `1` (and `accuracy_score`/
   `balanced_accuracy_score` have no such parameter, resolving to `None`).

`_build_threshold_scorer` passes `pos_label` only for the positive-class metrics
(`f1`/`precision`/`recall`). For the averaged metrics it builds the scorer **without**
`pos_label` (e.g. `make_scorer(f1_score, average="weighted")`). The engine coerces all targets to
**strings**, so the unset `pos_label` resolves to the integer `1`, which is not a valid label for
string classes `['0','1']` → the error, at fit time, for every model.

### Reproduction (minimal, verified)
```python
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TunedThresholdClassifierCV
from sklearn.metrics import make_scorer, f1_score
X = np.random.rand(60, 4); y = np.array(['0', '1'] * 30)   # STRING labels (engine convention)
# averaged scorer with NO pos_label → fails:
TunedThresholdClassifierCV(LogisticRegression(max_iter=200),
    scoring=make_scorer(f1_score, average='weighted'), cv=3, refit=True).fit(X, y)
# ValueError: pos_label=1 is not a valid label: It should be one of ['0' '1']
```
Full end-to-end repro: run `ModelRunner` on `real/arizona_buyingpropensity_imp.csv`
(target `converted`), `algorithms=['LogisticRegression','RandomForest']`, `threshold_mode='tuned'`,
`threshold_metric='f1_weighted'`, `calibrate_probs=True` → both models `failed`.

### Verified fix direction
Thread the engine's positive class (`pos_label`, the lexicographically-last label already computed
at `decision.py:175`) into **every** tuned scorer, so `_CurveScorer` uses it for the label
conversion. The averaged/accuracy metrics can't take `pos_label` directly (accuracy/balanced
rejects the kwarg; an `average!='binary'` f-metric only warns and ignores it), so wrap them in thin
module-level functions that **accept and ignore** `pos_label`:
```python
def _f1_weighted(y_true, y_pred, pos_label=None): return f1_score(y_true, y_pred, average="weighted")
def _f1_macro(y_true, y_pred, pos_label=None):    return f1_score(y_true, y_pred, average="macro")
def _balanced_accuracy(y_true, y_pred, pos_label=None): return balanced_accuracy_score(y_true, y_pred)
def _accuracy(y_true, y_pred, pos_label=None):    return accuracy_score(y_true, y_pred)
# then: make_scorer(_f1_weighted, pos_label=pos_label)  # etc.
```
This puts `pos_label` into the scorer kwargs (where `_get_pos_label` reads it) without feeding it to
a metric that would reject it or warn. Verified live on scikit-learn 1.9.0: all four averaged
metrics then train and yield a valid `best_threshold_`; the full end-to-end arizona run succeeds
(both models `ok`). Keep `f1`/`precision`/`recall` as-is (already correct). No API/contract change.

**Regression test to add:** a binary problem with string `'0'/'1'` labels, `threshold_mode="tuned"`,
parametrized over `threshold_metric ∈ {f1_weighted, f1_macro, balanced_accuracy, accuracy}`,
asserting training succeeds and `best_threshold_ ∈ (0,1)`. (`tests/test_decision.py`'s
`binary_matrices` fixture already yields string labels, so it reproduces directly.)

> Note (unrelated): the arizona dataset scores a perfect `f1_weighted=1.0` for all models — that is
> a separate, pre-existing **target-leakage** data issue on that dataset, not this bug.
