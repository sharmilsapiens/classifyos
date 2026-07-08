/* Runs page (schema 1.10, Interim 2a) — MLflow read-path list + reload.

   jsdom smoke tests over a mocked store + API client (no live server):
     • lists past runs from GET /runs and shows their summary fields + the tracking store;
     • a reloadable run's Load → api.loadRun → applyReloadedRun(envelope) → navigate("/");
     • a non-reloadable run's Load is disabled;
     • a failed list shows the error state (with retry);
     • an empty store shows the empty state. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import type { ReactElement } from "react"

import type { RunResponse, RunsListResponse } from "@/api/types"

// ── Store mock — the page only needs applyReloadedRun. ─────────────────────────
const applyReloadedRun = vi.fn()
vi.mock("@/store/AppStore", () => ({ useApp: () => ({ applyReloadedRun }) }))

// ── Router mock — capture navigate() while keeping the real MemoryRouter. ──────
const navigate = vi.fn()
vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useNavigate: () => navigate,
}))

// ── API client mock. ──────────────────────────────────────────────────────────
const listRunsMock = vi.fn()
const loadRunMock = vi.fn()
vi.mock("@/api/client", () => ({
  listRuns: () => listRunsMock(),
  loadRun: (id: string) => loadRunMock(id),
  ApiError: class ApiError extends Error {},
}))

import { ApiError } from "@/api/client"
import Runs from "./Runs"

const RELOADABLE = {
  run_id: "aaaa1111bbbb2222cccc",
  experiment_id: "1",
  experiment_name: "classifyos",
  run_name: "spirited-hog-42",
  status: "FINISHED",
  start_time: "2026-07-08T18:16:30.472000+00:00",
  end_time: "2026-07-08T18:16:46.481000+00:00",
  target: "will_lapse",
  problem_type: "binary",
  input_file: "policy_lapse.csv",
  algorithms: ["LogisticRegression", "XGBoost"],
  models_logged: 2,
  best_metric: "f1_weighted",
  best_value: 0.713,
  best_model: "XGBoost",
  reloadable: true,
}
const NOT_RELOADABLE = { ...RELOADABLE, run_id: "dddd3333", run_name: "cli-run", reloadable: false }

function listResponse(runs: unknown[]): RunsListResponse {
  return {
    schema_version: "1.10",
    tracking_uri: "postgresql://classifyos@localhost:5432/mlflow",
    runs: runs as RunsListResponse["runs"],
  }
}

beforeEach(() => {
  listRunsMock.mockReset()
  loadRunMock.mockReset()
  applyReloadedRun.mockReset()
  navigate.mockReset()
})
afterEach(() => vi.clearAllMocks())

function renderPage(ui: ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

describe("Runs — list", () => {
  it("lists past runs with their summary fields and the tracking store", async () => {
    listRunsMock.mockResolvedValue(listResponse([RELOADABLE]))
    renderPage(<Runs />)

    expect(await screen.findByText("spirited-hog-42")).toBeInTheDocument()
    expect(screen.getByText("will_lapse")).toBeInTheDocument()
    expect(screen.getByText("0.713")).toBeInTheDocument() // best F1 via fmtMetric
    expect(screen.getByText("FINISHED")).toBeInTheDocument()
    expect(screen.getByText(/postgresql:\/\/classifyos@localhost:5432\/mlflow/)).toBeInTheDocument()
  })

  it("shows the empty state when no runs exist", async () => {
    listRunsMock.mockResolvedValue(listResponse([]))
    renderPage(<Runs />)
    expect(await screen.findByText(/No past runs yet/i)).toBeInTheDocument()
  })

  it("shows the error state when the store is unreachable", async () => {
    listRunsMock.mockRejectedValue(new ApiError("MLflow tracking store unavailable"))
    renderPage(<Runs />)
    expect(await screen.findByText(/Couldn.t load runs/i)).toBeInTheDocument()
    expect(screen.getByText(/MLflow tracking store unavailable/i)).toBeInTheDocument()
  })
})

describe("Runs — reload", () => {
  it("reloads a run into the store and navigates to Overview", async () => {
    listRunsMock.mockResolvedValue(listResponse([RELOADABLE]))
    const envelope: RunResponse = {
      status: "ok",
      schema_version: "1.10",
      result: null,
      error: null,
    }
    loadRunMock.mockResolvedValue(envelope)
    renderPage(<Runs />)

    const loadBtn = await screen.findByRole("button", { name: /^Load$/i })
    fireEvent.click(loadBtn)

    await waitFor(() => expect(loadRunMock).toHaveBeenCalledWith(RELOADABLE.run_id))
    expect(applyReloadedRun).toHaveBeenCalledWith(envelope)
    expect(navigate).toHaveBeenCalledWith("/")
  })

  it("disables Load for a run with no reloadable snapshot", async () => {
    listRunsMock.mockResolvedValue(listResponse([NOT_RELOADABLE]))
    renderPage(<Runs />)
    const loadBtn = await screen.findByRole("button", { name: /^Load$/i })
    expect(loadBtn).toBeDisabled()
  })
})
