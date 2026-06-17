/* PngArtifact — render a plot PNG that the run wrote to OUTPUT_DIR.

   The locked contract gives interactive data for SOME visuals and only a PNG for
   others. PNGs are NEVER inlined in the /run response — they are fetched on
   demand here via the client's outputUrl(name) as a normal <img src>. Some plots
   are placeholders for some problem types (e.g. calibration is binary-only), and
   an artifact can be absent, so this component guards both cases:

   • If `name` is not in the run's artifact list → show a friendly "not generated
     for this run" panel (no broken image).
   • If the image fails to load (server down, file vanished) → same friendly panel.

   A download/open link is always offered when the artifact is expected to exist. */

import { useState } from "react"
import { ImageOff } from "lucide-react"

import { outputUrl } from "@/api/client"
import type { ArtifactEntry } from "@/api/types"

export function PngArtifact({
  name,
  alt,
  artifacts,
  caption,
}: {
  /** Artifact filename, e.g. "plot4_feature_impact.png". */
  name: string
  /** Accessible description of the chart. */
  alt: string
  /** The run's artifact list — used to know whether the file exists at all. */
  artifacts: ArtifactEntry[]
  caption?: string
}) {
  const [failed, setFailed] = useState(false)
  const present = artifacts.some((a) => a.name === name)

  // Either the run never produced this file, or the <img> failed to load it.
  if (!present || failed) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 rounded-md border border-dashed bg-muted/30 py-10 text-center text-sm text-muted-foreground">
        <ImageOff className="h-5 w-5" aria-hidden />
        <p>This plot was not generated for this run.</p>
        <p className="text-xs">
          <span className="font-mono">{name}</span>
          {present ? " could not be loaded — is the API running?" : " is not in this run's artifacts."}
        </p>
      </div>
    )
  }

  return (
    <figure className="space-y-2">
      <a href={outputUrl(name)} target="_blank" rel="noreferrer" className="block">
        <img
          src={outputUrl(name)}
          alt={alt}
          onError={() => setFailed(true)}
          className="w-full rounded-md border bg-card"
          loading="lazy"
        />
      </a>
      {caption && (
        <figcaption className="text-xs text-muted-foreground">
          {caption} ·{" "}
          <a
            href={outputUrl(name)}
            target="_blank"
            rel="noreferrer"
            className="text-primary underline-offset-2 hover:underline"
          >
            open full size
          </a>
        </figcaption>
      )}
    </figure>
  )
}
