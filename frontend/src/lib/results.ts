/* Small, pure helpers shared by the 9b result pages.

   Kept here (not in a page) so the chart palette, the "which class-report rows
   are averages" rule, and the interaction-name decoder are defined ONCE and can
   be unit-tested without rendering a page. No React in this file. */

import type { ClassReportRow } from "@/api/types"

/** The Recharts series palette (mirrors the --chart-N tokens in index.css). */
export const CHART_COLORS = ["#4f46e5", "#0ea5e9", "#10b981", "#f59e0b", "#a855f7", "#f43f5e"]

/** A stable color for a series index (wraps around the palette). */
export function seriesColor(index: number): string {
  return CHART_COLORS[index % CHART_COLORS.length]
}

/** The sklearn classification_report adds "macro avg"/"weighted avg"/"accuracy"
 *  summary rows alongside the real per-class rows. This flags those so a table
 *  can separate true classes from the aggregate footer. */
export function isAvgRow(row: ClassReportRow): boolean {
  const c = row.class.toLowerCase()
  return c.endsWith("avg") || c === "accuracy" || c === "micro avg"
}

/** Per-class rows only (drops the macro/weighted/accuracy summary rows). */
export function perClassRows(rows: ClassReportRow[]): ClassReportRow[] {
  return rows.filter((r) => !isAvgRow(r))
}

/** The summary (avg) rows only. */
export function avgRows(rows: ClassReportRow[]): ClassReportRow[] {
  return rows.filter(isAvgRow)
}

/**
 * Decode an interaction-feature column name into a readable expression.
 * The engine names them with `_x_` (multiply), `_div_` (ratio), `_minus_`
 * (difference) — see CLAUDE.md conventions. Names can be nested, so rather than
 * guess operand boundaries we just substitute the operator markers with math
 * symbols, which reads correctly regardless of nesting.
 * e.g. "a_div_b_x_c" → "a ÷ b × c".
 */
export function describeInteraction(col: string): string {
  return col
    .replace(/_x_/g, " × ")
    .replace(/_div_/g, " ÷ ")
    .replace(/_minus_/g, " − ")
}

/** The operations present in an interaction column (for a plain-language note). */
export function interactionOps(col: string): string[] {
  const ops: string[] = []
  if (col.includes("_x_")) ops.push("multiply")
  if (col.includes("_div_")) ops.push("ratio")
  if (col.includes("_minus_")) ops.push("difference")
  return ops
}

/** Models that trained successfully (have a real metrics row), name-keyed. */
export function okModelNames(models: { name: string; status: string }[]): string[] {
  return models.filter((m) => m.status === "ok").map((m) => m.name)
}
