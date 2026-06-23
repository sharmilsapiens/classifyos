/* Render-level tests for the Phase 12 "Tuning Results" page.

   The page consumes the schema-1.1 `result.tuning` block straight from the store
   (no network call). Like the other 9b/9c page tests these are smoke-level (jsdom),
   asserting the contract-driven DOM. Covered:
   • TUNING ON  — one section per tuned model with the right param values + the
     settings header strip; untuned run models shown as "ran on defaults".
   • Empty best_params ({}) for a tuned model → "no params returned" note.
   • TUNING OFF — a `tuning: null` run renders the "not enabled" state, not a crash.
   • NO RUN     — the friendly empty state.
   • NAV + ROUTE — the new "Tuning Results" entry exists and /tuning resolves. */

import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"

import binaryEnvelope from "@/test/fixtures/run_envelope.json"
import type { RunResponse, RunTuning } from "@/api/types"
import { NAV_ITEMS } from "@/lib/nav"

// Mock the store so the page (and the full App shell, for the route test) see a
// chosen result. The name must start with "mock" for the hoisted vi.mock factory.
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
import TuningResults from "./TuningResults"
import App from "../App"

const binary = binaryEnvelope as unknown as RunResponse

/** A 1.1 envelope: clone the binary fixture and attach a tuning block. */
function withTuning(tuning: RunTuning | null): RunResponse {
  const env = JSON.parse(JSON.stringify(binary)) as RunResponse
  env.schema_version = "1.1"
  env.result!.tuning = tuning
  return env
}

const TUNED: RunTuning = {
  enabled: true,
  metric: "f1_weighted",
  cv: true,
  cv_folds: 3,
  n_trials: 30,
  timeout_seconds: 600,
  // The binary fixture has LogisticRegression + RandomForest; tune only RF so LR
  // demonstrates the "ran on defaults" note.
  tuned_models: ["RandomForest"],
  best_params: {
    RandomForest: {
      n_estimators: 450,
      max_depth: 6,
      learning_rate: 0.07,
      bootstrap: true,
      criterion: "gini",
    },
  },
}

const BASE = {
  serverPath: "policy_lapse.csv",
  apiStatus: "online",
  apiMessage: "API connected",
  checkAPI: () => {},
}

beforeEach(() => {
  mockApp = { ...BASE, result: null }
})

function renderPage(result: RunResponse | null) {
  mockApp = { ...BASE, result }
  return render(
    <MemoryRouter>
      <TuningResults />
    </MemoryRouter>,
  )
}

describe("Tuning Results — tuning ON", () => {
  beforeEach(() => renderPage(withTuning(TUNED)))

  it("renders the settings header strip", () => {
    expect(screen.getByText("Tuning settings")).toBeInTheDocument()
    expect(screen.getByText("f1_weighted")).toBeInTheDocument()
    expect(screen.getByText("3-fold")).toBeInTheDocument()
    expect(screen.getByText("30")).toBeInTheDocument()
    expect(screen.getByText("600s")).toBeInTheDocument()
  })

  it("renders one card per tuned model with its chosen param values", () => {
    // The tuned model + its hyperparameter values (each defensively stringified).
    expect(screen.getAllByText("RandomForest").length).toBeGreaterThan(0)
    expect(screen.getByText("n_estimators")).toBeInTheDocument()
    expect(screen.getByText("450")).toBeInTheDocument()
    expect(screen.getByText("max_depth")).toBeInTheDocument()
    expect(screen.getByText("6")).toBeInTheDocument()
    expect(screen.getByText("0.07")).toBeInTheDocument()
    expect(screen.getByText("true")).toBeInTheDocument() // a boolean param
    expect(screen.getByText("gini")).toBeInTheDocument() // a string param
  })

  it("lists run models that were not tuned as 'ran on defaults'", () => {
    expect(screen.getByText(/Ran on default hyperparameters/i)).toBeInTheDocument()
    expect(screen.getByText("LogisticRegression")).toBeInTheDocument()
  })
})

describe("Tuning Results — edge cases", () => {
  it("shows a 'no params returned' note for a tuned model with empty best_params", () => {
    const t: RunTuning = { ...TUNED, tuned_models: ["RandomForest"], best_params: { RandomForest: {} } }
    renderPage(withTuning(t))
    expect(screen.getByText(/No params returned — used defaults/i)).toBeInTheDocument()
  })

  it("handles a null timeout (the per-model cap opt-out) without crashing", () => {
    renderPage(withTuning({ ...TUNED, timeout_seconds: null }))
    expect(screen.getByText("none")).toBeInTheDocument()
  })
})

describe("Tuning Results — tuning OFF / no run", () => {
  it("renders the 'not enabled' state when tuning is null", () => {
    renderPage(withTuning(null))
    expect(screen.getByText(/Tuning was not enabled for this run/i)).toBeInTheDocument()
    // Points the user at Configuration, never a dead end.
    expect(screen.getByText(/Open Configuration/i)).toBeInTheDocument()
  })

  it("renders the 'not enabled' state when enabled:false", () => {
    renderPage(withTuning({ ...TUNED, enabled: false }))
    expect(screen.getByText(/Tuning was not enabled for this run/i)).toBeInTheDocument()
  })

  it("renders the friendly empty state when there is no run", () => {
    renderPage(null)
    expect(screen.getByText(/No run yet/i)).toBeInTheDocument()
  })
})

describe("Tuning Results — nav + routing", () => {
  it("has a 'Tuning Results' nav entry pointing at /tuning in the Results group", () => {
    const item = NAV_ITEMS.find((i) => i.path === "/tuning")
    expect(item).toBeDefined()
    expect(item!.label).toBe("Tuning Results")
    expect(item!.group).toBe("Results")
  })

  it("resolves the /tuning route inside the app shell", () => {
    mockApp = { ...BASE, result: withTuning(TUNED) }
    render(
      <MemoryRouter initialEntries={["/tuning"]}>
        <App />
      </MemoryRouter>,
    )
    // The page heading renders (h1 from PageHeader). Sidebar also has the label,
    // so scope to the heading role to prove the route mounted the page.
    expect(screen.getByRole("heading", { name: /Tuning Results/i, level: 1 })).toBeInTheDocument()
  })
})
