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

/** Bytes → a short human size (for artifact lists). */
export function fmtBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
