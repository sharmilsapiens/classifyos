# ClassifyOS API Contract

> **STATUS: 🔒 LOCKED (Phase 8).** The `POST /api/v1/run` response schema below is frozen.
> The Phase 9 React frontend is generated against it; it must not change silently. Additive
> changes bump `schema_version` (`1.0` → `1.1`); `1.0` is never mutated in place.
> See CLAUDE.md → "API contract is locked after Phase 8."
>
> **`1.1` (additive, current default).** Adds one new **optional** block — `result.tuning` —
> carrying the per-model tuned hyperparameters when Optuna tuning was on. It is `null`/absent
> when tuning was OFF (or produced no tuned params), so a non-tuning run is byte-identical to
> `1.0`. No existing `1.0` field was renamed, retyped, or removed. The response envelope now
> reports `"schema_version": "1.1"`. Old clients ignore the new field; this is the first
> version bump of the locked contract.

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
| `POST` | `/api/v1/upload` | Multipart upload of a CSV/Excel/Parquet dataset → stores it under `DATA_DIR/uploads/` via the StorageAdapter and returns the `inspect_file` profile + `server_path`. |
| `POST` | `/api/v1/run` | Execute the full pipeline (`ModelRunner`) → the locked envelope below. |
| `POST` | `/api/v1/explain` | Single-row SHAP. **v1.0: structured stub** (no model persistence; deferred to v2.0). |
| `GET`  | `/api/v1/outputs` | List output artifacts → `[{name, suffix, size_bytes}]`. |
| `GET`  | `/api/v1/outputs/{name}` | Stream one artifact (CSV/PNG) — traversal-guarded by the StorageAdapter. |

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
  "missing_strategy": "median",
  "encoding_method": "onehot",
  "scaling_method": "standard",
  "outlier_method": "iqr",
  "high_cardinality_threshold": 20,
  "threshold": 0.5,
  "calibrate_probs": true,
  "random_state": 42,
  "feature_engineering": { "enabled": true, "polynomial": false, "ratios": true,
                           "binning": true, "max_poly_features": 8 },
  "interaction_features": { "enabled": true, "interaction_pairs": {},
                            "default_interactions": ["multiply"],
                            "drop_original_if_interacted": false,
                            "max_auto_pairs": 10, "fill_method": "zero" },
  "tuning": { "enabled": false, "models": [], "metric": "f1_weighted", "cv": true,
              "cv_folds": 3, "n_trials": 30, "timeout_seconds": 600,
              "search_space_overrides": {} },
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
        "accuracy": 0.0, "f1_weighted": 0.0, "f1_macro": 0.0,
        "precision_weighted": 0.0, "recall_weighted": 0.0,
        "roc_auc": 0.0, "pr_auc": 0.0, "log_loss": 0.0, "mcc": 0.0,
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
    "artifacts": [                 // the 11 output files; PNGs fetched on demand
      {"name": "plot1_confusion_matrix.png", "suffix": ".png", "size_bytes": 0}
    ],
    "tuning": {                    // NEW in 1.1 (additive); null/absent when tuning was OFF
      "enabled": true,
      "metric": "f1_weighted",
      "cv": true,
      "cv_folds": 3,
      "n_trials": 30,
      "timeout_seconds": 600,      // may be null (the per-model cap opt-out)
      "tuned_models": ["XGBoost"], // models that produced tuned params
      "best_params": {             // per-model chosen hyperparameters (heterogeneous values)
        "XGBoost": {"learning_rate": 0.07, "max_depth": 6, "gamma": 1.2}
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

### Execution model (limitation)

`POST /api/v1/run` is **synchronous**: it runs the pipeline on a worker thread
(`run_in_threadpool`, so the event loop stays responsive) and returns the full result in one
response. A long run can exceed a reverse-proxy/gateway timeout. A background-job path
(submit → poll → fetch) is deferred to **v1.5** (recorded in plan_tweak).

---

_Locked at Phase 8 sign-off. Any change to `schema_version: "1.0"` must be additive._
_`1.1` (additive): added the optional `result.tuning` block; all `1.0` fields are unchanged._
