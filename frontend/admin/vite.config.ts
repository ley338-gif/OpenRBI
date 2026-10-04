import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// base: "/admin/" in Compact (served by the same nginx as the User Portal,
// at a sub-path) — overridden to "/" for the illustrative Segmented
// example, where the Admin Portal gets its own dedicated origin (e.g.
// https://admin.openrbi.local). See
// docs/deployment.md#compact-vs-segmented-productization-v011.
// OPENRBI_ADMIN_BASE_PATH is read from the environment or from
// frontend/admin/.env (loadEnv with an empty prefix also returns variables
// without the VITE_ prefix; the environment wins over the file).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, import.meta.dirname, "");
  return {
    base: env.OPENRBI_ADMIN_BASE_PATH ?? "/admin/",
    plugins: [react()],
    resolve: {
      alias: {
        "@shared": path.resolve(import.meta.dirname, "../shared"),
      },
    },
    build: {
      outDir: "dist",
    },
    // `npm run dev` only — same /api proxy as frontend/user/vite.config.ts.
    server: {
      port: 5174,
      strictPort: true,
      proxy: {
        "/api": { target: env.OPENRBI_DEV_API_TARGET ?? "http://localhost:8080", ws: true },
      },
    },
  };
});
