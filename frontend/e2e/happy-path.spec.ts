/* ════════════════════════════════════════════════════════════════════════
   Happy-path E2E — the full flow through a REAL browser, REAL servers, and the
   REAL ML engine, asserting against the LOCKED contract (docs/api_contract.md).

   This is the layer continuous testing structurally could not reach:
   the vitest suite runs in jsdom (where Recharts renders 0×0, so no pixels), and
   the pytest "integration" hits the engine directly or the API via TestClient —
   never a real browser. Here a real Chromium loads the live Vite app, which talks
   to live uvicorn, which runs the engine, and we assert the charts/tables/PNGs
   actually RENDER.

   Parametrized over USE_CASES so Phase 11 can extend it to all seven insurance
   use cases. Phase 10 runs ONLY the binary + multiclass entries (multilabel, the
   7-use-case sweep, perf, tuning-at-budget, real data, and governance are Phase
   11 — deliberately out of scope here).
   ════════════════════════════════════════════════════════════════════════ */

import { expect, test, type Page } from "@playwright/test"
import {
  USE_CASES,
  configureAndRun,
  gotoResultViaLink,
  uploadDataset,
  waitForResults,
} from "./flows"

/**
 * Assert a Recharts chart actually drew real geometry. In a real browser the
 * ResponsiveContainer gets real width/height, so Recharts computes pixel
 * coordinates and emits <path d="..."> with real numbers — something impossible
 * in jsdom's 0×0 render. We grab the first data path inside the chart's
 * role="img" wrapper and assert its `d` is non-trivial.
 */
async function expectChartDrewGeometry(page: Page, ariaLabelPrefix: string) {
  const chart = page.locator(`[role="img"][aria-label^="${ariaLabelPrefix}"]`).first()
  await expect(chart).toBeVisible()
  // Recharts lines AND bars both render as <path>. A chart contains several paths
  // (grid, axes, data shapes); the DATA shapes carry long `d` strings full of real
  // pixel coordinates — something a 0×0 jsdom render can never produce. So we read
  // EVERY path's `d` and assert the longest one is substantial. We poll because the
  // SVG paints a tick after layout.
  const paths = chart.locator("svg path")
  await expect(paths.first()).toBeAttached()
  const longestD = async () => {
    const ds = await paths.evaluateAll((els) =>
      els.map((el) => el.getAttribute("d") ?? ""),
    )
    return ds.reduce((max, d) => Math.max(max, d.length), 0)
  }
  // A real line/bar path is well over 30 chars; a degenerate/grid path is ~15.
  await expect.poll(longestD, { timeout: 15_000 }).toBeGreaterThan(30)
}

for (const uc of USE_CASES) {
  test(`happy path: ${uc.problem_type} (${uc.file} → ${uc.target})`, async ({ page }) => {
    // ── Upload → Configure → Run (the three workspace steps). ───────────────
    await uploadDataset(page, uc)
    await configureAndRun(page, uc)
    await waitForResults(page)

    // ── Overview RESULTS: the KPI band populates. ───────────────────────────
    // "Best model" and "Test accuracy" are KPI-band labels unique to the band
    // (ROC-AUC/MCC also appear as scoreboard column headers, so we avoid those).
    await expect(page.getByText("Best model", { exact: true })).toBeVisible()
    await expect(page.getByText("Test accuracy", { exact: true })).toBeVisible()

    // The model-comparison BAR chart drew real bars (geometry, not 0×0).
    await expectChartDrewGeometry(page, "Bar chart comparing")

    // The scoreboard lists every trained model as a row cell (proves the per-model
    // table rendered, and implicitly that the "best model" is one of ours).
    for (const algo of uc.algorithms) {
      await expect(page.getByRole("cell", { name: algo, exact: true })).toBeVisible()
    }

    // ── ROC / PR Curves: real SVG curves (one for binary, N for multiclass). ─
    await gotoResultViaLink(page, /ROC \/ PR Curves/i)
    await expect(page.getByRole("heading", { name: /ROC \/ PR Curves/i })).toBeVisible()
    await expectChartDrewGeometry(page, "ROC curve for")
    // Count the per-class curve lines: Recharts <Line> → <path class=recharts-curve>.
    // Per the LOCKED contract, binary draws ONE curve (the positive class, one-vs-rest),
    // while multiclass draws one-vs-rest per class.
    const expectedRocCurves = uc.problem_type === "binary" ? 1 : uc.expectedClasses.length
    const rocCurves = page.locator('[aria-label^="ROC curve for"] path.recharts-curve')
    await expect(rocCurves).toHaveCount(expectedRocCurves)

    // A PNG artifact (fetched on demand via /outputs/{name}) actually loads.
    const plotImg = page.getByRole("img", { name: /ROC and PR curves across models/i })
    await plotImg.scrollIntoViewIfNeeded()
    await expect
      .poll(() => plotImg.evaluate((el: HTMLImageElement) => el.naturalWidth), {
        timeout: 15_000,
      })
      .toBeGreaterThan(0)

    // ── Confusion matrix: a heatmap with one cell per (true,predicted) pair. ─
    await gotoResultViaLink(page, /Confusion Matrix/i)
    const cells = page.locator('[role="cell"]')
    await expect(cells.first()).toBeVisible()
    // n classes → n×n cells (binary 2×2 = 4; multiclass 3×3 = 9).
    await expect(cells).toHaveCount(uc.expectedClasses.length ** 2)

    // ── Predictions table: the sampled banner + real rows. ──────────────────
    await gotoResultViaLink(page, /Predictions Table/i)
    await expect(page.getByText(/Showing a sample of/i)).toBeVisible()
    await expect(page.locator("table tbody tr").first()).toBeVisible()

    // ── /explain real path (binary case only — one exercise is enough). ─────
    if (uc.problem_type === "binary") {
      await exerciseExplainEndpoint(page)
    }
  })
}

/**
 * Drive the Explainability page against the LIVE /explain endpoint. v1.0 returns
 * a structured "unavailable" stub (no model persistence yet — see plan_tweak 29);
 * we assert the page surfaces that stub cleanly with the reserved waterfall region
 * present. This proves the real client → /explain → render path in a browser
 * (the vitest test for this mocks the client; here it's the live endpoint).
 */
async function exerciseExplainEndpoint(page: Page) {
  await gotoResultViaLink(page, /Explainability/i)
  await expect(page.getByText(/Explainability is coming in v2.0/i)).toBeVisible()

  // Pick a model + row and call the endpoint.
  await page.getByRole("button", { name: /^Explain$/i }).click()

  // The structured stub renders: status "unavailable", the server's own reason,
  // and the v2.0 waterfall placeholder (NOT a broken/empty chart over null data).
  await expect(page.getByText("unavailable")).toBeVisible()
  await expect(page.getByText(/no_persisted_model/)).toBeVisible()
  await expect(page.getByText(/SHAP waterfall — reserved for v2.0/i)).toBeVisible()
}
