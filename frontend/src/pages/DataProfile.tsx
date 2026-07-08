/* Data Profile — exploratory views of the UPLOADED dataset, before any run.

   Reads the inspection profile from the store (no new network call — the blocks
   are attached to the /upload response by the engine's profile_dataframe). For
   each column it shows the right view for its type:
     • numeric     → a smooth distribution (density) curve + summary stats (mean,
                     median, mode, std, min/p25/p75/max, skew).
     • categorical → a top-N value-frequency bar chart (+ an "other" bucket and a
                     cardinality/most-frequent summary). Numeric 0/1 columns are
                     profiled this way too.
     • datetime    → the observed date range.
   Plus two dataset-level views: a missingness overview (missing % per column)
   and a Pearson correlation heatmap over the numeric columns. */

import { useMemo } from "react"
import { Link } from "react-router-dom"
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { ArrowRight, ArrowUp, Hash, Type as TypeIcon } from "lucide-react"

import type { ColumnProfile, CorrelationMatrix, InspectProfile } from "@/api/types"
import { useApp } from "@/store/AppStore"
import { fmtInt, fmtNum, fmtPct } from "@/lib/format"
import { ColumnFlags } from "@/lib/columnFlags"
import { cn } from "@/lib/utils"
import { buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { EmptyState, PageHeader } from "@/components/common/States"

export default function DataProfile() {
  const { inspect } = useApp()

  // No upload yet (or an older upload without the profile blocks).
  if (!inspect || !inspect.column_profiles) {
    return (
      <div>
        <PageHeader
          title="Data Profile"
          subtitle="Distributions and summary statistics for your uploaded dataset."
        />
        <EmptyState
          title="No dataset uploaded yet"
          description="Upload a CSV, Excel, or Parquet file to explore its column distributions, value frequencies, missingness, and correlations."
          action={
            <Link to="/upload" className={cn(buttonVariants({ size: "sm" }))}>
              Go to Upload <ArrowRight className="h-4 w-4" />
            </Link>
          }
        />
      </div>
    )
  }

  return <DataProfileBody inspect={inspect} />
}

function DataProfileBody({ inspect }: { inspect: InspectProfile }) {
  const profiles = inspect.column_profiles ?? []
  const numeric = profiles.filter((c) => c.dtype_group === "numeric")
  const categorical = profiles.filter((c) => c.dtype_group === "categorical")
  const datetime = profiles.filter((c) => c.dtype_group === "datetime")

  return (
    <div>
      <PageHeader
        title="Data Profile"
        subtitle={`${inspect.server_path.split("/").pop()} · ${fmtInt(inspect.n_rows)} rows · ${profiles.length} columns`}
        actions={
          <Link to="/configure" className={cn(buttonVariants({ size: "sm" }))}>
            Continue to Configuration <ArrowRight className="h-4 w-4" />
          </Link>
        }
      />

      {inspect.profile_sampled && (
        <p className="mb-4 text-xs text-muted-foreground">
          Histograms and correlation were computed on a random sample of{" "}
          {fmtInt(inspect.n_rows_profiled)} rows (large file); per-column counts use every row.
        </p>
      )}

      {/* Dataset-level: missingness scan */}
      <MissingnessCard profiles={profiles} />

      {/* Numeric distributions */}
      {numeric.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-muted-foreground">
            <Hash className="h-4 w-4" /> Numeric columns · {numeric.length}
          </h2>
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            {numeric.map((c) => (
              <NumericCard key={c.name} col={c} nRows={inspect.n_rows} />
            ))}
          </div>
        </section>
      )}

      {/* Categorical / binary frequencies */}
      {categorical.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-muted-foreground">
            <TypeIcon className="h-4 w-4" /> Categorical columns · {categorical.length}
          </h2>
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            {categorical.map((c) => (
              <CategoricalCard key={c.name} col={c} nRows={inspect.n_rows} />
            ))}
          </div>
        </section>
      )}

      {/* Datetime ranges */}
      {datetime.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-3 text-sm font-semibold text-muted-foreground">
            Datetime columns · {datetime.length}
          </h2>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {datetime.map((c) => (
              <DatetimeCard key={c.name} col={c} nRows={inspect.n_rows} />
            ))}
          </div>
        </section>
      )}

      {/* Correlation heatmap */}
      {inspect.correlation && (
        <section className="mt-6">
          <CorrelationCard corr={inspect.correlation} />
        </section>
      )}

      {/* Footer: continue once you've seen everything, or jump back to the top. */}
      <div className="mt-8 flex flex-wrap items-center justify-between gap-3 border-t pt-6">
        <button
          type="button"
          onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
          className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
        >
          <ArrowUp className="h-4 w-4" /> Back to top
        </button>
        <Link to="/configure" className={cn(buttonVariants({ size: "sm" }))}>
          Continue to Configuration <ArrowRight className="h-4 w-4" />
        </Link>
      </div>
    </div>
  )
}

/* ───────────────────────────── missingness ──────────────────────────────── */

function MissingnessCard({ profiles }: { profiles: ColumnProfile[] }) {
  const withMissing = useMemo(
    () =>
      profiles
        .filter((c) => c.n_missing > 0)
        .map((c) => ({ name: c.name, pct: c.missing_pct ?? 0, n: c.n_missing }))
        .sort((a, b) => b.pct - a.pct),
    [profiles],
  )

  return (
    <Card>
      <CardHeader>
        <CardTitle>Missing values</CardTitle>
      </CardHeader>
      <CardContent>
        {withMissing.length === 0 ? (
          <p className="text-sm text-muted-foreground">No missing values in any column. 🎉</p>
        ) : (
          <ResponsiveContainer width="100%" height={Math.max(160, withMissing.length * 28)}>
            <BarChart
              layout="vertical"
              data={withMissing}
              margin={{ top: 4, right: 24, bottom: 4, left: 8 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
              <XAxis
                type="number"
                domain={[0, 100]}
                unit="%"
                tick={{ fontSize: 11, fill: "#64748b" }}
              />
              <YAxis
                type="category"
                dataKey="name"
                width={150}
                tick={{ fontSize: 11, fill: "#64748b" }}
              />
              <Tooltip
                formatter={(value, _n, item) =>
                  `${(value as number).toFixed(1)}%  (${fmtInt(item?.payload?.n)} rows)`
                }
                contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e2e8f0" }}
              />
              <Bar dataKey="pct" radius={[0, 4, 4, 0]}>
                {withMissing.map((d, i) => (
                  // amber→rose as missingness gets severe.
                  <Cell key={i} fill={d.pct > 40 ? "#f43f5e" : d.pct > 15 ? "#f59e0b" : "#4f46e5"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  )
}

/* ─────────────────────────────── numeric ────────────────────────────────── */

function NumericCard({ col, nRows }: { col: ColumnProfile; nRows: number }) {
  const stats = col.stats
  const hist = col.histogram

  // Plot the distribution as a smooth density curve rather than histogram bars —
  // for continuous data with many distinct values a curve reads the shape (bell,
  // skew, bimodal) far better than blocky bins. Each histogram bin contributes one
  // point at its MIDPOINT (x = (edge_i + edge_{i+1}) / 2, y = row count); Recharts'
  // natural-spline `Area` smooths between them. A numeric x-axis keeps the values
  // meaningful (unlike the old category axis of left-edge labels).
  const data = useMemo(() => {
    if (!hist) return []
    return hist.counts.map((count, i) => {
      const lo = hist.bin_edges[i]
      const hi = hist.bin_edges[i + 1]
      const mid = lo != null && hi != null ? (lo + hi) / 2 : (lo ?? hi ?? i)
      return { x: mid, count }
    })
  }, [hist])

  // Unique gradient id per card (many NumericCards share the DOM).
  const gradId = `density-${col.name.replace(/[^a-zA-Z0-9_-]/g, "-")}`
  // A near-unique (identifier-like) column has no meaningful distribution to plot.
  const isIdentifier = (col.flags ?? []).includes("identifier")

  const STAT_ROWS: Array<[string, number | null | undefined]> = [
    ["Mean", stats?.mean],
    ["Median", stats?.median],
    ["Mode", stats?.mode],
    ["Std dev", stats?.std],
    ["Min", stats?.min],
    ["25%", stats?.p25],
    ["75%", stats?.p75],
    ["Max", stats?.max],
    ["Skew", stats?.skew],
  ]

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span className="font-mono">{col.name}</span>
          <Badge variant="secondary">{fmtInt(col.n_unique)} unique</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ColumnFlags flags={col.flags} className="mb-3" profile={col} nRows={nRows} />
        {isIdentifier ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Near-unique values (identifier-like) — a distribution isn't meaningful here.
          </p>
        ) : data.length > 1 ? (
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
              <defs>
                <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#4f46e5" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#4f46e5" stopOpacity={0.03} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
              <XAxis
                dataKey="x"
                type="number"
                domain={["dataMin", "dataMax"]}
                tickFormatter={(v) => fmtNum(v as number)}
                tick={{ fontSize: 9, fill: "#94a3b8" }}
                interval="preserveStartEnd"
              />
              <YAxis tick={{ fontSize: 10, fill: "#64748b" }} allowDecimals={false} width={36} />
              <Tooltip
                labelFormatter={(label) => `≈ ${fmtNum(label as number)}`}
                formatter={(value) => [fmtInt(value as number), "rows"]}
                contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e2e8f0" }}
              />
              <Area
                type="natural"
                dataKey="count"
                stroke="#4f46e5"
                strokeWidth={2}
                fill={`url(#${gradId})`}
                dot={false}
                activeDot={{ r: 3 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {data.length === 1
              ? "Only one distinct value — no distribution to plot."
              : "No numeric values to chart."}
          </p>
        )}

        <dl className="mt-3 grid grid-cols-3 gap-x-4 gap-y-1.5 text-sm">
          {STAT_ROWS.map(([label, value]) => (
            <div key={label} className="flex flex-col">
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="font-mono font-medium">{fmtNum(value)}</dd>
            </div>
          ))}
        </dl>
        {col.n_missing > 0 && (
          <p className="mt-3 text-xs text-muted-foreground">
            {fmtInt(col.n_missing)} missing ({fmtPct(col.missing_pct)})
          </p>
        )}
      </CardContent>
    </Card>
  )
}

/* ───────────────────────────── categorical ──────────────────────────────── */

function CategoricalCard({ col, nRows }: { col: ColumnProfile; nRows: number }) {
  const values = col.top_values ?? []
  const data = useMemo(() => {
    const rows = values.map((v) => ({ value: v.value, count: v.count }))
    if (col.other_count && col.other_count > 0) {
      rows.push({ value: "(other)", count: col.other_count })
    }
    return rows
  }, [values, col.other_count])

  const top = values[0]

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span className="font-mono">{col.name}</span>
          <Badge variant="secondary">{fmtInt(col.n_unique)} unique</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ColumnFlags flags={col.flags} className="mb-3" profile={col} nRows={nRows} />
        {data.length > 0 ? (
          <ResponsiveContainer width="100%" height={Math.max(140, data.length * 26)}>
            <BarChart
              layout="vertical"
              data={data}
              margin={{ top: 4, right: 24, bottom: 4, left: 8 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 10, fill: "#64748b" }} allowDecimals={false} />
              <YAxis
                type="category"
                dataKey="value"
                width={120}
                tick={{ fontSize: 11, fill: "#64748b" }}
              />
              <Tooltip
                formatter={(value) => [fmtInt(value as number), "rows"]}
                contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e2e8f0" }}
              />
              <Bar dataKey="count" radius={[0, 3, 3, 0]}>
                {data.map((d, i) => (
                  <Cell key={i} fill={d.value === "(other)" ? "#94a3b8" : "#4f46e5"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <p className="py-6 text-center text-sm text-muted-foreground">No values to chart.</p>
        )}

        <div className="mt-3 space-y-1 text-xs text-muted-foreground">
          {top && (
            <p>
              Most frequent:{" "}
              <span className="font-mono font-medium text-foreground">{top.value}</span> (
              {fmtPct(top.pct)})
            </p>
          )}
          {col.truncated && <p>Showing top {values.length} of {fmtInt(col.n_unique)} values.</p>}
          {col.n_missing > 0 && (
            <p>
              {fmtInt(col.n_missing)} missing ({fmtPct(col.missing_pct)})
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

/* ─────────────────────────────── datetime ───────────────────────────────── */

function DatetimeCard({ col, nRows }: { col: ColumnProfile; nRows: number }) {
  const fmtDate = (iso?: string | null) => (iso ? iso.slice(0, 10) : "—")
  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-mono text-base">{col.name}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1.5 text-sm">
        <ColumnFlags flags={col.flags} className="mb-3" profile={col} nRows={nRows} />
        <div className="flex justify-between">
          <span className="text-muted-foreground">Earliest</span>
          <span className="font-mono">{fmtDate(col.min)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Latest</span>
          <span className="font-mono">{fmtDate(col.max)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Missing</span>
          <span className="font-mono">{fmtInt(col.n_missing)}</span>
        </div>
      </CardContent>
    </Card>
  )
}

/* ──────────────────────────── correlation ───────────────────────────────── */

/** Diverging color for a correlation value: indigo (+) ↔ white (0) ↔ rose (−). */
function corrColor(value: number | null): string {
  if (value === null) return "#f1f5f9" // undefined (e.g. a constant column)
  const m = Math.min(1, Math.abs(value))
  return value >= 0 ? `rgba(79, 70, 229, ${0.08 + m * 0.92})` : `rgba(244, 63, 94, ${0.08 + m * 0.92})`
}

function CorrelationCard({ corr }: { corr: CorrelationMatrix }) {
  const n = corr.columns.length
  const cell = n > 10 ? 32 : 44

  return (
    <Card>
      <CardHeader>
        <CardTitle>Correlation · numeric columns</CardTitle>
      </CardHeader>
      <CardContent>
        {corr.truncated && (
          <p className="mb-2 text-xs text-muted-foreground">
            Showing the first {n} numeric columns.
          </p>
        )}
        <div className="overflow-auto">
          <div
            className="grid gap-px"
            style={{ gridTemplateColumns: `minmax(90px,auto) repeat(${n}, ${cell}px)` }}
            role="table"
            aria-label="Numeric correlation matrix"
          >
            {/* header row */}
            <div />
            {corr.columns.map((c) => (
              <div
                key={`h-${c}`}
                className="truncate px-1 py-1 text-center text-[10px] font-semibold text-muted-foreground"
                title={c}
              >
                {c}
              </div>
            ))}

            {/* body rows */}
            {corr.matrix.map((row, ri) => (
              <CorrRow key={`r-${corr.columns[ri]}`} label={corr.columns[ri]} row={row} cell={cell} />
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function CorrRow({ label, row, cell }: { label: string; row: Array<number | null>; cell: number }) {
  return (
    <>
      <div
        className="flex items-center truncate px-2 text-[10px] font-semibold text-muted-foreground"
        title={label}
      >
        {label}
      </div>
      {row.map((value, ci) => {
        const dark = value !== null && Math.abs(value) > 0.6
        return (
          <div
            key={ci}
            role="cell"
            title={`${label} ↔ ${value === null ? "undefined" : value.toFixed(2)}`}
            className="flex items-center justify-center rounded-sm font-mono text-[10px]"
            style={{
              height: cell,
              backgroundColor: corrColor(value),
              color: dark ? "#ffffff" : "#0f172a",
            }}
          >
            {value === null ? "—" : value.toFixed(2)}
          </div>
        )
      })}
    </>
  )
}
