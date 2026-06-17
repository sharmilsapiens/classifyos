import * as React from "react"

import { cn } from "@/lib/utils"

// An on/off toggle for boolean config (calibrate, tuning, …).
//
// Under the hood this is a real checkbox <input> (so it is keyboard- and
// screen-reader-accessible and submits like a checkbox), visually restyled as a
// sliding switch with Tailwind peer-* classes. No Radix dependency needed.
export interface SwitchProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> {
  label?: string
}

const Switch = React.forwardRef<HTMLInputElement, SwitchProps>(
  ({ className, label, id, ...props }, ref) => (
    <label htmlFor={id} className="inline-flex cursor-pointer items-center gap-2 select-none">
      <span className="relative inline-flex">
        <input
          ref={ref}
          id={id}
          type="checkbox"
          className={cn("peer sr-only", className)}
          {...props}
        />
        {/* track */}
        <span className="h-5 w-9 rounded-full bg-input transition-colors peer-checked:bg-primary peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2" />
        {/* knob */}
        <span className="pointer-events-none absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform peer-checked:translate-x-4" />
      </span>
      {label && <span className="text-sm text-foreground">{label}</span>}
    </label>
  ),
)
Switch.displayName = "Switch"

export { Switch }
