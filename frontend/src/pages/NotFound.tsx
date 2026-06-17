import { Link } from "react-router-dom"

import { buttonVariants } from "@/components/ui/button"
import { EmptyState, PageHeader } from "@/components/common/States"

/** Fallback for any unknown URL. */
export default function NotFound() {
  return (
    <div>
      <PageHeader title="Page not found" subtitle="That route doesn't exist." />
      <EmptyState
        title="Nothing here"
        description="The page you tried to open isn't part of ClassifyOS."
        action={
          <Link to="/" className={buttonVariants({ variant: "outline", size: "sm" })}>
            Back to Overview
          </Link>
        }
      />
    </div>
  )
}
