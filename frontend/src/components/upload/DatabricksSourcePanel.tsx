/* Databricks (Unity Catalog) source — a catalog → schema → table browser (§6.6 Step 6, Part C).

   Shown only when the server runs the DATABRICKS execution backend. The user enters their PAT
   (kept in memory only, sent per-request as X-Databricks-Token — never stored) and "Connect" to
   browse catalogs; picking a catalog lists its schemas, picking a schema lists its tables. Picking
   a table calls back to the parent, which fetches that table's Unity Catalog schema
   (GET /databricks/table-profile) and drives the shared column picker from it.

   Note: the Unity Catalog LIST APIs return names only (no columns); the separate table-profile
   endpoint supplies the columns + types, so the target + feature pickers are populated from the
   schema and the user never types a column name by hand. */

import { useCallback, useEffect, useState } from "react"
import { Cpu, Database, Plug, RefreshCw, Table2 } from "lucide-react"

import { ApiError, listCatalogs, listClusters, listSchemas, listTables } from "@/api/client"
import type { ClusterInfo } from "@/api/types"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { EmptyState, ErrorState, Spinner } from "@/components/common/States"

interface Props {
  /** The user's Databricks PAT (from the store; in-memory only). */
  pat: string
  onPatChange: (pat: string) => void
  /** Called when the user picks a table to run on. */
  onSelectTable: (sel: { catalog: string; schema: string; table: string }) => void
  /** The currently selected table name (highlights its row). */
  selectedTable: string | null
  /** The currently selected cluster id ("" = server default), reflected in the cluster dropdown. */
  clusterId: string
  /** Called when the user picks a cluster ("" clears the choice → server env-var default). */
  onClusterChange: (clusterId: string) => void
  /** The parent is submitting a run (disables the controls). */
  busy?: boolean
}

type Load<T> =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; items: T }

function errMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback
}

export default function DatabricksSourcePanel({
  pat,
  onPatChange,
  onSelectTable,
  selectedTable,
  clusterId,
  onClusterChange,
  busy,
}: Props) {
  const [catalogs, setCatalogs] = useState<Load<string[]>>({ state: "idle" })
  const [catalog, setCatalog] = useState("")
  const [schemas, setSchemas] = useState<Load<string[]>>({ state: "idle" })
  const [schema, setSchema] = useState("")
  const [tables, setTables] = useState<Load<string[]>>({ state: "idle" })
  const [clusters, setClusters] = useState<Load<ClusterInfo[]>>({ state: "idle" })

  const connect = useCallback(async () => {
    if (!pat.trim()) {
      setCatalogs({ state: "error", message: "Enter your Databricks personal access token first." })
      return
    }
    setCatalogs({ state: "loading" })
    setCatalog("")
    setSchemas({ state: "idle" })
    setSchema("")
    setTables({ state: "idle" })
    // Fetch the cluster list in parallel with the catalog browse — the two are independent, and a
    // cluster-list failure must not block picking a table (the server env-var default still works).
    setClusters({ state: "loading" })
    listClusters(pat.trim())
      .then((res) => setClusters({ state: "ready", items: res.clusters }))
      .catch((err) =>
        setClusters({ state: "error", message: errMessage(err, "Could not list clusters.") }),
      )
    try {
      const res = await listCatalogs(pat.trim())
      setCatalogs({ state: "ready", items: res.catalogs })
    } catch (err) {
      setCatalogs({ state: "error", message: errMessage(err, "Could not reach Databricks.") })
    }
  }, [pat])

  // Load schemas when a catalog is chosen; tables when a schema is chosen (cascading).
  useEffect(() => {
    if (!catalog) return
    let cancelled = false
    setSchemas({ state: "loading" })
    setSchema("")
    setTables({ state: "idle" })
    listSchemas(catalog, pat.trim())
      .then((res) => !cancelled && setSchemas({ state: "ready", items: res.schemas }))
      .catch((err) => !cancelled && setSchemas({ state: "error", message: errMessage(err, "Could not list schemas.") }))
    return () => {
      cancelled = true
    }
  }, [catalog, pat])

  useEffect(() => {
    if (!catalog || !schema) return
    let cancelled = false
    setTables({ state: "loading" })
    listTables(catalog, schema, pat.trim())
      .then((res) => !cancelled && setTables({ state: "ready", items: res.tables }))
      .catch((err) => !cancelled && setTables({ state: "error", message: errMessage(err, "Could not list tables.") }))
    return () => {
      cancelled = true
    }
  }, [catalog, schema, pat])

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Database className="h-4 w-4 text-primary" aria-hidden />
          Unity Catalog
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* PAT + connect */}
        <div className="space-y-1.5">
          <Label htmlFor="dbx-pat">Databricks personal access token</Label>
          <div className="flex gap-2">
            <Input
              id="dbx-pat"
              type="password"
              value={pat}
              placeholder="dapi…"
              onChange={(e) => onPatChange(e.target.value)}
              disabled={busy}
              className="font-mono text-xs"
            />
            <Button variant="outline" size="sm" onClick={() => void connect()} disabled={busy || !pat.trim()}>
              <Plug className="h-4 w-4" />
              Connect
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Used only for this session to browse Unity Catalog and to run as you — never stored.
          </p>
        </div>

        {/* Cluster picker — which compute the training Job runs on. Appears once Connect fetches the
            cluster list; "server default" leaves the choice to the DATABRICKS_JOB_CLUSTER_ID env var. */}
        {clusters.state !== "idle" && (
          <div className="space-y-1.5">
            <Label htmlFor="dbx-cluster" className="flex items-center gap-2">
              <Cpu className="h-4 w-4 text-primary" aria-hidden />
              Cluster
            </Label>
            {clusters.state === "loading" && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Spinner /> Loading clusters…
              </div>
            )}
            {clusters.state === "error" && <ErrorState message={clusters.message} />}
            {clusters.state === "ready" && (
              <>
                <Select
                  id="dbx-cluster"
                  value={clusterId}
                  onChange={(e) => onClusterChange(e.target.value)}
                  disabled={busy}
                >
                  <option value="">— server default —</option>
                  {clusters.items.map((c) => (
                    <option key={c.cluster_id} value={c.cluster_id}>
                      {c.cluster_name} ({c.state.toLowerCase()})
                    </option>
                  ))}
                </Select>
                <p className="text-xs text-muted-foreground">
                  Which cluster the training job runs on. Leave as “server default” to use the
                  cluster configured on the server.
                </p>
              </>
            )}
          </div>
        )}

        {catalogs.state === "loading" && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Spinner /> Loading catalogs…
          </div>
        )}
        {catalogs.state === "error" && (
          <ErrorState title="Databricks unreachable" message={catalogs.message} onRetry={() => void connect()} />
        )}

        {catalogs.state === "ready" && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="dbx-catalog">Catalog</Label>
              <Select
                id="dbx-catalog"
                value={catalog}
                onChange={(e) => setCatalog(e.target.value)}
                disabled={busy || catalogs.items.length === 0}
              >
                <option value="">— choose —</option>
                {catalogs.items.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="dbx-schema">Schema</Label>
              <Select
                id="dbx-schema"
                value={schema}
                onChange={(e) => setSchema(e.target.value)}
                disabled={busy || schemas.state !== "ready"}
              >
                <option value="">— choose —</option>
                {schemas.state === "ready" &&
                  schemas.items.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
              </Select>
            </div>
          </div>
        )}

        {schemas.state === "loading" && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Spinner /> Loading schemas…
          </div>
        )}
        {schemas.state === "error" && <ErrorState message={schemas.message} />}

        {tables.state === "loading" && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Spinner /> Loading tables…
          </div>
        )}
        {tables.state === "error" && <ErrorState message={tables.message} />}
        {tables.state === "ready" && tables.items.length === 0 && (
          <EmptyState title="No tables" description={`No tables in ${catalog}.${schema}.`} />
        )}
        {tables.state === "ready" && tables.items.length > 0 && (
          <div className="space-y-2">
            <Label>Pick a table to run on</Label>
            <ul className="max-h-60 divide-y overflow-y-auto rounded-md border">
              {tables.items.map((t) => {
                const active = t === selectedTable
                return (
                  <li key={t}>
                    <button
                      type="button"
                      aria-pressed={active}
                      disabled={busy}
                      onClick={() => onSelectTable({ catalog, schema, table: t })}
                      className={cn(
                        "flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors",
                        "hover:bg-accent focus-visible:bg-accent focus-visible:outline-none",
                        "disabled:cursor-not-allowed disabled:opacity-60",
                        active && "bg-accent font-semibold text-primary",
                      )}
                    >
                      <Table2 className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                      <span className="font-mono">{catalog}.{schema}.{t}</span>
                    </button>
                  </li>
                )
              })}
            </ul>
            <button
              type="button"
              className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:underline"
              onClick={() => void connect()}
              disabled={busy}
            >
              <RefreshCw className="h-3 w-3" />
              Reconnect
            </button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
