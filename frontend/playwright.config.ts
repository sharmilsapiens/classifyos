/* ════════════════════════════════════════════════════════════════════════
   Playwright configuration — the BROWSER end-to-end (E2E) layer (Phase 10).

   New to web testing? Here is the whole idea in four sentences:
   • Playwright drives a REAL browser (Chromium) the way a person would — it
     clicks, types, navigates, and reads the rendered page.
   • A "spec" (a *.spec.ts file under ./e2e) is one E2E test scenario.
   • Unlike the vitest tests (which run in jsdom, a fake DOM where charts render
     0×0), a real browser actually paints pixels — so here we can assert that a
     chart drew real SVG geometry, an image loaded, a heatmap has cells, etc.
   • This config also starts the SERVERS the browser needs, before any test runs
     (see `webServer` below) — that is the "two-server problem".

   What this does NOT do: it adds no application code and changes no behaviour —
   Phase 10 is tests only. It asserts against the LOCKED contract
   (docs/api_contract.md). See prompts/testing_phases/phase_10_e2e_testing.md.
   ════════════════════════════════════════════════════════════════════════ */

import { defineConfig, devices } from "@playwright/test"
import path from "node:path"
import { fileURLToPath } from "node:url"

// This project is ESM ("type":"module" in package.json), so __dirname doesn't
// exist — we reconstruct it from import.meta.url (same trick as vite.config.ts).
const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, "..")
const backendDir = path.join(repoRoot, "backend")

/* ── Test-only environment for the backend server ───────────────────────────
   SAME data-hygiene rule as the pytest suite (conftest.py): the API under test
   READS the committed sample CSVs and WRITES artifacts to a THROWAWAY folder —
   never the real OUTPUT_DIR. We pass these as the spawned uvicorn process's env.

   Why this wins over backend/.env: api/main.py calls load_dotenv(), and
   python-dotenv does NOT override variables already set in the environment
   (override=False by default). So the values we set here take precedence over
   whatever backend/.env contains — the test run is self-contained and can't
   touch the developer's real input/output folders. */
const sampleDataDir = path.join(backendDir, "data", "samples")
// Throwaway artifact dir — MUST live OUTSIDE the frontend project. The Vite dev
// server watches the frontend tree, so writing run artifacts under frontend/
// would trigger an HMR full-reload mid-run and reset the app's in-memory state.
// Putting it under backend/ (uvicorn runs WITHOUT --reload) keeps it inert and
// still git-ignored + inspectable. Never the developer's real OUTPUT_DIR.
const throwawayOutputDir = path.join(backendDir, ".e2e_output")
const backendEnv: Record<string, string> = {
  DATA_DIR: sampleDataDir,
  OUTPUT_DIR: throwawayOutputDir,
  // The real allowlist the cross-origin CORS test relies on — NEVER "*".
  CORS_ORIGINS: "http://localhost:5173,http://127.0.0.1:5173",
}

// The backend runs from its own virtualenv. Pick the right interpreter per OS
// (this repo is Windows-first, but keep it portable for a teammate on macOS/Linux).
const isWin = process.platform === "win32"
const venvPython = isWin
  ? path.join(backendDir, ".venv", "Scripts", "python.exe")
  : path.join(backendDir, ".venv", "bin", "python")

export default defineConfig({
  testDir: "./e2e",
  // The backend /run is CPU-heavy (it trains real models), so don't run specs in
  // parallel against one shared backend — keep it serial and single-worker.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // Generous per-test budget: a real upload→configure→run round-trip trains
  // models server-side and can take tens of seconds.
  timeout: 180_000,
  expect: { timeout: 20_000 },
  reporter: [["list"], ["html", { open: "never" }]],

  use: {
    // baseURL lets specs use relative paths like page.goto("/") — the Vite dev
    // server (which proxies /api → :8000) is the browser's entry point.
    baseURL: "http://localhost:5173",
    trace: "on-first-retry", // capture a debuggable trace only when a test retries
    screenshot: "only-on-failure",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  /* ── The two-server problem ──────────────────────────────────────────────
     A real E2E run needs BOTH servers up at once:
       1. the FastAPI backend (uvicorn on :8000) — the ML engine over HTTP, and
       2. the Vite frontend (:5173) — the website the browser opens, whose dev
          proxy forwards /api → :8000 (see vite.config.ts).
     Playwright's `webServer` accepts an ARRAY: it starts each entry, waits until
     its readiness `url` responds, and only THEN runs the tests (and shuts them
     down afterwards). Each entry:
       • `url`     — the readiness probe Playwright polls before starting tests.
       • `timeout` — how long to wait for that probe. The backend imports the ML
                     engine + heavy libs (sklearn, xgboost, …) so it boots slowly
                     — we allow ~120s.
       • `reuseExistingServer: !CI` — locally, reuse a server you already have
                     running (fast iteration); on CI always start fresh. NOTE:
                     when a server is reused, OUR test env (throwaway OUTPUT_DIR)
                     is NOT applied — for a clean-hygiene run, start with no
                     uvicorn/vite already running so this config launches them.
       • `cwd`/`env` — run from the right folder with the test-only env above. */
  webServer: [
    {
      // `python -m uvicorn` from the backend venv. Quote the path in case it ever
      // contains a space; uvicorn serves api.main:app on :8000.
      command: `"${venvPython}" -m uvicorn api.main:app --port 8000`,
      cwd: backendDir,
      url: "http://localhost:8000/api/v1/health",
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: backendEnv,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: "npm run dev",
      cwd: __dirname,
      url: "http://localhost:5173",
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
})
