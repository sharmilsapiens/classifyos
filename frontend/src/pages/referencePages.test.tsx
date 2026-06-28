/* Render-level smoke tests for the 9c pages + the Overview/Pipeline merge + nav.

   Like the 9b tests these are smoke-level (jsdom; chart internals don't render),
   asserting the contract-driven DOM around each page. True browser E2E — incl. the
   unverified multilabel path — remains Phase 10/11.

   Covers:
   • Explainability — renders the v1.0 "unavailable" stub cleanly (the /explain
     client is mocked), the Explain action triggers the call, null fields don't crash.
   • Setup Guide / Risk Register — render without crashing; key sections present.
   • Merged Overview — the in-progress state AND the results state from a fixture.
   • Nav — 12 items, no dangling "Pipeline" entry. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import type { ReactElement } from "react"

import binaryEnvelope from "@/test/fixtures/run_envelope.json"
import type { RunResponse, ExplainResponse } from "@/api/types"
import { NAV_ITEMS } from "@/lib/nav"

// ── Mock the store. Each test sets the slice of state its page reads. ──────────
let mockApp: {
  result: RunResponse | null
  serverPath: string | null
  form: { input_file: string }
  running: boolean
  runError: string | null
  runFieldErrors: string[]
} = {
  result: null,
  serverPath: "policy_lapse.csv",
  form: { input_file: "policy_lapse.csv" },
  running: false,
  runError: null,
  runFieldErrors: [],
}
vi.mock("@/store/AppStore", () => ({ useApp: () => mockApp }))

// ── Mock the API client so /explain returns the v1.0 structured stub. ──────────
const STUB: ExplainResponse = {
  status: "unavailable",
  schema_version: "1.0",
  model: "RandomForest",
  sample_index: 0,
  method: null,
  shap_values: null,
  base_value: null,
  reason: "no_persisted_model",
  message: "Single-row SHAP explanations require a fitted model … deferred to v2.0 …",
}
const explainMock = vi.fn(async () => STUB)
vi.mock("@/api/client", () => ({
  explain: (...args: unknown[]) => explainMock(...args),
  outputUrl: (name: string) => `/api/v1/outputs/${name}`,
  // ApiError is referenced by Explainability's catch — provide a minimal stand-in.
  ApiError: class ApiError extends Error {},
}))

import Overview from "./Overview"
import Explainability from "./Explainability"
import SetupGuide from "./SetupGuide"
import RiskRegister from "./RiskRegister"

const binary = binaryEnvelope as unknown as RunResponse

const DEFAULT_APP = {
  result: null as RunResponse | null,
  serverPath: "policy_lapse.csv" as string | null,
  form: { input_file: "policy_lapse.csv" },
  running: false,
  runError: null as string | null,
  runFieldErrors: [] as string[],
}

beforeEach(() => {
  mockApp = { ...DEFAULT_APP }
  explainMock.mockClear()
})
afterEach(() => {
  vi.clearAllMocks()
})

function renderPage(ui: ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

describe("Navigation (post-merge)", () => {
  it("has exactly 12 items and no Pipeline entry", () => {
    // 12 after the 9c merge + the Phase 12 "Tuning Results" page = 13, minus the
    // temporarily-hidden Explainability entry (unwire.md #3, backend not implemented) = 12.
    expect(NAV_ITEMS).toHaveLength(12)
    expect(NAV_ITEMS.some((i) => i.path === "/pipeline")).toBe(false)
    expect(NAV_ITEMS.some((i) => i.label === "Pipeline")).toBe(false)
  })

  it("includes the reference pages as real routes", () => {
    const paths = NAV_ITEMS.map((i) => i.path)
    expect(paths).toContain("/setup")
    expect(paths).toContain("/risks")
    // TEMPORARILY HIDDEN — explainability is unwired from the nav until the backend
    // lands (see unwire.md #3). The page component + /explain client stay intact.
    expect(paths).not.toContain("/explainability")
  })
})

describe("Merged Overview", () => {
  it("shows the in-progress state while a run is running", () => {
    mockApp = { ...DEFAULT_APP, running: true }
    renderPage(<Overview />)
    expect(screen.getByText(/Running the full pipeline/i)).toBeInTheDocument()
    // The pipeline stages are listed honestly (no fake live log).
    expect(screen.getByText(/Train \+ evaluate every model/i)).toBeInTheDocument()
  })

  it("shows the results summary once a run completes", () => {
    mockApp = { ...DEFAULT_APP, result: binary }
    renderPage(<Overview />)
    expect(screen.getByText(/Model scoreboard/i)).toBeInTheDocument()
    expect(screen.getByText(/Model comparison/i)).toBeInTheDocument()
    // Artifacts + raw envelope (the old Pipeline content) carried over.
    expect(screen.getByText(/Artifacts \(/)).toBeInTheDocument()
  })

  it("shows a validation error distinctly", () => {
    mockApp = {
      ...DEFAULT_APP,
      runError: "bad config",
      runFieldErrors: ["target: required"],
    }
    renderPage(<Overview />)
    expect(screen.getByText(/Invalid configuration \(422\)/i)).toBeInTheDocument()
  })
})

describe("Explainability (v1.0 stub)", () => {
  it("invites a run when there is no result yet", () => {
    mockApp = { ...DEFAULT_APP, result: null }
    renderPage(<Explainability />)
    expect(screen.getByText(/No run yet/i)).toBeInTheDocument()
  })

  it("renders honestly and triggers the /explain call without crashing on null fields", async () => {
    mockApp = { ...DEFAULT_APP, result: binary }
    renderPage(<Explainability />)

    // Honest framing is shown up front.
    expect(screen.getByText(/Explainability is coming in v2.0/i)).toBeInTheDocument()

    // Hitting Explain calls the real client and shows the structured stub.
    fireEvent.click(screen.getByRole("button", { name: /Explain/i }))
    await waitFor(() => expect(explainMock).toHaveBeenCalledTimes(1))
    // The unavailable status + the server's own reason are surfaced.
    expect(await screen.findByText("unavailable")).toBeInTheDocument()
    expect(screen.getByText(/no_persisted_model/)).toBeInTheDocument()
    // The reserved waterfall region renders (intentional, not broken) once the
    // null-field stub is in hand.
    expect(screen.getByText(/SHAP waterfall/i)).toBeInTheDocument()
  })
})

describe("Setup Guide", () => {
  it("renders the key sections", () => {
    renderPage(<SetupGuide />)
    expect(screen.getByText(/Architecture/i)).toBeInTheDocument()
    expect(screen.getByText(/The run flow/i)).toBeInTheDocument()
    expect(screen.getByText(/API reference/i)).toBeInTheDocument()
    expect(screen.getByText(/Honest v1.0 limitations/i)).toBeInTheDocument()
    // The 6 endpoints are listed.
    expect(screen.getByText("/api/v1/run")).toBeInTheDocument()
  })
})

describe("Risk Register", () => {
  it("renders the risks and the governance checklist", () => {
    renderPage(<RiskRegister />)
    expect(screen.getByText(/Data leakage/i)).toBeInTheDocument()
    expect(screen.getByText(/Class imbalance/i)).toBeInTheDocument()
    expect(screen.getByText(/Governance checklist/i)).toBeInTheDocument()
    // Every risk shows a mitigation column.
    expect(screen.getAllByText(/Mitigation/i).length).toBeGreaterThan(0)
  })
})
