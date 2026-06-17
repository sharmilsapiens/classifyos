/* ModelSelector — a tiny labelled dropdown to pick which model's results to
   view. Used by Confusion Matrix, Class Report, and ROC/PR Curves whenever more
   than one model trained successfully. With a single model it renders nothing
   (no pointless one-option dropdown). */

import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"

export function ModelSelector({
  models,
  value,
  onChange,
  id = "model-selector",
}: {
  models: string[]
  value: string
  onChange: (model: string) => void
  id?: string
}) {
  if (models.length <= 1) return null
  return (
    <div className="flex items-center gap-2">
      <Label htmlFor={id} className="text-xs text-muted-foreground">
        Model
      </Label>
      <Select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-8 w-auto"
      >
        {models.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </Select>
    </div>
  )
}
