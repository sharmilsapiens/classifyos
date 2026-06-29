/* Fit Diagnostics (Train vs Test) — the overfitting / underfitting result page.

   The engine evaluates every model TWICE: on the held-out TEST split (the reported
   generalization performance) and on the pre-balance TRAIN split (real rows at the
   natural class distribution — NOT the SMOTE/undersampled matrix the model was fit on,
   so train and test are apples-to-apples). Both sets of headline metrics arrive in the
   contract: the test scalars on result.models[], and the train scalars in
   result.models[].train (schema 1.2). The Overview page surfaces only the F1 gap; this
   page surfaces the FULL picture across every headline metric.

   What it shows:
   • A cross-model summary: Test F1, Train F1, the gap, and a fit VERDICT per model
     (Good fit / Mild overfitting / Overfitting / Underfitting). Failed models are
     greyed, never dropped.
   • A per-model detail: a grouped train-vs-test bar across all bounded metrics, plus a
     full metric table (test · train · gap), including log-loss (where LOWER is better,
     so the gap is direction-aware).

   The verdict is a heuristic on the F1-weighted gap (see VERDICT thresholds) — a
   screening signal to prompt a closer look, not a definitive label. */

import { useMemo, useState } from "react"
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

import type { ModelMetrics, TrainMetrics } from "@/api/types"
import { fmtMetric } from "@/lib/format"
import { ResultGate } from "@/components/results/ResultGate"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { PageHeader } from "@/components/common/States"

// The headline metrics that exist on BOTH the test side (ModelMetrics) and the train
// side (TrainMetrics). `bounded` metrics sit on a 0–1 scale and go in the grouped bar
// chart; log-loss is unbounded (lower is better) so it is table-only and its gap is
// computed in the opposite direction.
const METRICS: Array<{
  key: keyof TrainMetrics
  label: string
  bounded: boolean
  lowerIsBetter?: boolean
}> = [
  { key: "accuracy", label: "Accuracy", bounded: true },
  { key: "f1_weighted", label: "F1 (weighted)", bounded: true },
  { key: "f1_macro", label: "F1 (macro)", bounded: true },
  { key: "precision_weighted", label: "Precision (weighted)", bounded: true },
  { key: "recall_weighted", label: "Recall (weighted)", bounded: true },
  { key: "roc_auc", label: "ROC-AUC", bounded: true },
  { key: "pr_auc", label: "PR-AUC", bounded: true },
  { key: "mcc", label: "MCC", bounded: true },
  { key: "log_loss", label: "Log loss", bounded: false, lowerIsBetter: true },
]

// --- Verdict heuristics (documented; tuned to match Overview's OverfitGapCell). ---
// The overfit gap is measured on F1-weighted, the project's primary metric. A large
// positive gap (train ≫ test) is the classic overfitting signature; a model that scores
// poorly even on its OWN training data is underfitting (too simple / under-trained).
const OVERFIT_STRONG = 0.2 // gap ≥ 0.20 → "Overfitting"
const OVERFIT_MILD = 0.1 // gap ≥ 0.10 → "Mild overfitting"
const UNDERFIT_TRAIN_F1 = 0.7 // train F1 below this → "Underfitting"

type VerdictTone = "good" | "warn" | "bad" | "muted"
interface Verdict {
  label: string
  tone: VerdictTone
  hint: string
}

/** Classify a model's fit from its train/test F1-weighted gap. A screening signal. */
function fitVerdict(m: ModelMetrics): Verdict {
  const test = m.f1_weighted
  const train = m.train?.f1_weighted
  if (test == null || train == null) {
    return { label: "—", tone: "muted", hint: "Train or test F1 is unavailable for this model." }
  }
  const gap = train - test
  if (train < UNDERFIT_TRAIN_F1) {
    return {
      label: "Underfitting",
      tone: "warn",
      hint: `Train F1 is only ${fmtMetric(train)} — the model can't fit even the training data well, so it is likely too simple or under-trained.`,
    }
  }
  if (gap >= OVERFIT_STRONG) {
    return {
      label: "Overfitting",
      tone: "bad",
      hint: `Train exceeds test by ${fmtMetric(gap)} F1 — the model has largely memorised the training set.`,
    }
  }
  if (gap >= OVERFIT_MILD) {
    return {
      label: "Mild overfitting",
      tone: "warn",
      hint: `Train exceeds test by ${fmtMetric(gap)} F1 — worth watching.`,
    }
  }
  return {
    label: "Good fit",
    tone: "good",
    hint: `Train and test F1 are close (gap ${fmtMetric(gap)}) — the model generalises well.`,
  }
}

const TONE_TO_VARIANT: Record<VerdictTone, "success" | "warning" | "destructive" | "secondary"> = {
  good: "success",
  warn: "warning",
  bad: "destructive",
  muted: "secondary",
}

export default function FitDiagnostics() {
  return (
    <ResultGate
      title="Train vs Test"
      subtitle="Compare train and test metrics to spot overfitting and underfitting."
    >
      {(run) => <FitDiagnosticsBody models={run.models} />}
    </ResultGate>
  )
}

function FitDiagnosticsBody({ models }: { models: ModelMetrics[] }) {
  // Models that actually have a train block to diagnose (ok status + the 1.2 field).
  const diagnosable = useMemo(
    () => models.filter((m) => m.status === "ok" && m.train != null),
    [models],
  )
  const [model, setModel] = useState<string | null>(null)
  const selected =
    model && diagnosable.some((m) => m.name === model)
      ? diagnosable.find((m) => m.name === model)!
      : (diagnosable[0] ?? null)

  // The 1.2 train block is absent entirely (older schema / pre-1.2 capture): explain it
  // honestly rather than render an empty page.
  if (diagnosable.length === 0) {
    return (
      <div>
        <Header />
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            This run has no train-side metrics to compare. Train-vs-test diagnostics need a
            response with the <code className="font-mono">models[].train</code> block (schema
            ≥ 1.2). Re-run the pipeline to populate this page.
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div>
      <Header />

      {/* Cross-model summary: the at-a-glance verdict table. */}
      <Card>
        <CardHeader>
          <CardTitle>Fit verdict · all models</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr className="border-b">
                  <th className="px-2 py-2 text-left font-medium">Model</th>
                  <th className="px-2 py-2 text-right font-medium">F1 · test</th>
                  <th className="px-2 py-2 text-right font-medium">F1 · train</th>
                  <th
                    className="px-2 py-2 text-right font-medium"
                    title="Train − test F1-weighted; a large positive gap suggests overfitting"
                  >
                    Gap
                  </th>
                  <th className="px-2 py-2 text-left font-medium">Verdict</th>
                </tr>
              </thead>
              <tbody>
                {models.map((m) => {
                  const verdict = fitVerdict(m)
                  const gap =
                    m.f1_weighted != null && m.train?.f1_weighted != null
                      ? m.train.f1_weighted - m.f1_weighted
                      : null
                  return (
                    <tr
                      key={m.name}
                      className={`border-b last:border-0 ${m.status === "failed" ? "text-muted-foreground" : ""}`}
                    >
                      <td className="px-2 py-2 font-medium">
                        {m.name}
                        {m.status === "failed" && (
                          <span className="ml-2 text-xs text-muted-foreground">(failed)</span>
                        )}
                      </td>
                      <td className="px-2 py-2 text-right font-mono">{fmtMetric(m.f1_weighted)}</td>
                      <td className="px-2 py-2 text-right font-mono">
                        {fmtMetric(m.train?.f1_weighted)}
                      </td>
                      <GapCell gap={gap} lowerIsBetter={false} />
                      <td className="px-2 py-2">
                        <Badge variant={TONE_TO_VARIANT[verdict.tone]} title={verdict.hint}>
                          {verdict.label}
                        </Badge>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            The verdict is a heuristic on the F1-weighted gap: a gap ≥ {OVERFIT_MILD} flags mild
            overfitting, ≥ {OVERFIT_STRONG} flags overfitting, and a train F1 below{" "}
            {UNDERFIT_TRAIN_F1} flags underfitting. It is a screening signal, not a definitive
            label — confirm against the per-metric breakdown below.
          </p>
        </CardContent>
      </Card>

      {/* Per-model detail: the full train-vs-test breakdown for one model. */}
      {selected && (
        <Card className="mt-5">
          <CardHeader>
            <CardTitle>Train vs test · per metric</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="mb-4 flex items-center gap-2">
              <Label htmlFor="fit-model" className="text-xs text-muted-foreground">
                Model
              </Label>
              <Select
                id="fit-model"
                value={selected.name}
                onChange={(e) => setModel(e.target.value)}
                className="h-8 w-auto"
              >
                {diagnosable.map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name}
                  </option>
                ))}
              </Select>
            </div>

            <MetricBars model={selected} />
            <MetricTable model={selected} />
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function Header() {
  return (
    <PageHeader
      title="Train vs Test"
      subtitle="The same headline metrics on the train and held-out test splits — the gap between them is the overfitting signal."
    />
  )
}

/** Grouped train-vs-test bar across the bounded (0–1) metrics for one model. */
function MetricBars({ model }: { model: ModelMetrics }) {
  const data = useMemo(
    () =>
      METRICS.filter((m) => m.bounded).map((m) => ({
        metric: m.label,
        test: (model[m.key as keyof ModelMetrics] as number | null) ?? 0,
        train: (model.train?.[m.key] as number | null) ?? 0,
      })),
    [model],
  )

  return (
    <div
      role="img"
      aria-label={`Grouped bar chart comparing train and test metrics for ${model.name}.`}
    >
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 8, left: -16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
          <XAxis dataKey="metric" tick={{ fontSize: 11, fill: "#475569" }} interval={0} angle={-15} textAnchor="end" height={56} />
          <YAxis domain={[0, 1]} tick={{ fontSize: 12, fill: "#475569" }} />
          <Tooltip
            formatter={(value, name) => [fmtMetric(Number(value)), String(name)]}
            contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e2e8f0" }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="test" name="Test" fill="#4f46e5" radius={[4, 4, 0, 0]} />
          <Bar dataKey="train" name="Train" fill="#94a3b8" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

/** Full per-metric table: test, train, and a direction-aware gap for one model. */
function MetricTable({ model }: { model: ModelMetrics }) {
  return (
    <div className="mt-5 overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-xs text-muted-foreground">
          <tr className="border-b">
            <th className="px-2 py-2 text-left font-medium">Metric</th>
            <th className="px-2 py-2 text-right font-medium">Test</th>
            <th className="px-2 py-2 text-right font-medium">Train</th>
            <th
              className="px-2 py-2 text-right font-medium"
              title="How much better train is than test (overfit gap). For log loss, where lower is better, the gap is test − train."
            >
              Gap
            </th>
          </tr>
        </thead>
        <tbody>
          {METRICS.map((m) => {
            const test = model[m.key as keyof ModelMetrics] as number | null
            const train = model.train?.[m.key] ?? null
            // Direction-aware gap: for most metrics (higher = better) the overfit gap is
            // train − test; for log loss (lower = better) it is test − train, so a positive
            // value always means "train looks better than test" → the overfitting direction.
            const gap =
              test != null && train != null
                ? m.lowerIsBetter
                  ? test - train
                  : train - test
                : null
            return (
              <tr key={m.key} className="border-b last:border-0">
                <td className="px-2 py-2 font-medium">{m.label}</td>
                <td className="px-2 py-2 text-right font-mono">{fmtMetric(test)}</td>
                <td className="px-2 py-2 text-right font-mono">{fmtMetric(train)}</td>
                <GapCell gap={gap} lowerIsBetter={m.lowerIsBetter} />
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/**
 * Gap table cell: train advantage over test. A large positive gap (train ≫ test) is the
 * overfitting signature, so it is tinted amber past 0.10 and red past 0.20 (matching
 * Overview's OverfitGapCell). Renders "—" when either side is missing.
 */
function GapCell({ gap, lowerIsBetter }: { gap: number | null; lowerIsBetter?: boolean }) {
  if (gap == null) {
    return <td className="px-2 py-2 text-right font-mono text-muted-foreground">—</td>
  }
  const tone =
    gap >= OVERFIT_STRONG
      ? "text-destructive"
      : gap >= OVERFIT_MILD
        ? "text-amber-600"
        : "text-muted-foreground"
  const sign = gap > 0 ? "+" : ""
  return (
    <td
      className={`px-2 py-2 text-right font-mono ${tone}`}
      title={
        gap >= OVERFIT_MILD
          ? `Train looks markedly better than test${lowerIsBetter ? " (lower log loss)" : ""} — likely overfitting`
          : undefined
      }
    >
      {sign}
      {fmtMetric(gap)}
    </td>
  )
}
