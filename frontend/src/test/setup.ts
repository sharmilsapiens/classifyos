// Vitest setup — runs before every test file (see vite.config.ts → test.setupFiles).
// Registers @testing-library/jest-dom's matchers (e.g. toBeInTheDocument) on
// Vitest's `expect`, and their TypeScript types.
import "@testing-library/jest-dom/vitest"

import { afterEach } from "vitest"
import { cleanup } from "@testing-library/react"

// We run with Vitest globals OFF (we import describe/it/expect explicitly), so
// React Testing Library's automatic DOM cleanup isn't auto-registered. Register
// it here so each test starts with a fresh DOM (no leaked renders between tests).
afterEach(() => cleanup())

// jsdom has no ResizeObserver, which Recharts' ResponsiveContainer needs. Provide
// a no-op stub so chart-bearing pages render in tests (the chart body stays empty
// at 0×0 — our render tests assert on the surrounding DOM, not chart internals).
if (!("ResizeObserver" in globalThis)) {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  ;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverStub
}
