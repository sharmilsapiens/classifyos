/* Reusable empty / loading / error states + a page header.

   These exist so NO page ever shows a blank white screen: every async surface
   renders one of these while it waits, when it fails, or when there's nothing
   yet. Keeping them in one place keeps the empty/loading/error look consistent. */

import type { ReactNode } from "react"
import { AlertTriangle, Loader2 } from "lucide-react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

/** A small spinning indicator. */
export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("h-4 w-4 animate-spin", className)} aria-hidden />
}

/** Page title + optional subtitle + optional right-side actions (every page uses this). */
export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string
  subtitle?: string
  actions?: ReactNode
}) {
  return (
    <div className="mb-6 flex items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

/** Centered loading panel. */
export function LoadingState({ message = "Loading…" }: { message?: string }) {
  return (
    <div
      role="status"
      className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed bg-card py-16 text-muted-foreground"
    >
      <Spinner className="h-6 w-6 text-primary" />
      <p className="text-sm">{message}</p>
    </div>
  )
}

/** "Nothing here yet" — an invitation to act, never a dead end. */
export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed bg-card py-16 text-center">
      <p className="text-sm font-semibold text-foreground">{title}</p>
      {description && <p className="max-w-md text-sm text-muted-foreground">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

/** Error panel — says what went wrong, offers a way forward (retry). */
export function ErrorState({
  title = "Something went wrong",
  message,
  details,
  onRetry,
}: {
  title?: string
  message: string
  details?: string[]
  onRetry?: () => void
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 py-12 text-center">
      <AlertTriangle className="h-6 w-6 text-destructive" aria-hidden />
      <p className="text-sm font-semibold text-destructive">{title}</p>
      <p className="max-w-md text-sm text-foreground">{message}</p>
      {details && details.length > 0 && (
        <ul className="max-w-md list-disc space-y-0.5 pl-5 text-left text-xs text-muted-foreground">
          {details.map((d, i) => (
            <li key={i}>{d}</li>
          ))}
        </ul>
      )}
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry} className="mt-1">
          Try again
        </Button>
      )}
    </div>
  )
}
