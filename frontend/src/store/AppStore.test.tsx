import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"

import type { InspectProfile } from "@/api/types"
import { AppProvider, useApp } from "./AppStore"

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
