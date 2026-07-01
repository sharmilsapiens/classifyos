/* Render-level smoke tests for the 9c pages + the Overview/Pipeline merge + nav.

   Like the 9b tests these are smoke-level (jsdom; chart internals don't render),
   asserting the contract-driven DOM around each page. True browser E2E — incl. the
   unverified multilabel path — remains Phase 10/11.

   Covers:
   • Setup Guide / Risk Register — render without crashing; key sections present.
   • Merged Overview — the in-progress state AND the results state from a fixture.
   • Nav — items, no dangling "Pipeline" entry. (Explainability now has its own
     explainability.test.tsx — it reads result.explanations from the store.) */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import type { ReactElement } from "react"

import binaryEnvelope from "@/test/fixtures/run_envelope.json"
import type { RunResponse } from "@/api/types"
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

import Overview from "./Overview"
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
})
afterEach(() => {
  vi.clearAllMocks()
})

function renderPage(ui: ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

describe("Navigation (post-merge)", () => {
  it("has exactly 14 items and no Pipeline entry", () => {
    // 12 after the 9c merge + "Tuning Results" (Phase 12) + "Train vs Test" (Fit
    // Diagnostics) = 13, + Explainability re-wired (real per-row SHAP via /run,
    // schema 1.6 — unwire.md #3 restored) = 14.
    expect(NAV_ITEMS).toHaveLength(14)
    expect(NAV_ITEMS.some((i) => i.path === "/pipeline")).toBe(false)
    expect(NAV_ITEMS.some((i) => i.label === "Pipeline")).toBe(false)
  })

  it("includes the reference pages as real routes", () => {
    const paths = NAV_ITEMS.map((i) => i.path)
    expect(paths).toContain("/setup")
    expect(paths).toContain("/risks")
    // Explainability is back in the nav now that per-row SHAP ships via /run.
    expect(paths).toContain("/explainability")
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
