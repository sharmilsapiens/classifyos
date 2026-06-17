import { describe, expect, it } from "vitest"

import { ContractError, parseRunResponse } from "./parse"
import validEnvelope from "@/test/fixtures/run_envelope.json"

describe("parseRunResponse", () => {
  it("accepts a real saved /run envelope", () => {
    const parsed = parseRunResponse(validEnvelope)
    expect(parsed.status).toBe("ok")
    expect(parsed.schema_version).toBe("1.0")
    expect(parsed.result).not.toBeNull()
    expect(Array.isArray(parsed.result?.models)).toBe(true)
    expect(parsed.result?.models[0].name).toBe("LogisticRegression")
  })

  it("accepts an error envelope (result null, error set)", () => {
    const parsed = parseRunResponse({
      status: "error",
      schema_version: "1.0",
      result: null,
      error: "FileNotFoundError: missing.csv",
    })
    expect(parsed.status).toBe("error")
    expect(parsed.result).toBeNull()
    expect(parsed.error).toContain("missing.csv")
  })

  it("rejects a non-object payload", () => {
    expect(() => parseRunResponse("not json")).toThrow(ContractError)
  })

  it("rejects a bad status value", () => {
    expect(() => parseRunResponse({ status: "weird", schema_version: "1.0" })).toThrow(ContractError)
  })

  it("rejects an 'ok' envelope missing the models array", () => {
    const malformed = {
      status: "ok",
      schema_version: "1.0",
      result: { run: {}, predictions: {}, confusion_matrix: {}, class_report: {}, curves: {} },
    }
    expect(() => parseRunResponse(malformed)).toThrow(ContractError)
  })

  it("rejects an 'error' envelope that still carries a result", () => {
    expect(() =>
      parseRunResponse({ status: "error", schema_version: "1.0", result: { run: {} }, error: "x" }),
    ).toThrow(ContractError)
  })
})
