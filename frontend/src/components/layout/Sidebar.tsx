/* The left sidebar: the brand + the canonical 13-page navigation.

   <NavLink> (from react-router) renders a link that knows whether it is the
   active route, so we can highlight the current page. The items come from the
   single NAV_ITEMS list (lib/nav.ts), grouped into Workspace / Results / Reference. */

import { NavLink } from "react-router-dom"

import { NAV_GROUPS, NAV_ITEMS } from "@/lib/nav"
import { cn } from "@/lib/utils"

export function Sidebar() {
  return (
    <aside className="flex h-screen w-60 flex-col gap-1 overflow-y-auto border-r bg-card px-3 py-5">
      {/* brand */}
      <div className="flex items-center gap-3 px-2 pb-4">
        <div className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-primary to-sky font-bold text-primary-foreground">
          C
        </div>
        <div className="leading-tight">
          <div className="text-sm font-bold tracking-tight">ClassifyOS</div>
          <div className="text-[11px] font-medium text-muted-foreground">Insurance ML · Sapiens</div>
        </div>
      </div>

      {NAV_GROUPS.map((group) => (
        <div key={group} className="mb-1">
          <div className="px-2 pb-1.5 pt-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            {group}
          </div>
          <nav className="flex flex-col gap-0.5">
            {NAV_ITEMS.filter((item) => item.group === group).map((item) => {
              const Icon = item.icon
              return (
                <NavLink
                  key={item.path}
                  to={item.path}
                  // `end` on "/" so Overview isn't marked active for every route.
                  end={item.path === "/"}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium transition-colors",
                      isActive
                        ? "bg-accent text-accent-foreground"
                        : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                    )
                  }
                >
                  <Icon className="h-4 w-4 shrink-0" aria-hidden />
                  <span className="truncate">{item.label}</span>
                </NavLink>
              )
            })}
          </nav>
        </div>
      ))}
    </aside>
  )
}
