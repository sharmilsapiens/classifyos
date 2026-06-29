/* Render-level tests for the "Train vs Test" (Fit Diagnostics) page.

   The page consumes result.models[].train (schema 1.2) straight from the store. The
   captured binary fixture predates 1.2, so we inject a train block to drive the
   verdicts. Smoke-level (jsdom) like the other result-page tests — chart internals
   don't render, so assertions target the surrounding DOM. Covered:
   • A clear overfitting model (train ≫ test) → "Overfitting" verdict.
   • A good-fit model (train ≈ test) → "Good fit".
   • An underfitting model (low train F1) → "Underfitting".
   • NO TRAIN BLOCK — the honest "no train-side metrics" fallback (no crash).
   • NO RUN — the friendly empty state.
   • NAV + ROUTE — the "Train vs Test" entry exists and /diagnostics resolves. */

import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"

import binaryEnvelope from "@/test/fixtures/run_envelope.json"
import type { ModelMetrics, RunResponse, TrainMetrics } from "@/api/types"
import { NAV_ITEMS } from "@/lib/nav"

let mockApp: {
  result: RunResponse | null
  serverPath: string | null
  apiStatus: string
  apiMessage: string
  checkAPI: () => void
} = {
  result: null,
  serverPath: "policy_lapse.csv",
  apiStatus: "online",
  apiMessage: "API connected",
  checkAPI: () => {},
}
vi.mock("@/store/AppStore", () => ({ useApp: () => mockApp }))

// Imported AFTER the mock is declared.
import FitDiagnostics from "./FitDiagnostics"
import App from "../App"

const binary = binaryEnvelope as unknown as RunResponse

/** Build a full TrainMetrics block from a single F1 (other fields mirror it loosely). */
function train(f1: number): TrainMetrics {
  return {
    accuracy: f1,
    f1_weighted: f1,
    f1_macro: f1,
    precision_weighted: f1,
    recall_weighted: f1,
    roc_auc: f1,
    pr_auc: f1,
    log_loss: 0.3,
    mcc: f1 - 0.1,
  }
}

/** Clone the binary fixture and give its models explicit test/train F1 values. */
function withTrain(specs: Array<{ testF1: number; trainF1: number }>): RunResponse {
  const env = JSON.parse(JSON.stringify(binary)) as RunResponse
  env.schema_version = "1.2"
  const models = env.result!.models
  specs.forEach((s, i) => {
    const m = models[i] as ModelMetrics
    m.status = "ok"
    m.f1_weighted = s.testF1
    m.train = train(s.trainF1)
  })
  // Drop any extra models so the asserted verdicts are exactly the ones we set.
  env.result!.models = models.slice(0, specs.length)
  return env
}

function renderPage(result: RunResponse | null) {
  mockApp = { ...mockApp, result, serverPath: "policy_lapse.csv" }
  return render(
    <MemoryRouter>
      <FitDiagnostics />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  mockApp = {
    result: null,
    serverPath: null,
    apiStatus: "online",
    apiMessage: "API connected",
    checkAPI: () => {},
  }
})

describe("Train vs Test page", () => {
  it("flags a clear overfitting model (train ≫ test)", () => {
    renderPage(withTrain([{ testF1: 0.6, trainF1: 0.95 }]))
    expect(screen.getByText("Overfitting")).toBeInTheDocument()
  })

  it("reports a good fit when train ≈ test", () => {
    renderPage(withTrain([{ testF1: 0.86, trainF1: 0.88 }]))
    expect(screen.getByText("Good fit")).toBeInTheDocument()
  })

  it("flags underfitting when train F1 is low", () => {
    renderPage(withTrain([{ testF1: 0.55, trainF1: 0.58 }]))
    expect(screen.getByText("Underfitting")).toBeInTheDocument()
  })

  it("renders the per-metric breakdown (test/train/gap table)", () => {
    renderPage(withTrain([{ testF1: 0.6, trainF1: 0.9 }]))
    expect(screen.getByText(/Train vs test · per metric/i)).toBeInTheDocument()
    // The bounded metrics all appear as table rows / chart-legend labels.
    expect(screen.getAllByText(/ROC-AUC/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/Log loss/i)).toBeInTheDocument()
  })

  it("shows the honest fallback when no train block is present", () => {
    // The raw binary fixture predates 1.2 → no models[].train.
    renderPage(binary)
    expect(screen.getByText(/no train-side metrics to compare/i)).toBeInTheDocument()
  })

  it("shows the friendly empty state when there is no run", () => {
    renderPage(null)
    expect(screen.getByText(/No run yet|No run/i)).toBeInTheDocument()
  })
})

describe("nav + route", () => {
  it('exposes a "Train vs Test" nav entry pointing at /diagnostics', () => {
    const item = NAV_ITEMS.find((n) => n.path === "/diagnostics")
    expect(item).toBeDefined()
    expect(item!.label).toBe("Train vs Test")
    expect(item!.group).toBe("Results")
  })

  it("resolves /diagnostics through the App router", () => {
    mockApp = { ...mockApp, result: withTrain([{ testF1: 0.6, trainF1: 0.9 }]), serverPath: "policy_lapse.csv" }
    render(
      <MemoryRouter initialEntries={["/diagnostics"]}>
        <App />
      </MemoryRouter>,
    )
    expect(screen.getByText(/Fit verdict · all models/i)).toBeInTheDocument()
  })
})
