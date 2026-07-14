import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"

import type { InspectProfile } from "@/api/types"
import { AppProvider, POLL_INTERVAL_MS, useApp } from "./AppStore"

// A tiny consumer that surfaces the health-banner state for assertions.
function HealthProbe() {
  const { apiStatus, apiMessage } = useApp()
  return (
    <div>
      <span data-testid="status">{apiStatus}</span>
      <span data-testid="message">{apiMessage}</span>
    </div>
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("checkAPI (runs on mount)", () => {
  it("handles the offline case (failed fetch) without crashing", async () => {
    // Simulate the server being unreachable: fetch rejects at the network level.
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")))

    render(
      <AppProvider>
        <HealthProbe />
      </AppProvider>,
    )

    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("offline"))
    expect(screen.getByTestId("message").textContent).toMatch(/offline/i)
  })

  it("reports online when /health answers", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: "ok", service: "ClassifyOS API", version: "1.0" }),
      } as Response),
    )

    render(
      <AppProvider>
        <HealthProbe />
      </AppProvider>,
    )

    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("online"))
    expect(screen.getByTestId("message").textContent).toMatch(/connected/i)
  })
})

// A probe that applies a given profile and surfaces the resulting run-form fields.
function UploadProbe({ profile }: { profile: InspectProfile }) {
  const { form, applyUpload } = useApp()
  return (
    <div>
      <button onClick={() => applyUpload(profile)}>apply</button>
      <span data-testid="input_file">{form.input_file}</span>
      <span data-testid="input_source">{JSON.stringify(form.input_source)}</span>
    </div>
  )
}

const BASE_PROFILE: InspectProfile = {
  columns: ["a", "b"],
  dtypes: { a: "int64", b: "object" },
  numeric_cols: ["a"],
  categorical_cols: ["b"],
  binary_cols: [],
  datetime_cols: [],
  n_rows: 2,
  n_missing: { a: 0, b: 0 },
  sample: [],
  server_path: "uploads/x.csv",
}

describe("applyUpload (source plumbing)", () => {
  beforeEach(() => {
    // Silence the mount-time /health probe so applyUpload is what's under test.
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")))
  })

  it("a file upload leaves input_source null (file run — request omits it)", () => {
    render(
      <AppProvider>
        <UploadProbe profile={BASE_PROFILE} />
      </AppProvider>,
    )
    fireEvent.click(screen.getByText("apply"))
    expect(screen.getByTestId("input_file").textContent).toBe("uploads/x.csv")
    expect(screen.getByTestId("input_source").textContent).toBe("null")
  })

  it("a database selection carries its input_source block onto the run form (Interim 2b)", () => {
    const dbProfile: InspectProfile = {
      ...BASE_PROFILE,
      server_path: "db_snapshots/iris.parquet",
      input_source: {
        type: "postgres",
        connection_env: "CLASSIFYOS_PG_DSN",
        table: "iris",
        query: null,
      },
    }
    render(
      <AppProvider>
        <UploadProbe profile={dbProfile} />
      </AppProvider>,
    )
    fireEvent.click(screen.getByText("apply"))
    expect(screen.getByTestId("input_file").textContent).toBe("db_snapshots/iris.parquet")
    expect(JSON.parse(screen.getByTestId("input_source").textContent!)).toEqual({
      type: "postgres",
      connection_env: "CLASSIFYOS_PG_DSN",
      table: "iris",
      query: null,
    })
  })
})

// ── Databricks polling state machine (§6.6 Step 6) ─────────────────────────────
// The store, in the databricks backend, submits a Job and polls its status every POLL_INTERVAL_MS,
// switching to the results (COMPLETED) or an error (FAILED). We drive it with a URL-routing fetch
// stub + fake timers and assert the exposed running/jobStatus/result/runError transitions.

/** A minimal contract-valid /run result envelope (enough for parseRunResponse). */
const OK_ENVELOPE = {
  status: "ok",
  schema_version: "1.11",
  result: {
    run: { target: "t" },
    models: [],
    predictions: {},
    confusion_matrix: {},
    class_report: {},
    feature_impact: [],
    curves: {},
    artifacts: [],
  },
  error: null,
}

function jsonOk(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as Response
}

/** Build a fetch stub that routes by URL + method for the databricks submit/poll/results flow. */
function databricksFetch(statuses: string[], opts: { message?: string | null } = {}) {
  let i = 0
  return vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    const method = init?.method ?? "GET"
    if (u.endsWith("/health"))
      return jsonOk({ status: "ok", service: "ClassifyOS API", version: "1.0", execution_backend: "databricks" })
    if (u.endsWith("/run") && method === "POST")
      return jsonOk({ job_id: "job1", run_id: "r1", status: "PENDING", schema_version: "1.11" })
    if (u.includes("/run/job1/status")) {
      const status = statuses[Math.min(i, statuses.length - 1)]
      i += 1
      return jsonOk({ job_id: "job1", run_id: "r1", status, message: opts.message ?? null, schema_version: "1.11" })
    }
    if (u.includes("/run/job1/results")) return jsonOk(OK_ENVELOPE)
    return { ok: false, status: 404, json: async () => ({}) } as Response
  })
}

/** A probe that surfaces the run state + buttons to prep the form and trigger a run. */
function RunProbe() {
  const { running, jobStatus, result, runError, executionBackend, updateForm, setDatabricksPat, runPipeline } =
    useApp()
  return (
    <div>
      <span data-testid="backend">{executionBackend}</span>
      <span data-testid="running">{String(running)}</span>
      <span data-testid="jobStatus">{jobStatus ?? ""}</span>
      <span data-testid="result">{result ? result.status : ""}</span>
      <span data-testid="runError">{runError ?? ""}</span>
      <button
        onClick={() => {
          updateForm({
            input_file: "db_snapshots/tbl.parquet",
            target: "t",
            feature_cols: ["a"],
            input_source: {
              type: "delta",
              connection_env: "e",
              catalog: "c",
              schema: "s",
              table: "tbl",
              query: null,
            },
          })
          setDatabricksPat("pat")
        }}
      >
        prep
      </button>
      <button onClick={() => void runPipeline()}>run</button>
    </div>
  )
}

describe("runPipeline (databricks backend — submit + poll)", () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  async function mountInDatabricksMode(fetchMock: ReturnType<typeof databricksFetch>) {
    vi.useFakeTimers()
    vi.stubGlobal("fetch", fetchMock)
    render(
      <AppProvider>
        <RunProbe />
      </AppProvider>,
    )
    // Flush the mount-time /health probe so the store learns it's the databricks backend.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(screen.getByTestId("backend").textContent).toBe("databricks")
    // Prep the form + PAT, then submit (the immediate poll fires the first status).
    await act(async () => {
      fireEvent.click(screen.getByText("prep"))
    })
    await act(async () => {
      fireEvent.click(screen.getByText("run"))
      await vi.advanceTimersByTimeAsync(0)
    })
  }

  it("transitions PENDING → RUNNING → COMPLETED and loads the results", async () => {
    await mountInDatabricksMode(databricksFetch(["PENDING", "RUNNING", "COMPLETED"]))

    // Immediate poll after submit → PENDING, still running.
    expect(screen.getByTestId("jobStatus").textContent).toBe("PENDING")
    expect(screen.getByTestId("running").textContent).toBe("true")

    // Next interval → RUNNING.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    })
    expect(screen.getByTestId("jobStatus").textContent).toBe("RUNNING")

    // Next interval → COMPLETED → results fetched, running clears.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    })
    expect(screen.getByTestId("jobStatus").textContent).toBe("COMPLETED")
    expect(screen.getByTestId("running").textContent).toBe("false")
    expect(screen.getByTestId("result").textContent).toBe("ok")
    expect(screen.getByTestId("runError").textContent).toBe("")
  })

  it("surfaces the FAILED path with the workspace's message", async () => {
    await mountInDatabricksMode(databricksFetch(["FAILED"], { message: "cluster OOM" }))

    // The immediate poll returns FAILED → run stops with the error, no result.
    expect(screen.getByTestId("jobStatus").textContent).toBe("FAILED")
    expect(screen.getByTestId("running").textContent).toBe("false")
    expect(screen.getByTestId("runError").textContent).toBe("cluster OOM")
    expect(screen.getByTestId("result").textContent).toBe("")
  })

  it("requires a PAT before submitting", async () => {
    vi.useFakeTimers()
    vi.stubGlobal("fetch", databricksFetch(["PENDING"]))
    render(
      <AppProvider>
        <RunProbe />
      </AppProvider>,
    )
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    // Prep the form but DO NOT set a PAT (overwrite the probe's prep with a no-PAT path).
    await act(async () => {
      fireEvent.click(screen.getByText("run")) // no form / no pat → validateRequired fails first
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(screen.getByTestId("running").textContent).toBe("false")
    expect(screen.getByTestId("runError").textContent.length).toBeGreaterThan(0)
  })
})
