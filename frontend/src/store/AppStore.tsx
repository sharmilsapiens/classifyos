/* ════════════════════════════════════════════════════════════════════════
   Global app state — a small React Context store.

   "Context" is React's built-in way to share state across many components
   without passing props through every level. We create one store that holds
   everything the pages share, plus the actions that change it, and wrap the app
   in <AppProvider>. Any component then calls `useApp()` to read state or act.

   What lives here (the state shape):
   ─────────────────────────────────────────────────────────────────────────
   apiStatus / apiMessage  health-banner state (online | offline | unknown)
   inspect / serverPath    the uploaded file's profile + its /run key (input_file)
   form                    the current RunConfig form state (Configuration page)
   running / result        the in-flight flag + the last /run envelope
   runError / runFieldErrors  the last run's readable error + any 422 field msgs
   ════════════════════════════════════════════════════════════════════════ */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"
import type { ReactNode } from "react"

import * as api from "@/api/client"
import { ApiError } from "@/api/client"
import type { InspectProfile, RunResponse } from "@/api/types"
import {
  buildPayload,
  DEFAULT_FORM_STATE,
  validateRequired,
  type ConfigFormState,
} from "@/lib/buildPayload"

type ApiStatus = "unknown" | "online" | "offline"

interface AppState {
  apiStatus: ApiStatus
  apiMessage: string
  inspect: InspectProfile | null
  serverPath: string | null
  form: ConfigFormState
  running: boolean
  result: RunResponse | null
  runError: string | null
  runFieldErrors: string[]
}

interface AppActions {
  /** Ping /health and update the banner. Called on load and by a manual retry. */
  checkAPI: () => Promise<void>
  /** Apply an /upload result: store the profile and seed the config form sensibly. */
  applyUpload: (profile: InspectProfile) => void
  /** Patch one or more config form fields. */
  updateForm: (patch: Partial<ConfigFormState>) => void
  /** Client-side required-field check (mirrors the server's, for a friendlier first pass). */
  formErrors: () => string[]
  /** Build the payload from the current form and POST /run. Returns the envelope or null. */
  runPipeline: () => Promise<RunResponse | null>
  /** Drop a reloaded past run (from GET /runs/{id}) into the store so the result pages show it. */
  applyReloadedRun: (envelope: RunResponse) => void
}

const INITIAL: AppState = {
  apiStatus: "unknown",
  apiMessage: "Checking API…",
  inspect: null,
  serverPath: null,
  form: DEFAULT_FORM_STATE,
  running: false,
  result: null,
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

  const checkAPI = useCallback(async () => {
    try {
      const h = await api.health()
      setState((s) => ({ ...s, apiStatus: "online", apiMessage: `API connected · ${h.service}` }))
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

  const formErrors = useCallback(() => validateRequired(stateRef.current.form), [])

  const runPipeline = useCallback(async (): Promise<RunResponse | null> => {
    const form = stateRef.current.form
    // Friendly client-side guard first (the server still validates).
    const missing = validateRequired(form)
    if (missing.length) {
      setState((s) => ({ ...s, runError: missing.join(" "), runFieldErrors: missing }))
      return null
    }

    setState((s) => ({ ...s, running: true, runError: null, runFieldErrors: [], result: null }))
    try {
      const envelope = await api.run(buildPayload(form))
      setState((s) => ({
        ...s,
        running: false,
        result: envelope,
        // A status:"error" envelope (HTTP 200 but logical error) carries .error.
        runError: envelope.status === "error" ? envelope.error : null,
      }))
      return envelope
    } catch (err) {
      const isApi = err instanceof ApiError
      setState((s) => ({
        ...s,
        running: false,
        runError: isApi ? err.message : "Unexpected error running the pipeline.",
        runFieldErrors: isApi ? err.fieldErrors : [],
      }))
      return null
    }
  }, [])

  const applyReloadedRun = useCallback((envelope: RunResponse) => {
    // A run reloaded from MLflow (persistence read-path) replaces the current result, exactly as
    // a fresh /run would — every result page reads `result` from here, so they all repopulate.
    setState((s) => ({
      ...s,
      running: false,
      result: envelope,
      runError: envelope.status === "error" ? envelope.error : null,
      runFieldErrors: [],
    }))
  }, [])

  // useMemo so the context value is stable between renders (avoids needless re-renders).
  const value = useMemo(
    () => ({ ...state, checkAPI, applyUpload, updateForm, formErrors, runPipeline, applyReloadedRun }),
    [state, checkAPI, applyUpload, updateForm, formErrors, runPipeline, applyReloadedRun],
  )

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

/** Read the global store. Throws if used outside <AppProvider> (a wiring mistake). */
export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error("useApp must be used inside <AppProvider>")
  return ctx
}
