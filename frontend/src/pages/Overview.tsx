/* Overview — the dashboard landing page AND the merged run screen.

   9c merge: the old separate "Pipeline" page is gone; its in-progress / error /
   results states live here now, so this is one continuous screen that matches
   the Configure → Run → watch → see-results flow. /pipeline redirects here.

   The four states this page renders:
   1. RUNNING   — /run is SYNCHRONOUS (one blocking request), so while we wait we
                  show the pipeline stages + a spinner. (There is no live log to
                  stream — the engine returns everything in one response — so we
                  show the canonical stage list honestly rather than fake a feed.)
   2. ERROR     — the run did not complete; we distinguish a 422 (validation) from
                  a 400 (run error) the same way the old Pipeline page did.
   3. NO RUN    — an invitation to start the Upload → Configure → Run flow.
   4. RESULTS   — the run summary: a KPI band, a per-model comparison, the active
                  configuration, the model scoreboard + artifact downloads, quick
                  links to the detail pages, and the raw envelope (collapsed).

   Failed models are never dropped: they appear as greyed chips / a failed row
   with the error in a tooltip (the contract includes failed rows by design). */

import { Link } from "react-router-dom"
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

import { useApp } from "@/store/AppStore"
import type { ModelMetrics } from "@/api/types"
import { outputUrl } from "@/api/client"
import { fmtBytes, fmtInt, fmtMetric } from "@/lib/format"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { buttonVariants } from "@/components/ui/button"
import { EmptyState, ErrorState, PageHeader, Spinner } from "@/components/common/States"

/** Pick the model with the highest F1-weighted among those that trained ok. */
function bestModel(models: ModelMetrics[]): ModelMetrics | null {
  const ok = models.filter((m) => m.status === "ok")
  if (!ok.length) return null
  return ok.reduce((best, m) => ((m.f1_weighted ?? -1) > (best.f1_weighted ?? -1) ? m : best))
}

// The result pages a successful run unlocks (quick links at the bottom).
const DETAIL_LINKS = [
  { to: "/feature-impact", label: "Feature Impact" },
  { to: "/confusion", label: "Confusion Matrix" },
  { to: "/class-report", label: "Class Report" },
  { to: "/curves", label: "ROC / PR Curves" },
  { to: "/predictions", label: "Predictions" },
  { to: "/interactions", label: "Interactions" },
]

// The canonical pipeline stages (RUNBOOK order). Shown while a run is in flight.
const PIPELINE_STAGES = [
  "Load data",
  "Feature impact (raw)",
  "Train / test split",
  "Preprocess (fit on train)",
  "Feature engineering",
  "Interaction features",
  "Class balancing (train only)",
  "Train + evaluate every model",
  "Write artifacts",
]

export default function Overview() {
  const { running, result, runError, runFieldErrors, serverPath } = useApp()
  const run = result?.result

  // 1. RUNNING — synchronous run in flight.
  if (running) {
    return (
      <div>
        <PageHeader title="Overview" subtitle="Running the full pipeline…" />
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Spinner className="h-4 w-4 text-primary" />
              Training models on the server
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="mb-4 text-sm text-muted-foreground">
              <code className="font-mono">/run</code> is synchronous — the request runs the whole
              pipeline and returns everything in one response, so this can take a while (more so
              with many algorithms or tuning on). The stages it works through:
            </p>
            <ol className="space-y-1.5 text-sm">
              {PIPELINE_STAGES.map((stage, i) => (
                <li key={stage} className="flex items-center gap-2.5 text-muted-foreground">
                  <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-muted font-mono text-[11px]">
                    {i + 1}
                  </span>
                  {stage}
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      </div>
    )
  }

  // 2. ERROR — distinguish a 422 (validation, field-level) from a 400 (run error).
  if (runError) {
    const isValidation = runFieldErrors.length > 0
    return (
      <div>
        <PageHeader title="Overview" subtitle="The run did not complete." />
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

  // 3. NO RUN — invite the user to start the flow.
  if (!run) {
    return (
      <div>
        <PageHeader title="Overview" subtitle="Your run summary will appear here." />
        <EmptyState
          title="No run yet"
          description={
            serverPath
              ? "Your dataset is uploaded. Configure a run to see results here."
              : "Upload a dataset, configure a run, and the results will be summarized here."
          }
          action={
            <Link to={serverPath ? "/configure" : "/upload"} className={buttonVariants({ size: "sm" })}>
              {serverPath ? "Configure a run" : "Upload data"}
            </Link>
          }
        />
      </div>
    )
  }

  // 4. RESULTS.
  const best = bestModel(run.models)
  // Per-model comparison across the key metrics (successful models only — failed
  // ones have null metrics and are shown as chips/rows below instead).
  const chartData = run.models
    .filter((m) => m.status === "ok")
    .map((m) => ({
      name: m.name,
      accuracy: m.accuracy ?? 0,
      f1: m.f1_weighted ?? 0,
      roc_auc: m.roc_auc ?? 0,
      mcc: m.mcc ?? 0,
    }))

  return (
    <div>
      <PageHeader
        title="Overview"
        subtitle={`Last run · ${run.run.target} · ${run.run.problem_type} · ${run.run.models_succeeded}/${run.models.length} models`}
        actions={<Badge variant="success">schema {result?.schema_version}</Badge>}
      />

      {/* KPI stats band */}
      <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        <StatCard
          label="Best model"
          value={best?.name ?? "—"}
          hint={best ? `F1-weighted ${fmtMetric(best.f1_weighted)}` : "no model trained"}
          featured
        />
        <StatCard label="Test accuracy" value={fmtMetric(best?.accuracy)} hint="best model" />
        <StatCard label="ROC-AUC" value={fmtMetric(best?.roc_auc)} hint="full test set" />
        <StatCard label="MCC" value={fmtMetric(best?.mcc)} hint="imbalance-robust" />
        <StatCard
          label="Models trained"
          value={`${run.run.models_succeeded} / ${run.models.length}`}
          hint={run.run.models_succeeded === run.models.length ? "all succeeded" : "some failed"}
        />
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_1.4fr]">
        {/* Active configuration */}
        <Card>
          <CardHeader>
            <CardTitle>Active configuration</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2.5 text-sm">
            <Row k="Dataset" v={serverPath ?? "—"} mono />
            <Row k="Rows · features" v={`${fmtInt(run.run.n_rows)} · ${run.run.features.length}`} mono />
            <Row k="Target" v={`${run.run.target} · ${run.run.problem_type}`} />
            <Row k="Class balance" v={run.run.class_balance ?? "—"} />
            <Row k="Train · test" v={`${fmtInt(run.run.n_train)} · ${fmtInt(run.run.n_test)}`} mono />
            <Row k="Interaction cols" v={`${run.run.interaction_cols.length}`} mono />
            <div className="pt-1">
              <div className="mb-1.5 text-xs text-muted-foreground">Algorithms</div>
              <div className="flex flex-wrap gap-1.5">
                {run.models.map((m) => (
                  <Badge
                    key={m.name}
                    variant={m.status === "ok" ? "default" : "destructive"}
                    title={m.status === "failed" && m.error ? m.error : undefined}
                  >
                    {m.name}
                    {m.status === "failed" && " (failed)"}
                  </Badge>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Per-model comparison across key metrics. */}
        <Card>
          <CardHeader>
            <CardTitle>Model comparison · key metrics</CardTitle>
          </CardHeader>
          <CardContent>
            {chartData.length === 0 ? (
              <p className="py-10 text-center text-sm text-muted-foreground">
                No successful models to chart.
              </p>
            ) : (
              <div
                role="img"
                aria-label={`Bar chart comparing accuracy, F1-weighted, ROC-AUC and MCC across ${chartData
                  .map((d) => d.name)
                  .join(", ")}.`}
              >
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={chartData} margin={{ top: 8, right: 8, bottom: 8, left: -16 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                    <XAxis dataKey="name" tick={{ fontSize: 12, fill: "#475569" }} />
                    <YAxis domain={[0, 1]} tick={{ fontSize: 12, fill: "#475569" }} />
                    <Tooltip
                      formatter={(value, name) => [fmtMetric(Number(value)), String(name)]}
                      contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e2e8f0" }}
                    />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Bar dataKey="accuracy" fill="#4f46e5" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="f1" fill="#0ea5e9" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="roc_auc" fill="#10b981" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="mcc" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Model scoreboard — the full per-model table (was the Pipeline page). */}
      <Card className="mt-5">
        <CardHeader>
          <CardTitle>Model scoreboard</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr className="border-b">
                  <th className="px-2 py-2 text-left font-medium">Model</th>
                  <th className="px-2 py-2 text-left font-medium">Status</th>
                  <th className="px-2 py-2 text-right font-medium">Accuracy</th>
                  <th className="px-2 py-2 text-right font-medium">F1 · test</th>
                  <th className="px-2 py-2 text-right font-medium" title="F1-weighted on the pre-balance train split">
                    F1 · train
                  </th>
                  <th className="px-2 py-2 text-right font-medium" title="Train − test F1-weighted; a large positive gap suggests overfitting">
                    Gap
                  </th>
                  <th className="px-2 py-2 text-right font-medium">ROC-AUC</th>
                  <th className="px-2 py-2 text-right font-medium">MCC</th>
                </tr>
              </thead>
              <tbody>
                {run.models.map((m) => (
                  <tr
                    key={m.name}
                    className={`border-b last:border-0 ${m.status === "failed" ? "text-muted-foreground" : ""}`}
                  >
                    <td className="px-2 py-2 font-medium">
                      {m.name}
                      {m.status === "failed" && m.error && (
                        <span className="ml-2 text-xs text-muted-foreground" title={m.error}>
                          ({m.error})
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-2">
                      <Badge variant={m.status === "ok" ? "success" : "destructive"}>{m.status}</Badge>
                    </td>
                    <td className="px-2 py-2 text-right font-mono">{fmtMetric(m.accuracy)}</td>
                    <td className="px-2 py-2 text-right font-mono">{fmtMetric(m.f1_weighted)}</td>
                    <td className="px-2 py-2 text-right font-mono">{fmtMetric(m.train?.f1_weighted)}</td>
                    <OverfitGapCell test={m.f1_weighted} train={m.train?.f1_weighted} />
                    <td className="px-2 py-2 text-right font-mono">{fmtMetric(m.roc_auc)}</td>
                    <td className="px-2 py-2 text-right font-mono">{fmtMetric(m.mcc)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            Accuracy, ROC-AUC and MCC are on the held-out <strong>test</strong> set. <strong>Gap</strong> is
            train − test F1-weighted (train measured on the pre-balance split): a large positive gap suggests
            the model is overfitting.
          </p>
        </CardContent>
      </Card>

      {/* Artifacts — the output files, fetched on demand from /outputs/{name}. */}
      <Card className="mt-5">
        <CardHeader>
          <CardTitle>Artifacts ({run.artifacts.length})</CardTitle>
        </CardHeader>
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

      {/* Quick links to the detail pages. */}
      <Card className="mt-5">
        <CardHeader>
          <CardTitle>Explore the results</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {DETAIL_LINKS.map((l) => (
            <Link key={l.to} to={l.to} className={buttonVariants({ variant: "outline", size: "sm" })}>
              {l.label}
            </Link>
          ))}
        </CardContent>
      </Card>

      {/* Raw envelope — proves the round-trip; collapsed by default. */}
      <Card className="mt-5">
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

function StatCard({
  label,
  value,
  hint,
  featured,
}: {
  label: string
  value: string
  hint?: string
  featured?: boolean
}) {
  return (
    <Card className={featured ? "border-transparent bg-primary text-primary-foreground" : ""}>
      <CardContent className="p-4">
        <div className={featured ? "text-xs text-primary-foreground/80" : "text-xs text-muted-foreground"}>
          {label}
        </div>
        <div className="mt-1.5 font-mono text-2xl font-bold tracking-tight">{value}</div>
        {hint && (
          <div className={featured ? "mt-1 text-[11px] text-primary-foreground/80" : "mt-1 text-[11px] text-muted-foreground"}>
            {hint}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/**
 * Overfit-gap table cell: train − test F1-weighted. A large positive gap (train ≫ test) is the
 * classic overfitting signature, so we tint it amber past 0.10 and red past 0.20. Renders "—"
 * when either side is missing (failed model, or train metrics absent on an older schema).
 */
function OverfitGapCell({ test, train }: { test: number | null; train: number | null | undefined }) {
  if (test == null || train == null) {
    return <td className="px-2 py-2 text-right font-mono text-muted-foreground">—</td>
  }
  const gap = train - test
  const tone =
    gap >= 0.2 ? "text-destructive" : gap >= 0.1 ? "text-amber-600" : "text-muted-foreground"
  const sign = gap > 0 ? "+" : ""
  return (
    <td
      className={`px-2 py-2 text-right font-mono ${tone}`}
      title={gap >= 0.1 ? "Train markedly above test — likely overfitting" : undefined}
    >
      {sign}
      {fmtMetric(gap)}
    </td>
  )
}

/** A simple key/value row used in the config card. */
function Row({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-dashed border-border pb-2 last:border-0">
      <span className="shrink-0 text-muted-foreground">{k}</span>
      <span className={`truncate text-right ${mono ? "font-mono font-semibold" : "font-semibold"}`}>{v}</span>
    </div>
  )
}
