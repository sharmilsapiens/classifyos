/* Per-column context notes for the LLM reason-code narrator.

   The narrator writes a plain-language "why" for each explained row. Giving it the business
   meaning of each column (e.g. "Decision_Days" = days from quote to decision) lets it describe
   drivers in domain terms instead of restating raw column names. This panel lists the columns
   currently chosen as features and lets the analyst attach a short note to any of them; a column
   left blank simply isn't described. It writes a {column: note} map (dropping empties), the mirror
   of `explainability.column_context`. Prompt-only — nothing here touches the ML. */

import { Input } from "@/components/ui/input"

interface Props {
  /** Columns currently selected as features (only these can drive an explanation). */
  featureCols: string[]
  /** The {column: note} map and its setter. */
  value: Record<string, string>
  onChange: (next: Record<string, string>) => void
}

export default function ExplainContextPanel({ featureCols, value, onChange }: Props) {
  if (featureCols.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Select feature columns above to add per-column context notes.
      </p>
    )
  }

  function setCol(col: string, note: string) {
    const next = { ...value }
    if (note.trim() === "") delete next[col]
    else next[col] = note
    onChange(next)
  }

  const noteCount = featureCols.filter((c) => value[c]?.trim()).length

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Optional: describe what a column means so the narrative can refer to it in business terms.
        Blank columns are left undescribed.
        {noteCount > 0 && (
          <span className="ml-1 text-foreground">
            {noteCount} column{noteCount === 1 ? "" : "s"} annotated.
          </span>
        )}
      </p>
      <div className="space-y-2">
        {featureCols.map((col) => (
          <div key={col} className="flex items-center gap-3">
            <span className="min-w-0 w-40 shrink-0 truncate text-sm" title={col}>
              {col}
            </span>
            <Input
              aria-label={`Context note for ${col}`}
              className="flex-1"
              placeholder="e.g. days from quote to decision"
              value={value[col] ?? ""}
              onChange={(e) => setCol(col, e.target.value)}
            />
          </div>
        ))}
      </div>
    </div>
  )
}
