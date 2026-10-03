/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // The setup wizard, served by nginx at /setup/. (The old Accounts page
  // entry moved into the LAN app — remote-ui, Admin → Accounts.)
  base: "/setup/",
  plugins: [react()],
  build: {
    outDir: "dist",
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
