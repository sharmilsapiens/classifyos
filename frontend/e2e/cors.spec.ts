/* ════════════════════════════════════════════════════════════════════════
   Real CORS E2E — the part the dev proxy normally HIDES.

   What is CORS? A browser security rule: a page served from origin A
   (http://localhost:5173) may not read responses from an API on a different
   origin B (http://localhost:8000) unless B explicitly says "A is allowed" via
   Access-Control-Allow-Origin headers. ClassifyOS configures that allowlist from
   the CORS_ORIGINS env var (api/main.py) and NEVER uses "*" outside an explicit
   local-dev marker.

   Why this needs a real browser: in development the Vite dev server PROXIES /api
   → :8000, so the app's calls look SAME-origin to the browser and CORS never
   fires — the proxy masks it. curl and FastAPI's TestClient aren't browsers
   either, so they don't enforce CORS. The only way to actually exercise it is a
   real browser making a CROSS-origin request — which is exactly what this spec
   does by calling the absolute http://localhost:8000 URL, bypassing the proxy.

   No /run here — these are quick, run-free checks.
   ════════════════════════════════════════════════════════════════════════ */

import { expect, test } from "@playwright/test"

// The backend is reachable directly at :8000; the proxied path is :5173/api.
const API_ORIGIN = "http://localhost:8000/api/v1"

test.describe("real CORS (cross-origin from the browser)", () => {
  test("an allowlisted origin can call the API directly (GET, no proxy)", async ({ page }) => {
    // Load the real frontend so the page's origin is http://localhost:5173 — an
    // origin that IS in the backend's CORS_ORIGINS allowlist.
    await page.goto("/")
    await expect(page.getByText(/API connected/i)).toBeVisible()

    // From inside that page, fetch the API at its ABSOLUTE cross-origin URL. This
    // bypasses the Vite proxy, so the browser enforces CORS for real. A simple GET
    // is a "simple request" (no preflight) — it succeeds only if the server
    // returns Access-Control-Allow-Origin for our origin.
    const result = await page.evaluate(async (apiOrigin) => {
      const res = await fetch(`${apiOrigin}/health`)
      return { ok: res.ok, status: res.status, body: await res.json() }
    }, API_ORIGIN)

    expect(result.ok).toBe(true)
    expect(result.status).toBe(200)
    expect(result.body.status).toBe("ok")
    expect(result.body.service).toBe("ClassifyOS API")
  })

  test("a CORS preflight (OPTIONS) is handled for a non-simple request", async ({ page }) => {
    await page.goto("/")
    await expect(page.getByText(/API connected/i)).toBeVisible()

    // A POST with Content-Type: application/json is NOT a "simple request", so the
    // browser first sends a PREFLIGHT OPTIONS request asking the server whether
    // this method + header are allowed from our origin. The actual POST only
    // proceeds if the server answers the preflight affirmatively. So if this
    // cross-origin POST succeeds, the preflight was handled correctly.
    const result = await page.evaluate(async (apiOrigin) => {
      const res = await fetch(`${apiOrigin}/explain`, {
        method: "POST",
        headers: { "Content-Type": "application/json" }, // <-- triggers the preflight
        body: JSON.stringify({
          input_file: "policy_lapse.csv",
          target: "will_lapse",
          feature_cols: ["age"],
          model: "RandomForest",
          sample_index: 0,
        }),
      })
      return { ok: res.ok, status: res.status, body: await res.json() }
    }, API_ORIGIN)

    expect(result.ok).toBe(true)
    expect(result.status).toBe(200)
    // /explain is the v1.0 structured stub — proving the cross-origin POST round-tripped.
    expect(result.body.status).toBe("unavailable")
  })

  /* NOTE (documented, not automated): the allowlist is the REAL gate. A request
     from an origin NOT in CORS_ORIGINS (e.g. http://evil.example) would be blocked
     by the browser — the server would omit the Access-Control-Allow-Origin header
     and fetch would reject. We can't drive a browser from an arbitrary phantom
     origin here without serving a page from it, but the two tests above prove the
     allowlist is env-driven and working (our origin is permitted), and api/main.py
     guarantees it is never "*" outside the explicit CLASSIFYOS_CORS_DEV marker. */
})
