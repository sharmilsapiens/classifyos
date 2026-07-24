/* Explainability (per-row SHAP) — store-driven render tests.

   The rewired page reads `result.explanations` (schema 1.6) from the store — no
   /explain network call — and draws a SHAP waterfall. Three states are covered:
   no run, explainability-off (block absent), and a rendered waterfall. */

import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"

import type { RunResponse } from "@/api/types"

// Mock the store; each test sets the slice the page (via ResultGate + useAutoNarrate) reads.
let mockApp: {
  result: RunResponse | null
  serverPath: string | null
  databricksPat: string
  applyReloadedRun: ReturnType<typeof vi.fn>
} = {
  result: null,
  serverPath: "policy_lapse.csv",
  databricksPat: "",
  applyReloadedRun: vi.fn(),
}
vi.mock("@/store/AppStore", () => ({ useApp: () => mockApp }))

// Mock the API client: capture narrateRun calls, keep a real-ish runScopedArtifactId (returns the
// run id ONLY for a databricks-backed run, exactly like the real one) so the auto-narrate gate works.
const narrateRunMock = vi.fn()
vi.mock("@/api/client", () => ({
  narrateRun: (...args: unknown[]) => narrateRunMock(...args),
  runScopedArtifactId: (m: { run_id?: string; tracking_uri?: string } | null | undefined) =>
    m?.run_id && m.tracking_uri?.startsWith("databricks") ? m.run_id : undefined,
}))

import Explainability from "./Explainability"

/** A minimal /run envelope carrying a per-row SHAP explanations block. */
function envelopeWithExplanations(): RunResponse {
  return {
    status: "ok",
    schema_version: "1.8",
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
              // schema 1.8: raw value per feature — one resolved (shows "= 3"), one null (plain).
              feature_values: { num_late_payments: "3", policy_tenure_years: null },
              narrative:
                "This policy is flagged high lapse risk chiefly due to a high number of late payments.",
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
  mockApp = {
    result: null,
    serverPath: "policy_lapse.csv",
    databricksPat: "",
    applyReloadedRun: vi.fn(),
  }
  narrateRunMock.mockReset()
})

/** A databricks-backed envelope (mlflow.tracking_uri="databricks…") with explanations. */
function databricksEnvelope(withNarrative: boolean): RunResponse {
  const env = envelopeWithExplanations()
  env.result!.mlflow = {
    run_id: "abc123def456",
    experiment_id: "e1",
    tracking_uri: "databricks",
    models: {},
  }
  if (!withNarrative) {
    // strip the seeded narrative so the page must fetch it
    env.result!.explanations!.RandomForest.rows[0].narrative = undefined
  }
  return env
}

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
    // Feature contributions render. A resolved feature shows its raw value ("feature = value",
    // schema 1.8); a null-valued feature falls back to the plain feature name.
    expect(screen.getByText("num_late_payments = 3")).toBeInTheDocument()
    expect(screen.getByText("policy_tenure_years")).toBeInTheDocument()
    // The additive framing is present.
    expect(screen.getByText(/base value \+ all contributions = prediction/i)).toBeInTheDocument()
    // The LLM reason-code narrative (schema 1.7) renders when present on the row.
    expect(screen.getByText(/LLM reason-code narrative/i)).toBeInTheDocument()
    expect(screen.getByText(/high number of late payments/i)).toBeInTheDocument()
  })

  it("omits the narrative panel when a row has no narrative (SHAP-only)", () => {
    mockApp = { result: envelopeWithExplanations(), serverPath: "policy_lapse.csv" }
    renderPage()
    // The LogisticRegression row carries no narrative → the panel is absent for it.
    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "LogisticRegression" } })
    expect(screen.queryByText(/LLM reason-code narrative/i)).not.toBeInTheDocument()
  })

  it("switches models via the picker (kernel explainer path)", () => {
    mockApp = { ...mockApp, result: envelopeWithExplanations() }
    renderPage()

    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "LogisticRegression" } })
    expect(screen.getByText("shap.KernelExplainer")).toBeInTheDocument()
    expect(screen.getByText("annual_premium")).toBeInTheDocument()
  })

  it("auto-narrates a databricks-backed run that has no narratives, then swaps in the result", async () => {
    const applyReloadedRun = vi.fn()
    const narrated = databricksEnvelope(true) // the narrated envelope the server returns
    narrateRunMock.mockResolvedValue(narrated)
    mockApp = {
      ...mockApp,
      result: databricksEnvelope(false), // explanations present, narratives absent
      databricksPat: "dapi-xyz",
      applyReloadedRun,
    }
    renderPage()

    // The page calls POST /runs/{id}/narrate with the run id + the caller's PAT...
    await waitFor(() => expect(narrateRunMock).toHaveBeenCalledWith("abc123def456", "dapi-xyz"))
    // ...and swaps the narrated envelope into the store so every result page shows it.
    await waitFor(() => expect(applyReloadedRun).toHaveBeenCalledWith(narrated))
  })

  it("does NOT auto-narrate a local run (already narrated in-process)", async () => {
    mockApp = { ...mockApp, result: envelopeWithExplanations() } // no mlflow block → local
    renderPage()
    await new Promise((r) => setTimeout(r, 0))
    expect(narrateRunMock).not.toHaveBeenCalled()
  })

  it("does NOT auto-narrate when narratives are already present (databricks reload)", async () => {
    mockApp = { ...mockApp, result: databricksEnvelope(true), databricksPat: "dapi" }
    renderPage()
    await new Promise((r) => setTimeout(r, 0))
    expect(narrateRunMock).not.toHaveBeenCalled()
  })
})
