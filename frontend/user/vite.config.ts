import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// base "/": User Portal is served at the origin root in both Compact
// (nginx location "/") and the illustrative Segmented example (its own
// dedicated origin, e.g. https://browser.openrbi.local) — see
// docs/deployment.md#compact-vs-segmented-productization-v011.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, import.meta.dirname, "");
  return {
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
    // `npm run dev` only (docs/development.md#frontend-development): /api,
    // including the display WebSocket, goes to a running stack's reverse
    // proxy, which strips the prefix like in production. The Host header is
    // passed through unchanged (no changeOrigin), so the display handshake's
    // Origin/Host comparison and the session cookie keep working.
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": { target: env.OPENRBI_DEV_API_TARGET ?? "http://localhost:8080", ws: true },
      },
    },
  };
});
