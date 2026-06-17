/* The top bar: app-wide controls that sit above every page.

   It holds the API health banner (left of center) and the primary "New run"
   action (right), which routes to the Upload page to begin the
   Upload → Configure → Run flow. Page-specific titles are rendered by each page
   via <PageHeader>, not here. */

import { useNavigate } from "react-router-dom"
import { Plus } from "lucide-react"

import { Button } from "@/components/ui/button"
import { HealthBanner } from "./HealthBanner"

export function Topbar() {
  const navigate = useNavigate()
  return (
    <header className="sticky top-0 z-10 flex items-center justify-between gap-4 border-b bg-background/80 px-8 py-3 backdrop-blur">
      <HealthBanner />
      <Button size="sm" onClick={() => navigate("/upload")}>
        <Plus className="h-4 w-4" />
        New run
      </Button>
    </header>
  )
}
