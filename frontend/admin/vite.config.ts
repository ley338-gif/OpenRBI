import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// base: "/admin/" in Compact (served by the same nginx as the User Portal,
// at a sub-path) — overridden to "/" for the illustrative Segmented
// example, where the Admin Portal gets its own dedicated origin (e.g.
// https://admin.openrbi.local). See
// docs/deployment.md#compact-vs-segmented-productization-v011.
const base = process.env.OPENRBI_ADMIN_BASE_PATH ?? "/admin/";

export default defineConfig({
  base,
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
