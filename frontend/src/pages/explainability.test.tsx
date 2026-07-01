/* Explainability (per-row SHAP) — store-driven render tests.

   The rewired page reads `result.explanations` (schema 1.6) from the store — no
   /explain network call — and draws a SHAP waterfall. Three states are covered:
   no run, explainability-off (block absent), and a rendered waterfall. */

import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"

import type { RunResponse } from "@/api/types"

// Mock the store; each test sets the slice the page (via ResultGate) reads.
let mockApp: { result: RunResponse | null; serverPath: string | null } = {
  result: null,
  serverPath: "policy_lapse.csv",
}
vi.mock("@/store/AppStore", () => ({ useApp: () => mockApp }))

import Explainability from "./Explainability"

/** A minimal /run envelope carrying a per-row SHAP explanations block. */
function envelopeWithExplanations(): RunResponse {
  return {
    status: "ok",
    schema_version: "1.6",
    error: null,
    result: {
      explanations: {
        RandomForest: {
          method: "shap.TreeExplainer",
          rows: [
            {
              sample_index: 0,
              explained_class: "1",
              base_value: 0.3,
              prediction: 0.62,
              contributions: { num_late_payments: 0.25, policy_tenure_years: 0.07 },
            },
          ],
        },
        LogisticRegression: {
          method: "shap.KernelExplainer",
          rows: [
            {
              sample_index: 0,
              explained_class: "1",
              base_value: 0.28,
              prediction: 0.4,
              contributions: { annual_premium: -0.1, age: 0.22 },
            },
          ],
        },
      },
    },
  } as unknown as RunResponse
}

function renderPage() {
  return render(
    <MemoryRouter>
      <Explainability />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  mockApp = { result: null, serverPath: "policy_lapse.csv" }
})

describe("Explainability (per-row SHAP)", () => {
  it("invites a run when there is no result yet", () => {
    renderPage()
    expect(screen.getByText(/No run yet/i)).toBeInTheDocument()
  })

  it("says explainability was not computed when the block is absent (OFF)", () => {
    mockApp = {
      result: { result: { explanations: null } } as unknown as RunResponse,
      serverPath: "policy_lapse.csv",
    }
    renderPage()
    expect(screen.getByText(/was not computed for this run/i)).toBeInTheDocument()
  })

  it("renders a SHAP waterfall from the store block", () => {
    mockApp = { result: envelopeWithExplanations(), serverPath: "policy_lapse.csv" }
    renderPage()

    // The explainer used for the default (first) model is surfaced as a badge.
    expect(screen.getByText("shap.TreeExplainer")).toBeInTheDocument()
    // Feature contributions render (a couple of the RandomForest row's features).
    expect(screen.getByText("num_late_payments")).toBeInTheDocument()
    expect(screen.getByText("policy_tenure_years")).toBeInTheDocument()
    // The additive framing is present.
    expect(screen.getByText(/base value \+ all contributions = prediction/i)).toBeInTheDocument()
  })

  it("switches models via the picker (kernel explainer path)", () => {
    mockApp = { result: envelopeWithExplanations(), serverPath: "policy_lapse.csv" }
    renderPage()

    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "LogisticRegression" } })
    expect(screen.getByText("shap.KernelExplainer")).toBeInTheDocument()
    expect(screen.getByText("annual_premium")).toBeInTheDocument()
  })
})
