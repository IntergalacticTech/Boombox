/// <reference types="vitest/config" />
import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // Assets for both pages live under /setup/assets/; nginx serves
  // dist/accounts.html at /accounts/.
  base: "/setup/",
  plugins: [react()],
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      input: {
        setup: resolve(__dirname, "index.html"),
        accounts: resolve(__dirname, "accounts.html"),
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
