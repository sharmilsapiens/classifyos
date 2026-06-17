import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"

import { PngArtifact } from "./PngArtifact"
import type { ArtifactEntry } from "@/api/types"

const artifacts: ArtifactEntry[] = [
  { name: "plot4_feature_impact.png", suffix: ".png", size_bytes: 12345 },
]

describe("PngArtifact", () => {
  it("renders an <img> fetched via outputUrl when the artifact exists", () => {
    render(<PngArtifact name="plot4_feature_impact.png" alt="feature impact" artifacts={artifacts} />)
    const img = screen.getByAltText("feature impact") as HTMLImageElement
    // outputUrl(name) → "/api/v1/outputs/plot4_feature_impact.png" (encoded).
    expect(img.getAttribute("src")).toContain("plot4_feature_impact.png")
    expect(img.getAttribute("src")).toContain("/outputs/")
  })

  it("shows a friendly fallback when the artifact is absent (never a broken image)", () => {
    render(<PngArtifact name="plot5_calibration_curve.png" alt="calibration" artifacts={artifacts} />)
    expect(screen.queryByAltText("calibration")).toBeNull()
    expect(screen.getByText(/not generated for this run/i)).toBeInTheDocument()
  })
})
