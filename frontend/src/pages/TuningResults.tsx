/* Tuning Results — the hyperparameters Optuna chose for the last run.

   Reads `result.tuning` (schema 1.1, additive) straight from the store — no new
   network call, and NOT scraped from run_profile.json. The block is optional, so
   this page renders three honest states:

   1. NO RUN        — handled by <ResultGate> (an invitation to run a pipeline).
   2. TUNING OFF    — a run exists but `tuning` is null or `enabled:false`: a clear
                      "tuning was not enabled" message, pointing at Configuration.
   3. TUNING ON     — a settings header strip (metric / CV / trials / timeout) plus
                      one card per tuned model listing its chosen hyperparameters.
                      Models that ran on defaults (in the run, absent from
                      `tuned_models`) get a small note so the picture is complete.

   Every best_params value is `unknown`, so it is rendered defensively (numbers /
   bools / strings stringified; never crashes on an unexpected type). A tuned model
   whose best_params is empty ({}) shows "no params returned — used defaults". */

import type { ModelMetrics, RunTuning } from "@/api/types"
import { ResultGate } from "@/components/results/ResultGate"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Link } from "react-router-dom"
import { buttonVariants } from "@/components/ui/button"
import { EmptyState, PageHeader } from "@/components/common/States"

/** Stringify a heterogeneous best_params value safely — never throws on a surprise type. */
function fmtParamValue(value: unknown): string {
  if (value === null || value === undefined) return "—"
  if (typeof value === "number") {
    if (Number.isNaN(value)) return "—"
    return String(value)
  }
  if (typeof value === "boolean") return value ? "true" : "false"
  if (typeof value === "string") return value
  // Arrays / nested objects / anything unexpected: a safe JSON fallback.
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

export default function TuningResults() {
  return (
    <ResultGate
      title="Tuning Results"
      subtitle="The hyperparameters Optuna chose for each tuned model."
    >
      {(run) => <TuningBody tuning={run.tuning ?? null} models={run.models} />}
    </ResultGate>
  )
}

function TuningBody({
  tuning,
  models,
}: {
  tuning: RunTuning | null
  models: ModelMetrics[]
}) {
  // State 2 — a run exists, but tuning was OFF (null block, or enabled:false).
  if (!tuning || !tuning.enabled) {
    return (
      <div>
        <PageHeader
          title="Tuning Results"
          subtitle="Hyperparameter tuning for the last run."
        />
        <EmptyState
          title="Tuning was not enabled for this run"
          description="Optuna hyperparameter tuning is off by default, so the models trained on their default hyperparameters. Turn it on under Tuning in Configuration, then run again to see the chosen values here."
          action={
            <Link to="/configure" className={buttonVariants({ size: "sm" })}>
              Open Configuration
            </Link>
          }
        />
      </div>
    )
  }

  // State 3 — tuning was ON. Settings header + one card per tuned model.
  const tuned = tuning.tuned_models ?? []
  const tunedSet = new Set(tuned)
  // Models that ran on defaults: present in the run but absent from tuned_models.
  const untuned = models.filter((m) => !tunedSet.has(m.name))

  return (
    <div>
      <PageHeader
        title="Tuning Results"
        subtitle={`${tuned.length} model${tuned.length === 1 ? "" : "s"} tuned with Optuna.`}
        actions={<Badge variant="success">tuning on</Badge>}
      />

      {/* Settings header strip — how the studies were run. */}
      <Card className="mb-5">
        <CardHeader>
          <CardTitle>Tuning settings</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
            <Setting label="Metric" value={tuning.metric} mono />
            <Setting
              label="Cross-validation"
              value={tuning.cv ? `${tuning.cv_folds}-fold` : "single split"}
            />
            <Setting label="Trials / model" value={String(tuning.n_trials)} mono />
            <Setting
              label="Timeout / model"
              value={tuning.timeout_seconds === null ? "none" : `${tuning.timeout_seconds}s`}
              mono
            />
            <Setting label="Models tuned" value={String(tuned.length)} mono />
          </div>
        </CardContent>
      </Card>

      {/* One card per tuned model. */}
      {tuned.length === 0 ? (
        <EmptyState
          title="No model produced tuned parameters"
          description="Tuning was enabled, but no study returned a result (every model fell back to its defaults)."
        />
      ) : (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
          {tuned.map((name) => (
            <ModelParamsCard
              key={name}
              name={name}
              params={tuning.best_params?.[name] ?? {}}
            />
          ))}
        </div>
      )}

      {/* Models that ran on defaults — so the picture is complete. */}
      {untuned.length > 0 && (
        <Card className="mt-5">
          <CardHeader>
            <CardTitle>Ran on default hyperparameters</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="mb-3 text-sm text-muted-foreground">
              These models were part of the run but were not tuned, so they used their
              built-in defaults.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {untuned.map((m) => (
                <Badge key={m.name} variant="outline">
                  {m.name}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

/** One tuned model's chosen hyperparameters as a key → value table. */
function ModelParamsCard({
  name,
  params,
}: {
  name: string
  params: Record<string, unknown>
}) {
  const entries = Object.entries(params)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {name}
          <Badge variant="secondary">tuned</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No params returned — used defaults.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr className="border-b">
                <th className="px-2 py-2 text-left font-medium">Hyperparameter</th>
                <th className="px-2 py-2 text-right font-medium">Value</th>
              </tr>
            </thead>
            <tbody>
              {entries.map(([key, value]) => (
                <tr key={key} className="border-b last:border-0">
                  <td className="px-2 py-2 font-medium">{key}</td>
                  <td className="px-2 py-2 text-right font-mono">{fmtParamValue(value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  )
}

/** A small labelled value used in the settings header strip. */
function Setting({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-1 text-sm font-semibold ${mono ? "font-mono" : ""}`}>{value}</div>
    </div>
  )
}
