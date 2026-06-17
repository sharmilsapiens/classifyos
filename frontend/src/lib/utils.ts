import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

/**
 * `cn` merges Tailwind class names safely.
 *
 * - `clsx` lets you pass conditional class names (strings, arrays, objects).
 * - `twMerge` resolves Tailwind conflicts so the LAST class wins
 *   (e.g. `cn("p-2", "p-4")` → `"p-4"`, not both).
 *
 * This is the shadcn/ui convention used by every component in `components/ui`.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
