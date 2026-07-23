/* Predictions Table — a SAMPLE of per-row predictions (result.predictions).

   IMPORTANT (and shown as a banner): this is a sample (≤100 rows per model), not
   the whole test set. The full prediction table is the classification_results.csv
   artifact, downloadable via /outputs/{name} — we never imply the sample is the
   whole thing.

   Each row shows the true label, the prediction, the per-class probabilities, the
   confidence (the winning probability), and whether it was correct. You can filter
   by correct/incorrect and by model, and sort by confidence. */

import { useMemo, useState } from "react"
import { Download } from "lucide-react"

import type { PredictionsBlock } from "@/api/types"
import { outputUrl, runScopedArtifactId } from "@/api/client"
import { fmtInt, fmtMetric } from "@/lib/format"
import { ResultGate } from "@/components/results/ResultGate"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { buttonVariants } from "@/components/ui/button"
import { PageHeader } from "@/components/common/States"

type Correctness = "all" | "correct" | "incorrect"

export default function Predictions() {
  return (
    <ResultGate title="Predictions Table" subtitle="A sample of per-row predictions.">
      {(run) => (
        <PredictionsBody predictions={run.predictions} runId={runScopedArtifactId(run.mlflow)} />
      )}
    </ResultGate>
  )
}

function PredictionsBody({
  predictions,
  runId,
}: {
  predictions: PredictionsBlock
  runId?: string
}) {
  const rows = predictions.sample_rows
  const models = useMemo(() => Array.from(new Set(rows.map((r) => r.model))), [rows])
  // The class columns = the union of probability keys (stable order from the first row).
  const classes = useMemo(
    () => (rows.length ? Object.keys(rows[0].probabilities) : []),
    [rows],
  )

  const [modelFilter, setModelFilter] = useState<string>(models[0] ?? "all")
  const [correctness, setCorrectness] = useState<Correctness>("all")
  const [sortDesc, setSortDesc] = useState(true)

  const visible = useMemo(() => {
    let out = rows
    if (modelFilter !== "all") out = out.filter((r) => r.model === modelFilter)
    if (correctness === "correct") out = out.filter((r) => r.correct_flag)
    if (correctness === "incorrect") out = out.filter((r) => !r.correct_flag)
    // Sort a COPY by confidence (nulls last).
    return [...out].sort((a, b) => {
      const av = a.confidence ?? -Infinity
      const bv = b.confidence ?? -Infinity
      return sortDesc ? bv - av : av - bv
    })
  }, [rows, modelFilter, correctness, sortDesc])

  return (
    <div>
      <PageHeader
        title="Predictions Table"
        subtitle={`${visible.length} rows shown`}
        actions={
          <a
            href={outputUrl(predictions.full_csv, runId)}
            target="_blank"
            rel="noreferrer"
            className={buttonVariants({ variant: "outline", size: "sm" })}
          >
            <Download className="h-4 w-4" /> Download full CSV
          </a>
        }
      />

      {/* Sampling banner — never imply the sample is the whole table. */}
      {predictions.sampled && (
        <div className="mb-5 rounded-lg border border-sky/30 bg-sky/5 p-3 text-sm text-muted-foreground">
          Showing a sample of{" "}
          <span className="font-mono font-semibold text-foreground">
            {fmtInt(predictions.rows_returned)}
          </span>{" "}
          of{" "}
          <span className="font-mono font-semibold text-foreground">
            {fmtInt(predictions.rows_total)}
          </span>{" "}
          total predictions (≤100 per model). The full table is{" "}
          <a
            href={outputUrl(predictions.full_csv, runId)}
            target="_blank"
            rel="noreferrer"
            className="font-mono text-primary underline-offset-2 hover:underline"
          >
            {predictions.full_csv}
          </a>
          .
        </div>
      )}

      {/* Filters */}
      <div className="mb-4 flex flex-wrap items-center gap-4">
        {models.length > 1 && (
          <div className="flex items-center gap-2">
            <Label htmlFor="pred-model" className="text-xs text-muted-foreground">
              Model
            </Label>
            <Select
              id="pred-model"
              value={modelFilter}
              onChange={(e) => setModelFilter(e.target.value)}
              className="h-8 w-auto"
            >
              <option value="all">All models</option>
              {models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </Select>
          </div>
        )}
        <div className="flex items-center gap-2">
          <Label htmlFor="pred-correct" className="text-xs text-muted-foreground">
            Show
          </Label>
          <Select
            id="pred-correct"
            value={correctness}
            onChange={(e) => setCorrectness(e.target.value as Correctness)}
            className="h-8 w-auto"
          >
            <option value="all">All</option>
            <option value="correct">Correct only</option>
            <option value="incorrect">Incorrect only</option>
          </Select>
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr className="border-b">
                  <th className="px-3 py-2 text-left font-medium">Model</th>
                  <th className="px-3 py-2 text-right font-medium">Row</th>
                  <th className="px-3 py-2 text-left font-medium">Actual</th>
                  <th className="px-3 py-2 text-left font-medium">Predicted</th>
                  <th className="px-3 py-2 text-left font-medium">Result</th>
                  <th
                    className="cursor-pointer select-none px-3 py-2 text-right font-medium hover:text-foreground"
                    onClick={() => setSortDesc((d) => !d)}
                    title="Sort by confidence"
                  >
                    Confidence {sortDesc ? "▼" : "▲"}
                  </th>
                  {classes.map((c) => (
                    <th key={c} className="px-3 py-2 text-right font-medium">
                      P({c})
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visible.map((r, i) => (
                  <tr key={`${r.model}-${r.sample_index}-${i}`} className="border-b last:border-0">
                    <td className="px-3 py-2 font-medium">{r.model}</td>
                    <td className="px-3 py-2 text-right font-mono text-muted-foreground">
                      {r.sample_index}
                    </td>
                    <td className="px-3 py-2 font-mono">{r.actual}</td>
                    <td className="px-3 py-2 font-mono">{r.predicted}</td>
                    <td className="px-3 py-2">
                      <Badge variant={r.correct_flag ? "success" : "destructive"}>
                        {r.correct_flag ? "✓" : "✗"}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-right font-mono">{fmtMetric(r.confidence)}</td>
                    {classes.map((c) => (
                      <td key={c} className="px-3 py-2 text-right font-mono text-muted-foreground">
                        {fmtMetric(r.probabilities[c] ?? null)}
                      </td>
                    ))}
                  </tr>
                ))}
                {visible.length === 0 && (
                  <tr>
                    <td colSpan={6 + classes.length} className="px-3 py-8 text-center text-muted-foreground">
                      No rows match the current filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
