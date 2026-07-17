import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './lib/fonts'
import './index.css'
import App from './App.tsx'
import { redirectToSetupIfIncomplete } from './lib/setupGate'

async function boot() {
  // On the kiosk, a fresh (unconfigured) device redirects to the setup
  // wizard before the player mounts. If it redirects, don't render.
  if (await redirectToSetupIfIncomplete()) return
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

void boot()
