import { describe, expect, it } from "vitest"

import { buildPayload, DEFAULT_FORM_STATE, validateRequired } from "./buildPayload"

describe("buildPayload", () => {
  const form = {
    ...DEFAULT_FORM_STATE,
    input_file: "  policy_lapse.csv  ", // leading/trailing space to test trimming
    target: "will_lapse",
    feature_cols: ["age", "premium", "tenure_months"],
  }

  it("produces a contract-valid RunConfig from form state", () => {
    const payload = buildPayload(form)

    // Required fields, trimmed.
    expect(payload.input_file).toBe("policy_lapse.csv")
    expect(payload.target).toBe("will_lapse")
    expect(payload.feature_cols).toEqual(["age", "premium", "tenure_months"])

    // Scalars carried through.
    expect(payload.problem_type).toBe("binary")
    expect(payload.test_size).toBe(0.2)
    expect(payload.algorithms).toContain("XGBoost")

    // Nested capability configs are assembled with the contract's shape.
    expect(payload.feature_engineering).toMatchObject({
      enabled: true,
      polynomial: false,
      ratios: true,
      binning: true,
      max_poly_features: 8,
    })
    expect(payload.interaction_features.default_interactions).toEqual(["multiply"])
    expect(payload.interaction_features.interaction_pairs).toEqual({})
    expect(payload.tuning).toMatchObject({
      enabled: false,
      models: [],
      metric: "f1_weighted",
      timeout_seconds: null, // no per-model wall-clock cap by default
      search_space_overrides: {},
    })
  })

  it("splits the missing-value strategy by feature type", () => {
    const payload = buildPayload({
      ...form,
      missing_strategy_numeric: "knn",
      missing_strategy_categorical: "ffill",
    })
    expect(payload.missing_strategy_numeric).toBe("knn")
    expect(payload.missing_strategy_categorical).toBe("ffill")
    // Defaults: median for numeric, mode for categorical.
    const defaults = buildPayload(form)
    expect(defaults.missing_strategy_numeric).toBe("median")
    expect(defaults.missing_strategy_categorical).toBe("mode")
  })

  it("carries per-column imputation overrides (default {}; map respected)", () => {
    expect(buildPayload(form).missing_strategy_by_column).toEqual({})
    const payload = buildPayload({
      ...form,
      missing_strategy_by_column: { age: "knn", region: "ffill" },
    })
    expect(payload.missing_strategy_by_column).toEqual({ age: "knn", region: "ffill" })
  })

  it("includes every required key the API expects", () => {
    const payload = buildPayload(form)
    for (const key of ["input_file", "target", "feature_cols"]) {
      expect(payload).toHaveProperty(key)
    }
  })

  it("defaults user_features to an empty list (a non-user-feature run is unchanged)", () => {
    expect(buildPayload(form).user_features).toEqual([])
  })

  it("carries the permutation_metric (default f1_weighted; override respected)", () => {
    expect(buildPayload(form).permutation_metric).toBe("f1_weighted")
    expect(buildPayload({ ...form, permutation_metric: "roc_auc" }).permutation_metric).toBe("roc_auc")
  })

  it("carries the decision-threshold policy (UI defaults to auto-tune)", () => {
    const payload = buildPayload(form)
    expect(payload.threshold_mode).toBe("tuned")
    expect(payload.threshold_metric).toBe("f1")
    expect(payload.threshold).toBe(0.5)
    const fixed = buildPayload({ ...form, threshold_mode: "fixed", threshold: 0.3 })
    expect(fixed.threshold_mode).toBe("fixed")
    expect(fixed.threshold).toBe(0.3)
  })

  it("carries the explainability toggle (default OFF; opt-in respected)", () => {
    expect(buildPayload(form).explainability).toEqual({
      enabled: false,
      sample_rows: 20,
      background_size: 100,
      llm_narratives: false,
      context_mode: "both",
      dataset_context: "",
      column_context: {},
    })
    expect(buildPayload({ ...form, explain_enabled: true }).explainability.enabled).toBe(true)
  })

  it("carries the LLM narrative context (mode, dataset text, per-column notes)", () => {
    const payload = buildPayload({
      ...form,
      explain_enabled: true,
      explain_llm: true,
      explain_context_mode: "given",
      explain_dataset_context: "Arizona quotes; converted = bound.",
      explain_column_context: { Decision_Days: "days to decision" },
    })
    expect(payload.explainability.context_mode).toBe("given")
    expect(payload.explainability.dataset_context).toBe("Arizona quotes; converted = bound.")
    expect(payload.explainability.column_context).toEqual({ Decision_Days: "days to decision" })
  })

  it("only sends llm_narratives when SHAP is also on (guard)", () => {
    // LLM without SHAP is meaningless — buildPayload forces it off.
    expect(
      buildPayload({ ...form, explain_enabled: false, explain_llm: true }).explainability
        .llm_narratives,
    ).toBe(false)
    // With both on, the narrative flag is carried through.
    expect(
      buildPayload({ ...form, explain_enabled: true, explain_llm: true }).explainability
        .llm_narratives,
    ).toBe(true)
  })

  it("logs to MLflow by default (UI default ON, differs from the engine's OFF); flips when toggled off", () => {
    // The UI deliberately defaults mlflow logging ON — more helpful than the engine/API default of
    // OFF (see DEFAULT_FORM_STATE), same pattern as threshold_mode.
    expect(buildPayload(form).mlflow).toEqual({ enabled: true })
    // Toggling the form field off sends enabled: false.
    expect(buildPayload({ ...form, mlflow_enabled: false }).mlflow).toEqual({ enabled: false })
  })

  it("omits input_source for a file run (byte-identical to before)", () => {
    // Default form has input_source: null → the request must not carry an input_source key at all.
    const payload = buildPayload(form)
    expect("input_source" in payload).toBe(false)
  })

  it("sends input_source when a database table was selected (Interim 2b)", () => {
    const payload = buildPayload({
      ...form,
      input_file: "db_snapshots/iris.parquet",
      input_source: {
        type: "postgres",
        connection_env: "CLASSIFYOS_PG_DSN",
        table: "iris",
        query: null,
      },
    })
    expect(payload.input_source).toEqual({
      type: "postgres",
      connection_env: "CLASSIFYOS_PG_DSN",
      table: "iris",
      query: null,
    })
    expect(payload.input_file).toBe("db_snapshots/iris.parquet")
  })

  it("carries user-defined feature specs through to the payload verbatim", () => {
    const specs = [
      { name: "premium_per_sum", type: "numeric" as const, op: "divide", col_a: "premium", col_b: "sum_assured" },
      { name: "start_year", type: "single" as const, op: "year", col_a: "start_date" },
    ]
    const payload = buildPayload({ ...form, user_features: specs })
    expect(payload.user_features).toEqual(specs)
  })
})

describe("validateRequired", () => {
  it("passes a complete form", () => {
    const form = {
      ...DEFAULT_FORM_STATE,
      input_file: "f.csv",
      target: "y",
      feature_cols: ["a"],
    }
    expect(validateRequired(form)).toEqual([])
  })

  it("flags each missing required field", () => {
    const errors = validateRequired(DEFAULT_FORM_STATE)
    expect(errors.length).toBeGreaterThanOrEqual(3)
  })

  it("flags the target also being a feature", () => {
    const form = {
      ...DEFAULT_FORM_STATE,
      input_file: "f.csv",
      target: "y",
      feature_cols: ["y", "a"],
    }
    expect(validateRequired(form).some((e) => e.includes("must not also be a feature"))).toBe(true)
  })
})
