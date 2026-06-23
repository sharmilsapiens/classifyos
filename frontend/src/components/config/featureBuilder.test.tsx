/* Render-level tests for the user-defined feature-builder panel (Configuration).

   The panel is a CONTROLLED component: it owns only the in-progress draft, the
   committed list lives in the caller's form state. These tests drive it through a
   small stateful harness and assert the assembled RunConfig payload (via
   buildPayload) gets the right structured specs — and crucially that there is NO
   free-text formula input (the engine's no-eval safety contract carried to the UI). */

import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useState } from "react"

import type { InspectProfile, UserFeatureSpec } from "@/api/types"
import { buildPayload, DEFAULT_FORM_STATE } from "@/lib/buildPayload"
import FeatureBuilderPanel from "./FeatureBuilderPanel"

const INSPECT: InspectProfile = {
  columns: ["age", "premium", "sum_assured", "start_date", "end_date", "will_lapse"],
  dtypes: {},
  numeric_cols: ["age", "premium", "sum_assured"],
  categorical_cols: [],
  binary_cols: [],
  datetime_cols: ["start_date", "end_date"],
  n_rows: 100,
  n_missing: {},
  sample: [],
  server_path: "policy_lapse.csv",
}

/** Wraps the panel, mirroring how Configuration stores the list in form state, and
    renders the assembled payload so tests can assert what /run would receive. */
function Harness({ initial = [] as UserFeatureSpec[] }) {
  const [uf, setUf] = useState<UserFeatureSpec[]>(initial)
  return (
    <>
      <FeatureBuilderPanel inspect={INSPECT} userFeatures={uf} onChange={setUf} />
      <pre data-testid="payload">
        {JSON.stringify(buildPayload({ ...DEFAULT_FORM_STATE, user_features: uf }))}
      </pre>
    </>
  )
}

/** Read the user_features array out of the rendered payload. */
function payloadFeatures(): UserFeatureSpec[] {
  const json = screen.getByTestId("payload").textContent ?? "{}"
  return JSON.parse(json).user_features as UserFeatureSpec[]
}

describe("FeatureBuilderPanel", () => {
  it("adds a numeric feature with the right spec shape to the payload", async () => {
    const user = userEvent.setup()
    render(<Harness />)

    // type defaults to numeric.
    await user.selectOptions(screen.getByLabelText("Column A"), "premium")
    await user.selectOptions(screen.getByLabelText("Operation"), "divide")
    await user.selectOptions(screen.getByLabelText("Column B"), "sum_assured")
    await user.type(screen.getByLabelText("New feature name"), "premium_per_sum")
    await user.click(screen.getByRole("button", { name: /add feature/i }))

    expect(payloadFeatures()).toEqual([
      { name: "premium_per_sum", type: "numeric", op: "divide", col_a: "premium", col_b: "sum_assured" },
    ])
    // Readable, formula-free chip.
    expect(screen.getByText("premium_per_sum = premium ÷ sum_assured")).toBeInTheDocument()
  })

  it("builds a datetime_diff feature with the chosen unit", async () => {
    const user = userEvent.setup()
    render(<Harness />)

    await user.selectOptions(screen.getByLabelText("Feature type"), "datetime_diff")
    await user.selectOptions(screen.getByLabelText("End column"), "end_date")
    await user.selectOptions(screen.getByLabelText("Start column"), "start_date")
    await user.selectOptions(screen.getByLabelText("Unit"), "hours")
    await user.type(screen.getByLabelText("New feature name"), "duration_hours")
    await user.click(screen.getByRole("button", { name: /add feature/i }))

    expect(payloadFeatures()).toEqual([
      {
        name: "duration_hours",
        type: "datetime_diff",
        op: "subtract",
        col_a: "end_date",
        col_b: "start_date",
        unit: "hours",
      },
    ])
  })

  it("builds a single-column transform spec (no col_b)", async () => {
    const user = userEvent.setup()
    render(<Harness />)

    await user.selectOptions(screen.getByLabelText("Feature type"), "single")
    await user.selectOptions(screen.getByLabelText("Transform"), "log")
    await user.selectOptions(screen.getByLabelText("Column"), "premium")
    await user.type(screen.getByLabelText("New feature name"), "log_premium")
    await user.click(screen.getByRole("button", { name: /add feature/i }))

    expect(payloadFeatures()).toEqual([
      { name: "log_premium", type: "single", op: "log", col_a: "premium" },
    ])
  })

  it("blocks an empty name with a clear message", async () => {
    const user = userEvent.setup()
    render(<Harness />)

    await user.selectOptions(screen.getByLabelText("Column A"), "premium")
    await user.selectOptions(screen.getByLabelText("Column B"), "sum_assured")
    await user.click(screen.getByRole("button", { name: /add feature/i }))

    expect(screen.getByRole("alert")).toHaveTextContent(/enter a name/i)
    expect(payloadFeatures()).toEqual([])
  })

  it("blocks a duplicate name (collision with an existing column or added feature)", async () => {
    const user = userEvent.setup()
    render(<Harness />)

    // Collides with an existing dataset column → blocked.
    await user.selectOptions(screen.getByLabelText("Column A"), "premium")
    await user.selectOptions(screen.getByLabelText("Column B"), "sum_assured")
    await user.type(screen.getByLabelText("New feature name"), "age")
    await user.click(screen.getByRole("button", { name: /add feature/i }))

    expect(screen.getByRole("alert")).toHaveTextContent(/already exists/i)
    expect(payloadFeatures()).toEqual([])
  })

  it("removes an added feature from the payload", async () => {
    const user = userEvent.setup()
    const spec: UserFeatureSpec = {
      name: "premium_per_sum",
      type: "numeric",
      op: "divide",
      col_a: "premium",
      col_b: "sum_assured",
    }
    render(<Harness initial={[spec]} />)

    expect(payloadFeatures()).toHaveLength(1)
    await user.click(screen.getByRole("button", { name: /remove premium_per_sum/i }))
    expect(payloadFeatures()).toEqual([])
  })

  it("offers NO free-text formula input — only the name textbox", () => {
    render(<Harness />)
    // The only text input is the new-feature name; everything else is a <select>.
    const textboxes = screen.getAllByRole("textbox")
    expect(textboxes).toHaveLength(1)
    expect(textboxes[0]).toBe(screen.getByLabelText("New feature name"))
  })
})
