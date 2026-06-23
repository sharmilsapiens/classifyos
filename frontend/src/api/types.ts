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
  /** hard per-model wall-clock cap (seconds); null opts out. */
  timeout_seconds: number | null
  search_space_overrides: Record<string, unknown>
}

export type ProblemType = "binary" | "multiclass" | "multilabel"
export type ClassBalance = "smote" | "undersample" | "class_weight" | "none"

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
  missing_strategy: string
  encoding_method: string
  scaling_method: string
  outlier_method: string
  high_cardinality_threshold: number
  threshold: number
  calibrate_probs: boolean
  random_state: number
  // nested capability configs
  feature_engineering: FeatureEngineeringConfig
  interaction_features: InteractionFeaturesConfig
  tuning: TuningConfig
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

/** One row in result.models (a LIST; includes failed rows). Consumed by: Overview, Class Report. */
export interface ModelMetrics {
  name: string
  status: "ok" | "failed"
  accuracy: number | null
  f1_weighted: number | null
  f1_macro: number | null
  precision_weighted: number | null
  recall_weighted: number | null
  roc_auc: number | null
  pr_auc: number | null
  log_loss: number | null
  mcc: number | null
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
}

/** Top-level envelope for POST /api/v1/run (the forward-compat seam). */
export interface RunResponse {
  status: "ok" | "error"
  schema_version: string
  result: RunResult | null // null when status === "error"
  error: string | null // top-level string when status === "error"
}

/* ──────────────────────── Other endpoint shapes ─────────────────────────── */

/** GET /api/v1/health → liveness payload. Consumed by: the health banner. */
export interface HealthResponse {
  status: string
  service: string
  version: string
}

/**
 * POST /api/v1/upload → the inspect_file profile + server_path.
 * Mirrors classifyos.io.inspect.inspect_file. Consumed by: Upload, Configuration.
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
