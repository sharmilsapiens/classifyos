/* Explainability — single-row SHAP (v1.0 structured stub).

   Honest constraint (see docs/api_contract.md, api_short_desc.md, plan_tweak #29):
   a FastAPI process holds NO trained model between requests, and v1.0 has no model
   registry. So /explain cannot produce a real SHAP explanation yet — it returns a
   structured "unavailable" payload (status:"unavailable", method/shap_values/
   base_value = null, a reason + a plain-language message). Real SHAP is a v2.0 item
   (model persistence / MLflow).

   This page is built to present that honestly — NOT to fake a waterfall over empty
   data:
   • You still pick a model + a test-row index and hit "Explain", so the real
     client → /explain path is exercised end to end (v2.0 only has to fill the
     fields, not rebuild this page).
   • The structured stub response is then shown cleanly as an intentional
     "coming in v2.0" state, surfacing the server's own reason/message.
   • The region where the SHAP waterfall WILL render is left clearly stubbed (see
     <WaterfallPlaceholder> below) so a future real response drops into an
     already-designed layout.

   We read the model list / features / target from the last /run result in the
   store (so the picker reflects what actually trained); input_file comes from the
   uploaded dataset's server_path. */

import { useState } from "react"
import { Link } from "react-router-dom"
import { Lightbulb, Sparkles } from "lucide-react"

import { useApp } from "@/store/AppStore"
import * as api from "@/api/client"
import { ApiError } from "@/api/client"
import type { ExplainResponse } from "@/api/types"
import { okModelNames } from "@/lib/results"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { EmptyState, ErrorState, PageHeader, Spinner } from "@/components/common/States"

export default function Explainability() {
  const { result, serverPath, form } = useApp()
  const run = result?.result

  // Need a completed run to know which models trained and on what features.
  if (!run) {
    return (
      <div>
        <PageHeader title="Explainability" subtitle="Per-row SHAP — a v1.0 stub (real in v2.0)." />
        <EmptyState
          title="No run yet"
          description={
            serverPath
              ? "Run a pipeline first — then you can pick a trained model and a row to (try to) explain."
              : "Upload a dataset and run a pipeline, then return here to exercise the /explain endpoint."
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

  return (
    <ExplainabilityBody
      models={okModelNames(run.models)}
      features={run.run.features}
      target={run.run.target}
      inputFile={serverPath ?? form.input_file}
      testRows={run.run.n_test}
    />
  )
}

function ExplainabilityBody({
  models,
  features,
  target,
  inputFile,
  testRows,
}: {
  models: string[]
  features: string[]
  target: string
  inputFile: string
  testRows: number
}) {
  const [model, setModel] = useState(models[0] ?? "")
  const [sampleIndex, setSampleIndex] = useState(0)
  const [loading, setLoading] = useState(false)
  const [response, setResponse] = useState<ExplainResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const maxIndex = Math.max(0, testRows - 1)

  async function onExplain() {
    setLoading(true)
    setError(null)
    setResponse(null)
    try {
      // The real client call — proves the wiring even though v1.0 returns a stub.
      const res = await api.explain({
        input_file: inputFile,
        target,
        feature_cols: features,
        model,
        sample_index: sampleIndex,
      })
      setResponse(res)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unexpected error calling /explain.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Explainability"
        subtitle="Why did the model predict this for one row? (single-row SHAP)"
        actions={<Badge variant="warning">v1.0 stub</Badge>}
      />

      {/* The honest framing — set expectations before the controls. */}
      <div className="mb-5 flex items-start gap-3 rounded-lg border border-primary/30 bg-accent p-4">
        <Lightbulb className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden />
        <div className="text-sm">
          <p className="font-semibold text-foreground">Explainability is coming in v2.0</p>
          <p className="mt-0.5 text-muted-foreground">
            A SHAP explanation needs a <em>fitted</em> model kept in memory. The API is stateless —
            it holds no model between requests and has no model registry yet — so single-row SHAP is
            deferred to v2.0 (model persistence / MLflow). You can still run the request below: it
            calls the real <code className="font-mono">/explain</code> endpoint and shows its
            structured response, so the wiring is proven and v2.0 only has to fill in the values.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[360px_1fr]">
        {/* Controls */}
        <Card>
          <CardHeader>
            <CardTitle>Explain a prediction</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="explain-model">Model</Label>
              <Select
                id="explain-model"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                disabled={models.length === 0}
              >
                {models.length === 0 ? (
                  <option value="">No successful models</option>
                ) : (
                  models.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))
                )}
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="explain-row">Test row index (0–{maxIndex})</Label>
              <Input
                id="explain-row"
                type="number"
                min={0}
                max={maxIndex}
                value={sampleIndex}
                onChange={(e) => {
                  const n = Number(e.target.value)
                  // Clamp into the valid test-row range.
                  setSampleIndex(Number.isFinite(n) ? Math.min(maxIndex, Math.max(0, Math.trunc(n))) : 0)
                }}
              />
              <p className="text-xs text-muted-foreground">
                The row in the held-out test set to explain ({testRows.toLocaleString("en-US")} rows).
              </p>
            </div>

            <Button onClick={onExplain} disabled={loading || !model} className="w-full">
              {loading ? <Spinner className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />}
              Explain
            </Button>
          </CardContent>
        </Card>

        {/* Response / waterfall region */}
        <Card>
          <CardHeader>
            <CardTitle>Explanation</CardTitle>
          </CardHeader>
          <CardContent>
            {error ? (
              <ErrorState title="Could not reach /explain" message={error} onRetry={onExplain} />
            ) : loading ? (
              <div className="flex items-center gap-2 py-10 text-sm text-muted-foreground">
                <Spinner className="h-4 w-4 text-primary" />
                Calling /explain…
              </div>
            ) : response ? (
              <ExplainResult response={response} />
            ) : (
              <p className="py-10 text-center text-sm text-muted-foreground">
                Pick a model and a row, then hit <span className="font-medium">Explain</span> to call
                the endpoint.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

/** Render the structured /explain response. In v1.0 this is the "unavailable"
 *  stub; the layout is shaped so a future real response (shap_values + base_value)
 *  drops straight into the waterfall region below. */
function ExplainResult({ response }: { response: ExplainResponse }) {
  const isUnavailable = response.status === "unavailable"

  return (
    <div className="space-y-4">
      {/* Status line — what the server said about this request. */}
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge variant={isUnavailable ? "warning" : "success"}>{response.status}</Badge>
        <span className="font-mono">{response.model}</span>
        <span className="text-muted-foreground">· row {response.sample_index}</span>
        <span className="text-muted-foreground">· schema {response.schema_version}</span>
      </div>

      {/* The server's own plain-language message (don't paraphrase it). */}
      {response.message && (
        <p className="rounded-md border bg-muted/40 p-3 text-sm text-muted-foreground">
          {response.message}
        </p>
      )}
      {response.reason && (
        <p className="text-xs text-muted-foreground">
          reason: <span className="font-mono">{response.reason}</span>
        </p>
      )}

      <WaterfallPlaceholder response={response} />
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────────
   The SHAP waterfall goes HERE in v2.0.

   When /explain returns real values, `shap_values` is a {feature: contribution}
   map and `base_value` is the model's expected value. A waterfall chart starts at
   base_value and adds each feature's contribution to reach the prediction. For
   now those fields are null, so we render an intentional placeholder instead of a
   broken/empty chart. NEXT DEV: swap the placeholder body for a Recharts waterfall
   driven by `response.shap_values` / `response.base_value` — the surrounding page,
   controls, and request wiring are already done.
   ───────────────────────────────────────────────────────────────────────────── */
function WaterfallPlaceholder({ response }: { response: ExplainResponse }) {
  const hasValues = response.shap_values != null && response.base_value != null

  if (hasValues) {
    // v2.0 path (not reachable in v1.0 — kept so the contract shape is honoured).
    return (
      <div className="rounded-md border bg-card p-4 text-sm">
        <p className="mb-2 font-medium">Feature contributions</p>
        <p className="text-xs text-muted-foreground">
          base value <span className="font-mono">{response.base_value}</span>
        </p>
        <ul className="mt-2 space-y-1">
          {Object.entries(response.shap_values ?? {}).map(([feature, contribution]) => (
            <li key={feature} className="flex justify-between font-mono text-xs">
              <span>{feature}</span>
              <span>{contribution}</span>
            </li>
          ))}
        </ul>
      </div>
    )
  }

  return (
    <div className="rounded-md border border-dashed bg-muted/20 p-6 text-center">
      <p className="text-sm font-medium text-foreground">SHAP waterfall — reserved for v2.0</p>
      <p className="mx-auto mt-1 max-w-sm text-xs text-muted-foreground">
        Once a model is persisted, this region will chart how each feature pushed the prediction
        away from the base value (<code className="font-mono">base_value</code> +{" "}
        <code className="font-mono">shap_values</code>). Both fields are{" "}
        <span className="font-mono">null</span> in v1.0.
      </p>
    </div>
  )
}
