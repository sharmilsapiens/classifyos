/* ROC / PR Curves — interactive curves from the FULL test set (result.curves).

   The contract gives raw curve coordinates (computed once by the engine's
   curves helper, the same source the plot2 PNG draws from), so these are real
   interactive charts, not images.

   • ROC: false-positive rate (x) vs true-positive rate (y), with the no-skill
     diagonal as a reference line; AUC shown per class in the legend.
   • PR: recall (x) vs precision (y); AP (average precision) per class in legend.
   • Binary → a single curve keyed by the positive (lexicographically-last)
     class. Multiclass → one-vs-rest, one line per class.
   • Per-model selector. plot2 (and plot5 calibration, binary-only) shown as the
     downloadable PNG artifacts.

   Recharts 3.x notes (this differs from 2.x):
   • Each curve is its own <Line> with its OWN `data` prop and a numeric XAxis
     (type="number", dataKey="x") so lines with different x-grids coexist.
   • The custom tooltip uses the 3.x content-prop (a component receiving
     {active,payload,label}); the old 2.x TooltipProps generic is not used.
   • Overlap/stacking is controlled by JSX render order, not a z-index prop. */

import { useMemo, useState } from "react"
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import type { ModelCurves } from "@/api/types"
import { fmtMetric } from "@/lib/format"
import { seriesColor } from "@/lib/results"
import { ResultGate } from "@/components/results/ResultGate"
import { ModelSelector } from "@/components/results/ModelSelector"
import { PngArtifact } from "@/components/results/PngArtifact"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { EmptyState, PageHeader } from "@/components/common/States"

export default function Curves() {
  return (
    <ResultGate title="ROC / PR Curves" subtitle="Classifier discrimination on the test set.">
      {(run) => (
        <CurvesBody
          curves={run.curves}
          artifacts={run.artifacts}
          problemType={run.run.problem_type}
        />
      )}
    </ResultGate>
  )
}

/* ── Custom tooltip (3.x content-prop style) ─────────────────────────────── */
// The shape Recharts passes to a content component in 3.x. We type only the
// fields we read (no 2.x TooltipProps generic).
interface CurveTooltipProps {
  active?: boolean
  label?: number | string
  xLabel?: string
  yLabel?: string
  payload?: Array<{ name?: string; value?: number; color?: string }>
}

function CurveTooltip({ active, label, payload, xLabel, yLabel }: CurveTooltipProps) {
  if (!active || !payload || payload.length === 0) return null
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2 text-xs shadow-sm">
      <div className="mb-1 text-muted-foreground">
        {xLabel}: {typeof label === "number" ? label.toFixed(3) : label}
      </div>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-1.5" style={{ color: p.color }}>
          <span className="font-medium">{p.name}</span>
          <span className="font-mono text-foreground">
            {yLabel} {fmtMetric(p.value ?? null)}
          </span>
        </div>
      ))}
    </div>
  )
}

function CurvesBody({
  curves,
  artifacts,
  problemType,
}: {
  curves: Record<string, ModelCurves>
  artifacts: import("@/api/types").ArtifactEntry[]
  problemType: string
}) {
  const modelNames = Object.keys(curves)
  const [model, setModel] = useState(modelNames[0] ?? "")

  if (modelNames.length === 0) {
    return (
      <div>
        <PageHeader title="ROC / PR Curves" />
        <EmptyState
          title="No curves"
          description="No model trained successfully on this run, so there are no curves to draw."
        />
      </div>
    )
  }

  const entry = curves[model] ?? curves[modelNames[0]]
  const rocClasses = Object.keys(entry.roc ?? {})
  const prClasses = Object.keys(entry.pr ?? {})

  // Build per-class line data: each curve carries its own {x,y} points.
  const rocSeries = useMemo(
    () =>
      rocClasses.map((cls, i) => ({
        cls,
        color: seriesColor(i),
        auc: entry.roc[cls].auc,
        data: entry.roc[cls].fpr.map((x, j) => ({ x, y: entry.roc[cls].tpr[j] })),
      })),
    [entry, rocClasses],
  )
  const prSeries = useMemo(
    () =>
      prClasses.map((cls, i) => ({
        cls,
        color: seriesColor(i),
        ap: entry.pr[cls].ap,
        data: entry.pr[cls].recall.map((x, j) => ({ x, y: entry.pr[cls].precision[j] })),
      })),
    [entry, prClasses],
  )

  const isMulticlass = problemType === "multiclass"

  return (
    <div>
      <PageHeader
        title="ROC / PR Curves"
        subtitle={
          isMulticlass
            ? `${rocClasses.length} classes · one-vs-rest · ${model}`
            : `binary · positive class "${rocClasses[0] ?? "?"}" · ${model}`
        }
        actions={<ModelSelector models={modelNames} value={model} onChange={setModel} />}
      />

      {problemType === "multilabel" && (
        <div className="mb-5 rounded-lg border border-amber/40 bg-amber/10 p-3 text-sm text-muted-foreground">
          <span className="font-semibold text-foreground">Multilabel view is preliminary.</span>{" "}
          The multilabel path has not been validated end-to-end; treat these curves with caution.
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* ROC */}
        <Card>
          <CardHeader>
            <CardTitle>ROC curve{rocClasses.length > 1 ? "s (one-vs-rest)" : ""}</CardTitle>
          </CardHeader>
          <CardContent>
            <div
              role="img"
              aria-label={`ROC curve for ${model}: ${rocSeries
                .map((s) => `${s.cls} AUC ${fmtMetric(s.auc)}`)
                .join(", ")}`}
            >
              <ResponsiveContainer width="100%" height={320}>
                <LineChart margin={{ top: 8, right: 12, bottom: 16, left: -8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis
                    type="number"
                    dataKey="x"
                    domain={[0, 1]}
                    tick={{ fontSize: 11, fill: "#64748b" }}
                    label={{ value: "False positive rate", position: "insideBottom", offset: -8, fontSize: 11, fill: "#64748b" }}
                  />
                  <YAxis
                    type="number"
                    domain={[0, 1]}
                    tick={{ fontSize: 11, fill: "#64748b" }}
                  />
                  <Tooltip content={<CurveTooltip xLabel="FPR" yLabel="TPR" />} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  {/* no-skill diagonal — drawn first so curves render on top */}
                  <ReferenceLine
                    segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]}
                    stroke="#94a3b8"
                    strokeDasharray="4 4"
                    ifOverflow="extendDomain"
                  />
                  {rocSeries.map((s) => (
                    <Line
                      key={s.cls}
                      type="monotone"
                      data={s.data}
                      dataKey="y"
                      name={`${s.cls} · AUC ${fmtMetric(s.auc)}`}
                      stroke={s.color}
                      dot={false}
                      strokeWidth={2}
                      isAnimationActive={false}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        {/* PR */}
        <Card>
          <CardHeader>
            <CardTitle>Precision–Recall curve{prClasses.length > 1 ? "s (one-vs-rest)" : ""}</CardTitle>
          </CardHeader>
          <CardContent>
            {prClasses.length === 0 ? (
              <p className="py-16 text-center text-sm text-muted-foreground">
                PR curve not provided for this run.
              </p>
            ) : (
              <div
                role="img"
                aria-label={`Precision-recall curve for ${model}: ${prSeries
                  .map((s) => `${s.cls} AP ${fmtMetric(s.ap)}`)
                  .join(", ")}`}
              >
                <ResponsiveContainer width="100%" height={320}>
                  <LineChart margin={{ top: 8, right: 12, bottom: 16, left: -8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis
                      type="number"
                      dataKey="x"
                      domain={[0, 1]}
                      tick={{ fontSize: 11, fill: "#64748b" }}
                      label={{ value: "Recall", position: "insideBottom", offset: -8, fontSize: 11, fill: "#64748b" }}
                    />
                    <YAxis type="number" domain={[0, 1]} tick={{ fontSize: 11, fill: "#64748b" }} />
                    <Tooltip content={<CurveTooltip xLabel="Recall" yLabel="Precision" />} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    {prSeries.map((s) => (
                      <Line
                        key={s.cls}
                        type="monotone"
                        data={s.data}
                        dataKey="y"
                        name={`${s.cls} · AP ${fmtMetric(s.ap)}`}
                        stroke={s.color}
                        dot={false}
                        strokeWidth={2}
                        isAnimationActive={false}
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* PNG artifacts — plot2 (the combined ROC/PR figure) and plot5 calibration
          (binary only; a placeholder PNG for multiclass). */}
      <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>ROC / PR plot (plot2)</CardTitle>
          </CardHeader>
          <CardContent>
            <PngArtifact
              name="plot2_roc_pr_curves.png"
              alt="ROC and PR curves across models"
              artifacts={artifacts}
              caption="All models, from the same curve points"
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Calibration (plot5)</CardTitle>
          </CardHeader>
          <CardContent>
            <PngArtifact
              name="plot5_calibration_curve.png"
              alt="Calibration curve (binary only)"
              artifacts={artifacts}
              caption="Binary only — a placeholder is shown for multiclass runs"
            />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
