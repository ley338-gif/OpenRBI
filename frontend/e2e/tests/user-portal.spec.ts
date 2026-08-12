import { test, expect } from "@playwright/test";

// Real, no-mock click-through of the User Portal against the live stack
// (see scripts/e2e-run.sh, which seeds e2e_user before this runs). Covers
// the core flow the productization task explicitly asked for: Login ->
// Dashboard -> Start Secure Browser -> ACTIVE -> real noVNC connected ->
// End Session -> Logout, plus a couple of honest-error-state checks.

const USERNAME = "e2e_user";
const PASSWORD = "E2E-Test-Password!2026";

test.describe("User Portal", () => {
  test("rejects wrong credentials with a generic message, not a raw error", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Username").fill(USERNAME);
    await page.getByLabel("Password").fill("definitely-wrong");
    await page.getByRole("button", { name: "Log in" }).click();
    await expect(page.getByText(/invalid credentials/i)).toBeVisible();
    await expect(page.locator("body")).not.toContainText("Traceback");
    await expect(page.locator("body")).not.toContainText("{\"detail\"");
  });

  test("logs in, starts a real Secure Browser session with a live noVNC connection, then ends it", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Username").fill(USERNAME);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Log in" }).click();

    // USER role has no mandatory MFA — should land straight on the dashboard.
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

    await page.getByRole("link", { name: "Secure Browser", exact: true }).click();
    await expect(page).toHaveURL(/\/browser$/);

    // e2e_user is freshly seeded with no active session, so this button is
    // always the one on screen — click() auto-waits for it rather than
    // relying on a non-retrying isVisible() snapshot, which can race the
    // route's first render and silently no-op right after navigation.
    await page.getByRole("button", { name: "Start Secure Browser" }).click();

    // Real lifecycle: QUEUED/STARTING -> ACTIVE, then a genuine RFB/noVNC
    // canvas actually renders — not a mocked/static screenshot. Sandbox
    // startup is a real Docker operation, so this needs real time.
    const canvas = page.locator("canvas");
    await expect(canvas).toBeVisible({ timeout: 45_000 });
    await expect(page.getByText(/connecting display/i)).toHaveCount(0, { timeout: 30_000 });

    await page.getByRole("button", { name: "End session" }).click();
    await expect(page.getByText("This session has ended.")).toBeVisible({ timeout: 15_000 });
  });

  test("logging out invalidates the session and returns to the login form", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Username").fill(USERNAME);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Log in" }).click();
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

    await page.getByRole("button", { name: /log out/i }).click();
    await expect(page.getByLabel("Username")).toBeVisible();

    // A cleared session shouldn't let a fresh navigation back to the
    // dashboard route see protected content — RequireAuth must redirect
    // to /login again, not show a cached authenticated view.
    await page.goto("/");
    await expect(page.getByLabel("Username")).toBeVisible();
  });
});
