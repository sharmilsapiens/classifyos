/* Import from database — the table picker (Interim 2b UI).

   Fetches the input DB's tables from GET /input-sources/tables and shows them as a selectable
   list (the primary ask). Selecting one calls back to the parent, which profiles it via
   POST /input-sources/select and drops the user into the normal Configure flow — with the run's
   input_source set so the run reads from Postgres. A small SQL-query box is offered as a secondary
   path. Honest states throughout: loading, DB unreachable, and an empty table list. */

import { useCallback, useEffect, useState } from "react"
import { Database, Play, RefreshCw, Table2 } from "lucide-react"

import { ApiError, listInputTables } from "@/api/client"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { EmptyState, ErrorState, Spinner } from "@/components/common/States"

interface Props {
  /** The table currently selected/profiled (highlights its row). */
  selected: string | null
  /** Called when the user picks a table to profile. */
  onSelectTable: (table: string) => void
  /** Called when the user runs a raw SQL query (secondary path). */
  onRunQuery: (query: string) => void
  /** The parent is profiling a selection (disables the controls while it works). */
  busy?: boolean
}

type Load =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; tables: string[] }

export default function DatabaseSourcePanel({ selected, onSelectTable, onRunQuery, busy }: Props) {
  const [load, setLoad] = useState<Load>({ state: "loading" })
  const [query, setQuery] = useState("")

  const fetchTables = useCallback(async () => {
    setLoad({ state: "loading" })
    try {
      const res = await listInputTables()
      setLoad({ state: "ready", tables: res.tables })
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "Could not reach the database. Check that it's configured and running."
      setLoad({ state: "error", message })
    }
  }, [])

  useEffect(() => {
    void fetchTables()
  }, [fetchTables])

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Database className="h-4 w-4 text-primary" aria-hidden />
          Tables in the database
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {load.state === "loading" && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Spinner /> Loading tables…
          </div>
        )}

        {load.state === "error" && (
          <ErrorState
            title="Database unreachable"
            message={load.message}
            onRetry={() => void fetchTables()}
          />
        )}

        {load.state === "ready" && load.tables.length === 0 && (
          <EmptyState
            title="No tables found"
            description="The input database is reachable but has no tables. Seed it (see the RUNBOOK) or use “Upload a file” instead."
            action={
              <Button variant="outline" size="sm" onClick={() => void fetchTables()}>
                <RefreshCw className="h-4 w-4" />
                Refresh
              </Button>
            }
          />
        )}

        {load.state === "ready" && load.tables.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Pick a table to run on</Label>
              <Button variant="ghost" size="sm" onClick={() => void fetchTables()} disabled={busy}>
                <RefreshCw className="h-4 w-4" />
                Refresh
              </Button>
            </div>
            <ul className="max-h-72 divide-y overflow-y-auto rounded-md border">
              {load.tables.map((t) => {
                const active = t === selected
                return (
                  <li key={t}>
                    <button
                      type="button"
                      aria-pressed={active}
                      disabled={busy}
                      onClick={() => onSelectTable(t)}
                      className={cn(
                        "flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors",
                        "hover:bg-accent focus-visible:bg-accent focus-visible:outline-none",
                        "disabled:cursor-not-allowed disabled:opacity-60",
                        active && "bg-accent font-semibold text-primary",
                      )}
                    >
                      <Table2 className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                      <span className="font-mono">{t}</span>
                    </button>
                  </li>
                )
              })}
            </ul>
            {busy && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Spinner /> Profiling {selected}…
              </div>
            )}
          </div>
        )}

        {/* Secondary path: a raw SQL query. Optional — the picker above is the primary ask. */}
        {load.state === "ready" && (
          <div className="space-y-1.5 border-t pt-4">
            <Label htmlFor="db-query">Or run a SQL query (advanced)</Label>
            <div className="flex gap-2">
              <Input
                id="db-query"
                value={query}
                placeholder="SELECT * FROM my_table WHERE …"
                onChange={(e) => setQuery(e.target.value)}
                disabled={busy}
                className="font-mono text-xs"
              />
              <Button
                variant="outline"
                size="sm"
                disabled={busy || !query.trim()}
                onClick={() => onRunQuery(query.trim())}
              >
                <Play className="h-4 w-4" />
                Profile
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Add an <span className="font-mono">ORDER BY</span> for a reproducible snapshot (a SQL
              table is unordered).
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
