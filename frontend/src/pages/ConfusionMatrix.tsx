/* Confusion Matrix — for the selected model, how predicted classes line up
   against the true classes on the FULL test set (result.confusion_matrix).

   Rendered as a custom CSS-grid heatmap (not a chart library): rows are the true
   class, columns are the predicted class, and each cell is shaded by its value.
   The diagonal (correct predictions) should dominate a good model.

   • Normalise toggle: raw counts ↔ row-normalised (each true-class row sums to
     1.0). The normalisation is computed CLIENT-SIDE from the raw counts the
     contract provides — it is display math, not a second ML pass.
   • Model selector when more than one model succeeded.
   • Sizes to the label count and scrolls for many classes (multiclass-safe). */

import { useMemo, useState } from "react"

import type { ConfusionMatrixEntry } from "@/api/types"
import { fmtInt } from "@/lib/format"
import { ResultGate } from "@/components/results/ResultGate"
import { ModelSelector } from "@/components/results/ModelSelector"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Switch } from "@/components/ui/switch"
import { EmptyState, PageHeader } from "@/components/common/States"

export default function ConfusionMatrix() {
  return (
    <ResultGate title="Confusion Matrix" subtitle="Predicted vs. true classes on the test set.">
      {(run) => (
        <ConfusionBody
          matrices={run.confusion_matrix}
          problemType={run.run.problem_type}
        />
      )}
    </ResultGate>
  )
}

function ConfusionBody({
  matrices,
  problemType,
}: {
  matrices: Record<string, ConfusionMatrixEntry>
  problemType: string
}) {
  const modelNames = Object.keys(matrices)
  const [model, setModel] = useState(modelNames[0] ?? "")
  const [normalise, setNormalise] = useState(false)

  // Only successful models appear in confusion_matrix; if a run had none, say so.
  // For multilabel there is no single confusion matrix by design (each label is its own
  // one-vs-rest problem) — show the honest reason, not a misleading "no models" message.
  if (modelNames.length === 0) {
    return (
      <div>
        <PageHeader title="Confusion Matrix" />
        <EmptyState
          title="No confusion matrix"
          description={
            problemType === "multilabel"
              ? "A single confusion matrix is not defined for multilabel runs — each label is a separate one-vs-rest problem. See the per-label Class Report and ROC/PR Curves instead."
              : "No model trained successfully on this run, so there is nothing to chart."
          }
        />
      </div>
    )
  }

  const entry = matrices[model] ?? matrices[modelNames[0]]
  return (
    <div>
      <PageHeader
        title="Confusion Matrix"
        subtitle={`${entry.labels.length} classes · full test set`}
        actions={
          <div className="flex items-center gap-4">
            <Switch
              id="normalise"
              label="Row-normalise"
              checked={normalise}
              onChange={(e) => setNormalise(e.target.checked)}
            />
            <ModelSelector models={modelNames} value={model} onChange={setModel} />
          </div>
        }
      />
      <Card>
        <CardHeader>
          <CardTitle>{model}</CardTitle>
        </CardHeader>
        <CardContent>
          <Heatmap entry={entry} normalise={normalise} />
        </CardContent>
      </Card>
    </div>
  )
}

function Heatmap({ entry, normalise }: { entry: ConfusionMatrixEntry; normalise: boolean }) {
  const { labels, matrix } = entry

  // Per-row totals (used both for normalisation and to scale color intensity).
  const rowTotals = useMemo(() => matrix.map((row) => row.reduce((a, b) => a + b, 0)), [matrix])
  const globalMax = useMemo(() => Math.max(1, ...matrix.flat()), [matrix])

  const n = labels.length
  // auto cell size: shrink as classes grow, but keep a readable floor.
  const cell = n > 8 ? 48 : 64

  return (
    <div className="overflow-auto">
      <div className="inline-block min-w-full">
        {/* "Predicted →" title, aligned over the prediction columns only (not the
            left "True ↓" strip + row-label gutter), so it sits above the columns it labels. */}
        <div className="flex">
          <div className="invisible flex items-center pr-1" aria-hidden>
            <span className="text-xs font-medium [writing-mode:vertical-rl] rotate-180">True ↓</span>
          </div>
          <div
            className="grid gap-px"
            style={{ gridTemplateColumns: `minmax(72px,auto) repeat(${n}, ${cell}px)` }}
          >
            <div />
            <div
              className="mb-1 text-center text-xs font-medium text-muted-foreground"
              style={{ gridColumn: `span ${n}` }}
            >
              Predicted →
            </div>
          </div>
        </div>
        <div className="flex">
          {/* rotated "True" axis label */}
          <div className="flex items-center pr-1">
            <span className="text-xs font-medium text-muted-foreground [writing-mode:vertical-rl] rotate-180">
              True ↓
            </span>
          </div>
          <div
            className="grid gap-px"
            style={{ gridTemplateColumns: `minmax(72px,auto) repeat(${n}, ${cell}px)` }}
            role="table"
            aria-label={`Confusion matrix, ${normalise ? "row-normalised" : "raw counts"}`}
          >
            {/* header row: corner + predicted labels */}
            <div />
            {labels.map((l) => (
              <div
                key={`h-${l}`}
                className="truncate px-1 py-1 text-center text-xs font-semibold text-muted-foreground"
                title={l}
              >
                {l}
              </div>
            ))}

            {/* body rows */}
            {matrix.map((row, ri) => (
              <Row
                key={`r-${labels[ri]}`}
                label={labels[ri]}
                row={row}
                rowTotal={rowTotals[ri]}
                rowIndex={ri}
                globalMax={globalMax}
                normalise={normalise}
                cell={cell}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function Row({
  label,
  row,
  rowTotal,
  rowIndex,
  globalMax,
  normalise,
  cell,
}: {
  label: string
  row: number[]
  rowTotal: number
  rowIndex: number
  globalMax: number
  normalise: boolean
  cell: number
}) {
  return (
    <>
      <div
        className="flex items-center truncate px-2 text-xs font-semibold text-muted-foreground"
        title={label}
      >
        {label}
      </div>
      {row.map((value, ci) => {
        // Intensity 0–1: normalised uses the row fraction; raw uses value/globalMax.
        const fraction = rowTotal > 0 ? value / rowTotal : 0
        const intensity = normalise ? fraction : value / globalMax
        const onDiagonal = ci === rowIndex
        // White text once the indigo wash is dark enough to need it.
        const dark = intensity > 0.5
        const display = normalise ? fraction.toFixed(2) : fmtInt(value)
        return (
          <div
            key={ci}
            role="cell"
            title={`true ${label} → predicted: ${value} (${(fraction * 100).toFixed(1)}%)`}
            className="flex items-center justify-center rounded-sm font-mono text-xs"
            style={{
              height: cell,
              backgroundColor: `rgba(79, 70, 229, ${0.08 + intensity * 0.92})`,
              color: dark ? "#ffffff" : "#0f172a",
              outline: onDiagonal ? "2px solid rgba(16,185,129,0.7)" : "none",
              outlineOffset: -2,
            }}
          >
            {display}
          </div>
        )
      })}
    </>
  )
}
