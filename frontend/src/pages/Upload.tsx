/* Upload Data — step 1 of the Upload → Configure → Run flow.

   Three data sources, ONE shared profile+target flow:
   • "Upload a file" — drag-drop (or pick) a CSV/Excel/Parquet file → POST /upload.
   • "Import from database" — pick a table from the input DB (Interim 2b) → POST
     /input-sources/select, which materializes + profiles it and returns the SAME profile shape.
   • "Databricks (Unity Catalog)" — browse catalog → schema → table, then GET
     /databricks/table-profile, which fetches the table's UC schema and returns the SAME profile
     shape (only offered when the server runs the databricks backend).

   Every source returns an inspection profile (columns, dtypes, column groups; the file/DB paths
   also carry missing counts + a suggested problem type + — once a target is chosen — the class
   distribution). We store the profile + server_path in the global store via the same `applyUpload`
   plumbing; a DB/Databricks selection additionally carries an `input_source` block so the run reads
   from Postgres / the Delta table. The Configuration page reads the profile to populate its target
   and feature pickers — identically for all three sources, so the user never types a column name. */

import { useRef, useState } from "react"
import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { Cloud, Database, FileUp, ScanSearch, UploadCloud } from "lucide-react"

import { ApiError, getTableProfile, selectInputTable, upload } from "@/api/client"
import { useApp } from "@/store/AppStore"
import { fmtInt } from "@/lib/format"
import { cn } from "@/lib/utils"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { buttonVariants } from "@/components/ui/button"
import { ErrorState, PageHeader, Spinner } from "@/components/common/States"
import DatabaseSourcePanel from "@/components/upload/DatabaseSourcePanel"
import DatabricksSourcePanel from "@/components/upload/DatabricksSourcePanel"

type SourceMode = "file" | "database" | "databricks"
/** A selected Unity Catalog table (Databricks source). */
type UcSelection = { catalog: string; schema: string; table: string }
/** The last DB selection (table OR query) so a target change can re-profile the same source. */
type DbSelection = { table?: string; query?: string }

export default function UploadPage() {
  const {
    inspect,
    serverPath,
    form,
    applyUpload,
    updateForm,
    executionBackend,
    databricksPat,
    setDatabricksPat,
    running,
  } = useApp()
  const [mode, setMode] = useState<SourceMode>("file")
  const [file, setFile] = useState<File | null>(null)
  const [dbSelection, setDbSelection] = useState<DbSelection | null>(null)
  const [ucSelection, setUcSelection] = useState<UcSelection | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const onDatabricks = executionBackend === "databricks"

  // Upload a file (and re-inspect when a target is chosen, to fetch its class distribution).
  async function doUpload(f: File, target?: string) {
    setBusy(true)
    setError(null)
    try {
      const profile = await upload(f, target)
      applyUpload(profile)
      if (target) updateForm({ target })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed.")
    } finally {
      setBusy(false)
    }
  }

  // Profile a DB table/query (POST /input-sources/select) via the same applyUpload plumbing.
  async function doSelect(sel: DbSelection, target?: string) {
    setBusy(true)
    setError(null)
    try {
      const profile = await selectInputTable({ ...sel, target })
      applyUpload(profile)
      setDbSelection(sel)
      if (target) updateForm({ target })
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not load data from the database.",
      )
    } finally {
      setBusy(false)
    }
  }

  function onFiles(files: FileList | null) {
    const f = files?.[0]
    if (!f) return
    setFile(f)
    void doUpload(f)
  }

  // Databricks (Unity Catalog): picking a table fetches its schema from Unity Catalog and flows it
  // through the SAME applyUpload plumbing a CSV upload uses — the /table-profile endpoint returns
  // the InspectProfile shape plus a `delta` input_source + snapshot server_path. No manual column
  // entry: the shared column picker below (target dropdown) and the Configuration page's feature
  // selector are populated from the fetched schema, identically to a file upload.
  async function doSelectUc(sel: UcSelection) {
    const pat = databricksPat.trim()
    if (!pat) {
      setError("Enter your Databricks personal access token first.")
      return
    }
    setBusy(true)
    setError(null)
    setUcSelection(sel)
    try {
      const profile = await getTableProfile(sel, pat)
      applyUpload(profile)
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not load the table schema from Unity Catalog.",
      )
    } finally {
      setBusy(false)
    }
  }

  // A target change re-profiles the current source. File/DB re-fetch to get the class distribution;
  // a Databricks schema-only profile has no data to recompute one, so it just records the choice.
  function onTargetChange(target: string) {
    if (mode === "file") {
      if (file) void doUpload(file, target)
    } else if (mode === "database") {
      if (dbSelection) void doSelect(dbSelection, target)
    } else {
      updateForm({ target })
    }
  }

  function switchMode(next: SourceMode) {
    setMode(next)
    setError(null)
  }

  return (
    <div>
      <PageHeader
        title="Upload Data"
        subtitle="Bring in a file or import a table from the database to inspect it and start a run."
      />

      {/* Source switch: file (today's flow) vs database (Interim 2b). */}
      <div
        role="tablist"
        aria-label="Data source"
        className="mb-6 inline-flex rounded-lg border bg-card p-1"
      >
        <SourceTab
          active={mode === "file"}
          onClick={() => switchMode("file")}
          icon={<UploadCloud className="h-4 w-4" aria-hidden />}
          label="Upload a file"
        />
        <SourceTab
          active={mode === "database"}
          onClick={() => switchMode("database")}
          icon={<Database className="h-4 w-4" aria-hidden />}
          label="Import from database"
        />
        {/* Databricks (Unity Catalog) — only offered when the server runs the databricks backend. */}
        {onDatabricks && (
          <SourceTab
            active={mode === "databricks"}
            onClick={() => switchMode("databricks")}
            icon={<Cloud className="h-4 w-4" aria-hidden />}
            label="Databricks (Unity Catalog)"
          />
        )}
      </div>

      {/* Source input — file drop zone OR the database table picker. */}
      {mode === "file" ? (
        <div
          role="button"
          tabIndex={0}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") inputRef.current?.click()
          }}
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragOver(false)
            onFiles(e.dataTransfer.files)
          }}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed bg-card py-14 text-center transition-colors",
            dragOver ? "border-primary bg-accent" : "border-border hover:border-primary/50",
          )}
        >
          <UploadCloud className="h-8 w-8 text-primary" aria-hidden />
          <div className="text-sm font-medium">
            {busy ? "Uploading…" : "Drag a file here, or click to browse"}
          </div>
          <div className="text-xs text-muted-foreground">.csv · .xlsx · .parquet</div>
          <input
            ref={inputRef}
            type="file"
            accept=".csv,.xlsx,.xls,.parquet,.pq"
            className="hidden"
            onChange={(e) => onFiles(e.target.files)}
          />
        </div>
      ) : mode === "database" ? (
        <DatabaseSourcePanel
          selected={dbSelection?.table ?? null}
          onSelectTable={(t) => void doSelect({ table: t })}
          onRunQuery={(q) => void doSelect({ query: q })}
          busy={busy}
        />
      ) : (
        <div className="space-y-5">
          <DatabricksSourcePanel
            pat={databricksPat}
            onPatChange={setDatabricksPat}
            onSelectTable={(sel) => void doSelectUc(sel)}
            selectedTable={ucSelection?.table ?? null}
            clusterId={form.cluster_id}
            onClusterChange={(clusterId) => updateForm({ cluster_id: clusterId })}
            busy={busy || running}
          />
          {busy && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Spinner /> Loading table schema…
            </div>
          )}
        </div>
      )}

      {mode === "file" && busy && (
        <div className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner /> Inspecting {file?.name}…
        </div>
      )}

      {error && (
        <div className="mt-4">
          <ErrorState
            message={error}
            onRetry={
              mode === "file"
                ? file
                  ? () => void doUpload(file)
                  : undefined
                : mode === "database"
                  ? dbSelection
                    ? () => void doSelect(dbSelection)
                    : undefined
                  : ucSelection
                    ? () => void doSelectUc(ucSelection)
                    : undefined
            }
          />
        </div>
      )}

      {/* Inspection profile (shared by both sources). */}
      {inspect && !error && (
        <div className="mt-6 grid grid-cols-1 gap-5 lg:grid-cols-[1.5fr_1fr]">
          <Card>
            <CardHeader>
              <CardTitle>Columns · {inspect.columns.length}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="max-h-80 overflow-y-auto rounded-md border">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-muted text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">Column</th>
                      <th className="px-3 py-2 text-left font-medium">Type</th>
                      <th className="px-3 py-2 text-right font-medium">Missing</th>
                    </tr>
                  </thead>
                  <tbody>
                    {inspect.columns.map((col) => (
                      <tr key={col} className="border-t">
                        <td className="px-3 py-1.5 font-medium">
                          {col}
                          {inspect.binary_cols.includes(col) && (
                            <Badge variant="secondary" className="ml-2">binary</Badge>
                          )}
                          {inspect.datetime_cols.includes(col) && (
                            <Badge variant="secondary" className="ml-2">datetime</Badge>
                          )}
                        </td>
                        <td className="px-3 py-1.5 font-mono text-xs text-muted-foreground">
                          {inspect.dtypes[col]}
                        </td>
                        <td className="px-3 py-1.5 text-right font-mono text-xs">
                          {fmtInt(inspect.n_missing[col])}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          <div className="space-y-5">
            <Card>
              <CardHeader>
                <CardTitle>Profile</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2.5 text-sm">
                {form.input_source?.type === "postgres" && (
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Source</span>
                    <Badge variant="secondary" className="gap-1">
                      <Database className="h-3 w-3" aria-hidden />
                      database
                    </Badge>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Rows</span>
                  <span className="font-mono font-semibold">{fmtInt(inspect.n_rows)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Numeric / categorical</span>
                  <span className="font-mono font-semibold">
                    {inspect.numeric_cols.length} / {inspect.categorical_cols.length}
                  </span>
                </div>
                {inspect.suggested_problem_type && (
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Suggested type</span>
                    <Badge>{inspect.suggested_problem_type}</Badge>
                  </div>
                )}
                <Link
                  to="/data-profile"
                  className={cn(buttonVariants({ variant: "outline", size: "sm" }), "mt-1 w-full")}
                >
                  <ScanSearch className="h-4 w-4" />
                  Explore data profile
                </Link>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Target column</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="space-y-1.5">
                  <Label htmlFor="target">Pick the column to predict</Label>
                  <Select
                    id="target"
                    value={form.target}
                    onChange={(e) => onTargetChange(e.target.value)}
                    disabled={busy}
                  >
                    <option value="">— choose a target —</option>
                    {inspect.columns.map((col) => (
                      <option key={col} value={col}>
                        {col}
                      </option>
                    ))}
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    Choosing a target shows its class distribution below.
                  </p>
                </div>

                {inspect.class_distribution && (
                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(inspect.class_distribution).map(([k, v]) => (
                      <Badge key={k} variant="secondary">
                        {k}: {fmtInt(v)}
                      </Badge>
                    ))}
                  </div>
                )}

                <Link
                  to="/configure"
                  className={cn(
                    buttonVariants({ size: "sm" }),
                    "w-full",
                    (!serverPath || !form.target) && "pointer-events-none opacity-50",
                  )}
                  aria-disabled={!serverPath || !form.target}
                >
                  <FileUp className="h-4 w-4" />
                  Continue to Configuration
                </Link>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}

/** One tab in the data-source switch. */
function SourceTab({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean
  onClick: () => void
  icon: ReactNode
  label: string
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
        active
          ? "bg-primary text-primary-foreground shadow-sm"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {icon}
      {label}
    </button>
  )
}
