/* Tiny display formatters. Metrics can be null (the contract emits null for
   undefined/NaN values), so every formatter handles null → an em-dash. */

/** A 0–1 metric to 3 significant decimals, or "—" when null/undefined. */
export function fmtMetric(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  return value.toFixed(3)
}

/** An integer with thousands separators, or "—". */
export function fmtInt(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  return value.toLocaleString("en-US")
}

/** A number to ~3 significant decimals, compacting very small/large magnitudes to
    exponential; "—" when null/undefined/NaN. Shared by the Data Profile stats and
    the Configuration feature picker so numeric summaries read identically. */
export function fmtNum(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  const abs = Math.abs(value)
  if (abs !== 0 && (abs < 0.001 || abs >= 1e6)) return value.toExponential(2)
  return Number(value.toFixed(3)).toLocaleString("en-US")
}

/** Bytes → a short human size (for artifact lists). */
export function fmtBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
