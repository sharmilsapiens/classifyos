/* Shared copy + rendering for the degenerate-column advisories the engine flags
   (ColumnProfile.flags — "constant" | "identifier"). Kept in one place so the Data
   Profile page and the Configuration feature picker describe these columns
   identically (same near-unique / zero-variance story the engine uses). */

import { AlertTriangle } from "lucide-react"

import { cn } from "@/lib/utils"

/** Human-readable label, tooltip, and badge tone for each advisory flag. */
export const FLAG_INFO: Record<string, { label: string; tip: string; tone: string }> = {
  constant: {
    label: "Single value",
    tip: "Every row holds the same value — zero variance. It carries no predictive signal (std, skew, and correlations are undefined here), so it's a candidate to drop before training.",
    tone: "border-amber-300 bg-amber-50 text-amber-700",
  },
  identifier: {
    label: "Identifier-like",
    tip: "Nearly every row is a distinct value, so this looks like an ID or free-text key. High-cardinality columns like this don't generalise and can leak the target — usually excluded from the features.",
    tone: "border-rose-300 bg-rose-50 text-rose-700",
  },
}

/** Badges for a column's degenerate-data advisories; renders nothing when clean. */
export function ColumnFlags({ flags, className }: { flags?: string[]; className?: string }) {
  if (!flags || flags.length === 0) return null
  return (
    <div className={cn("flex flex-wrap gap-1.5", className)}>
      {flags.map((f) => {
        const info = FLAG_INFO[f]
        if (!info) return null
        return (
          <span
            key={f}
            title={info.tip}
            className={cn(
              "inline-flex cursor-help items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium",
              info.tone,
            )}
          >
            <AlertTriangle className="h-3 w-3" />
            {info.label}
          </span>
        )
      })}
    </div>
  )
}
