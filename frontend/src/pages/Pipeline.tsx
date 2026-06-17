/* Pipeline — step 3 of Upload → Configure → Run: watch the run and see results.

   /run is SYNCHRONOUS: the request blocks until the whole pipeline finishes, so
   this page shows a clear in-progress state while we wait. (A long run — big
   data, many models, tuning on — can approach a gateway timeout; v1.5 will add
   background jobs.) On success it shows a quick model scoreboard, the artifact
   downloads, and the raw result envelope. Rich per-result charts/tables are 9b —
   here we dump the JSON so the round-trip is verifiable end to end. */

import { Link } from "react-router-dom"

import { useApp } from "@/store/AppStore"
import { outputUrl } from "@/api/client"
import { fmtBytes, fmtInt, fmtMetric } from "@/lib/format"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { buttonVariants } from "@/components/ui/button"
import { EmptyState, ErrorState, LoadingState, PageHeader } from "@/components/common/States"

export default function Pipeline() {
  const { running, result, runError, runFieldErrors } = useApp()

  // 1. In progress.
  if (running) {
    return (
      <div>
        <PageHeader title="Pipeline" subtitle="Running the full pipeline…" />
        <LoadingState message="Training models on the server (this is synchronous — tuning runs can take a while)…" />
      </div>
    )
  }

  // 2. Error — distinguish a 422 (validation, field-level) from a 400 (run error).
  if (runError) {
    const isValidation = runFieldErrors.length > 0
    return (
      <div>
        <PageHeader title="Pipeline" subtitle="The run did not complete." />
        <ErrorState
          title={isValidation ? "Invalid configuration (422)" : "Run failed"}
          message={isValidation ? "The server rejected the configuration:" : runError}
          details={isValidation ? runFieldErrors : undefined}
        />
        <div className="mt-4">
          <Link to="/configure" className={buttonVariants({ variant: "outline", size: "sm" })}>
            Back to Configuration
          </Link>
        </div>
      </div>
    )
  }

  // 3. Nothing run yet.
  const run = result?.result
  if (!run) {
    return (
      <div>
        <PageHeader title="Pipeline" subtitle="Run a configured pipeline to see results." />
        <EmptyState
          title="No run yet"
          description="Configure a run, then start it — progress and results show here."
          action={<Link to="/configure" className={buttonVariants({ size: "sm" })}>Configure a run</Link>}
        />
      </div>
    )
  }

  // 4. Success — scoreboard + artifacts + raw envelope.
  return (
    <div>
      <PageHeader
        title="Pipeline"
        subtitle={`Done · ${run.run.models_succeeded}/${run.models.length} models · ${fmtInt(run.run.n_test)} test rows`}
        actions={<Badge variant="success">schema {result?.schema_version}</Badge>}
      />

      <Card className="mb-5">
        <CardHeader><CardTitle>Model scoreboard</CardTitle></CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr className="border-b">
                  <th className="px-2 py-2 text-left font-medium">Model</th>
                  <th className="px-2 py-2 text-left font-medium">Status</th>
                  <th className="px-2 py-2 text-right font-medium">Accuracy</th>
                  <th className="px-2 py-2 text-right font-medium">F1-weighted</th>
                  <th className="px-2 py-2 text-right font-medium">ROC-AUC</th>
                  <th className="px-2 py-2 text-right font-medium">MCC</th>
                </tr>
              </thead>
              <tbody>
                {run.models.map((m) => (
                  <tr key={m.name} className="border-b last:border-0">
                    <td className="px-2 py-2 font-medium">{m.name}</td>
                    <td className="px-2 py-2">
                      <Badge variant={m.status === "ok" ? "success" : "destructive"}>{m.status}</Badge>
                    </td>
                    <td className="px-2 py-2 text-right font-mono">{fmtMetric(m.accuracy)}</td>
                    <td className="px-2 py-2 text-right font-mono">{fmtMetric(m.f1_weighted)}</td>
                    <td className="px-2 py-2 text-right font-mono">{fmtMetric(m.roc_auc)}</td>
                    <td className="px-2 py-2 text-right font-mono">{fmtMetric(m.mcc)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <Card className="mb-5">
        <CardHeader><CardTitle>Artifacts ({run.artifacts.length})</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {run.artifacts.map((a) => (
            <a
              key={a.name}
              href={outputUrl(a.name)}
              target="_blank"
              rel="noreferrer"
              className={buttonVariants({ variant: "outline", size: "sm" })}
            >
              {a.name}
              <span className="ml-1 text-xs text-muted-foreground">{fmtBytes(a.size_bytes)}</span>
            </a>
          ))}
        </CardContent>
      </Card>

      {/* Raw envelope — proves the round-trip; rich rendering is 9b. */}
      <Card>
        <CardHeader>
          <CardTitle>Raw result envelope</CardTitle>
        </CardHeader>
        <CardContent>
          <details>
            <summary className="cursor-pointer text-sm text-muted-foreground">
              Show the full /api/v1/run JSON
            </summary>
            <pre className="mt-3 max-h-[480px] overflow-auto rounded-md border bg-muted/50 p-4 font-mono text-xs">
              {JSON.stringify(result, null, 2)}
            </pre>
          </details>
        </CardContent>
      </Card>
    </div>
  )
}
