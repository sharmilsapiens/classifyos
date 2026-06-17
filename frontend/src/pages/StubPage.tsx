/* Placeholder for the result/reference pages not built in 9a.

   Each stub names what the page WILL show and which part of the locked /run
   result (or which endpoint) it will read, so the nav is complete and honest
   rather than linking to dead ends. Filled in during 9b (result pages) and 9c. */

import { Link } from "react-router-dom"

import type { NavItem } from "@/lib/nav"
import { buttonVariants } from "@/components/ui/button"
import { EmptyState, PageHeader } from "@/components/common/States"

// What each stub page will eventually render (for an informative placeholder).
const WILL_SHOW: Record<string, string> = {
  "/feature-impact": "The ranked feature-impact table and plot4 (result.feature_impact + /outputs).",
  "/interactions": "Discovered interaction features and plot6 (result.run.interaction_cols + /outputs).",
  "/confusion": "Per-model confusion matrices as heatmaps (result.confusion_matrix).",
  "/class-report": "Per-class precision / recall / F1 / support tables (result.class_report).",
  "/curves": "Interactive ROC & PR curves from result.curves (rendered with Recharts).",
  "/predictions": "The sampled predictions table with a download link to the full CSV (result.predictions).",
  "/explainability": "Single-row SHAP — a v1.0 stub from /explain until model persistence (v2.0).",
  "/setup": "A getting-started guide: start the API, upload data, configure, run.",
  "/risks": "The [RISK] register: leakage, imbalance, calibration, threshold sensitivity.",
}

export function StubPage({ item }: { item: NavItem }) {
  return (
    <div>
      <PageHeader title={item.label} subtitle="Planned for a later 9b / 9c slice." />
      <EmptyState
        title="Coming soon"
        description={WILL_SHOW[item.path] ?? "This page is part of a later frontend slice."}
        action={
          <Link to="/" className={buttonVariants({ variant: "outline", size: "sm" })}>
            Back to Overview
          </Link>
        }
      />
    </div>
  )
}
