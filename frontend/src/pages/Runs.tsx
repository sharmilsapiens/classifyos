/* Runs — past pipeline runs, read back from MLflow (schema 1.10, Interim 2a).

   This is the payoff of moving MLflow's backend store to Postgres: runs now SURVIVE a browser
   refresh and a server restart. The page lists past runs from GET /api/v1/runs and can reload
   one (GET /api/v1/runs/{run_id}) straight into the existing result pages — the reloaded run
   replaces the current `result` in the store, then we navigate to Overview.

   A run is "reloadable" only when it carries the persisted /run envelope snapshot (i.e. it was
   produced via POST /api/v1/run). Runs logged some other way (e.g. the engine CLI) still list,
   but their Load button is disabled with a hint. If MLflow logging was never used — or the
   tracking store is down (e.g. Postgres stopped) — the list endpoint returns an error and we
   show a readable state, never a blank screen. */

import { useCallback, useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Database, RefreshCw } from "lucide-react"

import * as api from "@/api/client"
import { ApiError } from "@/api/client"
import type { RunSummary } from "@/api/types"
import { useApp } from "@/store/AppStore"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Spinner,
} from "@/components/common/States"
import { fmtMetric } from "@/lib/format"

type Phase = "loading" | "ready" | "error"

/** MLflow epoch/ISO → a readable local timestamp; em-dash when missing/invalid. */
function fmtWhen(iso: string | null): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "—"
  return d.toLocaleString()
}

/** Map an MLflow run status to a badge variant. */
function statusVariant(status: string): "success" | "destructive" | "secondary" {
  if (status === "FINISHED") return "success"
  if (status === "FAILED" || status === "KILLED") return "destructive"
  return "secondary"
}

export default function Runs() {
  const { applyReloadedRun } = useApp()
  const navigate = useNavigate()

  const [phase, setPhase] = useState<Phase>("loading")
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [trackingUri, setTrackingUri] = useState<string>("")
  const [listError, setListError] = useState<string>("")
  const [loadError, setLoadError] = useState<string>("")
  const [loadingId, setLoadingId] = useState<string | null>(null)

  const fetchRuns = useCallback(async () => {
    setPhase("loading")
    setLoadError("")
    try {
      const res = await api.listRuns()
      setRuns(res.runs)
      setTrackingUri(res.tracking_uri)
      setPhase("ready")
    } catch (err) {
      setListError(err instanceof ApiError ? err.message : "Could not load past runs.")
      setPhase("error")
    }
  }, [])

  useEffect(() => {
    void fetchRuns()
  }, [fetchRuns])

  const handleLoad = useCallback(
    async (runId: string) => {
      setLoadingId(runId)
      setLoadError("")
      try {
        const envelope = await api.loadRun(runId)
        applyReloadedRun(envelope)
        navigate("/") // Overview — every result page now reads the reloaded run.
      } catch (err) {
        setLoadError(
          err instanceof ApiError ? err.message : "Could not reload that run.",
        )
      } finally {
        setLoadingId(null)
      }
    },
    [applyReloadedRun, navigate],
  )

  const refreshBtn = (
    <Button variant="outline" size="sm" onClick={() => void fetchRuns()} disabled={phase === "loading"}>
      <RefreshCw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
      Refresh
    </Button>
  )

  return (
    <div>
      <PageHeader
        title="Runs"
        subtitle="Past pipeline runs recorded in MLflow — reload one to repopulate the result pages."
        actions={refreshBtn}
      />

      {trackingUri && (
        <p className="mb-4 flex items-center gap-1.5 text-xs text-muted-foreground">
          <Database className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="truncate">
            Tracking store: <span className="font-mono">{trackingUri}</span>
          </span>
        </p>
      )}

      {loadError && (
        <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {loadError}
        </div>
      )}

      {phase === "loading" && <LoadingState message="Loading past runs…" />}

      {phase === "error" && (
        <ErrorState
          title="Couldn’t load runs"
          message={listError}
          details={[
            "This needs MLflow logging: enable it under the MLflow card in Configuration so runs are recorded.",
            "If a Postgres backend store is configured, check the server is running.",
          ]}
          onRetry={() => void fetchRuns()}
        />
      )}

      {phase === "ready" && runs.length === 0 && (
        <EmptyState
          title="No past runs yet"
          description="Runs appear here once MLflow logging is enabled (the MLflow card in Configuration). Each logged run then survives a refresh and a server restart."
        />
      )}

      {phase === "ready" && runs.length > 0 && (
        <Card>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr className="border-b">
                    <th className="px-4 py-3 text-left font-medium">Run</th>
                    <th className="px-4 py-3 text-left font-medium">When</th>
                    <th className="px-4 py-3 text-left font-medium">Target</th>
                    <th className="px-4 py-3 text-left font-medium">Type</th>
                    <th className="px-4 py-3 text-left font-medium">Models</th>
                    <th className="px-4 py-3 text-right font-medium">Best F1</th>
                    <th className="px-4 py-3 text-left font-medium">Status</th>
                    <th className="px-4 py-3 text-right font-medium">Reload</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.run_id} className="border-b last:border-0 hover:bg-accent/40">
                      <td className="px-4 py-3">
                        <div className="font-medium">{r.run_name || "(unnamed run)"}</div>
                        <div className="font-mono text-[11px] text-muted-foreground">
                          {r.run_id.slice(0, 12)}… · {r.input_file ?? "—"}
                        </div>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-muted-foreground">
                        {fmtWhen(r.start_time)}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">{r.target ?? "—"}</td>
                      <td className="px-4 py-3">
                        {r.problem_type ? (
                          <Badge variant="outline">{r.problem_type}</Badge>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div>{r.models_logged}</div>
                        {r.best_model && (
                          <div className="text-[11px] text-muted-foreground">
                            best: {r.best_model}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right font-mono">{fmtMetric(r.best_value)}</td>
                      <td className="px-4 py-3">
                        <Badge variant={statusVariant(r.status)}>{r.status}</Badge>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Button
                          size="sm"
                          variant={r.reloadable ? "default" : "outline"}
                          disabled={!r.reloadable || loadingId !== null}
                          title={
                            r.reloadable
                              ? "Reload this run into the result pages"
                              : "No reloadable snapshot — this run was not produced via the API /run path"
                          }
                          onClick={() => void handleLoad(r.run_id)}
                        >
                          {loadingId === r.run_id ? (
                            <>
                              <Spinner className="mr-1.5" />
                              Loading…
                            </>
                          ) : (
                            "Load"
                          )}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
