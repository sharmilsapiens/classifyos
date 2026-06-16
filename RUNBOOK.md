# ClassifyOS — RUNBOOK

How to run the ClassifyOS ML engine on a local machine and read the results. This is an
operator's manual for the CLI (`python -m classifyos.cli`) and the `ModelRunner` it drives —
not a code-internals doc. Every command below is copy-pasteable.

> Scope: the standalone ML engine. The FastAPI layer and React dashboard are separate
> (and, as of this writing, not yet built). See `PROJECT_STATE.md` for current progress.

---

## 1. Prerequisites & setup

**Run everything from the `backend/` directory.** The CLI is invoked as a module
(`python -m classifyos.cli`), so the `classifyos` package must be importable — that only
works from `backend/`.

```powershell
# from the repo root
cd backend

# activate the venv (Windows PowerShell)
.\.venv\Scripts\Activate.ps1
```

If `.venv` does not exist yet, create it once:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**`.env` must be present and correct.** The CLI calls `load_dotenv()` at startup, which
reads `backend/.env`. That file sets where the engine reads data and writes outputs:

```ini
DATA_DIR=C:/Projects/classifyos_data/input
OUTPUT_DIR=C:/Projects/classifyos_data/output
CORS_ORIGINS=...
```

⚠️ **Fallback caveat.** `.env` is gitignored and machine-local — it does **not** travel with
the repo. If `.env` is missing (or the vars aren't otherwise exported), `LocalFolderStorage`
silently falls back to **relative defaults**: `./data` for input and `./classification_output`
for output (resolved against your current directory). The run will not error — it will just
look for data in the wrong place and write artifacts somewhere unexpected. The first two
lines the CLI prints (`DATA_DIR` / `OUTPUT_DIR`) are absolute resolved paths — **always
glance at them** to confirm `.env` loaded.

The first lines of every run echo the resolved config:

```
DATA_DIR   : C:\Projects\classifyos_data\input
OUTPUT_DIR : C:\Projects\classifyos_data\output
input file : policy_lapse.csv
target     : will_lapse
```

---

## 2. Inspect a file first (`--inspect`)

Before choosing a target or running anything, profile the CSV. `--inspect` reads the file,
prints a column/dtype/class profile, and exits — **no model is trained, nothing is written.**

```powershell
python -m classifyos.cli --file policy_lapse.csv --target will_lapse --inspect
```

`--file` is a key **relative to `DATA_DIR`** (not an absolute path). Representative output:

```
rows: 3000   columns: 15
numeric     : ['age', 'policy_tenure_years', 'annual_premium', 'sum_assured', 'num_late_payments', 'claims_count', 'has_agent', 'will_lapse']
categorical : ['policy_id', 'occupation', 'region', 'policy_type', 'channel', 'payment_frequency']
binary      : ['has_agent', 'will_lapse']
datetime    : ['policy_start_date']
missing     : {'age': 90, 'occupation': 90, 'annual_premium': 90}
class distribution[will_lapse]: {0: 1995, 1: 1005}
suggested problem type      : binary
```

**How to read it before committing to a target:**

- **`class distribution`** — confirm the target has ≥2 classes and check the balance. Here
  it's ~2:1 (mild); fraud-style targets can be ~99:1, which changes which metrics you trust
  (see §4). A target with only one class will fail the run.
- **`binary` columns** — these double as numeric. A 0/1 target (`will_lapse`) shows up here.
- **`datetime` columns** (`policy_start_date`) — these are auto-excluded from default
  features; you generally don't model on a raw date.
- **`categorical` columns with one value per row** (e.g. `policy_id`) are ID-like. They are
  auto-excluded from default features (leakage-bait — see §4), but `--inspect` does not flag
  them explicitly; eyeball anything that looks like an identifier.
- **`missing`** — columns with NaNs (imputed automatically during preprocessing). Heavy
  missingness on your intended target column is a reason to pick a different target.

---

## 3. Run the full pipeline

```powershell
python -m classifyos.cli --file <key> --target <col> [flags...]
```

The runner executes the whole pipeline end-to-end: load → feature impact → **split** →
preprocess → feature engineering → interactions → class balancing (train only) → train +
evaluate every algorithm → write all artifacts. (Preprocessing/balancing are fitted on the
training split only — the test set is never touched, so scores are leakage-free.)

### Flags

| Flag | Meaning | Default if omitted |
|---|---|---|
| `--file` *(required)* | Dataset key, **relative to `DATA_DIR`** (e.g. `policy_lapse.csv`, `real/iris.csv`). | — |
| `--target` *(required)* | Target column name. | — |
| `--features` | Comma-separated feature columns. | **All columns except** the target, detected datetime columns, and ID-like columns (≥99% unique and non-float). |
| `--problem-type` | `binary` / `multiclass` / `multilabel`. | Inferred by `inspect_file` (`binary` vs `multiclass`). |
| `--test-size` | Test fraction, in `(0, 0.5]`. | `0.2` |
| `--algos` | Comma-separated algorithms or aliases. | `LogisticRegression,RandomForest,XGBoost` |
| `--balance` | `smote` / `undersample` / `class_weight` / `none`. | `smote` |
| `--encoding` | `onehot` / `label` / `ordinal` / `target`. | `onehot` |
| `--scaling` | `standard` / `minmax` / `robust` / `none`. | `standard` |
| `--output-dir` | Override `OUTPUT_DIR` for this one run. | `OUTPUT_DIR` from `.env` |

### Algorithm names and aliases

`--algos` accepts canonical names or short aliases (case-insensitive):

| Alias | Canonical |
|---|---|
| `LR`, `LOGREG` | LogisticRegression |
| `RF` | RandomForest |
| `XGB` | XGBoost |
| `LGBM`, `GBM` | LightGBM |
| `SVM`, `SVC` | SVM |
| `NB`, `GAUSSIANNB` | NaiveBayes |

### Worked examples

**Binary (explicit algorithms):**

```powershell
python -m classifyos.cli --file policy_lapse.csv --target will_lapse --algos LR,RF,XGB
```

```
problem_type : binary
algorithms   : ['LR', 'RF', 'XGB']
balance=smote  encoding=onehot  scaling=standard

=== metrics summary ===
  model                status    accuracy    f1_wtd   roc_auc       mcc
  ---------------------------------------------------------------------
  LogisticRegression   ok          0.6133    0.6238    0.6543    0.2162
  RandomForest         ok          0.6467    0.6335    0.6016    0.1619
  XGBoost              ok          0.6400    0.6266    0.5823    0.1458
```

**Multiclass (with class-weight balancing instead of SMOTE):**

```powershell
python -m classifyos.cli --file risk_tier.csv --target risk_tier `
    --problem-type multiclass --algos LR,RF,LGBM --balance class_weight
```

```
=== metrics summary ===
  model                status    accuracy    f1_wtd   roc_auc       mcc
  ---------------------------------------------------------------------
  LogisticRegression   ok          0.7067    0.7070    0.8677    0.5488
  RandomForest         ok          0.6967    0.7004    0.8628    0.5288
  LightGBM             ok          0.6817    0.6837    0.8509    0.5001
```

**Defaults only (let the engine infer everything):**

```powershell
python -m classifyos.cli --file fraud_claims.csv --target is_fraud
```

This infers the problem type, uses the default `LR,RF,XGB` algorithms, default `smote`
balancing, and the auto-detected default feature set.

> PowerShell line continuation is a backtick (`` ` ``). On one line, drop it.

---

## 4. Outputs — where they go and what they mean

All artifacts are written to **`OUTPUT_DIR`** (from `.env`, e.g.
`C:\Projects\classifyos_data\output`), or to the folder you passed with `--output-dir`.
The CLI prints the exact list it wrote at the end of the run. Eleven files:

| File | What it contains / how to read it |
|---|---|
| `classification_results.csv` | Per-sample predictions for every successful model: `model`, `sample_index`, `actual`, `predicted`, `probability_<class>` (one column per class), `confidence` (row-max probability), `correct_flag`. Use to inspect individual mistakes. |
| `metrics_comparison.csv` | One summary row per algorithm: `status` (`ok`/`failed`), `accuracy`, `f1_weighted`, `f1_macro`, precision/recall (weighted), `roc_auc`, `pr_auc`, `mcc`, `log_loss`, `error`. This is the model-comparison table. |
| `class_report.csv` | Per-class precision/recall/F1/support for each model (sklearn classification report, flattened). Shows *which classes* a model is weak on — critical on imbalanced data where the headline number hides a poorly-predicted minority class. |
| `run_profile.json` | The run's audit record: input file, target, problem type, configured `features` vs final `active_features` (engineered + interaction columns), algorithms, balancing strategy, `class_weight`, `class_distribution`, `n_rows`/`n_train`/`n_test`, `models_succeeded`, and a UTC `timestamp`. |
| `plot1_confusion_matrix.png` | Confusion matrix per model — raw counts + row-normalized. Diagonal = correct. |
| `plot2_roc_pr_curves.png` | Binary: ROC + PR curves, one line per model, AUC/AP in the legend. Multiclass: one-vs-rest ROC per class per model (PR omitted). |
| `plot3_feature_importance.png` | Top-15 importances per model that exposes them (trees, LR). Models without importances (SVM, NaiveBayes) are skipped; if *none* expose them you get a labelled placeholder. |
| `plot4_feature_impact.png` | Raw association of each feature with the target (composite score + per-metric bars), computed on the raw data *before* preprocessing. Written by the feature-impact stage. |
| `plot5_calibration_curve.png` | Reliability diagram vs the perfect diagonal (binary only). Multiclass runs get a labelled placeholder (calibration is binary-only). |
| `plot6_interaction_summary.png` | \|correlation-with-target\| of the engineered interaction columns. Written by the interaction stage. |

### How to read the metrics

- **Don't trust raw `accuracy` on imbalanced data.** On a 99:1 target, predicting "always
  the majority" scores 99% accuracy while catching zero positives. Prefer:
  - **`f1_weighted`** — the framework's primary metric.
  - **`mcc`** (Matthews correlation) — robust to imbalance; ~0 means no better than chance.
  - **`pr_auc`** (binary) — focuses on the positive/minority class.
- **A suspiciously perfect score (≈1.0 accuracy / AUC) usually means leakage**, not a great
  model. Check:
  - `run_profile.json` `active_features` and `plot4` — is one feature almost perfectly
    associated with the target? (e.g. an outcome-derived column.)
  - Did an **ID-like column** sneak in via an explicit `--features` list? IDs are excluded
    from *defaults*, but an explicit `--features` is taken verbatim.

---

## 5. Re-running — what gets overwritten

**Output filenames are fixed constants** (`classification_results.csv`, `metrics_comparison.csv`,
`plot1_confusion_matrix.png`, …). Runs are **not** isolated into per-run subfolders. A second
run pointing at the same `OUTPUT_DIR` **overwrites every file from the previous run.**

This is a known limitation. To keep a run's outputs:

- **Use `--output-dir` per run** — the clean workaround:

  ```powershell
  python -m classifyos.cli --file policy_lapse.csv --target will_lapse `
      --output-dir C:/Projects/classifyos_data/output/lapse_2026-06-15_smote
  ```

- Or copy/rename the folder after each run before starting the next.

**Telling two runs apart after the fact:** `run_profile.json` records the input file, target,
problem type, configured + active features, algorithm list, balancing strategy, class
distribution, row counts, and a UTC `timestamp` — enough to identify *what* a run did and
*when*. It does **not** carry a unique run ID, and (because of the overwrite behavior) only
the **most recent** run's profile survives in a shared `OUTPUT_DIR`. If you need to compare
runs, isolate them with `--output-dir`.

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `FileNotFoundError` / `ERROR inspecting file` | `--file` path is wrong, or it's not relative to `DATA_DIR`. | Pass a key relative to `DATA_DIR` (e.g. `policy_lapse.csv`, `real/iris.csv`), not an absolute path. Confirm the printed `DATA_DIR` is correct. |
| Outputs land in `backend\classification_output\` (or reads fail with the right filename) | `.env` didn't load → relative-default fallback. | Run from `backend/`; confirm `backend/.env` exists with `DATA_DIR`/`OUTPUT_DIR`. Verify the `DATA_DIR`/`OUTPUT_DIR` lines the CLI prints are the absolute paths you expect. |
| `ERROR building config` mentioning the target | Target column not found, has <2 classes, or is also listed in `--features`. | Re-run `--inspect` to confirm the column name and class count; remove the target from any explicit `--features`. |
| One model row shows `status=failed` but the run finished | A single algorithm hit a library edge case (e.g. a degenerate split). By design this never aborts the run. | The error string is in that row's `error` column in `metrics_comparison.csv` (and the `! <model> failed:` line in the console). Other models still trained and all artifacts were written. |
| A run "succeeds" but a chart is a plain labelled placeholder | A degenerate case for that plot, not a failure. | Expected: `plot5` (calibration) is binary-only → placeholder on multiclass; `plot3` is a placeholder when no model exposes importances (e.g. only SVM/NaiveBayes). |
| `--problem-type` was wrong / suspiciously perfect scores | Wrong target or a leaking feature. | See §4 "How to read the metrics" — check `plot4` and `run_profile.json` `active_features`. |

To capture the full traceback for a hard failure, run with logging enabled:

```powershell
$env:PYTHONWARNINGS="default"; python -m classifyos.cli --file <key> --target <col>
```

The CLI prints readable `ERROR ...` lines (not raw tracebacks) and exits non-zero
(`2` for inspect/config errors, `1` for a run failure).

---

## 7. Hyperparameter tuning (optional, Optuna)

Tuning is **OFF by default.** When enabled, ClassifyOS runs an Optuna study per model
*before* fitting it, searching for better hyperparameters and using the best set for the
final fit. It wraps around the existing models — a non-tuned run is completely unchanged.

### Enable it from the CLI

```powershell
python -m classifyos.cli --file policy_lapse.csv --target will_lapse `
    --algos LR,RF,XGB --tune --tune-models XGB --trials 40 --timeout 300
```

### Flags

| Flag | Meaning | Default |
|---|---|---|
| `--tune` | Turn tuning ON. | OFF |
| `--tune-models` | Comma-separated models to tune (names/aliases). Empty → all. | all algorithms in the run |
| `--tune-metric` | Metric to maximise (`f1_weighted`, `roc_auc`, `mcc`, `pr_auc`, `accuracy`, `log_loss`, …). | `f1_weighted` |
| `--trials` | Optuna trials per model. | `30` |
| `--timeout` | Per-model wall-clock cap, in seconds (hard ceiling). | `600` |
| `--tune-cv-folds` | CV folds used to score each trial within the train split. | `3` |

The same dials are settable programmatically via the `tuning` config sub-dict (`enabled`,
`models`, `metric`, `cv`, `cv_folds`, `n_trials`, `timeout_seconds`,
`search_space_overrides`). `search_space_overrides` lets you narrow a model's bounds, e.g.
`{"XGBoost": {"max_depth": {"low": 3, "high": 6}}}`.

### How it's scored (no leakage)

Every trial is scored **inside the training split only** — k-fold CV (default) or a single
train-internal validation split (`cv=False`). The **test set is never seen during tuning.**
Class balancing (SMOTE) is *not* applied inside the CV folds — that would leak synthetic
minority rows across folds; tuning runs on the pre-balance train folds and balancing is
applied only to the final fit.

### Cost — tuning multiplies fits

Each tuned model costs roughly **`n_trials × cv_folds` model fits** before the final fit.
With the defaults (30 trials × 3 folds) that is ~90 fits *per tuned model*. Plan accordingly:

- **Tree models (XGBoost, LightGBM, RandomForest) benefit most** — they get rich search spaces.
- **SVM is slow** — its calibrated wrapper re-runs internal CV on every trial. Scope it with
  `--tune-models` and a small `--trials`/`--timeout`; don't hand it a large budget.
- **NaiveBayes rarely moves** — only `var_smoothing` to tune; usually not worth it.
- The per-model `--timeout` is a **hard ceiling**: a study stops at the timeout OR the trial
  cap, whichever comes first, so a tuning run can never go unbounded (default 600s/model).
  Set `timeout_seconds=None` in config only when you have scoped the run with a short
  `--tune-models` list.

### What's recorded

`run_profile.json` gains a `tuning` block — the audit trail: `enabled`, `metric`, `cv`,
`cv_folds`, `n_trials`, `timeout_seconds`, the list of `tuned_models`, and the `best_params`
found per model. The CLI also prints a `=== tuned hyperparameters ===` block after the
metrics summary.

### Worked example

```powershell
python -m classifyos.cli --file risk_tier.csv --target risk_tier `
    --problem-type multiclass --algos LR,RF,XGB --tune --tune-models XGB `
    --tune-metric f1_weighted --trials 25 --tune-cv-folds 3
```

Tunes only XGBoost (25 trials, 3-fold CV, maximising F1-weighted) and leaves LR and RF on
their defaults; the best XGBoost params land in `run_profile.json` under
`tuning.best_params` and are used for XGBoost's final fit.
