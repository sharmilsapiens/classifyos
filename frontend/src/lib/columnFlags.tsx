/* Shared copy + rendering for the degenerate-column advisories the engine flags
   (ColumnProfile.flags — "constant" | "identifier"). Kept in one place so the Data
   Profile page and the Configuration feature picker describe these columns
   identically (same near-unique / zero-variance story the engine uses).

   When a `profile` (and, for the ratio, `nRows`) is passed, each badge is annotated
   with the concrete detail an analyst asked for:
     • constant   → the single value the column holds ("Single value: 2024")
     • identifier → how many distinct values out of the total rows ("… · 9,950 of 10,000 unique"). */

import { AlertTriangle } from "lucide-react"

import type { ColumnProfile } from "@/api/types"
import { fmtInt, fmtNum } from "@/lib/format"
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

/** The lone value of a constant column, formatted for display (or null if unknown,
    e.g. an all-missing column). Reads the right block per display group. */
function constantValue(profile?: ColumnProfile): string | null {
  if (!profile) return null
  if (profile.dtype_group === "numeric") {
    const v = profile.stats?.mode ?? profile.stats?.min ?? profile.stats?.mean
    return v == null ? null : fmtNum(v)
  }
  if (profile.dtype_group === "datetime") {
    return profile.min ? profile.min.slice(0, 10) : null
  }
  // categorical / binary — the single distinct value is the sole top value.
  return profile.top_values?.[0]?.value ?? null
}

/** Keep a long constant value (e.g. a free-text string) from blowing out the badge. */
function truncate(value: string, max = 24): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value
}

/** Badges for a column's degenerate-data advisories; renders nothing when clean. */
export function ColumnFlags({
  flags,
  className,
  profile,
  nRows,
}: {
  flags?: string[]
  className?: string
  /** When given, the badge is annotated with the value / unique-count detail. */
  profile?: ColumnProfile
  /** Total rows, for the identifier "N of M unique" annotation. */
  nRows?: number
}) {
  if (!flags || flags.length === 0) return null
  return (
    <div className={cn("flex flex-wrap gap-1.5", className)}>
      {flags.map((f) => {
        const info = FLAG_INFO[f]
        if (!info) return null

        let detail = ""
        if (f === "constant") {
          const v = constantValue(profile)
          if (v != null && v !== "") detail = `: ${truncate(String(v))}`
        } else if (f === "identifier" && profile) {
          detail =
            nRows != null
              ? ` · ${fmtInt(profile.n_unique)} of ${fmtInt(nRows)} unique`
              : ` · ${fmtInt(profile.n_unique)} unique`
        }

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
            {detail}
          </span>
        )
      })}
    </div>
  )
}
