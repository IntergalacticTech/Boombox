/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// The LAN app, served by nginx at / on the LAN port (the kiosk UI is a
// separate server block on loopback :80). Hashed bundles go to /app-assets/
// so they can never be confused with the kiosk UI's /assets/.
export default defineConfig({
  base: "/",
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        id: "/",
        name: "Boombox",
        short_name: "Boombox",
        description: "Play, browse and manage your Boombox from a phone or computer",
        start_url: "/",
        scope: "/",
        display: "standalone",
        background_color: "#07060c",
        theme_color: "#07060c",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
        categories: ["music", "entertainment"],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,png,woff2}"],
        // The worker's scope is the whole LAN origin. Only the app's own
        // navigations may fall back to its index.html — the setup wizard,
        // the APIs and the old remote/accounts redirects must reach nginx.
        navigateFallbackDenylist: [/^\/(?:setup|api|remote|accounts|mopidy|local|audio)(?:\/|$)/],
      },
    }),
  ],
  build: {
    outDir: "dist",
    assetsDir: "app-assets",
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
