import { describe, expect, it } from "vitest"

import { avgRows, describeInteraction, interactionOps, isAvgRow, perClassRows } from "./results"
import type { ClassReportRow } from "@/api/types"

describe("describeInteraction", () => {
  it("decodes operator markers into readable math", () => {
    expect(describeInteraction("a_x_b")).toBe("a × b")
    expect(describeInteraction("a_div_b")).toBe("a ÷ b")
    expect(describeInteraction("a_minus_b")).toBe("a − b")
  })

  it("handles nested compositions", () => {
    expect(describeInteraction("a_div_b_x_c")).toBe("a ÷ b × c")
  })
})

describe("interactionOps", () => {
  it("lists every operation present", () => {
    expect(interactionOps("a_x_b")).toEqual(["multiply"])
    expect(interactionOps("a_div_b_x_c")).toEqual(["multiply", "ratio"])
  })
})

describe("class-report row splitting", () => {
  const rows: ClassReportRow[] = [
    { class: "0", precision: 0.7, recall: 0.6, f1: 0.65, support: 100 },
    { class: "1", precision: 0.4, recall: 0.5, f1: 0.45, support: 50 },
    { class: "macro avg", precision: 0.55, recall: 0.55, f1: 0.55, support: 150 },
    { class: "weighted avg", precision: 0.6, recall: 0.57, f1: 0.58, support: 150 },
  ]

  it("flags only the average summary rows", () => {
    expect(isAvgRow(rows[0])).toBe(false)
    expect(isAvgRow(rows[2])).toBe(true)
  })

  it("separates per-class from summary rows", () => {
    expect(perClassRows(rows).map((r) => r.class)).toEqual(["0", "1"])
    expect(avgRows(rows).map((r) => r.class)).toEqual(["macro avg", "weighted avg"])
  })
})
