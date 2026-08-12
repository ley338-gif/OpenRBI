import { defineConfig } from "@playwright/test";

// Runs against the already-running Compact stack (docker compose up -d),
// never a mocked or freshly-spawned dev server — see scripts/e2e-run.sh,
// which seeds e2e_admin/e2e_user before invoking this and tears them down
// afterward. baseURL matches Compact's default reverse-proxy origin;
// override with E2E_BASE_URL for a non-default host/port.
export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:8080",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
