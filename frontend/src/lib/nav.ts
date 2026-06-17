/* The canonical 12-page navigation, defined in ONE place so the sidebar, the
   router, and any "next step" links never drift.
   9a built the Workspace screens; 9b built the six Results pages; 9c built the
   last three (Explainability, Setup Guide, Risk Register) and MERGED the old
   "Pipeline" page into Overview — so the nav went from 13 → 12 items and there
   are no stub routes left. (/pipeline still resolves: it redirects to Overview.) */

import {
  BarChart3,
  BookOpen,
  ClipboardList,
  Combine,
  Grid3x3,
  LayoutDashboard,
  LineChart,
  Lightbulb,
  Settings2,
  ShieldAlert,
  Table2,
  Upload,
  type LucideIcon,
} from "lucide-react"

export interface NavItem {
  path: string
  label: string
  icon: LucideIcon
  group: "Workspace" | "Results" | "Reference"
}

export const NAV_ITEMS: NavItem[] = [
  { path: "/", label: "Overview", icon: LayoutDashboard, group: "Workspace" },
  { path: "/upload", label: "Upload Data", icon: Upload, group: "Workspace" },
  { path: "/configure", label: "Configuration", icon: Settings2, group: "Workspace" },

  { path: "/feature-impact", label: "Feature Impact", icon: BarChart3, group: "Results" },
  { path: "/interactions", label: "Interaction Features", icon: Combine, group: "Results" },
  { path: "/confusion", label: "Confusion Matrix", icon: Grid3x3, group: "Results" },
  { path: "/class-report", label: "Class Report", icon: ClipboardList, group: "Results" },
  { path: "/curves", label: "ROC / PR Curves", icon: LineChart, group: "Results" },
  { path: "/predictions", label: "Predictions Table", icon: Table2, group: "Results" },
  { path: "/explainability", label: "Explainability", icon: Lightbulb, group: "Results" },

  { path: "/setup", label: "Setup Guide", icon: BookOpen, group: "Reference" },
  { path: "/risks", label: "Risk Register", icon: ShieldAlert, group: "Reference" },
]

export const NAV_GROUPS = ["Workspace", "Results", "Reference"] as const
