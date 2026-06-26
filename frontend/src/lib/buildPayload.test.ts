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

  it("includes every required key the API expects", () => {
    const payload = buildPayload(form)
    for (const key of ["input_file", "target", "feature_cols"]) {
      expect(payload).toHaveProperty(key)
    }
  })

  it("defaults user_features to an empty list (a non-user-feature run is unchanged)", () => {
    expect(buildPayload(form).user_features).toEqual([])
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
