# ClassifyOS API Contract

> **STATUS: 🔒 LOCKED (Phase 8).** The `POST /api/v1/run` response schema below is frozen.
> The Phase 9 React frontend is generated against it; it must not change silently. Additive
> changes bump `schema_version` (`1.0` → `1.1`); `1.0` is never mutated in place.
> See CLAUDE.md → "API contract is locked after Phase 8."
>
> **`1.1` (additive).** Adds one new **optional** block — `result.tuning` —
> carrying the per-model tuned hyperparameters when Optuna tuning was on. It is `null`/absent
> when tuning was OFF (or produced no tuned params), so a non-tuning run is byte-identical to
> `1.0`. No existing `1.0` field was renamed, retyped, or removed. Old clients ignore the new
> field; this was the first version bump of the locked contract.
>
> **`1.2` (additive).** Adds one new **optional** object to each
> `result.models[]` row — `train` — carrying the same headline metrics computed on the
> **pre-balance TRAIN split**, so the dashboard can show the overfit gap (`test − train`).
> No `1.0`/`1.1` field was renamed, retyped, or removed. Old clients ignore the new field.
>
> **`1.3` (additive).** Adds one new **optional** block — `result.feature_importance` —
> carrying each model's **native (built-in) post-training** feature importance (tree impurity/gain or
> `|coef|`), keyed by model name. Models that expose none (RBF-SVM, GaussianNB) are omitted; the whole
> block is `null`/absent when no model exposes any, so an SVM/NB-only run is byte-identical to earlier
> schemas. This is **model-derived and post-training** — distinct from `result.feature_impact`, the
> pre-training statistical screen of raw features. No `1.0`/`1.1`/`1.2` field was renamed, retyped, or
> removed. Old clients ignore the new field.
>
> **`1.4` (additive).** Adds one new **optional** block — `result.permutation_importance` —
> carrying each model's **permutation** importance (the drop in F1-weighted on the held-out test split when
> each feature is shuffled), keyed by model name. Unlike `feature_importance` this is **model-agnostic** (it
> only needs `predict`), so it is present for **every** model — including the RBF-SVM and GaussianNB that
> expose no native importance. The block is `null`/absent when it could not be computed for any model. No
> `1.0`–`1.3` field was renamed, retyped, or removed. Old clients ignore the new field.
>
> **`1.5` (additive).** Adds two **optional** fields to each `result.models[]` row —
> `decision_threshold` and `calibrated` — reporting the **decision policy** applied to that model.
> `decision_threshold` is the effective positive-class operating threshold for a **binary** problem (the
> tuned best threshold, the analyst's fixed value, or `0.5` for the default argmax); it is `null` for
> multiclass/multilabel (no single scalar cut) and for failed models. `calibrated` is whether the model's
> probabilities are calibrated. These are driven by the request-side `threshold_mode` (`"default"` |
> `"fixed"` | `"tuned"`), `threshold`, `threshold_metric`, and `calibrate_probs` fields. No `1.0`–`1.4`
> field was renamed, retyped, or removed. The response envelope now reports `"schema_version": "1.5"`. Old
> clients ignore the new fields.
>
> **`1.10` (additive, current default).** Adds the **MLflow read-path endpoints** (Interim 2a):
> `GET /api/v1/runs` (list past runs) and `GET /api/v1/runs/{run_id}` (reload one). The `POST /api/v1/run`
> request/response envelope is **byte-identical to `1.9`** — nothing in it changed. This is what finally
> makes results survive a browser refresh and a server restart: a run logged to MLflow (opt-in
> `mlflow.enabled`) now also persists its rendered `/run` envelope as a run artifact, so `GET /runs/{run_id}`
> can return it verbatim and the dashboard reloads it into the existing result pages. The version marker
> moves so the contract doc's advance is recorded (locked-contract rule). The tracking store is a
> **server-side** concern (a local `./mlruns` by default, or the `MLFLOW_TRACKING_URI` target — a local
> Postgres backend store in Interim 2a); see the endpoint docs below. No `1.0`–`1.9` field was renamed,
> retyped, or removed; the response envelope now reports `"schema_version": "1.10"`.
>
> **`1.9` (additive).** Adds one new **optional** block — `result.mlflow` —
> a pointer to where the run was logged in **MLflow** (Databricks integration Phase A): `run_id`,
> `experiment_id`, `tracking_uri`, and `models` (a `{model_name: model_uri}` map, each loadable via
> `mlflow.<flavor>.load_model`). It is `null` unless the request-side opt-in `mlflow.enabled` was `true`
> **and** logging succeeded (MLflow is logged AFTER training — params, per-model headline test metrics, the
> artifact files, and one saved model per fitted algorithm); absent/broken MLflow degrades to `null`, so a
> run stays valid either way. No `1.0`–`1.8` field was renamed, retyped, or removed. The response envelope
> now reports `"schema_version": "1.9"`. Old clients ignore the new field.
>
> **`1.8` (additive).** Adds one new field —
> `result.explanations[model].rows[].feature_values` — a `{feature: value}` map giving each contributed
> feature's **original (raw) value**, keyed identically to `contributions`, so a client can render the
> waterfall as `feature = value` (the reason-code convention). A one-hot `col_cat` feature resolves to its
> source column's raw category; a derived/interaction feature with no raw source is `null`. It is present
> whenever `result.explanations` is (it is **not** gated on the LLM narrative flag). No `1.0`–`1.7` field was
> renamed, retyped, or removed. The response envelope now reports `"schema_version": "1.8"`. Old clients
> ignore the new field.
>
> **`1.7` (additive).** Adds one new **optional** field —
> `result.explanations[model].rows[].narrative` — an LLM-authored plain-language reason-code paragraph for
> that row (Azure OpenAI), grounded in the same SHAP contributions. It is `null` unless the request-side
> opt-in `explainability.llm_narratives` was `true` **and** the `AZURE_OPEN_AI_*` credentials were configured
> on the server; absent credentials or a failed call degrade to SHAP-only, so a run stays valid either way.
> No `1.0`–`1.6` field was renamed, retyped, or removed. The response envelope now reports
> `"schema_version": "1.7"`. Old clients ignore the new field.
>
> **`1.6` (additive).** Adds one new **optional** block — `result.explanations` —
> carrying **per-row SHAP** explanations keyed by model name (**local** explainability: why the model
> predicted what it did for individual held-out test rows). Each model entry is `{method, rows[]}` where a
> row is `{sample_index, explained_class, base_value, prediction, contributions}` and
> `base_value + Σ contributions == prediction` (the SHAP-additive waterfall). It covers **all six** models
> (`shap.TreeExplainer` for the tree models, `shap.KernelExplainer` for LogisticRegression/SVM/NaiveBayes).
> Computed **during the run** (no model persistence needed), gated by the request-side opt-in
> `explainability` block; the whole block is `null`/absent when explainability was OFF (the default), so a
> run without it is byte-identical to earlier schemas. Binary + multiclass only (multilabel omitted). No
> `1.0`–`1.5` field was renamed, retyped, or removed. The response envelope now reports
> `"schema_version": "1.6"`. Old clients ignore the new field.

## Conventions

- All routes are prefixed with **`/api/v1/`** (CLAUDE.md mandate; supersedes the scope doc's
  bare `/api/...` table — see plan_tweak).
- CORS uses an env-configured allowlist (`CORS_ORIGINS`, comma-separated) — never `["*"]`
  outside an explicit local-dev marker (`CLASSIFYOS_CORS_DEV`).
- Request bodies and responses are JSON. File uploads use `multipart/form-data`.
- `RunConfig` (Pydantic v2, `backend/api/models.py`) is the canonical request model for a run.
- All values are JSON-safe: numpy types are converted to plain Python, and `NaN`/`Infinity`
  are emitted as `null` (never invalid JSON).

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/api/v1/health` | Liveness check → `{status, service, version}`. |
| `POST` | `/api/v1/upload` | Multipart upload of a CSV/Excel/Parquet dataset → stores it under `DATA_DIR/uploads/` via the StorageAdapter and returns the `inspect_file` profile + `server_path` + the additive Data-Profile blocks (`column_profiles`, `correlation`) — see below. |
| `POST` | `/api/v1/run` | Execute the full pipeline (`ModelRunner`) → the locked envelope below. |
| `GET`  | `/api/v1/runs` | **(1.10)** List past MLflow-logged runs (most-recent first) → `{schema_version, tracking_uri, runs[]}`. See below. |
| `GET`  | `/api/v1/runs/{run_id}` | **(1.10)** Reload ONE past run → the same locked `/run` envelope it was rendered with (byte-identical). `404` if the run is unknown or has no persisted snapshot; `503` if the tracking store is unreachable. |
| `POST` | `/api/v1/explain` | On-demand single-row SHAP — **documented stub** (stateless; would need model persistence). Per-row SHAP is instead produced during a run: set `explainability.enabled` on `/run` and read `result.explanations` (schema 1.6). |
| `GET`  | `/api/v1/outputs` | List output artifacts → `[{name, suffix, size_bytes}]`. |
| `GET`  | `/api/v1/outputs/{name}` | Stream one artifact (CSV/PNG) — traversal-guarded by the StorageAdapter. |

## `POST /api/v1/upload`

Returns the `inspect_file` profile (`columns`, `dtypes`, the
numeric/categorical/binary/datetime column groups, `n_rows`, `n_missing`, a 5-row `sample`,
and — when `target` is given — `class_distribution` + `suggested_problem_type`), plus
`server_path` (the storage key to echo back to `/run` as `input_file`).

**Data-Profile blocks (additive).** The upload response also carries per-column exploratory
statistics for the dashboard's **Data Profile** view, computed once on the frame `inspect_file`
already loaded (no second read; fits nothing, so no leakage surface — these influence only what
is *displayed*). This is the `/upload`/inspect payload, **not** the locked `/run` envelope, so it
carries **no `schema_version`** and these keys are purely additive.

```jsonc
{
  // ...the existing inspect keys + server_path...
  "profile_sampled": false,       // true → histograms/correlation used a row sample (large file)
  "n_rows_profiled": 3000,        // rows used for the heavy (histogram/correlation) work
  "column_profiles": [            // one entry per column; dtype_group picks which block is filled
    { "name": "age", "dtype_group": "numeric",        // numeric | categorical | datetime
      "n_missing": 90, "missing_pct": 3.0, "n_unique": 49,
      "flags": [],                                    // degenerate-column advisories (see below); [] = clean
      "stats": { "count": 2910, "mean": 45.0, "std": 14.2, "min": 21.0,
                 "p25": 33.0, "median": 45.0, "p75": 57.0, "max": 69.0,
                 "mode": 66.0, "skew": 0.01 },         // any field null when undefined/non-finite
      "histogram": { "bin_edges": [21.0, 23.4, "..."], "counts": [170, 113, "..."] } },
    { "name": "region", "dtype_group": "categorical", // numeric binary 0/1 cols use this too
      "n_missing": 0, "missing_pct": 0.0, "n_unique": 5,
      "top_values": [ { "value": "West", "count": 812, "pct": 27.1 } ],  // top_k, then →
      "other_count": 0, "truncated": false },          // truncated=true → only top_k shown
    { "name": "policy_start_date", "dtype_group": "datetime",
      "n_missing": 0, "missing_pct": 0.0, "n_unique": 1200,
      "min": "2019-01-02T00:00:00", "max": "2023-12-30T00:00:00" }
  ],
  "correlation": {                // Pearson over numeric cols; null when <2 numeric cols
    "columns": ["age", "annual_premium"],
    "matrix": [[1.0, 0.12], [0.12, 1.0]],  // NaN cells (e.g. a constant column) → null
    "truncated": false            // true → capped to the first N numeric columns
  }
}
```

Each `column_profiles[]` entry carries a `flags` array (additive) — degenerate-column
advisories for the Data Profile screen, empty for ordinary columns. Values:

* `"constant"` — a single distinct value (or an all-missing column). Zero variance, so it
  carries no predictive signal (its std/skew and correlation cells are `null`); a candidate
  to drop before training.
* `"identifier"` — nearly every row is distinct (`n_unique / n_rows >= 0.99`). Looks like an
  ID or free-text key: high cardinality that won't generalise and is leakage-bait. Uses the
  same threshold as `feature_impact`'s `id_like`, so the two screens agree.

## `POST /api/v1/run`

### Request — `RunConfig`

The web-facing config. Three fields are **required** (missing/empty → HTTP 422):
`input_file`, `target`, `feature_cols`. All others default to the engine's own defaults.
`RunConfig.to_engine_config()` forwards everything to `build_config()`, which is the single
authoritative validator (enum checks, `test_size` range, target-not-in-features, …); a
problem there is returned as HTTP 422.

```jsonc
{
  "input_file": "policy_lapse.csv",   // required — storage key (e.g. an /upload server_path)
  "target": "will_lapse",             // required
  "feature_cols": ["age", "..."],     // required — at least one
  "problem_type": "binary",           // binary | multiclass | multilabel
  "test_size": 0.2,
  "stratify": true,
  "time_split_col": null,
  "algorithms": ["LogisticRegression", "RandomForest", "XGBoost"],
  "class_balance": "smote",           // smote | undersample | class_weight | none
  "missing_strategy": "median",       // LEGACY GLOBAL default (back-compat); per-type keys below override it
  "missing_strategy_numeric": null,   // null → inherit global. else: median|mean|mode|ffill|bfill|knn|iterative|drop
  "missing_strategy_categorical": null, // null → inherit (mode if global is numeric-only). else: mode|ffill|bfill|drop
  "missing_strategy_by_column": {},   // optional per-column overrides {col: strategy}; unlisted cols use the per-type default above
                                      //   value ∈ median|mean|mode|ffill|bfill|knn|iterative|drop (numeric-only strategy on a categorical col is coerced to that type's default)
  "encoding_method": "onehot",
  "scaling_method": "standard",
  "outlier_method": "iqr",
  "high_cardinality_threshold": 20,
  "threshold": 0.5,                   // positive-class cutoff used when threshold_mode == "fixed" (binary)
  "threshold_mode": "default",        // default (0.5 argmax) | fixed | tuned   (binary only)
  "threshold_metric": "f1",           // metric a "tuned" threshold maximises (binary): f1|f1_weighted|
                                       // f1_macro|balanced_accuracy|accuracy|precision|recall
  "calibrate_probs": true,            // calibrate probabilities (binary+multiclass; SVM already calibrated)
  "random_state": 42,
  "permutation_metric": "f1_weighted",  // metric the post-training permutation importance scores the drop in;
                                         // f1_weighted|f1_macro|accuracy|precision_weighted|precision_macro|
                                         // recall_weighted|recall_macro|roc_auc|pr_auc|mcc|log_loss
  "feature_engineering": { "enabled": true, "polynomial": false, "ratios": true,
                           "binning": true, "max_poly_features": 8 },
  "interaction_features": { "enabled": true, "interaction_pairs": {},
                            "default_interactions": ["multiply"],
                            "drop_original_if_interacted": false,
                            "max_auto_pairs": 10, "fill_method": "zero" },
  "tuning": { "enabled": false, "models": [], "metric": "f1_weighted", "cv": true,
              "cv_folds": 3, "n_trials": 30, "timeout_seconds": null,  // null = no per-model cap (default); n_trials bounds the study
              "search_space_overrides": {} },  // per-model bound/choice overrides, e.g. {"XGBoost": {"max_depth": {"low": 3, "high": 6}}}
  "explainability": { "enabled": false, "sample_rows": 20, "background_size": 100,
                      "llm_narratives": false,          // adds an Azure OpenAI reason-code paragraph per row (1.7; needs AZURE_OPEN_AI_* env)
                      "context_mode": "both",           // given | derived | both — how dataset context reaches the narrator (request-only)
                      "dataset_context": "",            // free-text: what the data/target mean (used when context_mode != "derived")
                      "column_context": {} },           // {column: note} per-column meaning (used when context_mode != "derived"); OPTIONAL; OFF → block absent
  "mlflow": { "enabled": false,                 // OFF by default; ON → log the run to MLflow + a saved model per algorithm (schema 1.9 result.mlflow)
              "experiment": "classifyos",       // MLflow experiment name to log under
              "run_name": null },               // optional run name (null → MLflow auto-generates); tracking store is server-side via MLFLOW_TRACKING_URI

  "user_features": [            // OPTIONAL; [] / omitted → no user features (unchanged)
    // STRUCTURED specs only — NO free-text formula, nothing is ever eval()'d. Each spec
    // applies a KNOWN op (from a fixed allowlist) to KNOWN existing column(s). An unknown
    // type/op, or a two-column type missing col_b, is rejected with HTTP 422 at the boundary.
    { "name": "premium_per_sum", "type": "numeric",       // numeric | datetime_diff | single
      "op": "divide",                                     // numeric: add|subtract|multiply|divide|ratio
      "col_a": "annual_premium", "col_b": "sum_assured" },
    { "name": "duration_days", "type": "datetime_diff",   // two datetime cols → numeric duration
      "op": "subtract", "col_a": "end_date", "col_b": "start_date",
      "unit": "days" },                                   // seconds|minutes|hours|days (default days)
    { "name": "start_year", "type": "single",             // one column; col_b must be omitted
      "op": "year",                                       // single: log|abs|bin | year|month|day|dayofweek|hour
      "col_a": "policy_start_date" }
  ]
}
```

**`user_features` (request-side only; response schema UNCHANGED).** The created columns are
real engineered columns, so they already surface in the existing `result.run.active_features`
list (and, when ranked, `result.feature_impact`) — there is no new response field and no
version bump. The API performs a fast-fail allowlist check (unknown `type`/`op`, or a
two-column type without `col_b` → 422), mirroring the `USER_FEATURE_*` allowlists in the
engine's `config.py`; the engine's `build_config` remains the authoritative validator.
Column existence/type are validated by the engine at fit time (a spec that references a
missing/wrong-typed column is skipped and logged — it never aborts the run).

### Response — LOCKED envelope (`schema_version` `1.0`)

```jsonc
{
  "status": "ok",                  // "ok" | "error"
  "schema_version": "1.0",
  "result": {                      // null when status == "error"
    "run": {                       // curated run metadata (subset of run_profile.json)
      "target": "...",
      "problem_type": "binary|multiclass|multilabel",
      "features": ["..."],         // configured
      "active_features": ["..."],  // final engineered cols (incl. interaction cols)
      "interaction_cols": ["..."], // derived: active_features matching _x_/_div_/_minus_
      "class_distribution": {"...": 0},
      "n_rows": 0, "n_train": 0, "n_test": 0,
      "class_balance": "...", "class_weight": {"...": 0.0},
      "models_succeeded": 0,       // COUNT of models that trained ok
      "timestamp": "UTC ISO-8601"
    },
    "models": [                    // LIST (renders with .map); includes failed rows
      {
        "name": "RandomForest",
        "status": "ok",            // "ok" | "failed"
        // headline metrics = HELD-OUT TEST split (1.0; unchanged)
        "accuracy": 0.0, "f1_weighted": 0.0, "f1_macro": 0.0,
        "precision_weighted": 0.0, "recall_weighted": 0.0,
        "roc_auc": 0.0, "pr_auc": 0.0, "log_loss": 0.0, "mcc": 0.0,
        "train": {                 // NEW in 1.2 (additive): same metrics on the PRE-balance TRAIN split
          "accuracy": 0.0, "f1_weighted": 0.0, "f1_macro": 0.0,
          "precision_weighted": 0.0, "recall_weighted": 0.0,
          "roc_auc": 0.0, "pr_auc": 0.0, "log_loss": 0.0, "mcc": 0.0
          // all null for a failed model (or if train eval was unavailable); block always present
        },
        "decision_threshold": 0.5, // NEW in 1.5 (additive): effective binary operating threshold
                                   //   (tuned best / fixed value / 0.5 default); null for
                                   //   multiclass/multilabel and failed models
        "calibrated": true,        // NEW in 1.5 (additive): whether probabilities are calibrated
        "error": null              // string when status == "failed"
      }
    ],
    "predictions": {               // SAMPLED (first 100 rows per model); full table via artifacts CSV
      "sample_rows": [ {"model": "...", "sample_index": 0, "actual": "...",
                        "predicted": "...", "confidence": 0.0, "correct_flag": true,
                        "probabilities": {"class_a": 0.0, "class_b": 0.0}} ],
      "sampled": true, "rows_returned": 0, "rows_total": 0,
      "full_csv": "classification_results.csv"   // fetch via /outputs/{name}
    },
    "confusion_matrix": {          // per successful model, FULL test set
      "RandomForest": {"labels": ["..."], "matrix": [[0,0],[0,0]]}
    },
    "class_report": {              // per class (and avg rows) per successful model
      "RandomForest": [ {"class": "...", "precision": 0.0, "recall": 0.0,
                         "f1": 0.0, "support": 0} ]
    },
    "feature_impact": [            // ranked; preserves id_like leakage flag
      {"feature": "...", "dtype_group": "...", "anova_f": 0.0, "anova_p": 0.0,
       "mutual_info": 0.0, "point_biserial": null, "corr_ratio": null,
       "composite_score": 0.0, "id_like": false, "rank": 1}
    ],
    "curves": {                    // FULL test set, via compute_curve_points
      "RandomForest": {
        "roc": {"class_a": {"fpr": [0.0], "tpr": [0.0], "thresholds": [0.0], "auc": 0.0}},
        "pr":  {"class_a": {"precision": [0.0], "recall": [0.0], "thresholds": [0.0], "ap": 0.0}}
        // binary: single entry keyed by the positive (lexicographically-last) class.
        // multiclass: one-vs-rest entry per class (ROC and PR both provided).
      }
    },
    "artifacts": [                 // output files present in OUTPUT_DIR; PNGs fetched on demand
      {"name": "plot1_confusion_matrix.png", "suffix": ".png", "size_bytes": 0}
    ],
    "feature_importance": {        // NEW in 1.3 (additive); null/absent when no model exposes any
      "RandomForest": [            // per model; omitted for models with no native importance (SVM, NaiveBayes)
        {"feature": "...", "importance": 0.0, "rank": 1}   // ranked desc WITHIN the model
      ]
    },
    "permutation_importance": {    // NEW in 1.4 (additive); null/absent when none could be computed
      "SVM": [                     // model-AGNOSTIC: present for EVERY model, incl. SVM / NaiveBayes
        {"feature": "...", "importance": 0.0, "rank": 1}   // F1-weighted drop, ranked desc WITHIN the model
      ]
    },
    "tuning": {                    // NEW in 1.1 (additive); null/absent when tuning was OFF
      "enabled": true,
      "metric": "f1_weighted",
      "cv": true,
      "cv_folds": 3,
      "n_trials": 30,
      "timeout_seconds": null,     // null = no per-model cap (the default); a number re-imposes one
      "tuned_models": ["XGBoost"], // models that produced tuned params
      "best_params": {             // per-model chosen hyperparameters (heterogeneous values)
        "XGBoost": {"learning_rate": 0.07, "max_depth": 6, "gamma": 1.2}
      }
    },
    "explanations": {              // NEW in 1.6 (additive); null/absent when explainability was OFF (default)
      "RandomForest": {            // per model; ALL six covered (tree → TreeExplainer, else KernelExplainer)
        "method": "shap.TreeExplainer",
        "rows": [                  // one per explained held-out test row (first `sample_rows` rows)
          {
            "sample_index": 0,     // 0-based row position in the test set
            "explained_class": "1",// positive class (binary) / predicted class (multiclass)
            "base_value": 0.36,    // model's average output — the waterfall's start
            "prediction": 0.87,    // == base_value + Σ contributions (SHAP-additive)
            "contributions": {"num_late_payments": 0.40, "policy_tenure_years": 0.11},  // signed per-feature push
            "feature_values": {"num_late_payments": "3", "policy_tenure_years": "8.0"},  // NEW in 1.8 (additive); raw value per feature (null for derived/interaction)
            "narrative": "The model flags this policy as high lapse risk chiefly because of a high number of late payments, which pushed the prediction up, only partly offset by a longer policy tenure."  // NEW in 1.7 (additive); null unless llm_narratives on AND creds configured
          }
        ]
      }
    },
    "mlflow": {                    // NEW in 1.9 (additive); null/absent when mlflow logging was OFF (default) or failed
      "run_id": "a427600d82104747a49ec8bbabdfe4e3",
      "experiment_id": "326595411761779270",
      "tracking_uri": "file:///C:/Projects/classifyos/backend/mlruns",  // local ./mlruns by default; a tracking server when MLFLOW_TRACKING_URI is set
      "models": {                  // per fitted algorithm → its logged-model URI (mlflow.<flavor>.load_model)
        "LogisticRegression": "models:/m-a99731321d5844418f7d5a21f98f3dcd",
        "XGBoost": "models:/m-1b2c3d4e5f60718293a4b5c6d7e8f900"
      }
    }
  },
  "error": null                    // top-level string when status == "error"
}
```

### Notes (part of the contract)

- The envelope + `schema_version` are the forward-compat seam; bump to `1.1` for additive
  changes, never silently mutate `1.0`.
- `models` is intentionally a **list** (frontend `.map`), not a dict; it includes failed-algorithm
  rows (`status="failed"`, `error` set) so a bad model is visible, not dropped.
- **`models[].train` (1.2, additive).** The top-level per-model metrics are the **held-out TEST**
  split. `train` mirrors the headline scalars on the **pre-balance TRAIN** split — real rows at
  the natural class distribution, **not** the SMOTE/undersampled matrix the model was fit on — so
  `test − train` is a clean overfit gap (a large positive gap ⇒ memorization), not one distorted
  by the balancing-induced distribution shift. There is no leakage surface: the model already
  trained on these rows; this only *reports* on them. The block is always present; every value is
  `null` for a failed model (or if train evaluation was unavailable). Confusion matrices, per-class
  reports, and curves remain **test-only** — `train` carries headline scalars only.
- `predictions` is **sampled by design** (≤100 rows/model) for display; `curves` and
  `confusion_matrix` are always computed on the **full test set**. The full prediction table is
  `classification_results.csv`, fetched via `/outputs/{name}`.
- Curve points come from the sanctioned `classifyos.evaluation.curves.compute_curve_points`
  helper — the same source `plot2` draws from — and each curve is downsampled to ≤500 points.
- PNGs are referenced by **name only** — fetched via `/outputs/{name}`, never base64-inlined.
- Numeric values are JSON-safe: `NaN`/`Infinity`/undefined metrics are `null`.
- On `status: "error"`, `result` is `null` and a top-level `error` string is present (HTTP 400
  for known input failures such as a missing file; config-validation failures are HTTP 422).
- **`result.tuning` (1.1, additive, optional)** carries the per-model tuned hyperparameters and
  the tuning settings that produced them. It is `null`/absent when tuning was OFF (or every
  study produced nothing). `best_params` is `{model: {param: value}}` with heterogeneous values
  (float/int/str/bool); `tuned_models` lists the models that yielded tuned params. The block is
  copied verbatim from the engine's `run_profile.json` `tuning` block — the API adds no ML.
- **`result.feature_importance` (1.3, additive, optional)** carries each model's **native** feature
  importance, read post-training from the fitted estimator: `{model: [{feature, importance, rank}, …]}`,
  ranked descending **within** each model. The values are **model-dependent** (RF/XGBoost/LightGBM tree
  impurity/gain, LogisticRegression `|coef|`) and **not comparable across models**; importances are over
  the **engineered/active feature columns** (e.g. one-hot `region_North`), the same columns `plot3` draws.
  Models that expose no native importance (RBF-SVM, GaussianNB) are **omitted**; the whole block is
  `null`/absent when no model exposes any. This is the post-training counterpart to `feature_impact`
  (the pre-training raw-data screen) — they answer different questions and can disagree. Also written as
  `feature_importance_summary.csv`. No leakage surface: read from fitted-model internals, no test data,
  no refit. Pure plumbing — the engine already computed the values.
- **`result.permutation_importance` (1.4, additive, optional)** carries each model's **permutation**
  importance: `{model: [{feature, importance, rank}, …]}`, ranked descending **within** each model, where
  `importance` is the **drop in the configured metric on the held-out test split** when that feature's
  values are shuffled (averaged over repeats; may be slightly negative — shuffle noise). The metric is the
  request-side `permutation_metric` field (default `f1_weighted`; **request-only — no `schema_version`
  bump**, the response shape is unchanged). Because it only needs
  `predict`, it is **model-agnostic** — present for **every** model, including the RBF-SVM and GaussianNB
  that have no native importance — and is in one consistent unit, so it **is** comparable across models
  (unlike `feature_importance`). Over the **engineered/active feature columns**. A model whose measure
  could not be computed is **omitted**; the block is `null`/absent when none could. Also written as
  `permutation_importance_summary.csv`. [RISK] correlated features can both look unimportant (the model
  leans on the untouched twin). No leakage surface: read from held-out test predictions only — fits
  nothing, refits nothing, never mutates the test matrix. Pure plumbing — the engine already computed it.
- **`result.models[].decision_threshold` + `.calibrated` (1.5, additive, optional)** report the **decision
  policy** applied to each model. `decision_threshold` is the effective positive-class operating threshold
  for a **binary** problem — the tuned best threshold (`threshold_mode: "tuned"`, chosen by
  `TunedThresholdClassifierCV` on internal CV folds of TRAIN to maximise `threshold_metric`), the analyst's
  `threshold` (`"fixed"`), or `0.5` (`"default"` argmax). It is `null` for multiclass/multilabel (no single
  scalar cut) and for failed models. `calibrated` reflects `calibrate_probs` (probabilities calibrated via
  `CalibratedClassifierCV`, fit on TRAIN only — and always `true` for the SVM, which is intrinsically
  calibrated). [RISK] leakage — the tuned threshold and the calibrator are fit on TRAIN-only internal CV;
  the held-out test set never informs the operating point. These are driven by the request-side
  `threshold_mode`/`threshold`/`threshold_metric`/`calibrate_probs` fields.
- **`result.explanations` (1.6, additive, optional)** carries **per-row SHAP** explanations —
  `{model: {method, rows: [{sample_index, explained_class, base_value, prediction, contributions}, …]}}` —
  the **local** counterpart to the two importance blocks (why THIS prediction, not what matters overall).
  For each explained row `base_value + Σ contributions == prediction` (SHAP-additive; a waterfall from the
  model's average output to this row's predicted probability). `method` is `"shap.TreeExplainer"` for the
  tree models (explains the base estimator's probability) or `"shap.KernelExplainer"` for
  LogisticRegression/SVM/NaiveBayes (over the model's calibrated `predict_proba`) — so **all six** models are
  covered. `explained_class` is the positive class (binary) or predicted class (multiclass). Computed
  **during the run** while models are fitted in memory — no model persistence needed — for the first
  `sample_rows` held-out test rows of each model, gated by the request-side opt-in `explainability` block
  (default OFF). Binary + multiclass only; a model whose explainer failed (or multilabel) is **omitted**,
  and the whole block is `null`/absent when explainability was OFF or produced nothing. Also written as
  `explanations_summary.csv` (only when enabled). [RISK] leakage — the SHAP background is a TRAIN reference
  sample (never fitted on); explained rows are read-only test rows; nothing is refit. Pure plumbing — the
  engine already computed the values.
- **`result.explanations[model].rows[].feature_values` (1.8, additive)** is a `{feature: value}` map giving
  each contributed feature's **original (raw, pre-preprocessing) value**, keyed identically to
  `contributions`, so a client can render each waterfall step as `feature = value` (the reason-code
  convention). A one-hot `col_cat` feature resolves to its source column's raw category; a derived/interaction
  feature with no raw source is `null`. Present whenever `result.explanations` is — it is **not** gated on the
  LLM narrative flag. The `explanations_summary.csv` gains a `feature_value` column (empty when unresolved).
  Pure plumbing — resolved from the held-out test frame the engine already retains; no refit, no ML.
- **`result.explanations[model].rows[].narrative` (1.7, additive, optional)** is an LLM-authored
  plain-language reason-code paragraph for that row (Azure OpenAI chat), grounded in the same SHAP
  contributions plus the row's model-space feature values. Gated by the request-side opt-in
  `explainability.llm_narratives` (requires `explainability.enabled`) **and** the `AZURE_OPEN_AI_*` server
  credentials; it is `null` when narratives were OFF, credentials were absent, or the call failed — a
  report-only layer that degrades to SHAP-only and never aborts a run. The `explanations_summary.csv` gains a
  `narrative` column (empty when absent). No new ML — a presentation layer over the SHAP numbers.
  The narrative quality is shaped by three **request-only** `explainability` fields (no response/version
  change): `dataset_context` (free-text on the data/target), `column_context` (`{column: note}`), and
  `context_mode` (`given` | `derived` | `both`) — `derived`/`both` also feed the model engine-derived facts
  (column headers + a sample row + light stats + class base rates + the global feature ranking) and the row's
  ORIGINAL (un-scaled) values, so a narrative can cite `num_late_payments = 3` in business terms rather than a
  scaled float. [RISK] privacy — `derived`/`both` send sample data values to Azure OpenAI (opt-in).
- **`result.mlflow` (1.9, additive, optional)** is a pointer to where the run was logged in MLflow —
  `{run_id, experiment_id, tracking_uri, models}`, where `models` maps each fitted algorithm to its
  logged-model URI (loadable via `mlflow.<flavor>.load_model`). Gated by the request-side opt-in
  `mlflow.enabled`; logging happens AFTER training (params = the run config, metrics = each model's headline
  TEST scalars, artifacts = the CSVs/PNGs/`run_profile.json`, plus one flavor-native saved model per model —
  `mlflow.xgboost`/`mlflow.lightgbm`/`mlflow.sklearn`, each unwrapped to its base estimator). It is `null`
  when logging was OFF (the default) or failed — a report-only layer that never aborts a run. The tracking
  store is a **server-side** concern (a local `./mlruns` folder by default, or the `MLFLOW_TRACKING_URI`
  target — Postgres/Databricks later), NOT a request field. [RISK] leakage — logging reads nothing back into
  fit/transform; it serializes fitted models and copies written artifacts only.

## MLflow read-path — `GET /api/v1/runs`, `GET /api/v1/runs/{run_id}` (1.10, additive)

The persistence read-path (Interim 2a). Once a run is logged to MLflow (opt-in `mlflow.enabled`
on `/run`), it is recorded in MLflow's backend store — a local `./mlruns` by default, or a **local
Postgres** backend store when `MLFLOW_TRACKING_URI` points at one (`postgresql://…`; artifacts stay
a local folder via `_MLFLOW_SERVER_ARTIFACT_ROOT`). The store is a **server-side** concern — never a
request field. These GET endpoints expose that history so results survive a browser refresh and a
server restart. They are purely additive: the `/run` envelope is unchanged.

### `GET /api/v1/runs` — list past runs

Lists runs across the active MLflow experiments, most-recent first (capped, newest first). Each row
is derived from the run's MLflow metadata only (no artifact download).

```jsonc
{
  "schema_version": "1.10",
  "tracking_uri": "postgresql://…@localhost:5432/mlflow",  // the store the API read from
  "runs": [
    {
      "run_id": "c2ce5d32817b488d9c2797178a9fda36",
      "experiment_id": "1",
      "experiment_name": "classifyos",
      "run_name": "spirited-hog-42",       // MLflow run name (null if unset)
      "status": "FINISHED",                 // MLflow lifecycle: FINISHED | FAILED | RUNNING | …
      "start_time": "2026-07-08T18:16:30.472000+00:00",  // UTC ISO-8601 (null if unset)
      "end_time":   "2026-07-08T18:16:46.481000+00:00",
      "target": "will_lapse",               // from the logged (flattened-config) params
      "problem_type": "binary",
      "input_file": "policy_lapse.csv",
      "algorithms": ["LogisticRegression", "XGBoost"],  // from the <model>.<metric> metric keys
      "models_logged": 2,
      "best_metric": "f1_weighted",         // the metric summarised for the list
      "best_value": 0.71,                   // best f1_weighted across the run's models (null if none)
      "best_model": "XGBoost",
      "reloadable": true                    // true → GET /runs/{run_id} can return the full envelope
    }
  ]
}
```

`503` (with a `{detail}` message) if the tracking store cannot be reached/queried (e.g. Postgres is
down) — the dashboard shows that state rather than failing.

### `GET /api/v1/runs/{run_id}` — reload one run

Returns the **exact `/run` envelope** the run was rendered with (`{status, schema_version, result,
error}` — the locked shape documented above), so the dashboard drops it straight into the existing
result pages. This works because `/run` persists its rendered envelope as the run artifact
`api/run_response.json` (report-only; a failure there only means the run is not `reloadable`).

- `404` — unknown `run_id`, **or** a run with no persisted snapshot (e.g. one logged by the engine
  CLI rather than via `/run`; such runs still appear in `GET /runs` with `reloadable: false`).
- `503` — the tracking store is unreachable.

No leakage surface and no ML: these endpoints only read back what a completed run already logged.

### Execution model (limitation)

`POST /api/v1/run` is **synchronous**: it runs the pipeline on a worker thread
(`run_in_threadpool`, so the event loop stays responsive) and returns the full result in one
response. A long run can exceed a reverse-proxy/gateway timeout. A background-job path
(submit → poll → fetch) is deferred to **v1.5** (recorded in plan_tweak).

---

_Locked at Phase 8 sign-off. Any change to `schema_version: "1.0"` must be additive._
_`1.1` (additive): added the optional `result.tuning` block; all `1.0` fields are unchanged._
_`1.2` (additive): added the optional `result.models[].train` block (pre-balance train headline
metrics, for the overfit gap); all `1.0`/`1.1` fields are unchanged._
_`1.3` (additive): added the optional `result.feature_importance` block (native per-model
post-training importance); all `1.0`/`1.1`/`1.2` fields are unchanged._
_`1.4` (additive): added the optional `result.permutation_importance` block (model-agnostic per-model
permutation importance, covering all models); all `1.0`–`1.3` fields are unchanged._
_`1.5` (additive): added `result.models[].decision_threshold` + `.calibrated` (the per-model decision
policy — effective binary operating threshold + calibration status); all `1.0`–`1.4` fields are unchanged._
_`1.6` (additive): added the optional `result.explanations` block (per-row SHAP — local explainability,
covering all six models; opt-in via the request `explainability` block); all `1.0`–`1.5` fields are unchanged._
_`1.7` (additive): added the optional `result.explanations[model].rows[].narrative` field (LLM-authored
reason-code paragraph, Azure OpenAI; opt-in via the request `explainability.llm_narratives` + `AZURE_OPEN_AI_*`
server credentials); all `1.0`–`1.6` fields are unchanged._
_`1.8` (additive): added `result.explanations[model].rows[].feature_values` (each contributed feature's raw
value, keyed like `contributions`, for `feature = value` reason codes; present whenever `result.explanations`
is — not gated on the LLM flag); all `1.0`–`1.7` fields are unchanged._
_`1.9` (additive): added the optional `result.mlflow` block (run id + per-model saved-model URIs) reporting
where the run was logged in MLflow (opt-in `mlflow.enabled`); all `1.0`–`1.8` fields are unchanged._
_`1.10` (additive): added the MLflow read-path endpoints `GET /api/v1/runs` (list past runs) and
`GET /api/v1/runs/{run_id}` (reload one, byte-identical) — Interim 2a. The `POST /api/v1/run` envelope is
unchanged from `1.9`; the version marker moves to record the new endpoints (locked-contract rule)._
_2026-06-26 (default-value change only, **no schema/version change** — field shapes unchanged):
`tuning.timeout_seconds` now defaults to `null` (no per-model wall-clock cap; `n_trials` bounds
the study) rather than `600`. `tuning.search_space_overrides` (always present in `1.0`) is now
exercised by the UI — `{model: {param: {low, high}}}` for numeric bounds, `{model: {param: [choices]}}`
for categoricals; `{}` = engine defaults. See plan_tweak #43._
