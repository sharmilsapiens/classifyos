/* ════════════════════════════════════════════════════════════════════════
   Global app state — a small React Context store.

   "Context" is React's built-in way to share state across many components
   without passing props through every level. We create one store that holds
   everything the pages share, plus the actions that change it, and wrap the app
   in <AppProvider>. Any component then calls `useApp()` to read state or act.

   What lives here (the state shape):
   ─────────────────────────────────────────────────────────────────────────
   apiStatus / apiMessage  health-banner state (online | offline | unknown)
   executionBackend        "local" | "databricks" (from /health) — drives /run flow
   inspect / serverPath    the uploaded file's profile + its /run key (input_file)
   form                    the current RunConfig form state (Configuration page)
   running / result        the in-flight flag + the last /run envelope
   jobId / jobStatus       (databricks backend) the submitted Job's handle + polled status
   databricksPat           (databricks backend) the user's PAT — in memory only, never stored
   runError / runFieldErrors  the last run's readable error + any 422 field msgs
   ════════════════════════════════════════════════════════════════════════ */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"
import type { ReactNode } from "react"

import * as api from "@/api/client"
import { ApiError } from "@/api/client"
import type { InspectProfile, JobStatus, RunResponse } from "@/api/types"
import {
  buildPayload,
  DEFAULT_FORM_STATE,
  validateRequired,
  type ConfigFormState,
} from "@/lib/buildPayload"

type ApiStatus = "unknown" | "online" | "offline"
type ExecutionBackend = "local" | "databricks"

/** How often the frontend polls a Databricks Job's status (ms). */
export const POLL_INTERVAL_MS = 5000

interface AppState {
  apiStatus: ApiStatus
  apiMessage: string
  executionBackend: ExecutionBackend
  inspect: InspectProfile | null
  serverPath: string | null
  form: ConfigFormState
  running: boolean
  result: RunResponse | null
  jobId: string | null
  jobStatus: JobStatus | null
  databricksPat: string
  runError: string | null
  runFieldErrors: string[]
}

interface AppActions {
  /** Ping /health and update the banner + the execution backend. Called on load and by retry. */
  checkAPI: () => Promise<void>
  /** Apply an /upload result: store the profile and seed the config form sensibly. */
  applyUpload: (profile: InspectProfile) => void
  /** Patch one or more config form fields. */
  updateForm: (patch: Partial<ConfigFormState>) => void
  /** Set the user's Databricks PAT (in-memory only; used for submit + UC browsing). */
  setDatabricksPat: (pat: string) => void
  /** Client-side required-field check (mirrors the server's, for a friendlier first pass). */
  formErrors: () => string[]
  /** Build the payload from the current form and run it (local: sync; databricks: submit+poll). */
  runPipeline: () => Promise<RunResponse | null>
  /** Drop a reloaded past run (from GET /runs/{id}) into the store so the result pages show it. */
  applyReloadedRun: (envelope: RunResponse) => void
}

const INITIAL: AppState = {
  apiStatus: "unknown",
  apiMessage: "Checking API…",
  executionBackend: "local",
  inspect: null,
  serverPath: null,
  form: DEFAULT_FORM_STATE,
  running: false,
  result: null,
  jobId: null,
  jobStatus: null,
  databricksPat: "",
  runError: null,
  runFieldErrors: [],
}

const AppContext = createContext<(AppState & AppActions) | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AppState>(INITIAL)

  // runPipeline runs asynchronously, so it must read the LATEST form, not the
  // value captured when it was created. We mirror state into a ref for that.
  const stateRef = useRef(state)
  useEffect(() => {
    stateRef.current = state
  }, [state])

  // The Databricks status-polling timer (databricks backend only). Held in a ref so we can
  // cancel it on a new run / on unmount without re-rendering.
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])
  useEffect(() => stopPolling, [stopPolling]) // clear any timer when the provider unmounts

  const checkAPI = useCallback(async () => {
    try {
      const h = await api.health()
      setState((s) => ({
        ...s,
        apiStatus: "online",
        apiMessage: `API connected · ${h.service}`,
        executionBackend: h.execution_backend === "databricks" ? "databricks" : "local",
      }))
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "API offline — start uvicorn on :8000."
      setState((s) => ({ ...s, apiStatus: "offline", apiMessage: message }))
    }
  }, [])

  // Check the API once when the app mounts.
  useEffect(() => {
    void checkAPI()
  }, [checkAPI])

  const applyUpload = useCallback((profile: InspectProfile) => {
    setState((s) => ({
      ...s,
      inspect: profile,
      serverPath: profile.server_path,
      form: {
        ...s.form,
        input_file: profile.server_path,
        // A DB selection (POST /input-sources/select) carries an `input_source` block so the run
        // reads from Postgres (Interim 2b); a plain file upload has none → null (file source). The
        // same plumbing serves both, so the file-upload path is unchanged.
        input_source: profile.input_source ?? null,
        // Seed problem type from the inspection if it offered one.
        problem_type: profile.suggested_problem_type ?? s.form.problem_type,
        // Reset target/features — the user picks these on Upload/Configure.
        target: "",
        feature_cols: [],
      },
    }))
  }, [])

  const updateForm = useCallback((patch: Partial<ConfigFormState>) => {
    setState((s) => ({ ...s, form: { ...s.form, ...patch } }))
  }, [])

  const setDatabricksPat = useCallback((pat: string) => {
    setState((s) => ({ ...s, databricksPat: pat }))
  }, [])

  const formErrors = useCallback(() => validateRequired(stateRef.current.form), [])

  // Poll one Databricks status tick; on a terminal state, stop the timer and either fetch the
  // results (COMPLETED) or surface the failure (FAILED). A transient status error is swallowed so
  // the polling loop keeps trying (the next tick may succeed) rather than killing the run view.
  const pollOnce = useCallback(
    async (jobId: string) => {
      let status: JobStatus
      let message: string | null
      try {
        const res = await api.getRunStatus(jobId)
        status = res.status
        message = res.message
      } catch {
        return // transient — keep the timer running for the next tick
      }
      setState((s) => (s.jobId === jobId ? { ...s, jobStatus: status } : s))
      if (status === "COMPLETED") {
        stopPolling()
        try {
          // Forward the user's PAT so the server resolves the SAME {user_email} namespace the Job
          // wrote under (else it falls back to unknown_user → 404 "not available yet").
          const envelope = await api.getRunResults(jobId, stateRef.current.databricksPat.trim())
          setState((s) => ({
            ...s,
            running: false,
            result: envelope,
            runError: envelope.status === "error" ? envelope.error : null,
          }))
        } catch (err) {
          setState((s) => ({
            ...s,
            running: false,
            runError:
              err instanceof ApiError ? err.message : "Could not fetch the run results.",
          }))
        }
      } else if (status === "FAILED") {
        stopPolling()
        setState((s) => ({
          ...s,
          running: false,
          runError: message || "The Databricks run failed.",
        }))
      }
    },
    [stopPolling],
  )

  const runPipeline = useCallback(async (): Promise<RunResponse | null> => {
    const s = stateRef.current
    const form = s.form
    // Friendly client-side guard first (the server still validates).
    const missing = validateRequired(form)
    if (missing.length) {
      setState((st) => ({ ...st, runError: missing.join(" "), runFieldErrors: missing }))
      return null
    }

    stopPolling() // cancel any prior poll before starting a fresh run
    setState((st) => ({
      ...st,
      running: true,
      runError: null,
      runFieldErrors: [],
      result: null,
      jobId: null,
      jobStatus: null,
    }))

    // ── Databricks backend: submit a Job, then poll for completion ──────────────
    if (s.executionBackend === "databricks") {
      const pat = s.databricksPat.trim()
      if (!pat) {
        setState((st) => ({
          ...st,
          running: false,
          runError: "A Databricks personal access token is required to submit a run.",
        }))
        return null
      }
      let jobId: string
      try {
        const submission = await api.submitRun(buildPayload(form), pat)
        jobId = submission.job_id
        setState((st) => ({ ...st, jobId, jobStatus: submission.status }))
      } catch (err) {
        setState((st) => ({
          ...st,
          running: false,
          runError:
            err instanceof ApiError ? err.message : "Could not submit the Databricks run.",
          runFieldErrors: err instanceof ApiError ? err.fieldErrors : [],
        }))
        return null
      }
      // Poll immediately (so the status updates without waiting a full interval), then every 5s.
      void pollOnce(jobId)
      pollRef.current = setInterval(() => void pollOnce(jobId), POLL_INTERVAL_MS)
      return null
    }

    // ── Local backend: run synchronously and return the full envelope (unchanged) ──
    try {
      const envelope = await api.run(buildPayload(form))
      setState((st) => ({
        ...st,
        running: false,
        result: envelope,
        // A status:"error" envelope (HTTP 200 but logical error) carries .error.
        runError: envelope.status === "error" ? envelope.error : null,
      }))
      return envelope
    } catch (err) {
      const isApi = err instanceof ApiError
      setState((st) => ({
        ...st,
        running: false,
        runError: isApi ? err.message : "Unexpected error running the pipeline.",
        runFieldErrors: isApi ? err.fieldErrors : [],
      }))
      return null
    }
  }, [pollOnce, stopPolling])

  const applyReloadedRun = useCallback(
    (envelope: RunResponse) => {
      // A run reloaded from MLflow (persistence read-path) replaces the current result, exactly as
      // a fresh /run would — every result page reads `result` from here, so they all repopulate.
      stopPolling()
      setState((s) => ({
        ...s,
        running: false,
        jobId: null,
        jobStatus: null,
        result: envelope,
        runError: envelope.status === "error" ? envelope.error : null,
        runFieldErrors: [],
      }))
    },
    [stopPolling],
  )

  // useMemo so the context value is stable between renders (avoids needless re-renders).
  const value = useMemo(
    () => ({
      ...state,
      checkAPI,
      applyUpload,
      updateForm,
      setDatabricksPat,
      formErrors,
      runPipeline,
      applyReloadedRun,
    }),
    [
      state,
      checkAPI,
      applyUpload,
      updateForm,
      setDatabricksPat,
      formErrors,
      runPipeline,
      applyReloadedRun,
    ],
  )

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

/** Read the global store. Throws if used outside <AppProvider> (a wiring mistake). */
export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error("useApp must be used inside <AppProvider>")
  return ctx
}
