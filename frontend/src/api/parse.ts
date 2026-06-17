/* ════════════════════════════════════════════════════════════════════════
   Response parser for the locked /run envelope.

   The server already validates what it SENDS (Pydantic response models), but a
   frontend should never blindly trust a payload: a contract drift or a proxy
   returning an HTML error page would otherwise surface as a confusing render
   crash deep in a chart. `parseRunResponse` checks the envelope's shape up front
   and throws one clear error if it doesn't match the contract.

   This is deliberately a STRUCTURAL check (the right keys of the right kinds),
   not a deep field-by-field schema — enough to fail fast and readably.
   ════════════════════════════════════════════════════════════════════════ */

import type { RunResponse, RunResult } from "./types"

/** Thrown when a /run payload does not match the locked contract shape. */
export class ContractError extends Error {
  constructor(message: string) {
    super(`Malformed /run response — ${message}`)
    this.name = "ContractError"
  }
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v)
}

/** Validate the `result` block has the contract's keys of the right kinds. */
function assertResult(result: unknown): asserts result is RunResult {
  if (!isObject(result)) throw new ContractError("result must be an object when status is 'ok'")
  if (!isObject(result.run)) throw new ContractError("result.run must be an object")
  if (!Array.isArray(result.models)) throw new ContractError("result.models must be an array")
  if (!isObject(result.predictions)) throw new ContractError("result.predictions must be an object")
  if (!isObject(result.confusion_matrix))
    throw new ContractError("result.confusion_matrix must be an object")
  if (!isObject(result.class_report)) throw new ContractError("result.class_report must be an object")
  if (!Array.isArray(result.feature_impact))
    throw new ContractError("result.feature_impact must be an array")
  if (!isObject(result.curves)) throw new ContractError("result.curves must be an object")
  if (!Array.isArray(result.artifacts)) throw new ContractError("result.artifacts must be an array")
}

/**
 * Validate and narrow an unknown payload to a `RunResponse`.
 * Throws `ContractError` on anything that doesn't match the locked shape.
 */
export function parseRunResponse(data: unknown): RunResponse {
  if (!isObject(data)) throw new ContractError("response is not a JSON object")

  const { status, schema_version, result, error } = data
  if (status !== "ok" && status !== "error")
    throw new ContractError(`status must be "ok" or "error" (got ${JSON.stringify(status)})`)
  if (typeof schema_version !== "string")
    throw new ContractError("schema_version must be a string")

  if (status === "error") {
    // On error the contract requires result === null and a top-level error string.
    if (result !== null && result !== undefined)
      throw new ContractError("result must be null when status is 'error'")
    return {
      status,
      schema_version,
      result: null,
      error: typeof error === "string" ? error : "Unknown run error.",
    }
  }

  // status === "ok": result must be present and well-formed.
  assertResult(result)
  return { status, schema_version, result, error: null }
}
