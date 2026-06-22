# Hyperparameter Search-Space Audit (read-only)

> **Status:** Investigation only — no code, tests, or config were changed in producing this
> document. It is a factual snapshot of the tuning layer as it exists today, sourced from the
> code, to inform a later decision about improving it.
>
> **Sources:** `backend/classifyos/tuning.py` (search spaces + scoring), `config.py`
> (`DEFAULT_CONFIG["tuning"]`, `TUNING_METRICS`), `models/wrappers.py` (defaults each tuned
> param overrides), `models/registry.py` (`build_model`), `runner.py` (flow), `cli.py`
> (flags), `api/models.py` (`TuningConfig`).
>
> **Installed library versions** (read from `backend/.venv`, so parameter names below are
> validated against *our* versions, not generic):
>
> | Library | Version |
> |---|---|
> | scikit-learn | 1.9.0 |
> | xgboost | 3.2.0 |
> | lightgbm | 4.6.0 |
> | optuna | 4.9.0 |
> | imbalanced-learn | 0.14.2 |

---

## How to read the tables

- **Currently tuned?** — whether the param appears in that model's `_space_*` function in
  `tuning.py`. Everything else falls back to the wrapper default (the "default when not tuned"
  column, sourced from `models/wrappers.py` `_build_estimator`).
- **Distribution** — `log` = `suggest_float(..., log=True)` (log-uniform), `uniform` =
  `suggest_float`/`suggest_int` without `log`, `categorical` = `suggest_categorical`.
- Every bound below is overridable per-model at run time via
  `config["tuning"]["search_space_overrides"]` (a `dict` for float/int bounds, a `list` for
  categoricals) — see "Configurability today". The bounds shown are the in-code defaults.

---

## 1. LogisticRegression

`_space_logreg` (tuning.py:183). Wrapper defaults: `max_iter=1000`, solver `lbfgs`, penalty
`l2`, `C=1.0` (`wrappers.py:176`).

| Hyperparameter | Currently tuned? | Type | Range / choices | Distribution |
|---|---|---|---|---|
| `C` (inverse reg. strength) | ✅ | float | `1e-3 … 1e2` | log |
| `max_iter` | ❌ (fixed 1000) | int | — | — |
| `solver` / `penalty` / `l1_ratio` | ❌ (lbfgs + L2) | — | — | — |
| `class_weight` | ❌ (handled outside tuning) | — | — | — |

**Important params NOT tuned:**

- **`penalty` / `solver` / `l1_ratio`** — the *type* of regularisation (L1 vs L2 vs
  elastic-net). Deliberately deferred and documented in the docstring: in sklearn 1.9 `penalty`
  is deprecated (warns, removal slated 1.10) and `liblinear` rejects multiclass; tuning the
  regularisation type cleanly now needs `solver="saga"` + `l1_ratio`, which is slower and risks
  non-convergence at the fixed `max_iter`. **Worth tuning** for sparse feature selection (L1),
  but the deferral rationale is sound for v1.0.
- **`class_weight`** — not tuned; balancing is decided upstream by `class_balance` and passed
  through as `sample_weight`. Reasonable to leave out.

**Range notes:** `C` over `1e-3 … 1e2` log is a standard, well-judged sweep around the
default of 1.0. No concerns.

---

## 2. RandomForest

`_space_randomforest` (tuning.py:159). Wrapper defaults: `n_estimators=200`, `n_jobs=-1`,
sklearn defaults otherwise (`max_features="sqrt"`, `max_depth=None`) (`wrappers.py:197`).

| Hyperparameter | Currently tuned? | Type | Range / choices | Distribution |
|---|---|---|---|---|
| `n_estimators` | ✅ | int | `100 … 600` | uniform |
| `max_depth` | ✅ | int | `3 … 30` | uniform |
| `max_features` | ✅ | categorical | `["sqrt", "log2", 0.5, 0.75, 1.0]` | categorical |
| `min_samples_leaf` | ✅ | int | `1 … 10` | uniform |
| `min_samples_split` | ✅ | int | `2 … 20` | uniform |
| `criterion` | ❌ (`gini`) | — | — | — |
| `bootstrap` / `max_samples` | ❌ | — | — | — |

**Important params NOT tuned:**

- **`max_depth=None`** — the unlimited-depth option is *deliberately excluded* (docstring) to
  keep per-fit cost bounded during search. Reasonable for runtime safety, but it means RF can
  never grow fully unpruned trees during tuning even when that would help; a generous cap (e.g.
  50) would be a softer compromise.
- **`criterion`** (`gini` vs `entropy`/`log_loss`) — minor effect; low priority.
- **`max_samples`** (with `bootstrap=True`) — subsample fraction per tree; mild
  regularisation, sometimes useful on large data. Low/medium priority.
- **`class_weight`** — handled outside tuning.

**Range notes:** Ranges are sensible. The richest, best-balanced space of the six.

---

## 3. XGBoost

`_space_xgboost` (tuning.py:93). Wrapper defaults: `n_estimators=200`, `tree_method="hist"`,
`eval_metric="logloss"`, `verbosity=0`, `n_jobs=-1` (`wrappers.py:217`).

| Hyperparameter | Currently tuned? | Type | Range / choices | Distribution |
|---|---|---|---|---|
| `learning_rate` | ✅ | float | `0.01 … 0.3` | log |
| `max_depth` | ✅ | int | `3 … 10` | uniform |
| `n_estimators` | ✅ | int | `100 … 800` | uniform |
| `subsample` | ✅ | float | `0.6 … 1.0` | uniform |
| `colsample_bytree` | ✅ | float | `0.6 … 1.0` | uniform |
| `min_child_weight` | ✅ | int | `1 … 10` | uniform |
| `reg_alpha` (L1) | ✅ | float | `1e-3 … 10.0` | log |
| `reg_lambda` (L2) | ✅ | float | `1e-3 … 10.0` | log |
| `gamma` (min_split_loss) | ❌ | — | — | — |
| `scale_pos_weight` | ❌ (class_weight via sample_weight) | — | — | — |

**Important params NOT tuned:**

- **`gamma` / `min_split_loss`** — minimum loss reduction to make a split; a strong, direct
  complexity regulariser distinct from depth. **Worth adding** (`0.0 … ~5.0`).
- **`colsample_bylevel` / `colsample_bynode`** — per-level / per-node column sampling; secondary
  to `colsample_bytree`. Low priority.
- **`max_delta_step`** — stabilises updates on very imbalanced data; situationally useful for
  the fraud (~99:1) use case. Low/medium priority.
- **`scale_pos_weight`** — XGBoost's native imbalance knob; not tuned because imbalance is
  handled upstream (`class_balance` → `sample_weight`). Correct to leave out given the
  architecture.

**Range notes:** Well-judged, idiomatic ranges. `learning_rate` log `0.01–0.3` pairs correctly
with the wide `n_estimators 100–800`. No concerns.

---

## 4. LightGBM

`_space_lightgbm` (tuning.py:121). Wrapper defaults: `n_estimators=200`, `verbose=-1`,
`n_jobs=-1` (`wrappers.py:243`).

| Hyperparameter | Currently tuned? | Type | Range / choices | Distribution |
|---|---|---|---|---|
| `num_leaves` | ✅ | int | `15 … 255` | uniform |
| `learning_rate` | ✅ | float | `0.01 … 0.3` | log |
| `n_estimators` | ✅ | int | `100 … 800` | uniform |
| `feature_fraction` | ✅ | float | `0.6 … 1.0` | uniform |
| `bagging_fraction` | ✅ | float | `0.6 … 1.0` | uniform |
| `bagging_freq` | ✅ | int | `1 … 7` | uniform |
| `min_child_samples` | ✅ | int | `5 … 100` | uniform |
| `reg_alpha` (L1) | ✅ | float | `1e-3 … 10.0` | log |
| `reg_lambda` (L2) | ✅ | float | `1e-3 … 10.0` | log |
| `max_depth` | ❌ (unbounded, -1) | — | — | — |
| `min_split_gain` | ❌ | — | — | — |

**Important params NOT tuned:**

- **`max_depth`** — **the most valuable missing knob.** LightGBM grows leaf-wise, so with
  `max_depth=-1` (default, unbounded) and `num_leaves` tuned up to **255**, trees can become
  very deep and overfit, especially on the smaller use-case datasets. The standard guard is to
  tune `max_depth` alongside `num_leaves` (keeping `num_leaves ≲ 2^max_depth`). **High priority.**
- **`min_split_gain`** — LightGBM's analogue of XGBoost's `gamma`; minimum gain to split.
  Medium priority.
- **`min_child_weight`** (min sum hessian in leaf) — complements `min_child_samples`. Low
  priority.

**Range notes:** `bagging_freq` is correctly suggested `1 … 7` rather than left at the default
0 (which would make `bagging_fraction` inert) — a deliberate, correct choice noted in the
docstring. The one real concern is `num_leaves` up to **255 with no `max_depth` cap** (see
above) — flagged as the highest-value range/structure fix for this model.

---

## 5. SVM

`_space_svm` (tuning.py:205). Wrapper: `CalibratedClassifierCV(SVC(), ensemble=False)`; SVC
defaults `C=1.0`, `gamma="scale"`, `kernel="rbf"` (`wrappers.py:265`).

| Hyperparameter | Currently tuned? | Type | Range / choices | Distribution |
|---|---|---|---|---|
| `C` | ✅ | float | `1e-2 … 1e2` | log |
| `gamma` | ✅ | float | `1e-4 … 1e0` | log |
| `kernel` | ✅ (but single choice) | categorical | `["rbf"]` | categorical |
| `degree` / `coef0` | ❌ | — | — | — |

**Important params NOT tuned (and quirks):**

- **`kernel` is a one-element categorical (`["rbf"]`)** — this is effectively a **no-op
  suggestion**: every trial picks `rbf`. It exists for override-ability (a user could pass
  `["rbf", "linear", "poly"]` via `search_space_overrides`) but as shipped it tunes nothing.
  **Flagged.**
- **`gamma` is forced numeric (`1e-4 … 1e0`)** — when tuned, SVM never uses sklearn's default
  string heuristic `gamma="scale"` (verified: `SVC().gamma == "scale"`). For most scaled data
  `"scale"` is a strong baseline; the numeric sweep *can* underperform it if the optimum sits
  outside `1e-4 … 1e0`. Worth being aware of, though the range is reasonable for standard-scaled
  features.
- **`degree` / `coef0`** — only relevant for `poly`/`sigmoid` kernels, which aren't offered;
  not worth adding unless the kernel set is expanded.

**Range/cost notes:** Intentionally minimal because the calibrated SVC re-runs internal
calibration CV **on every trial** (slow). The docstring explicitly warns to keep `n_trials`
small for SVM. The `C`/`gamma` ranges themselves are reasonable.

---

## 6. NaiveBayes (GaussianNB)

`_space_naivebayes` (tuning.py:215). Wrapper: `GaussianNB()` with sklearn defaults
(`var_smoothing=1e-9`, verified) (`wrappers.py:290`).

| Hyperparameter | Currently tuned? | Type | Range / choices | Distribution |
|---|---|---|---|---|
| `var_smoothing` | ✅ | float | `1e-12 … 1e-6` | log |

**Important params NOT tuned:** none of consequence — GaussianNB has only `var_smoothing` and
`priors`. `priors` is better left learned from the data.

**Range notes:** The default `1e-9` sits at the centre of the `1e-12 … 1e-6` log range — a
sensible sweep. As the docstring states, `var_smoothing` rarely moves results materially;
tuning it is supported for uniformity, not because it usually helps.

---

## Scoring & leakage boundary

**CV vs single split.** Controlled by `config["tuning"]["cv"]` (default `True`):

- `cv=True` → **k-fold cross-validation** via `StratifiedKFold(n_splits=cv_folds, shuffle=True,
  random_state=...)`, default **3 folds**. A trial's score is the **mean** metric across folds
  (`_score_params`, tuning.py:333). Fold count is clamped down to the smallest class size
  (`_effective_folds`); if it falls below 2, the run logs a warning and silently falls back to a
  single split.
- `cv=False` → a **single train-internal split**: `train_test_split(test_size=0.25,
  stratify=y)`.

**Which metric.** `config["tuning"]["metric"]`, default `f1_weighted`. Must be one of
`TUNING_METRICS` (config.py:28): `f1_weighted`, `f1_macro`, `accuracy`,
`precision_weighted/macro`, `recall_weighted/macro`, `roc_auc`, `pr_auc`, `mcc`, `log_loss`.
The study always maximises; `log_loss` is the sole minimise-metric and is negated internally
(`_MINIMIZE_METRICS`). The score is computed by **reusing `evaluate_model`** on the fold's
held-out portion, so the value a trial optimises is exactly the value reported later (single
source of truth). If a metric is undefined for a fold (e.g. `pr_auc` on multiclass), the trial
is **pruned** (`optuna.TrialPruned`) rather than scored 0.

**Leakage-safe boundary (confirmed).** Tuning never sees the test set:

- `ModelRunner._tune` (runner.py:258) is called with the **pre-balance TRAIN** matrices
  (`train_X`, `train_y`) only — the test split is never passed in.
- Inside `tune_model`, every fold's train/val portions are carved from that train matrix
  (`X.iloc[tr_idx]` / `X.iloc[val_idx]`). The test set is structurally absent from the module.
- **Balancing (SMOTE/undersample) is NOT applied inside the folds** — applying it before CV
  would leak synthetic minority rows across folds. The documented safe default is used: tune on
  the pre-balance train folds; `ModelRunner` balances **only the final fit** (`X_bal`/`y_bal`).
- `class_weight` (computed once on the full train split) **is** passed through to `build_model`
  during tuning — flagged in the module docstring and inline `[RISK]` comments as a mild,
  standard approximation (a per-class reweighting, not synthetic data).

This matches the CLAUDE.md "no data leakage" hard rule.

## Flow: tuned params → final fit

1. `tuning.tune_model(...)` returns a `dict` of best params (or `{}` to fall back to defaults)
   — the params are read from the winning trial's `user_attr("tuned_params")`, so the returned
   dict is exactly what was scored.
2. `ModelRunner._tune` (runner.py:258) loops the run's algorithms, calls `tune_model` for each
   that `should_tune_model` accepts, and collects `self.tuned_params_ = {model: best_params}`.
   A model whose study errors returns `{}` and is silently dropped to defaults (per-model
   isolation — one failed study never aborts the run).
3. `_run_one_algorithm(..., best_params=self.tuned_params_.get(name, {}))` (runner.py:303)
   splats those params into `build_model(name, ..., **params)` (registry.py:64) → `fit`. Empty
   params ⇒ identical to pre-tuning behaviour.
4. The full tuning profile (enabled/metric/cv/cv_folds/n_trials/timeout + `tuned_models` +
   `best_params`) is recorded in **`run_profile.json`** (runner.py:490) for the governance
   audit trail.

## Configurability today

**Config keys** (`DEFAULT_CONFIG["tuning"]`, config.py:87; validated by `_validate_tuning`):

| Key | Default | Validation |
|---|---|---|
| `enabled` | `False` | bool |
| `models` | `[]` (= all run algorithms; `["all"]` also = all) | list of strings |
| `metric` | `"f1_weighted"` | must be in `TUNING_METRICS` |
| `cv` | `True` | bool |
| `cv_folds` | `3` | int ≥ 2 |
| `n_trials` | `30` (per model) | int ≥ 1 (**no upper bound**) |
| `timeout_seconds` | `600` (per model; `None` opts out) | positive number or `None` |
| `search_space_overrides` | `{}` | must be a `dict` (**contents not validated**) |

**CLI flags** (cli.py): `--tune` (sets `enabled=True`), `--tune-models`, `--tune-metric`,
`--trials` (→ `n_trials`), `--timeout` (→ `timeout_seconds`), `--tune-cv-folds` (→ `cv_folds`).
Gaps in the CLI surface:

- **No flag for `cv`** (the k-fold ↔ single-split toggle) — only `--tune-cv-folds`. The CLI can
  change the fold count but not switch CV off.
- **No flag for `search_space_overrides`** — range overrides are config/API-only.
- **Misleading `--timeout` help text:** it reads *"default: no timeout"*, but the override only
  fires when `--timeout` is passed, so the **effective default is 600 s** (the `DEFAULT_CONFIG`
  cap, deep-copied by `_build_tuning_override`). The help text understates the safety cap and is
  worth correcting (doc-only).

**API surface** (`api/models.py`): `TuningConfig` is a full nested model on `RunConfig`,
exposing **every** tuning key — including `search_space_overrides` — to any `/api/v1/run`
caller. So tuning **is already user-facing through the API** (and therefore reachable by the
frontend, subject to whether the UI wires it up). The API contract default mirrors the engine:
`timeout_seconds: 600`, everything off.

## Safe vs dangerous to expose to a user

**Safe** (bounded, hard to misuse):

- `enabled`, `models` (selection), `metric` (enum-validated), `cv`, `cv_folds` (≥ 2; large
  values just cost more but are bounded by class size via `_effective_folds`).

**Dangerous / runtime-blowup risks** (all reachable via the API today):

- **`n_trials`** — validated only as a positive int with **no upper bound**. A large value
  multiplies per-model fit cost linearly; combined with "tune all" (`models=[]`) including the
  slow calibrated SVM, it can run very long. The `timeout_seconds` cap is the backstop.
- **`timeout_seconds=None`** — explicitly opts out of the hard per-model wall-clock cap. Safe
  only when paired with a short `models` list and small `n_trials`; exposed as a plain nullable
  field, so a user can disable the only unconditional runtime bound.
- **`search_space_overrides`** — **the most dangerous knob.** `_validate_tuning` checks only
  that it is a `dict`; the *contents* are unvalidated. A caller can widen any bound arbitrarily —
  e.g. `{"XGBoost": {"n_estimators": {"low": 5000, "high": 50000}}}` or unbounded
  `num_leaves`/`max_depth` — producing enormous per-trial fits. Unlike `n_estimators` in code
  (capped at 800), an override has no ceiling. If this is ever surfaced in the UI it should be
  bound-checked server-side, not passed through raw.

## Recommendations

Highest-value additions / fixes, ranked:

1. **LightGBM: add `max_depth`** (e.g. `3 … 12`) to the search space. With `num_leaves` tuned
   to 255 and depth currently unbounded, this is the single biggest overfitting gap. *(Highest
   value.)*
2. **XGBoost: add `gamma` / `min_split_loss`** (`0.0 … ~5.0`) — a strong complexity regulariser
   not currently covered by depth or the L1/L2 terms.
3. **SVM: make `kernel` a real choice or drop the categorical.** As shipped, `kernel=["rbf"]`
   tunes nothing. Either expand to `["rbf", "linear"]` (note: cost) or document it as
   override-only and remove the no-op suggestion.
4. **Validate `search_space_overrides` contents** before exposing tuning in the UI — at minimum
   cap `n_estimators`/`num_leaves`/`n_trials` and reject `timeout_seconds=None` from untrusted
   callers. Bounds in code are safe; user-supplied bounds currently are not.
5. **LightGBM: add `min_split_gain`**; **RandomForest: consider a higher `max_depth` ceiling**
   (e.g. 50) or a `None` escape so deep forests aren't entirely excluded. *(Lower priority.)*
6. **Doc fix (no engine change):** correct the `--timeout` CLI help text — the effective default
   is the 600 s cap, not "no timeout".

No range currently in code is outright wrong; the items above are gaps and one structural
overfitting risk (LightGBM depth ↔ leaves), not broken bounds.
