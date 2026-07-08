/* Per-column missing-value overrides.

   The Preprocessing card sets ONE strategy for all numeric columns and one for all
   categorical columns. This panel layers optional PER-COLUMN overrides on top: a
   named column uses its own imputation strategy instead of the per-type default;
   any column left on "Type default" keeps the per-type behaviour (so an untouched
   panel sends an empty map and changes nothing).

   Only the columns currently chosen as features are listed (only those are imputed),
   and each column's dtype (from the upload Data-Profile) decides which strategies are
   offered — numeric columns get the model-based imputers + numeric statistics, while
   categorical/datetime columns get only the type-agnostic strategies. This mirrors the
   engine: a numeric-only strategy set on a categorical column is coerced back to that
   column's type default at fit time, but we never offer it here in the first place. */

import type { ColumnProfile } from "@/api/types"
import { Select } from "@/components/ui/select"
import { fmtInt, fmtPct } from "@/lib/format"
import { cn } from "@/lib/utils"

// Strategy option lists — mirror config.py MISSING_STRATEGIES_NUMERIC / _CATEGORICAL.
const NUMERIC_OPTS = [
  "median", "mean", "mode", "ffill", "bfill", "knn", "iterative", "drop",
] as const
const CATEGORICAL_OPTS = ["mode", "ffill", "bfill", "drop"] as const

/** A numeric dtype gets the numeric strategy set; everything else is treated as categorical. */
function isNumeric(profile: ColumnProfile | undefined): boolean {
  return profile?.dtype_group === "numeric"
}

interface Props {
  /** Columns currently selected as features (only these are imputed). */
  featureCols: string[]
  /** Column name → its upload Data-Profile block (for the dtype). */
  profileByName: Map<string, ColumnProfile>
  /** The per-type defaults, shown as the "Type default (…)" option label. */
  numericDefault: string
  categoricalDefault: string
  /** The override map {column: strategy} and its setter. */
  value: Record<string, string>
  onChange: (next: Record<string, string>) => void
}

export default function MissingByColumnPanel({
  featureCols,
  profileByName,
  numericDefault,
  categoricalDefault,
  value,
  onChange,
}: Props) {
  // Need the dtype to pick the right option set, so only list profiled feature columns.
  const cols = featureCols.filter((c) => profileByName.has(c))

  if (cols.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Select feature columns above to set a per-column imputation method. (Requires
        the data profile captured at upload.)
      </p>
    )
  }

  function setCol(col: string, strategy: string) {
    const next = { ...value }
    if (strategy === "") delete next[col] // back to the per-type default
    else next[col] = strategy
    onChange(next)
  }

  const overrideCount = cols.filter((c) => value[c]).length

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Override the per-type default for individual columns. Leave a column on
        <span className="font-medium"> Default</span> to keep the per-type setting above.
        {overrideCount > 0 && (
          <span className="ml-1 text-foreground">
            {overrideCount} column{overrideCount === 1 ? "" : "s"} overridden.
          </span>
        )}
      </p>
      <div className="space-y-2">
        {cols.map((col) => {
          const profile = profileByName.get(col)
          const numeric = isNumeric(profile)
          const opts = numeric ? NUMERIC_OPTS : CATEGORICAL_OPTS
          const def = numeric ? numericDefault : categoricalDefault
          const overridden = Boolean(value[col])
          // Surface how much of THIS column is missing right where its imputation
          // method is chosen — a column with no gaps needs no strategy at all.
          const nMissing = profile?.n_missing ?? 0
          return (
            <div key={col} className="flex items-center gap-3">
              <span className="min-w-0 flex-1 truncate text-sm" title={col}>
                {col}
              </span>
              <span
                className={cn(
                  "shrink-0 rounded px-1.5 py-0.5 text-xs",
                  nMissing > 0
                    ? "bg-amber-100 text-amber-700"
                    : "bg-muted text-muted-foreground",
                )}
                title={nMissing > 0 ? `${fmtInt(nMissing)} missing values` : "No missing values"}
              >
                {nMissing > 0
                  ? `${fmtInt(nMissing)} missing (${fmtPct(profile?.missing_pct)})`
                  : "no gaps"}
              </span>
              <span
                className={cn(
                  "shrink-0 rounded px-1.5 py-0.5 text-xs",
                  numeric
                    ? "bg-sky-100 text-sky-700"
                    : "bg-violet-100 text-violet-700",
                )}
              >
                {numeric ? "numeric" : "categorical"}
              </span>
              <Select
                aria-label={`Imputation method for ${col}`}
                className={cn("w-56 shrink-0", overridden && "border-indigo-400")}
                value={value[col] ?? ""}
                onChange={(e) => setCol(col, e.target.value)}
              >
                <option value="">Default ({def})</option>
                {opts.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </Select>
            </div>
          )
        })}
      </div>
    </div>
  )
}
