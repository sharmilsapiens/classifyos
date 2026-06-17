/* Render-level smoke tests for the 9b result pages.

   These mount each page with a REAL captured /run envelope (binary AND
   multiclass fixtures) and assert the page renders the expected, contract-driven
   DOM around the charts. They are smoke-level by design — true browser E2E
   across all 7 insurance use cases (incl. the unverified multilabel path) is
   Phase 10/11. Chart internals don't render in jsdom (0×0 ResponsiveContainer),
   so assertions target surrounding DOM (headers, tables, aria-labels, banners). */

import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import type { ReactElement } from "react"

import binaryEnvelope from "@/test/fixtures/run_envelope.json"
import multiclassEnvelope from "@/test/fixtures/run_envelope_multiclass.json"
import type { RunResponse } from "@/api/types"

// Mock the store so each page sees a chosen result. (Vitest requires the name to
// start with "mock" to be referenced inside the hoisted vi.mock factory.)
let mockApp: { result: RunResponse | null; serverPath: string | null } = {
  result: null,
  serverPath: "policy_lapse.csv",
}
vi.mock("@/store/AppStore", () => ({
  useApp: () => mockApp,
}))

// Import pages AFTER the mock is declared.
import Overview from "./Overview"
import FeatureImpact from "./FeatureImpact"
import ConfusionMatrix from "./ConfusionMatrix"
import ClassReport from "./ClassReport"
import Curves from "./Curves"
import Predictions from "./Predictions"
import Interactions from "./Interactions"

const binary = binaryEnvelope as unknown as RunResponse
const multiclass = multiclassEnvelope as unknown as RunResponse

function renderPage(ui: ReactElement, result: RunResponse | null) {
  mockApp = { result, serverPath: "policy_lapse.csv" }
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

const PAGES: Array<[string, ReactElement]> = [
  ["Overview", <Overview />],
  ["FeatureImpact", <FeatureImpact />],
  ["ConfusionMatrix", <ConfusionMatrix />],
  ["ClassReport", <ClassReport />],
  ["Curves", <Curves />],
  ["Predictions", <Predictions />],
  ["Interactions", <Interactions />],
]

beforeEach(() => {
  mockApp = { result: null, serverPath: null }
})

describe("result pages render against fixtures", () => {
  it.each(PAGES)("%s renders with the binary fixture", (_name, ui) => {
    renderPage(ui, binary)
    // Each page has a heading; just assert no throw + a heading exists.
    expect(screen.getAllByRole("heading").length).toBeGreaterThan(0)
  })

  it.each(PAGES)("%s renders with the multiclass fixture", (_name, ui) => {
    renderPage(ui, multiclass)
    expect(screen.getAllByRole("heading").length).toBeGreaterThan(0)
  })

  it.each(PAGES)("%s shows a friendly empty state when there is no run", (_name, ui) => {
    renderPage(ui, null)
    expect(screen.getByText(/No run yet|No run/i)).toBeInTheDocument()
  })
})

describe("Feature Impact", () => {
  it("surfaces the id_like leakage warning when a flagged feature is present", () => {
    // Both fixtures have at least one id_like feature. "ID-like" shows both in
    // the warning banner and as a table badge, so assert at least one match.
    renderPage(<FeatureImpact />, binary)
    expect(screen.getAllByText(/ID-like/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/leakage, not signal/i)).toBeInTheDocument()
  })
})

describe("Predictions Table", () => {
  it("shows the sampled banner with the correct counts and a full-CSV link", () => {
    renderPage(<Predictions />, binary)
    const block = binary.result!.predictions
    // Counts use thousands separators (fmtInt): 200 and 1,200.
    expect(screen.getByText(block.rows_returned.toLocaleString("en-US"))).toBeInTheDocument()
    expect(screen.getByText(block.rows_total.toLocaleString("en-US"))).toBeInTheDocument()
    expect(screen.getByText(/Download full CSV/i)).toBeInTheDocument()
  })
})

describe("ROC / PR Curves", () => {
  it("renders a single positive-class curve for binary (AUC in the aria-label)", () => {
    renderPage(<Curves />, binary)
    const roc = screen.getByLabelText(/^ROC curve for/i)
    // binary → exactly one "AUC" entry in the accessible label.
    expect(roc.getAttribute("aria-label")).toMatch(/AUC/)
    expect((roc.getAttribute("aria-label")!.match(/AUC/g) ?? []).length).toBe(1)
  })

  it("renders one-vs-rest curves per class for multiclass", () => {
    renderPage(<Curves />, multiclass)
    const roc = screen.getByLabelText(/^ROC curve for/i)
    const label = roc.getAttribute("aria-label")!
    // multiclass risk_tier → High / Low / Medium, three AUC entries.
    expect(label).toContain("High")
    expect(label).toContain("Low")
    expect(label).toContain("Medium")
    expect((label.match(/AUC/g) ?? []).length).toBe(3)
  })
})

describe("failed-model handling", () => {
  it("renders a status:failed model row (greyed) without crashing the Overview", () => {
    // Clone the binary envelope and append a failed model.
    const withFailed = JSON.parse(JSON.stringify(binary)) as RunResponse
    withFailed.result!.models.push({
      name: "SVM",
      status: "failed",
      accuracy: null,
      f1_weighted: null,
      f1_macro: null,
      precision_weighted: null,
      recall_weighted: null,
      roc_auc: null,
      pr_auc: null,
      log_loss: null,
      mcc: null,
      error: "fit failed: out of memory",
    })
    renderPage(<Overview />, withFailed)
    // The failed model is shown (never silently dropped), marked failed. (The
    // merged Overview shows it in both the algorithm chips and the scoreboard.)
    expect(screen.getAllByText(/SVM/).length).toBeGreaterThan(0)
    expect(screen.getByText(/\(failed\)/i)).toBeInTheDocument()
  })
})
