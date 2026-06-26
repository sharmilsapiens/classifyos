/* TuningOverridesPanel — per-model Optuna search-space editor.

   Lets a user override the default search bounds/choices the engine tunes over
   (`tuning.search_space_overrides`). Layout is two levels of collapsible:
   an outer "all models" disclosure containing one disclosure per algorithm
   (native <details>/<summary> — accessible, dependency-free, matching the 9a
   Select/Switch native-element convention).

   It is purely additive: a blank numeric field uses the engine default (shown
   as the placeholder); an unchanged categorical set is omitted. So an untouched
   panel sends `{}` and a non-tuning (or default-tuning) run is unchanged.

   Overrides apply only to models that are actually tuned at run time — listing
   a model here does not enable tuning for it. */

import { ChevronRight } from "lucide-react"

import { cn } from "@/lib/utils"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  SEARCH_SPACES,
  type NumericOverride,
  type SearchSpaceOverrides,
  type SpaceParam,
} from "@/lib/searchSpaces"

// Canonical algorithm order (mirrors Configure.tsx ALGORITHMS / the registry).
const MODELS = [
  "LogisticRegression", "RandomForest", "XGBoost", "LightGBM", "SVM", "NaiveBayes",
] as const

interface Props {
  overrides: SearchSpaceOverrides
  onChange: (next: SearchSpaceOverrides) => void
}

/** Count of params with an override for a model (used for the badges). */
function modelCount(overrides: SearchSpaceOverrides, model: string): number {
  return Object.keys(overrides[model] ?? {}).length
}

export default function TuningOverridesPanel({ overrides, onChange }: Props) {
  const total = MODELS.reduce((n, m) => n + modelCount(overrides, m), 0)

  /** Replace one model's override map, pruning empty maps off the top level. */
  function commit(model: string, modelOv: Record<string, NumericOverride | (string | number)[]>) {
    const next: SearchSpaceOverrides = { ...overrides }
    if (Object.keys(modelOv).length === 0) delete next[model]
    else next[model] = modelOv
    onChange(next)
  }

  /** Set one numeric bound; clearing both bounds removes the param override. */
  function setNumeric(model: string, param: string, bound: "low" | "high", value: number | undefined) {
    const modelOv = { ...(overrides[model] ?? {}) }
    const cur = (modelOv[param] as NumericOverride | undefined) ?? {}
    const nextOv: NumericOverride = { ...cur }
    if (value === undefined || Number.isNaN(value)) delete nextOv[bound]
    else nextOv[bound] = value
    if (nextOv.low === undefined && nextOv.high === undefined) delete modelOv[param]
    else modelOv[param] = nextOv
    commit(model, modelOv)
  }

  /** Toggle a categorical choice; the full default set (or empty) = no override. */
  function toggleChoice(model: string, p: Extract<SpaceParam, { kind: "categorical" }>, choice: string | number) {
    const modelOv = { ...(overrides[model] ?? {}) }
    const cur = modelOv[param(p)] as (string | number)[] | undefined
    const selected = cur ?? [...p.choices] // no override yet → all choices selected
    const next = selected.includes(choice)
      ? selected.filter((c) => c !== choice)
      : [...selected, choice]
    // Same membership as the default (or empty) → drop the override entirely.
    const isDefault = next.length === 0 || next.length === p.choices.length
    if (isDefault) delete modelOv[param(p)]
    else modelOv[param(p)] = next
    commit(model, modelOv)
  }

  return (
    <div className="rounded-md border border-border/60">
      <details className="group">
        <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm font-medium">
          <ChevronRight className="h-4 w-4 shrink-0 transition-transform group-open:rotate-90" />
          <span>Search space (advanced) — per-model bounds</span>
          {total > 0 && (
            <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
              {total} overridden
            </span>
          )}
        </summary>
        <div className="space-y-2 border-t border-border/60 p-3">
          <p className="text-xs text-muted-foreground">
            Leave a field blank to use the engine default (shown greyed as the placeholder).
            Overrides apply only to models that are actually tuned in this run.
          </p>
          {MODELS.map((model) => {
            const count = modelCount(overrides, model)
            return (
              <details key={model} className="group/m rounded border border-border/60">
                <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-1.5 text-sm">
                  <ChevronRight className="h-3.5 w-3.5 shrink-0 transition-transform group-open/m:rotate-90" />
                  <span className="font-medium">{model}</span>
                  {count > 0 && (
                    <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary">
                      {count}
                    </span>
                  )}
                </summary>
                <div className="space-y-2.5 border-t border-border/60 px-3 py-2.5">
                  {/* header row for the numeric bound columns */}
                  <div className="grid grid-cols-[1fr_5.5rem_5.5rem] items-center gap-2 text-[11px] uppercase tracking-wide text-muted-foreground">
                    <span>Parameter</span>
                    <span>Low</span>
                    <span>High</span>
                  </div>
                  {SEARCH_SPACES[model].map((p) =>
                    p.kind === "categorical" ? (
                      <CategoricalRow
                        key={p.name}
                        param={p}
                        selected={overrides[model]?.[p.name] as (string | number)[] | undefined}
                        onToggle={(choice) => toggleChoice(model, p, choice)}
                      />
                    ) : (
                      <NumericRow
                        key={p.name}
                        param={p}
                        value={overrides[model]?.[p.name] as NumericOverride | undefined}
                        onSet={(bound, v) => setNumeric(model, p.name, bound, v)}
                      />
                    ),
                  )}
                </div>
              </details>
            )
          })}
        </div>
      </details>
    </div>
  )
}

/** stable key for a categorical param (its name). */
function param(p: SpaceParam): string {
  return p.name
}

function NumericRow({
  param: p,
  value,
  onSet,
}: {
  param: Extract<SpaceParam, { kind: "float" | "int" }>
  value: NumericOverride | undefined
  onSet: (bound: "low" | "high", v: number | undefined) => void
}) {
  const step = p.kind === "int" ? 1 : "any"
  const parse = (s: string) => (s === "" ? undefined : Number(s))
  return (
    <div className="grid grid-cols-[1fr_5.5rem_5.5rem] items-center gap-2">
      <Label className="truncate font-normal">
        {p.name}
        {p.log && <span className="ml-1 text-xs text-muted-foreground">(log)</span>}
      </Label>
      <Input
        type="number"
        step={step}
        className="h-8"
        placeholder={`${p.low}`}
        value={value?.low ?? ""}
        onChange={(e) => onSet("low", parse(e.target.value))}
        aria-label={`${p.name} lower bound`}
      />
      <Input
        type="number"
        step={step}
        className="h-8"
        placeholder={`${p.high}`}
        value={value?.high ?? ""}
        onChange={(e) => onSet("high", parse(e.target.value))}
        aria-label={`${p.name} upper bound`}
      />
    </div>
  )
}

function CategoricalRow({
  param: p,
  selected,
  onToggle,
}: {
  param: Extract<SpaceParam, { kind: "categorical" }>
  selected: (string | number)[] | undefined
  onToggle: (choice: string | number) => void
}) {
  // No override → every default choice is in play.
  const isChecked = (c: string | number) => (selected ? selected.includes(c) : true)
  return (
    <div className="space-y-1">
      <Label className="font-normal">
        {p.name}
        {p.note && <span className="ml-1 text-xs text-muted-foreground">({p.note})</span>}
      </Label>
      <div className="flex flex-wrap gap-x-4 gap-y-1.5">
        {p.choices.map((c) => (
          <label key={String(c)} className="flex items-center gap-1.5 text-sm">
            <input
              type="checkbox"
              className={cn("h-4 w-4 accent-[color:var(--primary)]")}
              checked={isChecked(c)}
              onChange={() => onToggle(c)}
            />
            <span>{String(c)}</span>
          </label>
        ))}
      </div>
    </div>
  )
}
