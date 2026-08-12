import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// base "/": User Portal is served at the origin root in both Compact
// (nginx location "/") and the illustrative Segmented example (its own
// dedicated origin, e.g. https://browser.openrbi.local) — see
// docs/deployment.md#compact-vs-segmented-productization-v011.
export default defineConfig({
  base: "/",
  plugins: [react()],
  resolve: {
    alias: {
      "@shared": path.resolve(import.meta.dirname, "../shared"),
    },
  },
  build: {
    outDir: "dist",
  },
});
