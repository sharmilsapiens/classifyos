import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import './index.css'
import App from './App.tsx'
import { AppProvider } from '@/store/AppStore'

// The app is wrapped in two providers:
//  • <BrowserRouter> enables client-side routing (URL ↔ page) via react-router.
//  • <AppProvider> supplies the shared global state (see store/AppStore.tsx).
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AppProvider>
        <App />
      </AppProvider>
    </BrowserRouter>
  </StrictMode>,
)
