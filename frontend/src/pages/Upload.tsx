/* Upload Data — step 1 of the Upload → Configure → Run flow.

   Drag-drop (or pick) a CSV/Excel/Parquet file → POST /upload → the server saves
   it and returns its inspection profile (columns, dtypes, missing counts, a
   suggested problem type, and — if a target is chosen — the class distribution).
   We store the profile + server_path in the global store; the Configuration page
   reads them to populate its target and feature pickers. */

import { useRef, useState } from "react"
import { Link } from "react-router-dom"
import { FileUp, ScanSearch, UploadCloud } from "lucide-react"

import { ApiError, upload } from "@/api/client"
import { useApp } from "@/store/AppStore"
import { fmtInt } from "@/lib/format"
import { cn } from "@/lib/utils"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { buttonVariants } from "@/components/ui/button"
import { ErrorState, PageHeader, Spinner } from "@/components/common/States"

export default function UploadPage() {
  const { inspect, serverPath, form, applyUpload, updateForm } = useApp()
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  // Upload (and re-inspect when a target is chosen, to fetch its class distribution).
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

  function onFiles(files: FileList | null) {
    const f = files?.[0]
    if (!f) return
    setFile(f)
    void doUpload(f)
  }

  return (
    <div>
      <PageHeader
        title="Upload Data"
        subtitle="Drop a CSV, Excel, or Parquet file to inspect it and start a run."
      />

      {/* Drop zone */}
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

      {busy && (
        <div className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner /> Inspecting {file?.name}…
        </div>
      )}

      {error && (
        <div className="mt-4">
          <ErrorState message={error} onRetry={file ? () => void doUpload(file) : undefined} />
        </div>
      )}

      {/* Inspection profile */}
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
                    onChange={(e) => file && void doUpload(file, e.target.value)}
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
