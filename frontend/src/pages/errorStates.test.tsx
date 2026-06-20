/* Error / empty-state coverage (Phase 10 gap fill).

   The render tests (resultPages/referencePages) cover the happy results and the
   422 validation path on Overview. These fill the remaining UI error paths the
   suite didn't assert:
     • Overview's 400 RUN-ERROR state (a run-time failure, NOT a 422) — shown as
       "Run failed" with the server's message, distinct from the validation case.
     • Upload's error surface — a failed /upload renders the ErrorState message
       (the typed ApiError message), not a blank screen.

   Both run in jsdom against mocked store/client (no live server needed). */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import type { ReactElement } from "react"

import type { RunResponse } from "@/api/types"

// ── Mutable store mock shared by both pages (each test sets the slice it needs). ──
type MockApp = {
  // Overview reads:
  running: boolean
  result: RunResponse | null
  runError: string | null
  runFieldErrors: string[]
  serverPath: string | null
  // Upload reads:
  inspect: unknown
  form: { target: string }
  applyUpload: ReturnType<typeof vi.fn>
  updateForm: ReturnType<typeof vi.fn>
}
let mockApp: MockApp
vi.mock("@/store/AppStore", () => ({ useApp: () => mockApp }))

// ── Mock the API client so Upload's /upload call can be made to fail. ──────────
// The factory must not reference outer top-level variables (it is hoisted and
// runs before they initialize), so ApiError is declared INLINE here and imported
// below for use in the tests; uploadMock is reached lazily via a closure.
const uploadMock = vi.fn()
vi.mock("@/api/client", () => ({
  upload: (...args: unknown[]) => uploadMock(...args),
  ApiError: class ApiError extends Error {},
}))

import { ApiError } from "@/api/client"
import Overview from "./Overview"
import UploadPage from "./Upload"

function freshApp(): MockApp {
  return {
    running: false,
    result: null,
    runError: null,
    runFieldErrors: [],
    serverPath: null,
    inspect: null,
    form: { target: "" },
    applyUpload: vi.fn(),
    updateForm: vi.fn(),
  }
}

beforeEach(() => {
  mockApp = freshApp()
  uploadMock.mockReset()
})
afterEach(() => vi.clearAllMocks())

function renderPage(ui: ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

describe("Overview — run-error (400) state", () => {
  it("shows 'Run failed' with the server message when the error is NOT a validation error", () => {
    mockApp = {
      ...freshApp(),
      runError: "FileNotFoundError: missing.csv",
      runFieldErrors: [], // no field errors → a run error, not a 422
    }
    renderPage(<Overview />)

    expect(screen.getByText(/Run failed/i)).toBeInTheDocument()
    expect(screen.getByText(/missing\.csv/)).toBeInTheDocument()
    // It must NOT be presented as a validation error.
    expect(screen.queryByText(/Invalid configuration \(422\)/i)).not.toBeInTheDocument()
    // And it offers a way back to fix the config.
    expect(screen.getByRole("link", { name: /Back to Configuration/i })).toBeInTheDocument()
  })
})

describe("Upload — error surface", () => {
  it("renders the ApiError message when /upload fails (no blank screen)", async () => {
    uploadMock.mockRejectedValue(new ApiError("Upload failed — unsupported file type"))
    renderPage(<UploadPage />)

    // Select a file → triggers doUpload → the mocked client rejects.
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(["a,b\n1,2"], "bad.txt", { type: "text/plain" })
    fireEvent.change(fileInput, { target: { files: [file] } })

    await waitFor(() =>
      expect(screen.getByText(/Upload failed — unsupported file type/i)).toBeInTheDocument(),
    )
    expect(uploadMock).toHaveBeenCalledTimes(1)
  })
})
