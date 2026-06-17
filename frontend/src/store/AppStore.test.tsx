import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"

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
