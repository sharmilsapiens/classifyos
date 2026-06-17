/* The canonical 13-page navigation, defined in ONE place so the sidebar, the
   router, and any "next step" links never drift. (Locked in Phase 9a.)
   Only Overview, Upload, and Configuration are real screens in 9a; the rest are
   stub routes filled in during 9b/9c. */

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
  Workflow,
  type LucideIcon,
} from "lucide-react"

export interface NavItem {
  path: string
  label: string
  icon: LucideIcon
  group: "Workspace" | "Results" | "Reference"
  /** false → real screen in 9a; true → stub route (filled in 9b/9c). */
  stub?: boolean
}

export const NAV_ITEMS: NavItem[] = [
  { path: "/", label: "Overview", icon: LayoutDashboard, group: "Workspace" },
  { path: "/upload", label: "Upload Data", icon: Upload, group: "Workspace" },
  { path: "/configure", label: "Configuration", icon: Settings2, group: "Workspace" },
  { path: "/pipeline", label: "Pipeline", icon: Workflow, group: "Workspace" },

  { path: "/feature-impact", label: "Feature Impact", icon: BarChart3, group: "Results", stub: true },
  { path: "/interactions", label: "Interaction Features", icon: Combine, group: "Results", stub: true },
  { path: "/confusion", label: "Confusion Matrix", icon: Grid3x3, group: "Results", stub: true },
  { path: "/class-report", label: "Class Report", icon: ClipboardList, group: "Results", stub: true },
  { path: "/curves", label: "ROC / PR Curves", icon: LineChart, group: "Results", stub: true },
  { path: "/predictions", label: "Predictions Table", icon: Table2, group: "Results", stub: true },
  { path: "/explainability", label: "Explainability", icon: Lightbulb, group: "Results", stub: true },

  { path: "/setup", label: "Setup Guide", icon: BookOpen, group: "Reference", stub: true },
  { path: "/risks", label: "Risk Register", icon: ShieldAlert, group: "Reference", stub: true },
]

export const NAV_GROUPS = ["Workspace", "Results", "Reference"] as const
