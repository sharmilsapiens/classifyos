/* Feature Impact — how strongly each feature associates with the target,
   measured on the RAW data before modelling (result.feature_impact).

   What it shows:
   • A ranked horizontal bar of the composite score (or any single metric you
     pick) — Recharts, one bar per feature.
   • A full per-metric table (ANOVA-F, mutual info, point-biserial / corr-ratio).
     These are null-safe: binary problems have point_biserial, multiclass have
     corr_ratio — the other is null, shown as "—".
   • The id_like flag surfaced PROMINENTLY (a warning chip + a banner). An
     id_like feature is leakage bait — near-unique like an ID column — and a high
     score there usually means the model is "cheating", not learning.
   • The plot4 PNG (the richer 2-panel artifact) alongside, fetched on demand. */

import { useMemo, useState } from "react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { AlertTriangle } from "lucide-react"

import type { FeatureImpactRow, FeatureImportanceRow, PermutationImportanceRow } from "@/api/types"
import { runScopedArtifactId } from "@/api/client"
import { useApp } from "@/store/AppStore"
import { fmtMetric } from "@/lib/format"
import { ResultGate } from "@/components/results/ResultGate"
import { PngArtifact } from "@/components/results/PngArtifact"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { PageHeader } from "@/components/common/States"

// The metrics a user can rank by. Each notes which problem type populates it.
const METRICS = [
  { key: "composite_score", label: "Composite score" },
  { key: "anova_f", label: "ANOVA F" },
  { key: "mutual_info", label: "Mutual information" },
  { key: "point_biserial", label: "Point-biserial (binary)" },
  { key: "corr_ratio", label: "Correlation ratio (multiclass)" },
] as const

type MetricKey = (typeof METRICS)[number]["key"]

export default function FeatureImpact() {
  return (
    <ResultGate title="Feature Impact" subtitle="Raw association of each feature with the target.">
      {(run) => (
        <FeatureImpactBody
          rows={run.feature_impact}
          artifacts={run.artifacts}
          importance={run.feature_importance ?? null}
          permutation={run.permutation_importance ?? null}
          runId={runScopedArtifactId(run.mlflow)}
        />
      )}
    </ResultGate>
  )
}

function FeatureImpactBody({
  rows,
  artifacts,
  importance,
  permutation,
  runId,
}: {
  rows: FeatureImpactRow[]
  artifacts: import("@/api/types").ArtifactEntry[]
  importance: Record<string, FeatureImportanceRow[]> | null
  permutation: Record<string, PermutationImportanceRow[]> | null
  runId?: string
}) {
  const [metric, setMetric] = useState<MetricKey>("composite_score")
  // The permutation-importance scoring metric the run was configured with (the form persists
  // in the store after a run). Falls back to the default if the form isn't available.
  const { form } = useApp()
  const permutationMetric = form?.permutation_metric ?? "f1_weighted"
  const flagged = rows.filter((r) => r.id_like)

  // Chart data: keep the contract's rank order, show the top 20 for readability.
  const chartData = useMemo(
    () =>
      rows
        .slice(0, 20)
        .map((r) => ({ feature: r.feature, value: r[metric] ?? 0, id_like: r.id_like })),
    [rows, metric],
  )
  const chartHeight = Math.max(220, chartData.length * 28)

  return (
    <div>
      <PageHeader
        title="Feature Impact"
        subtitle="Ranked on the raw data, before preprocessing — a screening signal, not a final selection."
        actions={
          <div className="flex items-center gap-2">
            <Label htmlFor="metric" className="text-xs text-muted-foreground">
              Rank by
            </Label>
            <Select
              id="metric"
              value={metric}
              onChange={(e) => setMetric(e.target.value as MetricKey)}
              className="h-8 w-auto"
            >
              {METRICS.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.label}
                </option>
              ))}
            </Select>
          </div>
        }
      />

      {/* Leakage warning — the headline of the whole feature-impact story. */}
      {flagged.length > 0 && (
        <div className="mb-5 flex items-start gap-3 rounded-lg border border-amber/40 bg-amber/10 p-4">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber" aria-hidden />
          <div className="text-sm">
            <p className="font-semibold text-foreground">
              {flagged.length} near-unique (ID-like) feature{flagged.length > 1 ? "s" : ""} flagged
            </p>
            <p className="mt-0.5 text-muted-foreground">
              These columns are nearly unique per row (like an ID). A high score here usually means
              leakage, not signal — consider excluding them:{" "}
              {flagged.map((f) => (
                <span key={f.feature} className="mr-1 font-mono font-medium text-amber">
                  {f.feature}
                </span>
              ))}
            </p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* Ranked bar */}
        <Card>
          <CardHeader>
            <CardTitle>Ranking · {METRICS.find((m) => m.key === metric)?.label}</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={chartHeight}>
              <BarChart
                layout="vertical"
                data={chartData}
                margin={{ top: 4, right: 16, bottom: 4, left: 8 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 11, fill: "#64748b" }} />
                <YAxis
                  type="category"
                  dataKey="feature"
                  width={150}
                  tick={{ fontSize: 11, fill: "#64748b" }}
                />
                <Tooltip
                  formatter={(value) => fmtMetric(Number(value))}
                  contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e2e8f0" }}
                />
                <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                  {chartData.map((d, i) => (
                    // id_like bars are rose to flag the leakage risk visually.
                    <Cell key={i} fill={d.id_like ? "#f43f5e" : "#4f46e5"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* plot4 — the richer 2-panel artifact. */}
        <Card>
          <CardHeader>
            <CardTitle>Feature impact plot (plot4)</CardTitle>
          </CardHeader>
          <CardContent>
            <PngArtifact
              name="plot4_feature_impact.png"
              alt="Feature impact: composite scores and per-metric comparison"
              artifacts={artifacts}
              caption="Composite barh + grouped normalized metrics"
              runId={runId}
            />
          </CardContent>
        </Card>
      </div>

      {/* Full per-metric table */}
      <Card className="mt-5">
        <CardHeader>
          <CardTitle>All features · per-metric scores</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr className="border-b">
                  <th className="px-2 py-2 text-left font-medium">#</th>
                  <th className="px-2 py-2 text-left font-medium">Feature</th>
                  <th className="px-2 py-2 text-left font-medium">Type</th>
                  <th className="px-2 py-2 text-right font-medium">Composite</th>
                  <th className="px-2 py-2 text-right font-medium">ANOVA F</th>
                  <th className="px-2 py-2 text-right font-medium">Mutual info</th>
                  <th className="px-2 py-2 text-right font-medium">Pt-biserial</th>
                  <th className="px-2 py-2 text-right font-medium">Corr-ratio</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.feature} className="border-b last:border-0">
                    <td className="px-2 py-2 font-mono text-muted-foreground">{r.rank ?? "—"}</td>
                    <td className="px-2 py-2 font-medium">
                      <span className="font-mono">{r.feature}</span>
                      {r.id_like && (
                        <Badge variant="warning" className="ml-2">
                          ID-like
                        </Badge>
                      )}
                    </td>
                    <td className="px-2 py-2 text-muted-foreground">{r.dtype_group ?? "—"}</td>
                    <td className="px-2 py-2 text-right font-mono">{fmtMetric(r.composite_score)}</td>
                    <td className="px-2 py-2 text-right font-mono">{fmtMetric(r.anova_f)}</td>
                    <td className="px-2 py-2 text-right font-mono">{fmtMetric(r.mutual_info)}</td>
                    <td className="px-2 py-2 text-right font-mono">{fmtMetric(r.point_biserial)}</td>
                    <td className="px-2 py-2 text-right font-mono">{fmtMetric(r.corr_ratio)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* Post-training (native, per-model) importance — a MODEL property, distinct from
          the raw pre-training screen above. */}
      <PostTrainingImportance importance={importance} artifacts={artifacts} runId={runId} />

      {/* Permutation importance — the model-agnostic counterpart, covering EVERY model
          (incl. SVM / NaiveBayes which have no native importance). */}
      <PermutationImportance permutation={permutation} metric={permutationMetric} />
    </div>
  )
}

// Models known to expose no native feature importance (RBF-SVM, GaussianNB) — used to
// explain an absent/partial block rather than implying the data is missing.
const NO_NATIVE_IMPORTANCE = "SVM and Naive Bayes expose no native importance, so they are omitted."

function PostTrainingImportance({
  importance,
  artifacts,
  runId,
}: {
  importance: Record<string, FeatureImportanceRow[]> | null
  artifacts: import("@/api/types").ArtifactEntry[]
  runId?: string
}) {
  const models = useMemo(
    () => Object.keys(importance ?? {}).filter((m) => (importance?.[m]?.length ?? 0) > 0),
    [importance],
  )
  const [model, setModel] = useState<string | null>(null)
  // Pick the first model with importances once the data arrives.
  const selected = model && models.includes(model) ? model : (models[0] ?? null)

  const chartData = useMemo(() => {
    if (!selected || !importance) return []
    return importance[selected]
      .slice(0, 20)
      .map((r) => ({ feature: r.feature, value: r.importance ?? 0 }))
  }, [importance, selected])
  const chartHeight = Math.max(220, chartData.length * 28)

  return (
    <Card className="mt-5">
      <CardHeader>
        <CardTitle>Post-training importance · per model</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="mb-4 text-sm text-muted-foreground">
          How much the <em>trained</em> model relied on each feature — its native importance
          (tree impurity/gain or coefficient magnitude). This is a model property, measured
          after training, and differs from the raw pre-training screen above. Values are{" "}
          <strong>not comparable across models</strong>, and cover the engineered columns
          (e.g. one-hot categories).
        </p>

        {selected ? (
          <>
            <div className="mb-3 flex items-center gap-2">
              <Label htmlFor="imp-model" className="text-xs text-muted-foreground">
                Model
              </Label>
              <Select
                id="imp-model"
                value={selected}
                onChange={(e) => setModel(e.target.value)}
                className="h-8 w-auto"
              >
                {models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </Select>
            </div>

            <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
              {/* Ranked native-importance bar for the selected model */}
              <div>
                <ResponsiveContainer width="100%" height={chartHeight}>
                  <BarChart
                    layout="vertical"
                    data={chartData}
                    margin={{ top: 4, right: 16, bottom: 4, left: 8 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                    <XAxis type="number" tick={{ fontSize: 11, fill: "#64748b" }} />
                    <YAxis
                      type="category"
                      dataKey="feature"
                      width={150}
                      tick={{ fontSize: 11, fill: "#64748b" }}
                    />
                    <Tooltip
                      formatter={(value) => fmtMetric(Number(value))}
                      contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e2e8f0" }}
                    />
                    <Bar dataKey="value" radius={[0, 4, 4, 0]} fill="#0ea5e9" />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* plot3 — the per-model importance artifact (all models in one figure). */}
              <PngArtifact
                name="plot3_feature_importance.png"
                alt="Per-model feature importance"
                artifacts={artifacts}
                caption="Top features per model that exposes importances"
                runId={runId}
              />
            </div>
            {models.length > 0 && (
              <p className="mt-3 text-xs text-muted-foreground">{NO_NATIVE_IMPORTANCE}</p>
            )}
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            No model in this run exposes a native feature importance. {NO_NATIVE_IMPORTANCE}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function PermutationImportance({
  permutation,
  metric,
}: {
  permutation: Record<string, PermutationImportanceRow[]> | null
  metric: string
}) {
  const models = useMemo(
    () => Object.keys(permutation ?? {}).filter((m) => (permutation?.[m]?.length ?? 0) > 0),
    [permutation],
  )
  const [model, setModel] = useState<string | null>(null)
  const selected = model && models.includes(model) ? model : (models[0] ?? null)

  const chartData = useMemo(() => {
    if (!selected || !permutation) return []
    return permutation[selected]
      .slice(0, 20)
      .map((r) => ({ feature: r.feature, value: r.importance ?? 0 }))
  }, [permutation, selected])
  const chartHeight = Math.max(220, chartData.length * 28)

  return (
    <Card className="mt-5">
      <CardHeader>
        <CardTitle>Permutation importance · per model</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="mb-4 text-sm text-muted-foreground">
          How much the model's <strong>test-set {metric} drops when each feature is shuffled</strong>{" "}
          — a model-agnostic measure that works for <em>every</em> model, including SVM and Naive
          Bayes (which have no native importance). Higher = the model relied on it more; a small
          negative value is shuffle noise. Measured in one consistent unit, so unlike the native
          importances above these <strong>are comparable across models</strong>. The scoring metric
          is set on the Configuration page.{" "}
          <span className="italic">
            Note: two correlated features can both look unimportant (the model leans on the
            untouched twin).
          </span>
        </p>

        {selected ? (
          <>
            <div className="mb-3 flex items-center gap-2">
              <Label htmlFor="perm-model" className="text-xs text-muted-foreground">
                Model
              </Label>
              <Select
                id="perm-model"
                value={selected}
                onChange={(e) => setModel(e.target.value)}
                className="h-8 w-auto"
              >
                {models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </Select>
            </div>

            <ResponsiveContainer width="100%" height={chartHeight}>
              <BarChart
                layout="vertical"
                data={chartData}
                margin={{ top: 4, right: 16, bottom: 4, left: 8 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 11, fill: "#64748b" }} />
                <YAxis
                  type="category"
                  dataKey="feature"
                  width={150}
                  tick={{ fontSize: 11, fill: "#64748b" }}
                />
                <Tooltip
                  formatter={(value) => fmtMetric(Number(value))}
                  contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e2e8f0" }}
                />
                <Bar dataKey="value" radius={[0, 4, 4, 0]} fill="#10b981" />
              </BarChart>
            </ResponsiveContainer>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            Permutation importance was not computed for this run.
          </p>
        )}
      </CardContent>
    </Card>
  )
}
