import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
// Served by nginx at /, with /mopidy/* proxied to Mopidy on 127.0.0.1:6680.
// Mopidy 3.4.2 dropped [http] static_dir, so a proper webclient extension
// (or this nginx setup) is needed. Long-term: write a Mopidy-Boombox extension.
const boomboxTarget = process.env.BOOMBOX_DEV_TARGET ?? 'http://10.0.5.178'

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
      },
      '/api': {
        target: boomboxTarget,
        changeOrigin: true,
      },
      '/audio': {
        target: boomboxTarget,
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
