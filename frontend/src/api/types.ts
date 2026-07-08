/* ════════════════════════════════════════════════════════════════════════
   TypeScript types mirroring the LOCKED API contract (docs/api_contract.md,
   schema_version "1.0") and the backend Pydantic models (backend/api/models.py).

   RULE: these types mirror the contract EXACTLY. We never invent or rename a
   field. If a page needs something not in the contract, we flag the gap — we do
   not patch it here (the contract is frozen; additive changes bump the version).

   Each block notes which page(s) consume it.
   ════════════════════════════════════════════════════════════════════════ */

/* ─────────────────────────── REQUEST: RunConfig ─────────────────────────── */
// Sent by the Configuration page to POST /api/v1/run. Three fields are required
// (input_file, target, feature_cols); the rest carry the engine's defaults.

/** Section 7 (FeatureBuilder) toggles. */
export interface FeatureEngineeringConfig {
  enabled: boolean
  polynomial: boolean
  ratios: boolean
  binning: boolean
  max_poly_features: number
}

/** Section 7B (InteractionFeatureBuilder) toggles. */
export interface InteractionFeaturesConfig {
  enabled: boolean
  /** map of "colA+colB" → op ("multiply"|"ratio"|"diff"|"auto"|"all"). */
  interaction_pairs: Record<string, string>
  default_interactions: string[]
  drop_original_if_interacted: boolean
  max_auto_pairs: number
  fill_method: string
}

/** Section 8B (Optuna) tuning dials. OFF by default. */
export interface TuningConfig {
  enabled: boolean
  /** [] or ["all"] → tune every run algorithm. */
  models: string[]
  metric: string
  cv: boolean
  cv_folds: number
  n_trials: number
  /** per-model wall-clock cap (seconds); null = no cap (the default — n_trials bounds the study). */
  timeout_seconds: number | null
  /** per-model search-space bound/choice overrides; {} = engine defaults. */
  search_space_overrides: Record<string, unknown>
}

/** Per-row SHAP explainability dials. OFF by default (opt-in — KernelExplainer has cost). */
export interface ExplainabilityConfig {
  enabled: boolean
  /** first N held-out TEST rows per model to explain. */
  sample_rows: number
  /** TRAIN rows sampled as the SHAP reference distribution. */
  background_size: number
  /**
   * schema 1.7 (opt-in): add an Azure OpenAI reason-code paragraph per explained row. Requires
   * `enabled` and server-side AZURE_OPEN_AI_* credentials; degrades to SHAP-only otherwise.
   */
  llm_narratives: boolean
  /** How dataset context reaches the narrator (request-only; prompt quality, not the ML). */
  context_mode: "given" | "derived" | "both"
  /** Free-text describing the data/target (used when context_mode !== "derived"). */
  dataset_context: string
  /** Per-column meaning {column: note} (used when context_mode !== "derived"). */
  column_context: Record<string, string>
}

export type ProblemType = "binary" | "multiclass" | "multilabel"
export type ClassBalance = "smote" | "undersample" | "class_weight" | "none"

/**
 * One user-defined STRUCTURED feature spec (mirrors backend/api/models.py
 * `UserFeatureSpec` and the engine's `USER_FEATURE_*` allowlists EXACTLY).
 *
 * A new column built by applying a KNOWN `op` (from a fixed allowlist) to KNOWN
 * existing column(s) — NEVER a free-text formula, nothing is ever eval()'d.
 *  • type="numeric"       — two numeric cols + op add|subtract|multiply|divide|ratio (col_b required).
 *  • type="datetime_diff" — two datetime cols, op="subtract" → a duration in `unit` (col_b required).
 *  • type="single"        — one column + op log|abs|bin | year|month|day|dayofweek|hour (col_b omitted).
 *
 * The API rejects an unknown type/op (or a two-column type missing col_b) with a 422;
 * column existence/type are validated by the engine at fit time.
 */
export type UserFeatureType = "numeric" | "datetime_diff" | "single"
export interface UserFeatureSpec {
  name: string
  type: UserFeatureType
  op: string
  col_a: string
  /** required for two-column types (numeric, datetime_diff); omitted for single. */
  col_b?: string
  /** datetime_diff only: seconds|minutes|hours|days (default days). */
  unit?: string
}

/** The full run request body (POST /api/v1/run). Consumed by: Configuration. */
export interface RunConfig {
  // required
  input_file: string // storage key — usually an /upload server_path
  target: string
  feature_cols: string[] // at least one
  // problem framing
  problem_type: ProblemType
  test_size: number
  stratify: boolean
  time_split_col: string | null
  // modelling / preprocessing
  algorithms: string[]
  class_balance: ClassBalance
  /** Legacy GLOBAL missing-value strategy (back-compat default). */
  missing_strategy: string
  /** Per-type override for NUMERIC columns; null → inherit the global. */
  missing_strategy_numeric: string | null
  /** Per-type override for NON-NUMERIC columns; null → inherit (mode if global is numeric-only). */
  missing_strategy_categorical: string | null
  /** Optional per-column overrides {column: strategy}; unlisted columns use the per-type default. */
  missing_strategy_by_column: Record<string, string>
  encoding_method: string
  scaling_method: string
  outlier_method: string
  high_cardinality_threshold: number
  /** Positive-class cutoff used when threshold_mode === "fixed" (binary only). */
  threshold: number
  /** Decision-threshold mode (binary): "default" (0.5 argmax) | "fixed" | "tuned". */
  threshold_mode: string
  /** Metric a "tuned" threshold maximises (binary): f1 | balanced_accuracy | precision | … */
  threshold_metric: string
  calibrate_probs: boolean
  random_state: number
  /** metric the post-training permutation importance scores the drop in (default f1_weighted). */
  permutation_metric: string
  // nested capability configs
  feature_engineering: FeatureEngineeringConfig
  interaction_features: InteractionFeaturesConfig
  tuning: TuningConfig
  /** OPTIONAL; opt-in per-row SHAP → result.explanations (schema 1.6). OFF → block absent. */
  explainability: ExplainabilityConfig
  /** OPTIONAL; [] / omitted → no user-defined features (request unchanged). */
  user_features: UserFeatureSpec[]
}

/* ─────────────────────── RESPONSE: locked /run envelope ─────────────────── */

/** result.run — curated run metadata. Consumed by: Overview, Pipeline. */
export interface RunMeta {
  target: string
  problem_type: string
  features: string[] // configured
  active_features: string[] // final engineered cols (incl. interaction cols)
  interaction_cols: string[] // active_features matching _x_ / _div_ / _minus_
  class_distribution: Record<string, number>
  n_rows: number
  n_train: number
  n_test: number
  class_balance: string | null
  class_weight: Record<string, number> | null
  models_succeeded: number // COUNT of models that trained ok
  timestamp: string // UTC ISO-8601
}

/**
 * Headline metrics on the PRE-balance TRAIN split (schema 1.2, additive). Same scalars as
 * the test-side fields on ModelMetrics, measured on real pre-balance train rows so the
 * overfit gap (test − train) is meaningful. All null for a failed model. Consumed by: Overview.
 */
export interface TrainMetrics {
  accuracy: number | null
  f1_weighted: number | null
  f1_macro: number | null
  precision_weighted: number | null
  recall_weighted: number | null
  roc_auc: number | null
  pr_auc: number | null
  log_loss: number | null
  mcc: number | null
}

/** One row in result.models (a LIST; includes failed rows). Consumed by: Overview, Class Report. */
export interface ModelMetrics {
  name: string
  status: "ok" | "failed"
  // Headline metrics are the HELD-OUT TEST split.
  accuracy: number | null
  f1_weighted: number | null
  f1_macro: number | null
  precision_weighted: number | null
  recall_weighted: number | null
  roc_auc: number | null
  pr_auc: number | null
  log_loss: number | null
  mcc: number | null
  /** schema 1.2 (additive): same headline metrics on the pre-balance train split (overfit gap). */
  train?: TrainMetrics | null
  /** schema 1.5 (additive): effective binary operating threshold (tuned best / fixed / 0.5);
   *  null for multiclass/multilabel and failed models. */
  decision_threshold?: number | null
  /** schema 1.5 (additive): whether this model's probabilities are calibrated. */
  calibrated?: boolean | null
  error: string | null // set when status === "failed"
}

/** One sampled prediction. Consumed by: Predictions Table. */
export interface PredictionRow {
  model: string
  sample_index: number
  actual: string
  predicted: string
  confidence: number | null
  correct_flag: boolean
  probabilities: Record<string, number | null>
}

/** result.predictions — SAMPLED (≤100/model); full table is the artifacts CSV. */
export interface PredictionsBlock {
  sample_rows: PredictionRow[]
  sampled: boolean
  rows_returned: number
  rows_total: number
  full_csv: string // fetch via /outputs/{name}
}

/** result.confusion_matrix[model] — full test set. Consumed by: Confusion Matrix. */
export interface ConfusionMatrixEntry {
  labels: string[]
  matrix: number[][]
}

/** One row in result.class_report[model]. Consumed by: Class Report. */
export interface ClassReportRow {
  class: string
  precision: number | null
  recall: number | null
  f1: number | null
  support: number | null
}

/** One ranked feature in result.feature_impact. Consumed by: Feature Impact. */
export interface FeatureImpactRow {
  feature: string
  dtype_group: string | null
  anova_f: number | null
  anova_p: number | null
  mutual_info: number | null
  point_biserial: number | null
  corr_ratio: number | null
  composite_score: number | null
  id_like: boolean // leakage-bait flag — surfaced, never silently dropped
  rank: number | null
}

/**
 * One ranked feature in result.feature_importance[model] (schema 1.3, additive).
 * The model's NATIVE (built-in) importance for one feature, read post-training from the
 * fitted estimator (tree impurity/gain or |coef|), ranked descending WITHIN the model.
 * Model-dependent and NOT comparable across models. Consumed by: Feature Impact.
 */
export interface FeatureImportanceRow {
  feature: string
  importance: number | null
  rank: number | null
}

/**
 * One ranked feature in result.permutation_importance[model] (schema 1.4, additive).
 * The model's PERMUTATION importance for one feature — the drop in F1-weighted on the
 * held-out test split when that feature is shuffled — ranked descending WITHIN the model.
 * Model-AGNOSTIC, so present for EVERY model (incl. SVM / NaiveBayes), and comparable
 * across models (one unit: F1-weighted drop). May be slightly negative. Consumed by:
 * Feature Impact.
 */
export interface PermutationImportanceRow {
  feature: string
  importance: number | null
  rank: number | null
}

/** One ROC curve (one-vs-rest per class). Consumed by: ROC / PR Curves. */
export interface RocCurve {
  fpr: number[]
  tpr: number[]
  thresholds: number[]
  auc: number | null
}

/** One PR curve (one-vs-rest per class). Consumed by: ROC / PR Curves. */
export interface PrCurve {
  precision: number[]
  recall: number[]
  thresholds: number[]
  ap: number | null
}

/**
 * result.curves[model] — ROC/PR points per class, full test set.
 * Binary: a single entry keyed by the positive (lexicographically-last) class.
 * Multiclass: one-vs-rest entry per class (ROC and PR both provided).
 */
export interface ModelCurves {
  roc: Record<string, RocCurve>
  pr: Record<string, PrCurve>
}

/** One output file. Consumed by: every page that links/downloads artifacts. */
export interface ArtifactEntry {
  name: string
  suffix: string
  size_bytes: number
}

/**
 * result.tuning — per-model tuned hyperparameters (schema 1.1, additive, optional).
 * Mirrors the api_contract.md 1.1 block one-for-one; `null`/absent when Optuna tuning
 * was OFF (or every study produced nothing), so a non-tuning run is byte-identical to
 * 1.0. `best_params` values are heterogeneous (number / string / bool), hence `unknown`
 * — the UI stringifies them defensively. Consumed by: Tuning Results.
 */
export interface RunTuning {
  enabled: boolean
  metric: string
  cv: boolean
  cv_folds: number
  n_trials: number
  /** hard per-model wall-clock cap (seconds); null when the cap was opted out. */
  timeout_seconds: number | null
  /** models that produced tuned params. */
  tuned_models: string[]
  /** {model: {param: value}} — values are heterogeneous, never assume a type. */
  best_params: Record<string, Record<string, unknown>>
}

/** result — the whole reshaped run output. */
export interface RunResult {
  run: RunMeta
  models: ModelMetrics[]
  predictions: PredictionsBlock
  confusion_matrix: Record<string, ConfusionMatrixEntry>
  class_report: Record<string, ClassReportRow[]>
  feature_impact: FeatureImpactRow[]
  curves: Record<string, ModelCurves>
  artifacts: ArtifactEntry[]
  /** schema 1.1 (additive): per-model tuned hyperparameters; null/absent when tuning was OFF. */
  tuning?: RunTuning | null
  /**
   * schema 1.3 (additive): native per-model post-training feature importance, keyed by model.
   * Models with no native importance (RBF-SVM, GaussianNB) are omitted; null/absent when no
   * model exposes any. Distinct from feature_impact (the pre-training raw-data screen).
   */
  feature_importance?: Record<string, FeatureImportanceRow[]> | null
  /**
   * schema 1.4 (additive): per-model PERMUTATION importance, keyed by model. Model-agnostic,
   * so it covers ALL models (SVM / NaiveBayes included) — the complement to feature_importance.
   * null/absent when it could not be computed for any model.
   */
  permutation_importance?: Record<string, PermutationImportanceRow[]> | null
  /**
   * schema 1.6 (additive): per-row SHAP explanations keyed by model — LOCAL explainability
   * (why THIS prediction). null/absent when explainability was OFF (the default). Consumed by:
   * Explainability.
   */
  explanations?: Record<string, ModelExplanation> | null
}

/** One explained held-out test row (schema 1.6). base_value + Σ contributions === prediction. */
export interface ExplanationRow {
  /** 0-based row position within the held-out test set. */
  sample_index: number
  /** class the waterfall describes — positive class (binary) / predicted class (multiclass). */
  explained_class: string
  /** the model's average output — the waterfall's starting point. */
  base_value: number
  /** base_value + Σ contributions (the SHAP-additive landing point). */
  prediction: number
  /** signed per-feature push toward the explained class. */
  contributions: Record<string, number>
  /**
   * schema 1.8: each feature's ORIGINAL (raw) value, keyed like `contributions` — so the
   * waterfall can show "feature = value". A derived/interaction feature with no raw source is
   * null. Present whenever SHAP explanations are (not gated on LLM narratives).
   */
  feature_values?: Record<string, string | null>
  /**
   * schema 1.7 (optional): LLM-authored plain-language reason-code paragraph for this row
   * (Azure OpenAI). null/absent unless `explainability.llm_narratives` was on AND the server
   * had AZURE_OPEN_AI_* credentials.
   */
  narrative?: string | null
}

/** One model's per-row SHAP explanations (schema 1.6). */
export interface ModelExplanation {
  /** "shap.TreeExplainer" (tree models) | "shap.KernelExplainer" (LR/SVM/NaiveBayes). */
  method: string
  rows: ExplanationRow[]
}

/** Top-level envelope for POST /api/v1/run (the forward-compat seam). */
export interface RunResponse {
  status: "ok" | "error"
  schema_version: string
  result: RunResult | null // null when status === "error"
  error: string | null // top-level string when status === "error"
}

/* ─────────────────── MLflow read-path (schema 1.10, Interim 2a) ──────────── */
// Past runs read back from MLflow so results survive a refresh + a server restart.
// Mirrors backend/api/models.py RunSummary / RunsListResponse EXACTLY. Consumed by: Runs.

/** One past run in GET /api/v1/runs — a lightweight list-row (no artifact download). */
export interface RunSummary {
  run_id: string
  experiment_id: string
  experiment_name: string | null
  run_name: string | null
  /** MLflow lifecycle: "FINISHED" | "FAILED" | "RUNNING" | "SCHEDULED" | "KILLED". */
  status: string
  /** UTC ISO-8601 (converted from MLflow's epoch-millis); null if unset. */
  start_time: string | null
  end_time: string | null
  target: string | null
  problem_type: string | null
  input_file: string | null
  /** algorithm names logged for this run (from the <model>.<metric> metric keys). */
  algorithms: string[]
  models_logged: number
  /** the metric summarised for the list (always "f1_weighted") + its best value / model. */
  best_metric: string
  best_value: number | null
  best_model: string | null
  /** true → GET /runs/{run_id} can reload the full /run envelope for this run. */
  reloadable: boolean
}

/** GET /api/v1/runs → past runs, most-recent first. Consumed by: Runs. */
export interface RunsListResponse {
  schema_version: string
  /** the MLflow store the API read from (local ./mlruns, or a Postgres backend store). */
  tracking_uri: string
  runs: RunSummary[]
}

/* ──────────────────────── Other endpoint shapes ─────────────────────────── */

/** GET /api/v1/health → liveness payload. Consumed by: the health banner. */
export interface HealthResponse {
  status: string
  service: string
  version: string
}

/* ─────────────────── Data Profile (additive /upload blocks) ──────────────── */
// Per-column exploratory statistics attached when /upload profiles a file
// (engine: classifyos.analysis.profile.profile_dataframe). Consumed by: Data Profile.

/** Summary statistics for one numeric column (non-null values only). */
export interface NumericStats {
  count: number
  mean: number | null
  std: number | null
  min: number | null
  p25: number | null
  median: number | null
  p75: number | null
  max: number | null
  mode: number | null
  skew: number | null
}

/** A binned distribution: `counts[i]` falls in `[bin_edges[i], bin_edges[i+1])`. */
export interface Histogram {
  bin_edges: Array<number | null>
  counts: number[]
}

/** One row of a categorical column's value-frequency breakdown. */
export interface TopValue {
  value: string
  count: number
  pct: number | null
}

/**
 * One column's profile. `dtype_group` drives which block is populated:
 *  • "numeric"     → `stats` + `histogram`
 *  • "categorical" → `top_values` + `other_count` + `truncated` (also numeric binary 0/1)
 *  • "datetime"    → `min` + `max` (ISO strings)
 */
export interface ColumnProfile {
  name: string
  dtype_group: "numeric" | "categorical" | "datetime"
  n_missing: number
  missing_pct: number | null
  n_unique: number
  // degenerate-column advisories ("constant" | "identifier"); [] for normal columns.
  flags?: string[]
  // numeric:
  stats?: NumericStats | null
  histogram?: Histogram | null
  // categorical / binary:
  top_values?: TopValue[] | null
  other_count?: number | null
  truncated?: boolean
  // datetime:
  min?: string | null
  max?: string | null
}

/** Pearson correlation over numeric columns; `null` when <2 numeric cols. */
export interface CorrelationMatrix {
  columns: string[]
  matrix: Array<Array<number | null>>
  truncated: boolean
}

/**
 * POST /api/v1/upload → the inspect_file profile + server_path.
 * Mirrors classifyos.io.inspect.inspect_file. Consumed by: Upload, Configuration,
 * Data Profile.
 */
export interface InspectProfile {
  columns: string[]
  dtypes: Record<string, string>
  numeric_cols: string[]
  categorical_cols: string[]
  binary_cols: string[]
  datetime_cols: string[]
  n_rows: number
  n_missing: Record<string, number>
  sample: Array<Record<string, unknown>>
  // present only when a target was supplied to /upload:
  class_distribution?: Record<string, number>
  suggested_problem_type?: ProblemType
  // added by the upload route — the key to echo back to /run as input_file:
  server_path: string
  // additive Data-Profile blocks (present when /upload profiled the file):
  column_profiles?: ColumnProfile[]
  correlation?: CorrelationMatrix | null
  profile_sampled?: boolean
  n_rows_profiled?: number
}

/** POST /api/v1/explain → v1.0 structured stub. Consumed by: Explainability. */
export interface ExplainRequest {
  input_file: string
  target: string
  feature_cols: string[]
  model: string
  sample_index: number
}

export interface ExplainResponse {
  status: string // "unavailable" in v1.0
  schema_version: string
  model: string
  sample_index: number
  method: string | null
  shap_values: Record<string, number> | null
  base_value: number | null
  reason: string
  message: string
}
