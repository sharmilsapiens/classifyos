/* ════════════════════════════════════════════════════════════════════════
   buildPayload — assemble a contract-valid RunConfig from the Configure form.

   The Configuration page keeps its inputs in a flat `ConfigFormState` (easy to
   bind to form controls). `buildPayload` is the ONE pure function that turns
   that flat state into the nested `RunConfig` the API expects. Keeping it pure
   (no React, no fetch) is what lets us unit-test it directly.
   ════════════════════════════════════════════════════════════════════════ */

import type { ClassBalance, ProblemType, RunConfig, UserFeatureSpec } from "@/api/types"
import type { SearchSpaceOverrides } from "@/lib/searchSpaces"

/** Flat, form-friendly mirror of RunConfig (nested groups flattened with fe_ / ix_ / tune_ prefixes). */
export interface ConfigFormState {
  input_file: string
  target: string
  feature_cols: string[]
  problem_type: ProblemType
  test_size: number
  stratify: boolean
  time_split_col: string | null
  algorithms: string[]
  class_balance: ClassBalance
  /** Legacy global default; kept for back-compat (the two per-type keys drive behaviour). */
  missing_strategy: string
  /** Missing-value strategy for numeric columns (median/mean/mode/ffill/bfill/knn/iterative/drop). */
  missing_strategy_numeric: string
  /** Missing-value strategy for non-numeric columns (mode/ffill/bfill/drop). */
  missing_strategy_categorical: string
  /** Optional per-column overrides {column: strategy}; unlisted columns use the per-type default. */
  missing_strategy_by_column: Record<string, string>
  encoding_method: string
  scaling_method: string
  outlier_method: string
  high_cardinality_threshold: number
  /** Positive-class cutoff used when threshold_mode === "fixed" (binary only). */
  threshold: number
  /** Decision-threshold mode (binary): "default" | "fixed" | "tuned". */
  threshold_mode: string
  /** Metric a "tuned" threshold maximises (binary). */
  threshold_metric: string
  calibrate_probs: boolean
  random_state: number
  /** metric the post-training permutation importance scores the drop in. */
  permutation_metric: string
  // feature engineering
  fe_enabled: boolean
  fe_polynomial: boolean
  fe_ratios: boolean
  fe_binning: boolean
  fe_max_poly_features: number
  // interaction features
  ix_enabled: boolean
  ix_max_auto_pairs: number
  ix_fill_method: string
  ix_drop_original: boolean
  // tuning
  tune_enabled: boolean
  tune_metric: string
  tune_cv: boolean
  tune_cv_folds: number
  tune_n_trials: number
  /** per-model wall-clock cap (seconds); null = no timeout (the default). */
  tune_timeout_seconds: number | null
  /** per-model search-space bound/choice overrides; {} = engine defaults. */
  tune_search_space_overrides: SearchSpaceOverrides
  // explainability (per-row SHAP; opt-in)
  explain_enabled: boolean
  // user-defined structured features (built via the feature-builder panel)
  user_features: UserFeatureSpec[]
}

/** Defaults mirror backend/api/models.py RunConfig (so an untouched form is valid). */
export const DEFAULT_FORM_STATE: ConfigFormState = {
  input_file: "",
  target: "",
  feature_cols: [],
  problem_type: "binary",
  test_size: 0.2,
  stratify: true,
  time_split_col: null,
  algorithms: ["LogisticRegression", "RandomForest", "XGBoost"],
  class_balance: "smote",
  missing_strategy: "median",
  missing_strategy_numeric: "median",
  missing_strategy_categorical: "mode",
  missing_strategy_by_column: {},
  encoding_method: "onehot",
  scaling_method: "standard",
  outlier_method: "iqr",
  high_cardinality_threshold: 20,
  threshold: 0.5,
  // UI default is "tuned" (let the engine optimize the cut) — deliberately more helpful than the
  // engine/API default of "default" (0.5), which is what a raw API/CLI caller gets. Binary only.
  threshold_mode: "tuned",
  threshold_metric: "f1",
  calibrate_probs: true,
  random_state: 42,
  permutation_metric: "f1_weighted",
  fe_enabled: true,
  fe_polynomial: false,
  fe_ratios: true,
  fe_binning: true,
  fe_max_poly_features: 8,
  ix_enabled: true,
  ix_max_auto_pairs: 10,
  ix_fill_method: "zero",
  ix_drop_original: false,
  tune_enabled: false,
  tune_metric: "f1_weighted",
  tune_cv: true,
  tune_cv_folds: 3,
  tune_n_trials: 30,
  tune_timeout_seconds: null, // no per-model wall-clock cap by default (n_trials bounds the study)
  tune_search_space_overrides: {},
  explain_enabled: false, // per-row SHAP is opt-in (KernelExplainer has cost)
  user_features: [],
}

/** The three fields the contract requires; everything else has a default. */
export const REQUIRED_FIELDS = ["input_file", "target", "feature_cols"] as const

/**
 * Client-side mirror of the server's required-field check, so the user sees the
 * problem before the 422. (The server still validates — this is just a friendlier
 * first line.) Returns a list of human-readable messages; empty means OK.
 */
export function validateRequired(form: ConfigFormState): string[] {
  const errors: string[] = []
  if (!form.input_file.trim()) errors.push("Upload a dataset first (input_file is required).")
  if (!form.target.trim()) errors.push("Choose a target column (target is required).")
  if (form.feature_cols.length === 0) errors.push("Select at least one feature column.")
  if (form.target && form.feature_cols.includes(form.target))
    errors.push("The target column must not also be a feature.")
  return errors
}

/** Assemble the nested RunConfig payload from flat form state. */
export function buildPayload(form: ConfigFormState): RunConfig {
  return {
    input_file: form.input_file.trim(),
    target: form.target.trim(),
    feature_cols: form.feature_cols,
    problem_type: form.problem_type,
    test_size: form.test_size,
    stratify: form.stratify,
    time_split_col: form.time_split_col,
    algorithms: form.algorithms,
    class_balance: form.class_balance,
    missing_strategy: form.missing_strategy,
    missing_strategy_numeric: form.missing_strategy_numeric,
    missing_strategy_categorical: form.missing_strategy_categorical,
    missing_strategy_by_column: form.missing_strategy_by_column,
    encoding_method: form.encoding_method,
    scaling_method: form.scaling_method,
    outlier_method: form.outlier_method,
    high_cardinality_threshold: form.high_cardinality_threshold,
    threshold: form.threshold,
    threshold_mode: form.threshold_mode,
    threshold_metric: form.threshold_metric,
    calibrate_probs: form.calibrate_probs,
    random_state: form.random_state,
    permutation_metric: form.permutation_metric,
    feature_engineering: {
      enabled: form.fe_enabled,
      polynomial: form.fe_polynomial,
      ratios: form.fe_ratios,
      binning: form.fe_binning,
      max_poly_features: form.fe_max_poly_features,
    },
    interaction_features: {
      enabled: form.ix_enabled,
      interaction_pairs: {},
      default_interactions: ["multiply"],
      drop_original_if_interacted: form.ix_drop_original,
      max_auto_pairs: form.ix_max_auto_pairs,
      fill_method: form.ix_fill_method,
    },
    tuning: {
      enabled: form.tune_enabled,
      models: [],
      metric: form.tune_metric,
      cv: form.tune_cv,
      cv_folds: form.tune_cv_folds,
      n_trials: form.tune_n_trials,
      timeout_seconds: form.tune_timeout_seconds,
      search_space_overrides: form.tune_search_space_overrides,
    },
    explainability: {
      enabled: form.explain_enabled,
      // sample_rows / background_size use the engine defaults (20 / 100); not surfaced in the UI.
      sample_rows: 20,
      background_size: 100,
    },
    // Structured specs only — assembled from dropdowns; never a free-text formula.
    user_features: form.user_features,
  }
}
