/* Tests for the typed API client's ERROR-MAPPING layer (Phase 10 gap fill).

   parse.test.ts already covers parseRunResponse (the /run envelope shape). What
   was NOT covered is client.ts's own normalization of failed HTTP calls into the
   single `ApiError` type — the layer every page relies on to show a readable
   message. We exercise it here by stubbing the global `fetch` (same technique as
   AppStore.test.tsx) and asserting the three error kinds + the happy path. */

import { afterEach, describe, expect, it, vi } from "vitest"

import { ApiError, explain, health, outputUrl, run, runScopedArtifactId } from "./client"
import type { MlflowInfo } from "./types"

/** Build a minimal fetch Response stand-in (only the fields the client reads). */
function jsonResponse(body: unknown, init: { ok: boolean; status: number }): Response {
  return {
    ok: init.ok,
    status: init.status,
    json: async () => body,
  } as Response
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("ApiError mapping", () => {
  it("maps a network-level failure (server down) to kind 'network', status 0", async () => {
    // fetch rejects when the server is unreachable (DNS/connection/CORS).
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")))

    await expect(health()).rejects.toMatchObject({
      name: "ApiError",
      kind: "network",
      status: 0,
    })
  })

  it("maps a 422 with FastAPI field errors to kind 'validation' with field messages", async () => {
    // FastAPI validation errors: detail is a list of { loc, msg }.
    const body = {
      detail: [
        { loc: ["body", "target"], msg: "field required" },
        { loc: ["body", "feature_cols"], msg: "at least one feature" },
      ],
    }
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(body, { ok: false, status: 422 })))

    try {
      await explain({ input_file: "x.csv", target: "", feature_cols: [] })
      throw new Error("expected explain() to throw")
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError)
      const e = err as ApiError
      expect(e.kind).toBe("validation")
      expect(e.status).toBe(422)
      // The "body" prefix is stripped; the field path + message are surfaced.
      expect(e.fieldErrors).toContain("target: field required")
      expect(e.fieldErrors).toContain("feature_cols: at least one feature")
      expect(e.message).toMatch(/field required/)
    }
  })

  it("maps a 422 with a plain string detail to a single field message", async () => {
    const body = { detail: "target 'will_lapse' is also a feature column" }
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(body, { ok: false, status: 422 })))

    await expect(
      explain({ input_file: "x.csv", target: "will_lapse", feature_cols: ["will_lapse"] }),
    ).rejects.toMatchObject({ kind: "validation", status: 422 })
  })

  it("maps a 400 run-error envelope to kind 'http' using the envelope's error string", async () => {
    // /run returns its error envelope ({status:"error", error}) with HTTP 400.
    const body = { status: "error", schema_version: "1.0", result: null, error: "FileNotFoundError: missing.csv" }
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(body, { ok: false, status: 400 })))

    try {
      await run({ input_file: "missing.csv", target: "t", feature_cols: ["a"] })
      throw new Error("expected run() to throw")
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError)
      const e = err as ApiError
      expect(e.kind).toBe("http")
      expect(e.status).toBe(400)
      expect(e.message).toContain("missing.csv")
    }
  })

  it("returns the parsed body on a successful call (no throw)", async () => {
    const body = {
      status: "unavailable",
      schema_version: "1.0",
      model: "RandomForest",
      sample_index: 0,
      method: null,
      shap_values: null,
      base_value: null,
      reason: "no_persisted_model",
      message: "deferred to v2.0",
    }
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(body, { ok: true, status: 200 })))

    const res = await explain({ input_file: "x.csv", target: "t", feature_cols: ["a"] })
    expect(res.status).toBe("unavailable")
    expect(res.reason).toBe("no_persisted_model")
  })
})

/* ── Artifact URLs — run-scoped fetch for Databricks runs (§6.2) ──────────────
   API_BASE resolves to "/api/v1" in tests (no VITE_API_BASE_URL — see vite.config.ts). */

describe("outputUrl", () => {
  it("builds a flat /outputs/{name} URL with no runId (a LOCAL run — unchanged)", () => {
    expect(outputUrl("plot2_roc_pr_curves.png")).toBe("/api/v1/outputs/plot2_roc_pr_curves.png")
  })

  it("builds a run-scoped /outputs/{runId}/{name} URL with a runId (a Databricks run)", () => {
    expect(outputUrl("plot2_roc_pr_curves.png", "abc123def456")).toBe(
      "/api/v1/outputs/abc123def456/plot2_roc_pr_curves.png",
    )
  })

  it("treats a null/empty runId as flat (a run with no MLflow pointer is unchanged)", () => {
    expect(outputUrl("m.csv", null)).toBe("/api/v1/outputs/m.csv")
    expect(outputUrl("m.csv", "")).toBe("/api/v1/outputs/m.csv")
  })

  it("URL-encodes both segments", () => {
    expect(outputUrl("a b.csv", "r/1")).toBe("/api/v1/outputs/r%2F1/a%20b.csv")
  })
})

const DBX_MLFLOW: MlflowInfo = {
  run_id: "abc123def456",
  experiment_id: "42",
  tracking_uri: "databricks",
  models: {},
}

describe("runScopedArtifactId", () => {
  it("returns the run id for a Databricks-backed run (tracking_uri 'databricks')", () => {
    expect(runScopedArtifactId(DBX_MLFLOW)).toBe("abc123def456")
    // A profile-qualified databricks URI (e.g. "databricks://prod") still counts.
    expect(runScopedArtifactId({ ...DBX_MLFLOW, tracking_uri: "databricks://prod" })).toBe(
      "abc123def456",
    )
  })

  it("returns undefined for a LOCAL run, so it keeps the flat /outputs/{name} (byte-identical)", () => {
    expect(
      runScopedArtifactId({
        ...DBX_MLFLOW,
        tracking_uri: "postgresql://classifyos@localhost:5432/mlflow",
      }),
    ).toBeUndefined()
    expect(
      runScopedArtifactId({
        ...DBX_MLFLOW,
        tracking_uri: "file:///C:/Projects/classifyos/backend/mlruns",
      }),
    ).toBeUndefined()
  })

  it("returns undefined when there is no MLflow pointer (a non-MLflow run)", () => {
    expect(runScopedArtifactId(null)).toBeUndefined()
    expect(runScopedArtifactId(undefined)).toBeUndefined()
  })
})
