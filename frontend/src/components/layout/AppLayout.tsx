/* The app shell: a fixed sidebar on the left, a sticky topbar, and the routed
   page content in the scrollable main area.

   <Outlet> is where react-router renders whichever page matches the current
   URL. So this layout is drawn once and the page swaps inside it as you navigate. */

import { Outlet } from "react-router-dom"

import { Sidebar } from "./Sidebar"
import { Topbar } from "./Topbar"

export function AppLayout() {
  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <main className="mx-auto w-full max-w-[1200px] flex-1 px-8 py-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
