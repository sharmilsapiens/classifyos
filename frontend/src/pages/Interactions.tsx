/* Interaction Features — the engineered columns built by combining two original
   features (result.run.interaction_cols).

   The engine names them with operator markers: `_x_` (multiply), `_div_`
   (ratio), `_minus_` (difference) — see CLAUDE.md conventions. We decode each
   name into a readable expression so a non-technical reader can see which two
   columns were combined and how. plot6 (the interaction summary) is shown as the
   visual. When interactions were disabled (or none were discovered), we show a
   clear empty state rather than an empty list. */

import type { RunResult } from "@/api/types"
import { describeInteraction, interactionOps } from "@/lib/results"
import { ResultGate } from "@/components/results/ResultGate"
import { PngArtifact } from "@/components/results/PngArtifact"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { EmptyState, PageHeader } from "@/components/common/States"

const OP_LABEL: Record<string, string> = {
  multiply: "×",
  ratio: "÷",
  difference: "−",
}

export default function Interactions() {
  return (
    <ResultGate title="Interaction Features" subtitle="Features built by combining two columns.">
      {(run) => <InteractionsBody run={run} />}
    </ResultGate>
  )
}

function InteractionsBody({ run }: { run: RunResult }) {
  const cols = run.run.interaction_cols

  if (cols.length === 0) {
    return (
      <div>
        <PageHeader title="Interaction Features" />
        <EmptyState
          title="No interaction features"
          description="Interaction features were disabled for this run, or none were discovered. Enable them on the Configuration page to engineer combined columns."
        />
      </div>
    )
  }

  return (
    <div>
      <PageHeader
        title="Interaction Features"
        subtitle={`${cols.length} engineered column${cols.length > 1 ? "s" : ""} · part of ${run.run.active_features.length} active features`}
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1.3fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Engineered columns</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="divide-y">
              {cols.map((col) => {
                const ops = interactionOps(col)
                return (
                  <li key={col} className="py-2.5">
                    <div className="font-mono text-sm font-medium">{describeInteraction(col)}</div>
                    <div className="mt-1 flex items-center gap-2">
                      <code className="truncate text-xs text-muted-foreground">{col}</code>
                      <span className="flex gap-1">
                        {ops.map((op) => (
                          <Badge key={op} variant="secondary">
                            {OP_LABEL[op]} {op}
                          </Badge>
                        ))}
                      </span>
                    </div>
                  </li>
                )
              })}
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Interaction summary (plot6)</CardTitle>
          </CardHeader>
          <CardContent>
            <PngArtifact
              name="plot6_interaction_summary.png"
              alt="Interaction features summary: correlation with the target"
              artifacts={run.artifacts}
              caption="|correlation| of each interaction column with the target"
            />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
