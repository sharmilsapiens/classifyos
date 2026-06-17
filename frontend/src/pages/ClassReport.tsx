/* Class Report — per-class precision / recall / F1 / support for the selected
   model (result.class_report[model]).

   This is the imbalanced-data story: overall accuracy can look fine while a
   minority class is barely predicted. So we:
   • Show every class's precision/recall/F1/support in a table.
   • Separate the macro/weighted-average summary rows into a footer (they are not
     classes — see lib/results.isAvgRow).
   • Highlight the weakest class by recall — the one most likely being missed.
   • Offer a grouped bar across classes (precision/recall/F1) for a quick read. */

import { useState } from "react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import type { ClassReportRow } from "@/api/types"
import { fmtInt, fmtMetric } from "@/lib/format"
import { avgRows, perClassRows } from "@/lib/results"
import { ResultGate } from "@/components/results/ResultGate"
import { ModelSelector } from "@/components/results/ModelSelector"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { EmptyState, PageHeader } from "@/components/common/States"

export default function ClassReport() {
  return (
    <ResultGate title="Class Report" subtitle="Per-class precision, recall, and F1.">
      {(run) => <ClassReportBody reports={run.class_report} />}
    </ResultGate>
  )
}

/** Index of the per-class row with the lowest recall (the weak class), or -1. */
function weakestByRecall(rows: ClassReportRow[]): number {
  let idx = -1
  let lo = Infinity
  rows.forEach((r, i) => {
    if (r.recall !== null && r.recall < lo) {
      lo = r.recall
      idx = i
    }
  })
  return idx
}

function ClassReportBody({ reports }: { reports: Record<string, ClassReportRow[]> }) {
  const modelNames = Object.keys(reports)
  const [model, setModel] = useState(modelNames[0] ?? "")

  if (modelNames.length === 0) {
    return (
      <div>
        <PageHeader title="Class Report" />
        <EmptyState
          title="No class report"
          description="No model trained successfully on this run, so there is nothing to report."
        />
      </div>
    )
  }

  const rows = reports[model] ?? reports[modelNames[0]]
  const classes = perClassRows(rows)
  const summary = avgRows(rows)
  const weakIdx = weakestByRecall(classes)
  const chartData = classes.map((r) => ({
    class: r.class,
    precision: r.precision ?? 0,
    recall: r.recall ?? 0,
    f1: r.f1 ?? 0,
  }))

  return (
    <div>
      <PageHeader
        title="Class Report"
        subtitle={`${classes.length} classes · ${model}`}
        actions={<ModelSelector models={modelNames} value={model} onChange={setModel} />}
      />

      {weakIdx >= 0 && classes[weakIdx].recall !== null && classes[weakIdx].recall! < 0.6 && (
        <div className="mb-5 rounded-lg border border-amber/40 bg-amber/10 p-4 text-sm">
          <span className="font-semibold text-foreground">Weak class: </span>
          <span className="font-mono font-medium">{classes[weakIdx].class}</span>{" "}
          <span className="text-muted-foreground">
            is recalled at only {fmtMetric(classes[weakIdx].recall)} — the model misses most of its
            true cases. On imbalanced data this is the metric that matters more than accuracy.
          </span>
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* Per-class table */}
        <Card>
          <CardHeader>
            <CardTitle>Per-class metrics</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr className="border-b">
                    <th className="px-2 py-2 text-left font-medium">Class</th>
                    <th className="px-2 py-2 text-right font-medium">Precision</th>
                    <th className="px-2 py-2 text-right font-medium">Recall</th>
                    <th className="px-2 py-2 text-right font-medium">F1</th>
                    <th className="px-2 py-2 text-right font-medium">Support</th>
                  </tr>
                </thead>
                <tbody>
                  {classes.map((r, i) => (
                    <tr
                      key={r.class}
                      className={`border-b last:border-0 ${i === weakIdx ? "bg-amber/5" : ""}`}
                    >
                      <td className="px-2 py-2 font-mono font-medium">
                        {r.class}
                        {i === weakIdx && (
                          <Badge variant="warning" className="ml-2">
                            weak
                          </Badge>
                        )}
                      </td>
                      <td className="px-2 py-2 text-right font-mono">{fmtMetric(r.precision)}</td>
                      <td className="px-2 py-2 text-right font-mono">{fmtMetric(r.recall)}</td>
                      <td className="px-2 py-2 text-right font-mono">{fmtMetric(r.f1)}</td>
                      <td className="px-2 py-2 text-right font-mono">{fmtInt(r.support)}</td>
                    </tr>
                  ))}
                </tbody>
                {summary.length > 0 && (
                  <tfoot className="text-muted-foreground">
                    {summary.map((r) => (
                      <tr key={r.class} className="border-t">
                        <td className="px-2 py-2 italic">{r.class}</td>
                        <td className="px-2 py-2 text-right font-mono">{fmtMetric(r.precision)}</td>
                        <td className="px-2 py-2 text-right font-mono">{fmtMetric(r.recall)}</td>
                        <td className="px-2 py-2 text-right font-mono">{fmtMetric(r.f1)}</td>
                        <td className="px-2 py-2 text-right font-mono">{fmtInt(r.support)}</td>
                      </tr>
                    ))}
                  </tfoot>
                )}
              </table>
            </div>
          </CardContent>
        </Card>

        {/* Grouped bar across classes */}
        <Card>
          <CardHeader>
            <CardTitle>Precision / Recall / F1 by class</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={chartData} margin={{ top: 8, right: 8, bottom: 8, left: -16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                <XAxis dataKey="class" tick={{ fontSize: 11, fill: "#64748b" }} />
                <YAxis domain={[0, 1]} tick={{ fontSize: 11, fill: "#64748b" }} />
                <Tooltip
                  formatter={(value, name) => [fmtMetric(Number(value)), String(name)]}
                  contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e2e8f0" }}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="precision" fill="#4f46e5" radius={[3, 3, 0, 0]} />
                <Bar dataKey="recall" fill="#0ea5e9" radius={[3, 3, 0, 0]} />
                <Bar dataKey="f1" fill="#10b981" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
