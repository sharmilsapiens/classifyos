/* ════════════════════════════════════════════════════════════════════════
   FeatureBuilderPanel — build user-defined STRUCTURED features from dropdowns.

   CRITICAL SAFETY CONTRACT (carried from the engine): the panel sends STRUCTURED
   specs only — { name, op, type, col_a, col_b?, unit? }. There is NO free-text
   formula input anywhere. The user CHOOSES from dropdowns; the only free-text
   control is the new column's NAME. The UI never lets a user type an expression
   the backend would evaluate (the engine never eval()/exec()'s anything).

   Controlled component: it owns only the in-progress "draft" of the next feature;
   the committed list lives in the caller's form state (`userFeatures` / `onChange`),
   so it is part of the same RunConfig the rest of Configuration assembles.
   ════════════════════════════════════════════════════════════════════════ */

import { useState } from "react"
import { Plus, X } from "lucide-react"

import type { InspectProfile, UserFeatureSpec, UserFeatureType } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"

/* Allowlists — mirror the engine's USER_FEATURE_* tuples (config.py) EXACTLY so a
   built spec never 422s on a bad enum. */
const NUMERIC_OPS = ["add", "subtract", "multiply", "divide", "ratio"] as const
const SINGLE_NUMERIC_OPS = ["log", "abs", "bin"] as const
const SINGLE_DATE_OPS = ["year", "month", "day", "dayofweek", "hour"] as const
const DATETIME_UNITS = ["days", "hours", "minutes", "seconds"] as const

/** Operators we render as a symbol in a feature's readable label. */
const NUMERIC_SYMBOL: Record<string, string> = {
  add: "+",
  subtract: "−",
  multiply: "×",
  divide: "÷",
  ratio: "÷ (ratio)",
}

/** True for the single-column ops that operate on a DATE column (vs a numeric one). */
function isDateOp(op: string): boolean {
  return (SINGLE_DATE_OPS as readonly string[]).includes(op)
}

/**
 * Validate the proposed feature NAME client-side (the only free-text input):
 * non-empty, and unique among existing columns + already-added user features.
 * Returns a human-readable message, or null when the name is OK. Exported so the
 * render tests can assert the messages directly.
 */
export function validateFeatureName(name: string, taken: string[]): string | null {
  const n = name.trim()
  if (!n) return "Enter a name for the new feature."
  if (taken.includes(n)) return `"${n}" already exists — choose a unique name.`
  return null
}

/** A readable, formula-free description of a committed spec (for the chips/rows). */
export function describeSpec(spec: UserFeatureSpec): string {
  if (spec.type === "numeric") {
    const sym = NUMERIC_SYMBOL[spec.op] ?? spec.op
    return `${spec.name} = ${spec.col_a} ${sym} ${spec.col_b}`
  }
  if (spec.type === "datetime_diff") {
    return `${spec.name} = ${spec.col_a} − ${spec.col_b} (${spec.unit ?? "days"})`
  }
  return `${spec.name} = ${spec.op}(${spec.col_a})`
}

interface FeatureBuilderPanelProps {
  /** The uploaded file's inspect profile — supplies the typed column lists. */
  inspect: InspectProfile
  /** The committed user-feature list (lives in the form). */
  userFeatures: UserFeatureSpec[]
  /** Replace the committed list (add / remove). */
  onChange: (next: UserFeatureSpec[]) => void
}

export default function FeatureBuilderPanel({
  inspect,
  userFeatures,
  onChange,
}: FeatureBuilderPanelProps) {
  // The in-progress draft. type/op persist between adds; cols + name reset.
  const [type, setType] = useState<UserFeatureType>("numeric")
  const [op, setOp] = useState<string>("divide")
  const [colA, setColA] = useState("")
  const [colB, setColB] = useState("")
  const [unit, setUnit] = useState<string>("days")
  const [name, setName] = useState("")
  const [error, setError] = useState<string | null>(null)

  // Names already in use: every dataset column + every already-added feature.
  const taken = [...inspect.columns, ...userFeatures.map((f) => f.name)]

  // Column options, filtered by type where inspect gives us the info. Fall back to
  // every column when the typed list is empty (then the API's 422 guides the user).
  const numericCols = inspect.numeric_cols.length ? inspect.numeric_cols : inspect.columns
  const datetimeCols = inspect.datetime_cols.length ? inspect.datetime_cols : inspect.columns
  // single: the op decides whether col_a should be a date or a numeric column.
  const singleCols = type === "single" && isDateOp(op) ? datetimeCols : numericCols
  const colAOptions =
    type === "numeric" ? numericCols : type === "datetime_diff" ? datetimeCols : singleCols
  const colBOptions = type === "datetime_diff" ? datetimeCols : numericCols

  const twoColumn = type === "numeric" || type === "datetime_diff"

  /** Switch the feature type, resetting the op to a valid default + clearing cols. */
  function changeType(next: UserFeatureType) {
    setType(next)
    setOp(next === "numeric" ? "divide" : next === "datetime_diff" ? "subtract" : "log")
    setColA("")
    setColB("")
    setError(null)
  }

  /** Validate the draft and append it to the committed list. */
  function addFeature() {
    const nameError = validateFeatureName(name, taken)
    if (nameError) {
      setError(nameError)
      return
    }
    if (!colA) {
      setError("Choose the source column.")
      return
    }
    if (twoColumn && !colB) {
      setError("Choose the second source column.")
      return
    }

    const trimmed = name.trim()
    let spec: UserFeatureSpec
    if (type === "numeric") {
      spec = { name: trimmed, type, op, col_a: colA, col_b: colB }
    } else if (type === "datetime_diff") {
      spec = { name: trimmed, type, op: "subtract", col_a: colA, col_b: colB, unit }
    } else {
      spec = { name: trimmed, type, op, col_a: colA }
    }

    onChange([...userFeatures, spec])
    // Reset the per-feature fields (keep type/op so adding several of a kind is quick).
    setName("")
    setColA("")
    setColB("")
    setError(null)
  }

  function removeFeature(index: number) {
    onChange(userFeatures.filter((_, i) => i !== index))
  }

  return (
    <Card className="lg:col-span-2">
      <CardHeader>
        <CardTitle>User-defined features</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-xs text-muted-foreground">
          Build new columns from existing ones using a fixed set of operations. You pick
          everything from dropdowns — there is no formula box, and nothing you enter is ever
          evaluated as code.
        </p>

        {/* The builder controls */}
        <div className="grid grid-cols-1 gap-4 rounded-md border p-4 md:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="uf_type">Feature type</Label>
            <Select
              id="uf_type"
              value={type}
              onChange={(e) => changeType(e.target.value as UserFeatureType)}
            >
              <option value="numeric">Numeric (two columns)</option>
              <option value="single">Single-column transform</option>
              <option value="datetime_diff">Datetime difference</option>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="uf_name">New column name</Label>
            <Input
              id="uf_name"
              aria-label="New feature name"
              placeholder="e.g. premium_per_sum"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          {/* numeric: [col_a] [op] [col_b] */}
          {type === "numeric" && (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="uf_col_a">Column A</Label>
                <Select id="uf_col_a" value={colA} onChange={(e) => setColA(e.target.value)}>
                  <option value="">— choose —</option>
                  {colAOptions.map((c) => <option key={c} value={c}>{c}</option>)}
                </Select>
              </div>
              <div className="grid grid-cols-[110px_1fr] gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="uf_op">Operation</Label>
                  <Select id="uf_op" value={op} onChange={(e) => setOp(e.target.value)}>
                    {NUMERIC_OPS.map((o) => <option key={o} value={o}>{o}</option>)}
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="uf_col_b">Column B</Label>
                  <Select id="uf_col_b" value={colB} onChange={(e) => setColB(e.target.value)}>
                    <option value="">— choose —</option>
                    {colBOptions.map((c) => <option key={c} value={c}>{c}</option>)}
                  </Select>
                </div>
              </div>
            </>
          )}

          {/* single: [col_a] [transform] */}
          {type === "single" && (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="uf_op">Transform</Label>
                <Select id="uf_op" value={op} onChange={(e) => setOp(e.target.value)}>
                  <optgroup label="Numeric">
                    {SINGLE_NUMERIC_OPS.map((o) => <option key={o} value={o}>{o}</option>)}
                  </optgroup>
                  <optgroup label="Date part">
                    {SINGLE_DATE_OPS.map((o) => <option key={o} value={o}>{o}</option>)}
                  </optgroup>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="uf_col_a">Column</Label>
                <Select id="uf_col_a" value={colA} onChange={(e) => setColA(e.target.value)}>
                  <option value="">— choose —</option>
                  {colAOptions.map((c) => <option key={c} value={c}>{c}</option>)}
                </Select>
              </div>
            </>
          )}

          {/* datetime_diff: [col_a end] [col_b start] [unit] (op fixed to subtract) */}
          {type === "datetime_diff" && (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="uf_col_a">End column</Label>
                <Select id="uf_col_a" value={colA} onChange={(e) => setColA(e.target.value)}>
                  <option value="">— choose —</option>
                  {colAOptions.map((c) => <option key={c} value={c}>{c}</option>)}
                </Select>
              </div>
              <div className="grid grid-cols-[1fr_110px] gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="uf_col_b">Start column</Label>
                  <Select id="uf_col_b" value={colB} onChange={(e) => setColB(e.target.value)}>
                    <option value="">— choose —</option>
                    {colBOptions.map((c) => <option key={c} value={c}>{c}</option>)}
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="uf_unit">Unit</Label>
                  <Select id="uf_unit" value={unit} onChange={(e) => setUnit(e.target.value)}>
                    {DATETIME_UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
                  </Select>
                </div>
              </div>
            </>
          )}

          <div className="md:col-span-2 flex items-center justify-between gap-4">
            {error
              ? <p className="text-xs text-destructive" role="alert">{error}</p>
              : <span className="text-xs text-muted-foreground">Choose columns + an operation, name it, then add.</span>}
            <Button type="button" variant="outline" size="sm" onClick={addFeature}>
              <Plus className="h-4 w-4" />
              Add feature
            </Button>
          </div>
        </div>

        {/* The committed features as removable rows. */}
        {userFeatures.length > 0 ? (
          <div className="space-y-2">
            <Label>Added features ({userFeatures.length})</Label>
            <ul className="space-y-1.5">
              {userFeatures.map((spec, i) => (
                <li
                  key={`${spec.name}-${i}`}
                  className="flex items-center justify-between gap-3 rounded-md border bg-muted/30 px-3 py-2"
                >
                  <div className="flex items-center gap-2 text-sm">
                    <Badge variant="secondary">{spec.type}</Badge>
                    <code className="font-mono text-xs">{describeSpec(spec)}</code>
                  </div>
                  <button
                    type="button"
                    aria-label={`Remove ${spec.name}`}
                    className="text-muted-foreground hover:text-destructive"
                    onClick={() => removeFeature(i)}
                  >
                    <X className="h-4 w-4" />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">No user-defined features yet.</p>
        )}
      </CardContent>
    </Card>
  )
}
