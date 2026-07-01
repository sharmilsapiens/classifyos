/* Explainability — per-row SHAP (schema 1.6).

   LOCAL explainability: "why did the model predict THIS for this one row?" —
   the reason-code / adverse-action view an underwriter or claims adjuster needs.

   The explanations are computed DURING the run (while every model is still fitted
   in memory) and shipped in the /run response as `result.explanations` — the same
   compute-during-run pattern as feature_importance / permutation_importance. So
   this page just reads them from the store (no /explain call, no model
   persistence). It renders three honest states:

     1. NO RUN            — handled by <ResultGate>.
     2. NOT COMPUTED      — a run exists but explainability was OFF (the default):
                            a clear "enable it and re-run" message.
     3. EXPLANATIONS ON   — a model + row picker driving a real SHAP waterfall:
                            base value → each feature's signed push → the prediction
                            (base_value + Σ contributions == prediction, exactly).

   Covers all six models (TreeExplainer for the tree models, KernelExplainer for
   LogisticRegression / SVM / NaiveBayes). Binary explains the positive class;
   multiclass explains the predicted class. Multilabel produces nothing (omitted). */

import { useState } from "react"
import { Link } from "react-router-dom"

import type { ExplanationRow, ModelExplanation } from "@/api/types"
import { ResultGate } from "@/components/results/ResultGate"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { buttonVariants } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { EmptyState, PageHeader } from "@/components/common/States"

/** Most feature bars to draw before the remainder is folded into one "Other" step. */
const MAX_BARS = 12

export default function Explainability() {
  return (
    <ResultGate
      title="Explainability"
      subtitle="Why did the model predict this for one row? (per-row SHAP)"
    >
      {(run) => <ExplainabilityBody explanations={run.explanations ?? null} />}
    </ResultGate>
  )
}

function ExplainabilityBody({
  explanations,
}: {
  explanations: Record<string, ModelExplanation> | null
}) {
  const models = explanations ? Object.keys(explanations) : []
  const [model, setModel] = useState(models[0] ?? "")
  const [rowIdx, setRowIdx] = useState(0)

  // State 2 — a run exists, but explainability was OFF (block null/absent or empty).
  if (!explanations || models.length === 0) {
    return (
      <div>
        <PageHeader
          title="Explainability"
          subtitle="Per-row SHAP explanations for the last run."
        />
        <EmptyState
          title="Explainability was not computed for this run"
          description="Per-row SHAP is opt-in (it adds run time). Turn on 'Per-row explainability (SHAP)' under Post-training analysis in Configuration, then run again to see, for each prediction, which features pushed it up or down."
          action={
            <Link to="/configure" className={buttonVariants({ size: "sm" })}>
              Open Configuration
            </Link>
          }
        />
      </div>
    )
  }

  const selected = explanations[model] ?? explanations[models[0]]
  const rows = selected?.rows ?? []
  const row = rows[Math.min(rowIdx, rows.length - 1)] ?? rows[0]

  return (
    <div>
      <PageHeader
        title="Explainability"
        subtitle="Why did the model predict this for one row? (per-row SHAP)"
        actions={selected ? <Badge variant="secondary">{selected.method}</Badge> : undefined}
      />

      <div className="mb-5 grid grid-cols-1 gap-4 sm:grid-cols-[1fr_1fr]">
        <div className="space-y-1.5">
          <Label htmlFor="explain-model">Model</Label>
          <Select
            id="explain-model"
            value={model}
            onChange={(e) => {
              setModel(e.target.value)
              setRowIdx(0)
            }}
          >
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="explain-row">Test row</Label>
          <Select
            id="explain-row"
            value={String(rowIdx)}
            onChange={(e) => setRowIdx(Number(e.target.value))}
          >
            {rows.map((r, i) => (
              <option key={r.sample_index} value={String(i)}>
                Row {r.sample_index}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {row ? (
        <Waterfall row={row} />
      ) : (
        <EmptyState
          title="No explained rows"
          description="This model produced no per-row explanations for the run."
        />
      )}
    </div>
  )
}

/** A signed, fixed-precision number with an explicit + / − (so pushes read clearly). */
function fmtSigned(value: number): string {
  const s = value.toFixed(4)
  return value > 0 ? `+${s}` : s
}

/**
 * A real SHAP waterfall: start at the model's average output (`base_value`) and add
 * each feature's signed contribution, stepping to this row's prediction. Bars are
 * positioned by their cumulative span so the chart literally walks base → prediction;
 * red pushes the prediction up, green pulls it down. Features are ordered by impact,
 * and any tail beyond MAX_BARS is folded into a single "Other" step so the waterfall
 * still lands exactly on `prediction`.
 */
function Waterfall({ row }: { row: ExplanationRow }) {
  const entries = Object.entries(row.contributions).sort(
    (a, b) => Math.abs(b[1]) - Math.abs(a[1]),
  )

  // Fold the low-impact tail into one "Other" step so the bars still sum to prediction.
  let steps: { feature: string; value: number }[]
  if (entries.length > MAX_BARS) {
    const head = entries.slice(0, MAX_BARS - 1)
    const tail = entries.slice(MAX_BARS - 1)
    const tailSum = tail.reduce((acc, [, v]) => acc + v, 0)
    steps = [
      ...head.map(([feature, value]) => ({ feature, value })),
      { feature: `Other (${tail.length} features)`, value: tailSum },
    ]
  } else {
    steps = entries.map(([feature, value]) => ({ feature, value }))
  }

  // Cumulative spans + a padded domain covering base, prediction and every waypoint.
  let cum = row.base_value
  const spans = steps.map((s) => {
    const start = cum
    const end = cum + s.value
    cum = end
    return { ...s, start, end }
  })
  const points = [row.base_value, row.prediction, ...spans.flatMap((s) => [s.start, s.end])]
  const lo = Math.min(...points)
  const hi = Math.max(...points)
  const pad = (hi - lo) * 0.06 || 0.1
  const dmin = lo - pad
  const dmax = hi + pad
  const pct = (x: number) => ((x - dmin) / (dmax - dmin)) * 100

  return (
    <Card>
      <CardHeader>
        <CardTitle>Feature contributions</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm">
          <span>
            Explaining class{" "}
            <span className="font-mono font-medium">{row.explained_class}</span>
          </span>
          <span className="text-muted-foreground">
            base value <span className="font-mono">{row.base_value.toFixed(4)}</span>
          </span>
          <span className="text-muted-foreground">
            prediction <span className="font-mono">{row.prediction.toFixed(4)}</span>
          </span>
        </div>

        <div className="space-y-1.5">
          {spans.map((s) => {
            const left = pct(Math.min(s.start, s.end))
            const width = Math.max(pct(Math.max(s.start, s.end)) - left, 0.5)
            const up = s.value > 0
            return (
              <div key={s.feature} className="flex items-center gap-3 text-xs">
                <div className="w-40 shrink-0 truncate text-right font-mono" title={s.feature}>
                  {s.feature}
                </div>
                <div className="relative h-5 flex-1 rounded bg-muted/40">
                  <div
                    className={`absolute top-0 h-5 rounded ${up ? "bg-rose-500" : "bg-emerald-500"}`}
                    style={{ left: `${left}%`, width: `${width}%` }}
                    aria-hidden
                  />
                </div>
                <div
                  className={`w-20 shrink-0 font-mono ${up ? "text-rose-600" : "text-emerald-600"}`}
                >
                  {fmtSigned(s.value)}
                </div>
              </div>
            )
          })}
        </div>

        <div className="flex items-center gap-4 border-t pt-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-3 w-3 rounded bg-rose-500" aria-hidden /> increases the
            prediction
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-3 w-3 rounded bg-emerald-500" aria-hidden /> decreases it
          </span>
          <span className="ml-auto">base value + all contributions = prediction</span>
        </div>
      </CardContent>
    </Card>
  )
}
