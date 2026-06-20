/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Vite is the dev server + build tool. Three things are configured here:
//  1. plugins: React (JSX/Fast-Refresh) + Tailwind v4 (the CSS engine shadcn/ui themes).
//  2. resolve.alias: "@" → ./src, so imports read `@/components/...` instead of long
//     relative paths. (shadcn/ui's convention; mirrored in tsconfig.app.json paths.)
//  3. server.proxy: in dev, any request to /api is forwarded to the FastAPI backend on
//     :8000, so the browser can call /api/v1/... without CORS or a hardcoded host.
//  4. test: Vitest config (jsdom DOM + a setup file that registers jest-dom matchers).
// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    // Proxy API calls to the FastAPI backend during development.
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: false, // we import describe/it/expect explicitly — clearer for newcomers
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // Vitest unit/render tests live under src/. The Playwright browser E2E specs
    // live in ./e2e and are run by `npx playwright test`, NOT vitest — scope the
    // include to src/ so vitest never tries to collect a *.spec.ts E2E file.
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
})
