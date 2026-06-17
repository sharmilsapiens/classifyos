import * as React from "react"

import { cn } from "@/lib/utils"

// A styled dropdown.
//
// shadcn/ui's own Select is built on Radix UI (a popover + listbox). For the
// 9a foundation we use the NATIVE <select> element instead: it is fully
// keyboard- and screen-reader-accessible out of the box, needs zero extra
// dependencies, and is the clearest thing to read. It still themes from the
// same design tokens. (We can swap in the Radix-based shadcn Select later if a
// page needs custom option rendering — that's a drop-in upgrade.)
const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        "flex h-9 w-full rounded-md border border-input bg-card px-3 py-1 text-sm shadow-sm transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  ),
)
Select.displayName = "Select"

export { Select }
