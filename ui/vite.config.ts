import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import path from 'node:path'

// https://vite.dev/config/
// Served by nginx at /, with /mopidy/* proxied to Mopidy on 127.0.0.1:6680.
// Mopidy 3.4.2 dropped [http] static_dir, so a proper webclient extension
// (or this nginx setup) is needed. Long-term: write a Mopidy-Boombox extension.

// Auto-load <repo>/.env so `npm run dev` works without remembering to export
// BOOMBOX_DEV_TARGET. Real env still wins. See .env.example.
const repoEnv = path.resolve(__dirname, '..', '.env')
if (fs.existsSync(repoEnv)) {
  for (const raw of fs.readFileSync(repoEnv, 'utf8').split('\n')) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const eq = line.indexOf('=')
    if (eq < 0) continue
    const key = line.slice(0, eq).trim()
    let val = line.slice(eq + 1).trim()
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1)
    }
    if (!(key in process.env)) process.env[key] = val
  }
}

const boomboxTarget = process.env.BOOMBOX_DEV_TARGET ?? 'http://10.0.5.178:8090'
const boomboxAuth = process.env.BOOMBOX_WEB_AUTH
  ?? (process.env.BOOMBOX_WEB_USER && process.env.BOOMBOX_WEB_PASSWORD
    ? `Basic ${Buffer.from(`${process.env.BOOMBOX_WEB_USER}:${process.env.BOOMBOX_WEB_PASSWORD}`).toString('base64')}`
    : undefined)

const proxyHeaders = boomboxAuth ? { Authorization: boomboxAuth } : undefined

export default defineConfig({
  plugins: [react()],
  base: '/',
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Proxy through the Pi's nginx so local dev sees the same /mopidy,
    // /api, and /audio paths as the kiosk.
    proxy: {
      '/mopidy': {
        target: boomboxTarget,
        changeOrigin: true,
        ws: true,
        headers: proxyHeaders,
      },
      '/api': {
        target: boomboxTarget,
        changeOrigin: true,
        headers: proxyHeaders,
      },
      '/audio': {
        target: boomboxTarget,
        changeOrigin: true,
        ws: true,
        headers: proxyHeaders,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
