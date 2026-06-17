/// <reference types="vite/client" />

// Declare the custom Vite env vars the app reads, so TypeScript knows their
// types on `import.meta.env`. Vite only exposes vars prefixed with VITE_.
interface ImportMetaEnv {
  /** Base URL for the API. Defaults to "/api/v1" (dev proxy). Set to point at a deployed API. */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
