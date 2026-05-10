import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
// Served by nginx at /, with /mopidy/* proxied to Mopidy on 127.0.0.1:6680.
// Mopidy 3.4.2 dropped [http] static_dir, so a proper webclient extension
// (or this nginx setup) is needed. Long-term: write a Mopidy-Boombox extension.
export default defineConfig({
  plugins: [react()],
  base: '/',
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Proxy Mopidy WS in dev so we can iterate on the Mac with live Pi data.
    proxy: {
      '/mopidy': {
        target: 'http://10.0.5.178:6680',
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
