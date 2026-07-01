/* Render-level tests for the Data Profile page.

   The page reads the inspection profile (with the additive column_profiles +
   correlation blocks) straight from the store — no network call. Covered:
   • HAS PROFILE — numeric stats, categorical frequency, datetime range, the
     missingness chart, and the correlation heatmap all render.
   • NO UPLOAD  — the friendly empty state with a link to Upload.
   • NAV + ROUTE — the "Data Profile" nav entry exists and /data-profile resolves. */

import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"

import type { InspectProfile } from "@/api/types"
import { NAV_ITEMS } from "@/lib/nav"

// Mock the store so the page sees a chosen inspect profile (or none).
let mockApp: { inspect: InspectProfile | null; apiStatus: string; apiMessage: string; checkAPI: () => void } = {
  inspect: null,
  apiStatus: "online",
  apiMessage: "API connected",
  checkAPI: () => {},
}
vi.mock("@/store/AppStore", () => ({ useApp: () => mockApp }))

// Recharts' ResponsiveContainer needs a measured size; jsdom has none. Stub it so
// children render with a fixed box (same pattern the other chart-page tests use).
vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts")
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactNode }) => (
      <div style={{ width: 600, height: 300 }}>{children}</div>
    ),
  }
})

import DataProfile from "./DataProfile"
import App from "../App"

const PROFILE: InspectProfile = {
  columns: ["age", "region", "joined"],
  dtypes: { age: "float64", region: "object", joined: "object" },
  numeric_cols: ["age"],
  categorical_cols: ["region"],
  binary_cols: [],
  datetime_cols: ["joined"],
  n_rows: 6,
  n_missing: { age: 1, region: 0, joined: 1 },
  sample: [],
  server_path: "uploads/policy_lapse.csv",
  profile_sampled: false,
  n_rows_profiled: 6,
  column_profiles: [
    {
      name: "age",
      dtype_group: "numeric",
      n_missing: 1,
      missing_pct: 16.7,
      n_unique: 5,
      stats: {
        count: 5, mean: 40, std: 15.8, min: 20, p25: 30, median: 40, p75: 50, max: 60, mode: 20, skew: 0,
      },
      histogram: { bin_edges: [20, 30, 40, 50, 60], counts: [1, 1, 1, 2] },
    },
    {
      name: "region",
      dtype_group: "categorical",
      n_missing: 0,
      missing_pct: 0,
      n_unique: 4,
      flags: ["identifier"],
      top_values: [
        { value: "N", count: 3, pct: 50 },
        { value: "S", count: 1, pct: 16.7 },
      ],
      other_count: 2,
      truncated: true,
    },
    {
      name: "joined",
      dtype_group: "datetime",
      n_missing: 1,
      missing_pct: 16.7,
      n_unique: 5,
      min: "2020-01-01T00:00:00",
      max: "2022-01-01T00:00:00",
    },
  ],
  correlation: {
    columns: ["age", "premium"],
    matrix: [
      [1, 0.42],
      [0.42, 1],
    ],
    truncated: false,
  },
}

describe("DataProfile", () => {
  it("renders numeric stats, categorical values, datetime range, and correlation", () => {
    mockApp = { ...mockApp, inspect: PROFILE }
    render(
      <MemoryRouter>
        <DataProfile />
      </MemoryRouter>,
    )

    // Section headers for each column group.
    expect(screen.getByText(/Numeric columns/)).toBeInTheDocument()
    expect(screen.getByText(/Categorical columns/)).toBeInTheDocument()
    expect(screen.getByText(/Datetime columns/)).toBeInTheDocument()

    // Numeric stats labels + a value.
    expect(screen.getByText("Median")).toBeInTheDocument()
    expect(screen.getByText("Mode")).toBeInTheDocument()
    expect(screen.getByText("Skew")).toBeInTheDocument()

    // Categorical: most-frequent value + truncation note.
    expect(screen.getByText(/Most frequent:/)).toBeInTheDocument()
    expect(screen.getByText(/Showing top 2 of/)).toBeInTheDocument()

    // Degenerate-column advisory badge renders for a flagged column, annotated
    // with the unique-of-total count (region: 4 distinct of 6 rows).
    expect(screen.getByText(/Identifier-like/)).toBeInTheDocument()
    expect(screen.getByText(/4 of 6 unique/)).toBeInTheDocument()

    // Datetime range.
    expect(screen.getByText("2020-01-01")).toBeInTheDocument()
    expect(screen.getByText("2022-01-01")).toBeInTheDocument()

    // Missingness + correlation cards present.
    expect(screen.getByText("Missing values")).toBeInTheDocument()
    expect(screen.getByText(/Correlation · numeric columns/)).toBeInTheDocument()
    // a correlation cell shows the off-diagonal value.
    expect(screen.getAllByText("0.42").length).toBeGreaterThan(0)
  })

  it("shows an empty state with an Upload link when nothing is uploaded", () => {
    mockApp = { ...mockApp, inspect: null }
    render(
      <MemoryRouter>
        <DataProfile />
      </MemoryRouter>,
    )
    expect(screen.getByText(/No dataset uploaded yet/)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Go to Upload/ })).toHaveAttribute("href", "/upload")
  })

  it("has a Data Profile nav entry resolving to /data-profile", () => {
    const entry = NAV_ITEMS.find((n) => n.path === "/data-profile")
    expect(entry).toBeDefined()
    expect(entry?.label).toBe("Data Profile")

    mockApp = { ...mockApp, inspect: PROFILE }
    render(
      <MemoryRouter initialEntries={["/data-profile"]}>
        <App />
      </MemoryRouter>,
    )
    // The page title renders inside the app shell at that route.
    const main = screen.getByRole("main")
    expect(within(main).getByText("Data Profile")).toBeInTheDocument()
  })
})
