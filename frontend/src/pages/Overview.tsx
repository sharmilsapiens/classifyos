/* Overview — the dashboard landing page and the run summary.

   Reads the LAST /run result from the global store and summarizes it: a KPI
   stats band, a per-model comparison across the key metrics (Recharts grouped
   bars), the active configuration, and quick links to the detail pages. Before
   any run it shows an invitation to start the Upload → Configure → Run flow
   (never a blank screen).

   Failed models are never dropped: they appear as greyed chips with the error in
   a tooltip (the contract includes failed rows by design). */

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
import { fmtInt, fmtMetric } from "@/lib/format"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { buttonVariants } from "@/components/ui/button"
import { EmptyState, PageHeader } from "@/components/common/States"

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

export default function Overview() {
  const { result, serverPath } = useApp()
  const run = result?.result

  // No run yet → invite the user to start the flow.
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

  const best = bestModel(run.models)
  // Per-model comparison across the key metrics (successful models only — failed
  // ones have null metrics and are shown as chips below instead).
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
        subtitle={`Last run · ${run.run.target} · ${run.run.problem_type}`}
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
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={chartData} margin={{ top: 8, right: 8, bottom: 8, left: -16 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 12, fill: "#64748b" }} />
                  <YAxis domain={[0, 1]} tick={{ fontSize: 12, fill: "#64748b" }} />
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
            )}
          </CardContent>
        </Card>
      </div>

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
    </div>
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
