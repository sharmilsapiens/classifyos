/* ════════════════════════════════════════════════════════════════════════
   The typed API client — ONE function per endpoint of the locked contract.

   Beginner's tour of the machinery used below:
   • `fetch(url, opts)` is the browser's built-in way to make an HTTP request.
     It returns a `Promise` — a placeholder for a value that arrives later.
   • `async`/`await` lets us write that asynchronous code top-to-bottom:
     `await fetch(...)` pauses until the response arrives, then continues.
   • Every function here is `async`, so callers also `await` them.

   Errors are normalized into one `ApiError` type so the UI can show a readable
   message and, for 422s, the offending field — no page has to parse raw JSON.
   ════════════════════════════════════════════════════════════════════════ */

import type {
  CatalogsResponse,
  ClustersResponse,
  ExplainRequest,
  ExplainResponse,
  HealthResponse,
  InputTablesResponse,
  InspectProfile,
  JobStatusResponse,
  MlflowInfo,
  RunConfig,
  RunResponse,
  RunsListResponse,
  RunSubmission,
  SchemasResponse,
  TablesResponse,
} from "./types"
import { parseRunResponse } from "./parse"

// Base URL for every call. In dev, Vite proxies "/api" → http://localhost:8000
// (see vite.config.ts), so the default relative base needs no host. To point the
// built app at a deployed API, set VITE_API_BASE_URL in a .env file at build time.
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1"

/** A single, readable error type for every failed call. */
export class ApiError extends Error {
  /** HTTP status, or 0 when the request never reached the server (offline). */
  readonly status: number
  /** "network" (server unreachable), "validation" (422), or "http" (other). */
  readonly kind: "network" | "validation" | "http"
  /** For 422s: per-field messages like ["target: must be a non-empty string"]. */
  readonly fieldErrors: string[]

  constructor(
    message: string,
    status: number,
    kind: ApiError["kind"],
    fieldErrors: string[] = [],
  ) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.kind = kind
    this.fieldErrors = fieldErrors
  }
}

/** Turn FastAPI's 422 `detail` (a string OR a list of field errors) into messages. */
function extractFieldErrors(detail: unknown): string[] {
  if (typeof detail === "string") return [detail]
  if (Array.isArray(detail)) {
    return detail.map((d) => {
      // FastAPI validation errors look like { loc: ["body","target"], msg: "..." }.
      const loc = Array.isArray(d?.loc) ? d.loc.filter((p: unknown) => p !== "body").join(".") : ""
      const msg = typeof d?.msg === "string" ? d.msg : JSON.stringify(d)
      return loc ? `${loc}: ${msg}` : msg
    })
  }
  return []
}

/** Read a Response, returning parsed JSON or throwing a typed ApiError. */
async function handleJson<T>(res: Response): Promise<T> {
  // Try to parse a JSON body even on errors (FastAPI returns JSON error bodies).
  let body: unknown = null
  try {
    body = await res.json()
  } catch {
    body = null
  }

  if (res.ok) return body as T

  const detail = (body as { detail?: unknown } | null)?.detail
  if (res.status === 422) {
    const fields = extractFieldErrors(detail)
    throw new ApiError(
      fields.length ? `Invalid request — ${fields.join("; ")}` : "Invalid request (422).",
      422,
      "validation",
      fields,
    )
  }
  // The /run endpoint returns its error envelope ({status:"error", error}) on 400.
  const envelopeError = (body as { error?: unknown } | null)?.error
  const message =
    (typeof envelopeError === "string" && envelopeError) ||
    (typeof detail === "string" && detail) ||
    `Request failed (HTTP ${res.status}).`
  throw new ApiError(message, res.status, "http")
}

/** Wrap fetch so a thrown network error (server down) becomes a typed ApiError. */
async function request(input: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init)
  } catch (cause) {
    // fetch only rejects on network-level failure (server unreachable, CORS, DNS).
    throw new ApiError(
      "API offline — could not reach the server. Start uvicorn on :8000.",
      0,
      "network",
    )
  }
}

/* ──────────────────────────── endpoints ─────────────────────────────────── */

/** GET /health — liveness check (drives the health banner). */
export async function health(): Promise<HealthResponse> {
  const res = await request(`${API_BASE}/health`)
  return handleJson<HealthResponse>(res)
}

/** POST /upload — multipart file upload; returns the inspect profile + server_path. */
export async function upload(file: File, target?: string): Promise<InspectProfile> {
  const form = new FormData()
  form.append("file", file) // field name must be "file" (matches the route)
  if (target) form.append("target", target)
  // NOTE: do NOT set Content-Type; the browser adds the multipart boundary itself.
  const res = await request(`${API_BASE}/upload`, { method: "POST", body: form })
  return handleJson<InspectProfile>(res)
}

/**
 * GET /input-sources/tables — list the tables in the input DB so the "Import from database"
 * picker can offer them. A 503 (DB unreachable/unconfigured) surfaces as an ApiError. Consumed
 * by: Upload (DatabaseSourcePanel).
 */
export async function listInputTables(): Promise<InputTablesResponse> {
  const res = await request(`${API_BASE}/input-sources/tables`)
  return handleJson<InputTablesResponse>(res)
}

/**
 * POST /input-sources/select — pick a DB table (or query): the server materializes + profiles it
 * and returns the SAME InspectProfile shape as /upload, plus an `input_source` block for the run.
 * The frontend feeds it through the same applyUpload plumbing as an uploaded file. Consumed by:
 * Upload.
 */
export async function selectInputTable(args: {
  table?: string
  query?: string
  target?: string
}): Promise<InspectProfile> {
  const res = await request(`${API_BASE}/input-sources/select`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(args),
  })
  return handleJson<InspectProfile>(res)
}

/** POST /run — execute the pipeline; returns (and validates) the locked envelope. */
export async function run(cfg: RunConfig): Promise<RunResponse> {
  const res = await request(`${API_BASE}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  })
  const body = await handleJson<unknown>(res)
  // Validate the shape against the contract before handing it to the UI.
  return parseRunResponse(body)
}

/* ───────────── Databricks orchestration (schema 1.11, §6.6 Step 6) ────────── */
// Used ONLY when GET /health reports execution_backend === "databricks". In that mode POST /run
// submits a Databricks Job and returns a {job_id} to poll (submitRun); the local backend keeps
// using run() above. The user's PAT is passed per-request as the X-Databricks-Token header and is
// never stored client-side beyond the in-memory store.

/** POST /run (databricks backend) — submit a Job; returns {job_id, run_id, status}. */
export async function submitRun(cfg: RunConfig, pat: string): Promise<RunSubmission> {
  const res = await request(`${API_BASE}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Databricks-Token": pat },
    body: JSON.stringify(cfg),
  })
  return handleJson<RunSubmission>(res)
}

/** GET /run/{job_id}/status — poll a submitted Job's status. */
export async function getRunStatus(jobId: string): Promise<JobStatusResponse> {
  const res = await request(`${API_BASE}/run/${encodeURIComponent(jobId)}/status`)
  return handleJson<JobStatusResponse>(res)
}

/**
 * GET /run/{job_id}/results — fetch a COMPLETED Job's result envelope (validated through the same
 * parser as a local /run, so it drops straight into the result pages). A 409 (not complete yet)
 * surfaces as an ApiError — the store only calls this once status is COMPLETED.
 *
 * The user's PAT MUST be sent as `X-Databricks-Token`: the server re-resolves it (via SCIM) to the
 * same `{user_email}` namespace the Job wrote its envelope under, so the fetch path matches. Without
 * it the server falls back to `unknown_user` and the envelope is never found (a 404 that surfaces as
 * "results envelope is not available yet").
 */
export async function getRunResults(jobId: string, pat: string): Promise<RunResponse> {
  const res = await request(`${API_BASE}/run/${encodeURIComponent(jobId)}/results`, {
    headers: { "X-Databricks-Token": pat },
  })
  const body = await handleJson<unknown>(res)
  return parseRunResponse(body)
}

/** GET /databricks/catalogs — list Unity Catalog catalogs (needs the user's PAT). */
export async function listCatalogs(pat: string): Promise<CatalogsResponse> {
  const res = await request(`${API_BASE}/databricks/catalogs`, {
    headers: { "X-Databricks-Token": pat },
  })
  return handleJson<CatalogsResponse>(res)
}

/** GET /databricks/schemas?catalog= — list schemas in a catalog. */
export async function listSchemas(catalog: string, pat: string): Promise<SchemasResponse> {
  const res = await request(`${API_BASE}/databricks/schemas?catalog=${encodeURIComponent(catalog)}`, {
    headers: { "X-Databricks-Token": pat },
  })
  return handleJson<SchemasResponse>(res)
}

/** GET /databricks/tables?catalog=&schema= — list tables in a schema. */
export async function listTables(
  catalog: string,
  schema: string,
  pat: string,
): Promise<TablesResponse> {
  const url = `${API_BASE}/databricks/tables?catalog=${encodeURIComponent(catalog)}&schema=${encodeURIComponent(schema)}`
  const res = await request(url, { headers: { "X-Databricks-Token": pat } })
  return handleJson<TablesResponse>(res)
}

/**
 * GET /databricks/clusters — list the clusters a run can be submitted to (usable state, sorted by
 * name). Authenticated server-side with the SERVICE token (not the user's PAT), since the service
 * identity submits the Job and picks the cluster — so no X-Databricks-Token header is sent. The
 * chosen cluster_id is set on the RunConfig to override the server's DATABRICKS_JOB_CLUSTER_ID env
 * var. Consumed by: Upload (Databricks cluster picker).
 */
export async function listClusters(): Promise<ClustersResponse> {
  const res = await request(`${API_BASE}/databricks/clusters`)
  return handleJson<ClustersResponse>(res)
}

/**
 * GET /databricks/table-profile?catalog=&schema=&table= — fetch a Unity Catalog table's schema and
 * return it in the SAME InspectProfile shape as /upload (columns, dtypes, column groups, plus a
 * `delta` input_source + snapshot server_path). The frontend feeds it through the same applyUpload
 * plumbing as an uploaded file, so the column picker (target dropdown + feature selector) is
 * populated without any manual column entry. A 503 (not the databricks backend / unreachable
 * workspace / columnless table) or 401 (no PAT) surfaces as an ApiError. Consumed by: Upload.
 */
export async function getTableProfile(
  args: { catalog: string; schema: string; table: string },
  pat: string,
): Promise<InspectProfile> {
  const q = new URLSearchParams({
    catalog: args.catalog,
    schema: args.schema,
    table: args.table,
  })
  const res = await request(`${API_BASE}/databricks/table-profile?${q.toString()}`, {
    headers: { "X-Databricks-Token": pat },
  })
  return handleJson<InspectProfile>(res)
}

/** GET /runs — list past MLflow-logged runs (most-recent first). Consumed by: Runs.
 *
 * Databricks backend: pass the caller's PAT (`X-Databricks-Token`) so the server scopes the list to
 * their OWN runs (filtered by the `classifyos.user_email` tag — see `routes/runs.py`). Local backend:
 * omit it — every run is listed. The header is sent only when a PAT is provided. */
export async function listRuns(pat?: string): Promise<RunsListResponse> {
  const init = pat ? { headers: { "X-Databricks-Token": pat } } : undefined
  const res = await request(`${API_BASE}/runs`, init)
  return handleJson<RunsListResponse>(res)
}

/**
 * GET /runs/{run_id} — reload one past run. Returns the SAME locked /run envelope the run was
 * rendered with, validated through the same parser, so it drops straight into the result pages.
 *
 * Databricks backend: pass the PAT so the server authorizes the reload to the run's owner (a run
 * owned by another user is a 404). Local backend: omit it.
 */
export async function loadRun(runId: string, pat?: string): Promise<RunResponse> {
  const init = pat ? { headers: { "X-Databricks-Token": pat } } : undefined
  const res = await request(`${API_BASE}/runs/${encodeURIComponent(runId)}`, init)
  const body = await handleJson<unknown>(res)
  return parseRunResponse(body)
}

/** POST /explain — v1.0 structured stub (no model persistence yet). */
export async function explain(req: ExplainRequest): Promise<ExplainResponse> {
  const res = await request(`${API_BASE}/explain`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  })
  return handleJson<ExplainResponse>(res)
}

/** GET /outputs — list the artifacts the last run produced. */
export async function listOutputs() {
  const res = await request(`${API_BASE}/outputs`)
  return handleJson<Array<{ name: string; suffix: string; size_bytes: number }>>(res)
}

/**
 * Build the URL for one output artifact (a PNG or CSV) — used as an <img src> or a download link.
 * PNGs are fetched on demand here, never inlined into /run.
 *
 * When `runId` is given the URL is RUN-SCOPED (`/outputs/{runId}/{name}`): the server serves it from
 * that run's store (MLflow, in the Databricks backend), which is where a Databricks run's artifacts
 * actually live. Without `runId` it's the flat `/outputs/{name}` served from the FastAPI's local
 * OUTPUT_DIR — the path a LOCAL run uses, unchanged. Callers pick via {@link runScopedArtifactId}.
 */
export function outputUrl(name: string, runId?: string | null): string {
  const base = `${API_BASE}/outputs`
  return runId
    ? `${base}/${encodeURIComponent(runId)}/${encodeURIComponent(name)}`
    : `${base}/${encodeURIComponent(name)}`
}

/**
 * The run id to scope artifact URLs to, or `undefined` for the flat `/outputs/{name}`.
 *
 * A DATABRICKS-backed run logs its artifact files to the workspace's managed MLflow (its
 * `mlflow.tracking_uri` is `"databricks…"`), NOT the FastAPI's local OUTPUT_DIR — so its PNGs/CSVs
 * must be fetched run-scoped via `/outputs/{run_id}/{name}` (the server streams them from MLflow).
 * A LOCAL run (or any run with no MLflow pointer) keeps the flat `/outputs/{name}`, so local
 * behaviour is byte-identical. This works for both a fresh run and one reloaded from the Runs tab,
 * since both carry the same `result.mlflow` block. Consumed by: the result pages that render
 * PngArtifact / artifact links (Overview, Curves, Feature Impact, Interactions, Predictions).
 */
export function runScopedArtifactId(mlflow?: MlflowInfo | null): string | undefined {
  return mlflow?.run_id && mlflow.tracking_uri?.startsWith("databricks")
    ? mlflow.run_id
    : undefined
}
