/* ResultGate — the common "is there a run to show?" wrapper.

   Every 9b result page reads the LAST /run result from the global store. Before
   any run exists there is nothing to render, so each page wraps its body in
   <ResultGate>: if a result is present it renders the children (given the
   result); otherwise it shows a friendly invitation to run the pipeline — never
   a blank screen. This keeps the empty-state logic in ONE place. */

import type { ReactNode } from "react"
import { Link } from "react-router-dom"

import { useApp } from "@/store/AppStore"
import type { RunResult } from "@/api/types"
import { buttonVariants } from "@/components/ui/button"
import { EmptyState, PageHeader } from "@/components/common/States"

export function ResultGate({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle?: string
  /** Render-prop: receives the (non-null) run result. */
  children: (result: RunResult) => ReactNode
}) {
  const { result, serverPath } = useApp()
  const run = result?.result

  if (!run) {
    return (
      <div>
        <PageHeader title={title} subtitle={subtitle ?? "Run a pipeline to see results here."} />
        <EmptyState
          title="No run yet"
          description={
            serverPath
              ? "Your dataset is uploaded. Configure and run a pipeline to populate this page."
              : "Upload a dataset, configure a run, and this page will fill with results."
          }
          action={
            <Link
              to={serverPath ? "/configure" : "/upload"}
              className={buttonVariants({ size: "sm" })}
            >
              {serverPath ? "Configure a run" : "Upload data"}
            </Link>
          }
        />
      </div>
    )
  }

  return <>{children(run)}</>
}
