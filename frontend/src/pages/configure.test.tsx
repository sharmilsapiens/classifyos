/* Render-level tests for the Configuration feature picker enrichment.

   The feature-selection list now surfaces, per candidate column, the upload's
   Data-Profile info: a mini distribution sparkline + avg · IQR · variance for
   numeric columns, and the degenerate-column flags (identifier / single-value)
   beside the column name. This backs the "show distribution + identifier tag in
   the selection column" request. Covered:
   • numeric column → avg/IQR/variance derived from stats + a distribution sparkline
   • flagged column → the "Identifier-like" tag renders in the picker
   • non-numeric column → no numeric stats line */

import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"

import type { InspectProfile } from "@/api/types"
import { DEFAULT_FORM_STATE } from "@/lib/buildPayload"

// Mock the store so Configure sees a chosen inspect profile + a valid form.
let mockApp: Record<string, unknown> = {}
vi.mock("@/store/AppStore", () => ({ useApp: () => mockApp }))

import Configure from "./Configure"

const PROFILE: InspectProfile = {
  columns: ["age", "policy_id", "region", "plan_year", "record_no"],
  dtypes: { age: "float64", policy_id: "object", region: "object", plan_year: "object", record_no: "int64" },
  numeric_cols: ["age", "record_no"],
  categorical_cols: ["policy_id", "region", "plan_year"],
  binary_cols: [],
  datetime_cols: [],
  n_rows: 6,
  n_missing: { age: 0, policy_id: 0, region: 0, plan_year: 0, record_no: 0 },
  sample: [],
  server_path: "uploads/policy_lapse.csv",
  column_profiles: [
    {
      name: "age",
      dtype_group: "numeric",
      n_missing: 0,
      missing_pct: 0,
      n_unique: 5,
      stats: {
        count: 6, mean: 40, std: 10, min: 20, p25: 30, median: 40, p75: 50, max: 60, mode: 20, skew: 0,
      },
      histogram: { bin_edges: [20, 30, 40, 50, 60], counts: [1, 1, 1, 3] },
    },
    {
      name: "policy_id",
      dtype_group: "categorical",
      n_missing: 0,
      missing_pct: 0,
      n_unique: 6,
      flags: ["identifier"],
    },
    {
      name: "region",
      dtype_group: "categorical",
      n_missing: 0,
      missing_pct: 0,
      n_unique: 3,
      top_values: [
        { value: "North", count: 3, pct: 50 },
        { value: "South", count: 2, pct: 33.3 },
        { value: "East", count: 1, pct: 16.7 },
      ],
      other_count: 0,
      truncated: false,
    },
    {
      name: "plan_year",
      dtype_group: "categorical",
      n_missing: 0,
      missing_pct: 0,
      n_unique: 1,
      flags: ["constant"],
      top_values: [{ value: "2024", count: 6, pct: 100 }],
      other_count: 0,
      truncated: false,
    },
    {
      // A numeric column that is near-unique → identifier-like: it has stats + a
      // histogram, but a distribution curve over near-unique values is meaningless,
      // so the picker must NOT draw one for it.
      name: "record_no",
      dtype_group: "numeric",
      n_missing: 0,
      missing_pct: 0,
      n_unique: 6,
      flags: ["identifier"],
      stats: {
        count: 6, mean: 1003, std: 2, min: 1000, p25: 1001, median: 1003, p75: 1005, max: 1006, mode: 1000, skew: 0,
      },
      histogram: { bin_edges: [1000, 1002, 1004, 1006], counts: [2, 2, 2] },
    },
  ],
}

function renderConfigure() {
  mockApp = {
    inspect: PROFILE,
    serverPath: PROFILE.server_path,
    form: { ...DEFAULT_FORM_STATE, target: "", feature_cols: ["age"] },
    updateForm: vi.fn(),
    runPipeline: vi.fn(),
    formErrors: () => [] as string[],
  }
  render(
    <MemoryRouter>
      <Configure />
    </MemoryRouter>,
  )
}

describe("Configure — feature picker enrichment", () => {
  it("shows a numeric column's avg · IQR · variance and a distribution sparkline", () => {
    renderConfigure()
    // avg = mean (40); IQR = p75 − p25 (50 − 30 = 20); variance = std² (10² = 100).
    expect(screen.getByText("avg 40")).toBeInTheDocument()
    expect(screen.getByText("IQR 20")).toBeInTheDocument()
    expect(screen.getByText("var 100")).toBeInTheDocument()
    // The mini distribution renders as a labelled decorative bar chart.
    expect(screen.getByRole("img", { name: "Value distribution" })).toBeInTheDocument()
  })

  it("flags an identifier-like column with its unique-of-total count", () => {
    renderConfigure()
    // policy_id + record_no: 6 distinct of 6 rows → "Identifier-like · 6 of 6 unique".
    expect(screen.getAllByText(/Identifier-like/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/6 of 6 unique/).length).toBeGreaterThan(0)
  })

  it("shows the single value for a constant column", () => {
    renderConfigure()
    // plan_year holds only "2024" → "Single value: 2024".
    expect(screen.getByText(/Single value: 2024/)).toBeInTheDocument()
  })

  it("lists the available categories for a plain categorical column", () => {
    renderConfigure()
    expect(screen.getByText("North")).toBeInTheDocument()
    expect(screen.getByText("South")).toBeInTheDocument()
    expect(screen.getByText("East")).toBeInTheDocument()
  })

  it("does not draw a distribution curve for an identifier-like numeric column", () => {
    renderConfigure()
    // Only `age` (a normal numeric column) gets a curve; `record_no` is
    // identifier-like, so no curve — exactly one distribution graph in the picker.
    expect(screen.getAllByRole("img", { name: "Value distribution" })).toHaveLength(1)
    // record_no is still listed and flagged with its unique count.
    expect(screen.getByText("record_no", { selector: "span" })).toBeInTheDocument()
  })

  it("does not show numeric stats for a plain categorical column", () => {
    renderConfigure()
    // Only the numeric column carries an avg line; the categorical ones do not,
    // so exactly one "avg …" appears across the picker.
    expect(screen.getAllByText(/^avg /)).toHaveLength(1)
    // Sanity: the categorical candidate is still listed and selectable in the
    // picker (scoped to the name span — "region" also appears as a target <option>).
    const region = screen.getByText("region", { selector: "span" }).closest("label")
    expect(region).not.toBeNull()
    expect(within(region as HTMLElement).getByRole("checkbox")).toBeInTheDocument()
  })
})

describe("Configure — decision threshold policy", () => {
  it("defaults to Auto-tune and shows the metric selector, not a value box", () => {
    renderConfigure()
    // The mode selector defaults to tuned; the metric selector is shown alongside.
    expect(screen.getByRole("option", { name: "Auto-tune (best cut)" })).toBeInTheDocument()
    expect(screen.getByText("Threshold metric")).toBeInTheDocument()
    // In tuned mode there is no editable "Threshold value" number box.
    expect(screen.queryByText("Threshold value")).not.toBeInTheDocument()
  })
})
