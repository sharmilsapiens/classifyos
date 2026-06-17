/* The API health banner shown in the topbar.

   It reflects the global `apiStatus` (set by checkAPI() on app load): a green
   "API connected" pill when the FastAPI server answers /health, or a red
   "API offline" pill with the reason and a Retry when it doesn't. This is the
   first thing that tells a user the backend isn't running. */

import { useApp } from "@/store/AppStore"
import { cn } from "@/lib/utils"

export function HealthBanner() {
  const { apiStatus, apiMessage, checkAPI } = useApp()

  const online = apiStatus === "online"
  const offline = apiStatus === "offline"

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold",
        online && "border-emerald/30 bg-emerald/10 text-emerald",
        offline && "border-destructive/30 bg-destructive/10 text-destructive",
        apiStatus === "unknown" && "border-border bg-muted text-muted-foreground",
      )}
    >
      <span
        className={cn(
          "h-2 w-2 rounded-full",
          online && "bg-emerald",
          offline && "bg-destructive",
          apiStatus === "unknown" && "bg-muted-foreground animate-pulse",
        )}
      />
      <span>{apiMessage}</span>
      {offline && (
        <button
          type="button"
          onClick={() => void checkAPI()}
          className="ml-1 underline underline-offset-2 hover:no-underline"
        >
          Retry
        </button>
      )}
    </div>
  )
}
