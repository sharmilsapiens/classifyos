/* Setup Guide — a static, getting-started reference.

   WHY STATIC: the setup steps and the API reference live in markdown docs
   (RUNBOOK.md, API_RUNBOOK.md) and the locked contract (docs/api_contract.md) —
   not in any API response. There is no endpoint that exposes them, and adding one
   would be a frozen-backend change. Authoring this page FROM those real docs gives
   accuracy without coupling the frontend to engine internals. (If we ever want it
   live, exposing setup/limits as data is a clean additive v1.1 endpoint — a future
   path, not built now.)

   Everything below is taken from API_RUNBOOK.md (start the API), RUNBOOK.md (the
   engine/CLI), and docs/api_contract.md (the flow + limitations) — not free-written. */

import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { ArrowRight, Terminal } from "lucide-react"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { buttonVariants } from "@/components/ui/button"
import { PageHeader } from "@/components/common/States"

/** A copy-pasteable command block (visual only — no clipboard side effects). */
function CommandBlock({ children }: { children: string }) {
  return (
    <pre className="overflow-x-auto rounded-md border bg-foreground/95 p-3 font-mono text-xs text-background">
      {children}
    </pre>
  )
}

// The 6 endpoints, from api_short_desc.md / docs/api_contract.md.
const ENDPOINTS: Array<{ method: string; path: string; purpose: string }> = [
  { method: "GET", path: "/api/v1/health", purpose: "Liveness check → {status, service, version}. Drives the health banner." },
  { method: "POST", path: "/api/v1/upload", purpose: "Multipart upload of a CSV/Excel/Parquet; stores it under DATA_DIR/uploads/ and returns the inspect profile + server_path." },
  { method: "POST", path: "/api/v1/run", purpose: "Execute the full pipeline (ModelRunner) → the locked result envelope (schema_version 1.0)." },
  { method: "POST", path: "/api/v1/explain", purpose: "Single-row SHAP. v1.0: a structured stub (no model persistence; deferred to v2.0)." },
  { method: "GET", path: "/api/v1/outputs", purpose: "List output artifacts → [{name, suffix, size_bytes}]." },
  { method: "GET", path: "/api/v1/outputs/{name}", purpose: "Stream one artifact (CSV/PNG) — traversal-guarded by the storage layer." },
]

// Honest v1.0 limitations, sourced from plan_tweak / the runbooks.
const LIMITATIONS: Array<{ title: string; body: string }> = [
  {
    title: "/run is synchronous",
    body: "The request blocks until the whole pipeline finishes (it runs on a worker thread so the server stays responsive). A long run — big data, many algorithms, or tuning on — can approach a reverse-proxy/gateway timeout. A background-job path (submit → poll → fetch) is deferred to v1.5.",
  },
  {
    title: "/explain is a v2.0 stub",
    body: "The API is stateless and has no model registry, so single-row SHAP returns a structured 'unavailable' response. Real explanations arrive with model persistence (v2.0 / MLflow).",
  },
  {
    title: "Outputs are overwritten each run",
    body: "Artifacts use fixed filenames and all runs share one OUTPUT_DIR, so each /run overwrites the previous run's files. Download what you need before the next run, or point OUTPUT_DIR at a fresh folder.",
  },
  {
    title: "Multilabel is preliminary",
    body: "Binary and multiclass are validated; the multilabel (Product Recommendation) path has not been run end-to-end and is unverified in v1.0. Resampling falls back to class weights for multilabel.",
  },
  {
    title: "Sample data is synthetic",
    body: "The bundled CSVs are generated with constructed signal, so the metric values you see are illustrative — not representative of real insurance data.",
  },
]

export default function SetupGuide() {
  return (
    <div>
      <PageHeader
        title="Setup Guide"
        subtitle="Start the API, upload a dataset, configure a run, and read the results."
      />

      {/* Architecture */}
      <Card className="mb-5">
        <CardHeader>
          <CardTitle>Architecture</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="mb-4 text-sm text-muted-foreground">
            Three layers. You set a run up in this browser app; it is POSTed to the FastAPI
            backend, executed by the pure-Python ML engine, and the JSON result streams back to
            fill these pages. The engine has no web dependencies — the API just wraps it.
          </p>
          <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-center">
            <ArchBox title="React frontend" sub="this dashboard" />
            <ArchArrow label="/api/v1 (HTTP/JSON)" />
            <ArchBox title="FastAPI backend" sub="thin translator" />
            <ArchArrow label="in-process call" />
            <ArchBox title="Python ML engine" sub="ModelRunner / CLI" />
          </div>
        </CardContent>
      </Card>

      {/* Run flow */}
      <Card className="mb-5">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Terminal className="h-4 w-4 text-primary" aria-hidden />
            The run flow
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-5 text-sm">
          <Step n={1} title="Start the API (uvicorn on :8000)">
            <p className="mb-2 text-muted-foreground">
              From the <span className="font-mono">backend/</span> directory, with the venv active.
              In development the Vite dev server proxies <span className="font-mono">/api</span> →{" "}
              <span className="font-mono">http://localhost:8000</span>, so the frontend and API
              appear same-origin.
            </p>
            <CommandBlock>{`cd backend
.\\.venv\\Scripts\\Activate.ps1
uvicorn api.main:app --reload --port 8000`}</CommandBlock>
            <p className="mt-2 text-xs text-muted-foreground">
              The startup log echoes the resolved DATA_DIR / OUTPUT_DIR and the CORS allowlist —
              glance at them to confirm it reads/writes where you expect. The health banner at the
              top of this app turns green when it connects.
            </p>
          </Step>

          <Step n={2} title="Upload a dataset">
            <p className="text-muted-foreground">
              On the <Link to="/upload" className="text-primary underline-offset-2 hover:underline">Upload</Link>{" "}
              page, drop a CSV/Excel/Parquet file. The API saves it under{" "}
              <span className="font-mono">DATA_DIR/uploads/</span> and inspects it — returning the
              columns, types, missing-value counts, a sample, and a suggested problem type — and
              hands back a <span className="font-mono">server_path</span> the run uses as its{" "}
              <span className="font-mono">input_file</span>.
            </p>
          </Step>

          <Step n={3} title="Configure the run">
            <p className="text-muted-foreground">
              On the <Link to="/configure" className="text-primary underline-offset-2 hover:underline">Configuration</Link>{" "}
              page, choose the target, the feature columns, the problem type, the algorithms, and
              the balancing / encoding / scaling / tuning options. Three fields are required
              (input_file, target, feature_cols); everything else has a sensible default.
            </p>
          </Step>

          <Step n={4} title="Run and watch">
            <p className="text-muted-foreground">
              Hit <span className="font-medium">Run pipeline</span>. Because{" "}
              <span className="font-mono">/run</span> is synchronous, the{" "}
              <Link to="/" className="text-primary underline-offset-2 hover:underline">Overview</Link>{" "}
              page shows the in-progress stages while the server trains every model, scores them,
              draws the charts, and writes all files — then it fills with the run summary.
            </p>
          </Step>

          <Step n={5} title="Explore results and download artifacts">
            <p className="text-muted-foreground">
              The result pages (Feature Impact, Confusion Matrix, Class Report, ROC / PR Curves,
              Predictions, Interactions) render from the run's JSON. Chart PNGs and the full
              predictions CSV are fetched on demand from{" "}
              <span className="font-mono">/api/v1/outputs/&#123;name&#125;</span>.
            </p>
          </Step>
        </CardContent>
      </Card>

      {/* API reference */}
      <Card className="mb-5">
        <CardHeader>
          <CardTitle>API reference (6 endpoints)</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr className="border-b">
                  <th className="px-2 py-2 text-left font-medium">Method</th>
                  <th className="px-2 py-2 text-left font-medium">Path</th>
                  <th className="px-2 py-2 text-left font-medium">Purpose</th>
                </tr>
              </thead>
              <tbody>
                {ENDPOINTS.map((e) => (
                  <tr key={e.path} className="border-b last:border-0 align-top">
                    <td className="px-2 py-2">
                      <Badge variant={e.method === "GET" ? "secondary" : "default"}>{e.method}</Badge>
                    </td>
                    <td className="px-2 py-2 font-mono text-xs">{e.path}</td>
                    <td className="px-2 py-2 text-muted-foreground">{e.purpose}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            The <span className="font-mono">/run</span> request/response schema is LOCKED at
            schema_version 1.0 (docs/api_contract.md). FastAPI also serves interactive docs at{" "}
            <span className="font-mono">http://localhost:8000/docs</span>.
          </p>
        </CardContent>
      </Card>

      {/* Limitations */}
      <Card>
        <CardHeader>
          <CardTitle>Honest v1.0 limitations</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {LIMITATIONS.map((l) => (
            <div key={l.title} className="border-b border-dashed border-border pb-3 last:border-0 last:pb-0">
              <p className="text-sm font-semibold text-foreground">{l.title}</p>
              <p className="mt-0.5 text-sm text-muted-foreground">{l.body}</p>
            </div>
          ))}
          <div className="pt-1">
            <Link to="/risks" className={buttonVariants({ variant: "outline", size: "sm" })}>
              See the Risk Register
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function ArchBox({ title, sub }: { title: string; sub: string }) {
  return (
    <div className="flex-1 rounded-lg border bg-card px-4 py-3 text-center">
      <div className="text-sm font-semibold">{title}</div>
      <div className="text-xs text-muted-foreground">{sub}</div>
    </div>
  )
}

function ArchArrow({ label }: { label: string }) {
  return (
    <div className="flex shrink-0 flex-col items-center px-1 text-muted-foreground">
      <ArrowRight className="h-4 w-4 rotate-90 sm:rotate-0" aria-hidden />
      <span className="text-[10px]">{label}</span>
    </div>
  )
}

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-primary font-mono text-xs font-bold text-primary-foreground">
        {n}
      </span>
      <div className="min-w-0 flex-1">
        <p className="mb-1 font-semibold text-foreground">{title}</p>
        {children}
      </div>
    </div>
  )
}
