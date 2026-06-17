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
  ExplainRequest,
  ExplainResponse,
  HealthResponse,
  InspectProfile,
  RunConfig,
  RunResponse,
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
 * Build the URL for one output artifact (a PNG or CSV) — used as an <img src>
 * or a download link. PNGs are fetched on demand here, never inlined into /run.
 */
export function outputUrl(name: string): string {
  return `${API_BASE}/outputs/${encodeURIComponent(name)}`
}
