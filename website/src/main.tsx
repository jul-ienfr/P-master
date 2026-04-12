import React from 'react'
import ReactDOM from 'react-dom/client'
import './index.css'

type BootstrapShell = {
  markReady?: () => void
  fail?: (error: unknown) => void
}

function getBootstrapShell(): BootstrapShell | null {
  const globalWindow = window as Window & { __PM_BOOTSTRAP_SHELL__?: BootstrapShell }
  return globalWindow.__PM_BOOTSTRAP_SHELL__ ?? null
}

function renderBootstrapError(error: unknown) {
  getBootstrapShell()?.fail?.(error)
  const root = document.getElementById('root')
  if (!root) {
    return
  }

  const message = error instanceof Error ? (error.stack || error.message) : String(error)
  root.innerHTML = `
    <div style="min-height:100vh;display:grid;place-items:center;padding:24px;background:#0b1220;color:#e5edf7;font-family:Segoe UI,Arial,sans-serif;">
      <div style="max-width:920px;width:100%;background:#111a2b;border:1px solid rgba(229,237,247,0.12);border-radius:16px;padding:24px;box-shadow:0 24px 60px rgba(0,0,0,0.35);">
        <div style="font-size:12px;letter-spacing:0.12em;text-transform:uppercase;opacity:0.7;margin-bottom:8px;">PokerMaster V2</div>
        <h1 style="margin:0 0 12px;font-size:28px;">Frontend bootstrap error</h1>
        <p style="margin:0 0 16px;opacity:0.85;">The UI crashed before React finished mounting.</p>
        <pre style="margin:0;padding:16px;border-radius:12px;overflow:auto;background:#0a1020;color:#ffb4b4;white-space:pre-wrap;word-break:break-word;">${message.replace(/[&<>]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[char] || char))}</pre>
      </div>
    </div>
  `
}

window.addEventListener('error', (event) => {
  console.error('PokerMaster bootstrap window error', event.error || event.message)
})

window.addEventListener('unhandledrejection', (event) => {
  console.error('PokerMaster bootstrap unhandled rejection', event.reason)
})

async function bootstrap() {
  try {
    const root = document.getElementById('root')
    if (!root) {
      throw new Error('Missing #root container')
    }

    const { default: App } = await import('./App')
    getBootstrapShell()?.markReady?.()

    ReactDOM.createRoot(root).render(
      <React.StrictMode>
        <App />
      </React.StrictMode>,
    )
  } catch (error) {
    renderBootstrapError(error)
  }
}

void bootstrap()
